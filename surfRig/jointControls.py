import pymel.core as pmc

import bkTools.mayaSceneUtil
from bkTools import rigCtrlUtil as rcu, matrixUtil as mu, surfaceUtil as su


"""
Joint control related functions for surfRig:
getRiggedJnts
makeFollCtrl
makeCtrlShape
makeJntDynamic
addRigJnt
setupJntLimits
setJntColor
hiliteDimension
limitJntInDimension
"""


def getRiggedJnts(surf):
    """Return a list of rigged joints associated with the given surface."""
    return [c.rangeU.outputs(type="joint")[0] for c in surf.controls.get()
            if hasattr(c, "rangeU")]


def makeFollCtrl(name, ctrlGrp, typeDict=None, rotOrder="xyz", shape="circle"):
    """Create a control & groups & attributes under the given ctrlGrp."""
    if not typeDict:
        typeDict = {
            "control": "CTRL",
            "control group": "CTRL_GRP",
            "offset group": "OFFSET_GRP"}

    ctrlGrp.rotateOrder.set(rotOrder)
    ctrlGrp.rename(name.format(type=typeDict["control group"]))

    # make control hierarchy - ctrlGrp is transform created by fakeFoll
    # auto-zero'd
    offsetGrp = pmc.nt.Transform(
        n=name.format(type=typeDict["offset group"]), p=ctrlGrp)
    # constraint group - wtAddMatrix which 
    constGrp = pmc.nt.Transform(
        n=name.format(type=typeDict["parent"] + "_" + typeDict["offset group"]), 
        p=offsetGrp)
    constGrp.rotateOrder.set(rotOrder)

    ctrl = makeCtrlShape(
        name.format(type=typeDict["control"]), rotOrder, shape=shape)
    ctrl.addAttr("surface", at="message")
    ctrl.addAttr("controlGroup", at="message")
    ctrl.addAttr("mirror", at="message")
    ctrl.addAttr("parentControls", at="message", multi=True, indexMatters=False)
    ctrlGrp.message >> ctrl.controlGroup

    ctrl.setParent(constGrp)
    pmc.makeIdentity(ctrl)

    return ctrl, ctrlGrp, offsetGrp


def makeCtrlShape(name, rotOrder, shape="circle"):
    """Make the actual control shape, which varies depending on whether
    it has a "normal" axis (twistAxis)"""
    if shape == "circle":
        normal = mu.getVectorForAxis(rotOrder[0])
        ctrl = pmc.circle(nr=normal, n=name)[0]
    elif shape == "diamond":
        ctrl = pmc.circle(nr=(1, 0, 0), d=1, s=4, n=name)[0]
        sy = pmc.circle(nr=(0, 1, 0), d=1, s=4)[0]
        sz = pmc.circle(nr=(0, 0, 1), d=1, s=4)[0]
        bkTools.mayaSceneUtil.parentChildShapes(sy, ctrl)
        bkTools.mayaSceneUtil.parentChildShapes(sz, ctrl)
        pmc.delete(sy, sz)

    ctrl.rotateOrder.set(rotOrder)

    return ctrl


def connectSizeDistFlip(surf, ctrl, ctrlGrp, offsetGrp, rotOrder):
    """For a given setup, connect the surface size and distance attributes,
    taking into account whether controls are flipped or not"""
    for sh in ctrl.getShapes():
        surf.controlSize >> sh.create.inputs()[0].radius
    surf.controlDistance >> offsetGrp.attr("t"+rotOrder[0])
    # flip ctrlGrp scale for DOMINANT axis
    flip = surf.controlsFlipped.outputs()[0]
    flip.outFloat >> ctrlGrp.attr("s"+rotOrder[-1])


def makeJntDynamic(surf, jnt, ctrl, rotOrder, n):
    """Given surface, joint and ctrl hierarchy, make the ctrl affect the
    joint via a new "follicle" and (dynamic offset) orient constraint."""

    # allow UV limiting to be turned off via jnt attr
    # which blends between unclamped and clamped: U >> R, V >> G
    limitSwitch = pmc.nt.BlendColors(n=n.format(type="limitSwitch"))
    jnt.SurfaceUV_LimitsOnJoint >> limitSwitch.blender
    # if limit is OFF use un-clamped U (cpos.u >> color2)
    jnt.clampedU >> limitSwitch.color1R
    jnt.clampedV >> limitSwitch.color1G
    jnt.preclampedU >> limitSwitch.color2R
    jnt.preclampedV >> limitSwitch.color2G

    # make follicle, connect (optionally) limited params to it
    dynPosi = pmc.nt.PointOnSurfaceInfo(n=n.format(type="dynposi"))
    surf.local >> dynPosi.inputSurface
    limitSwitch.outputR >> dynPosi.u
    limitSwitch.outputG >> dynPosi.v
    # all axes
    dynMat = su.makeFakeFollMatrix(
        dynPosi, n.format(type="dynMat"), "xyz", rotOrder)

    # create fakeFoll matrix nodes for all three axes at static params,
    # for autoRot and ctrl rotations
    ctrlGrp = ctrl.controlGroup.get()
    statPosi = ctrlGrp.translate.inputs()[0]
    statTripMat = su.makeFakeFollMatrix(
        statPosi, n.format(type="statTripMat"), "xyz", rotOrder)
    jnt.jointOrient.set(0, 0, 0)

    # wtAdd switches between autorotate along surf movements
    autoSwitch = pmc.nt.WtAddMatrix(n=n.format(type="autoSwitch"))
    dynMat.output >> autoSwitch.wtMatrix[0].matrixIn
    ctrl.autoRotate >> autoSwitch.wtMatrix[0].weightIn
    statTripMat.output >> autoSwitch.wtMatrix[1].matrixIn
    flip = pmc.nt.Reverse(n=n.format(type="autoRotFlip"))
    ctrl.autoRotate >> flip.inputX
    flip.outputX >> autoSwitch.wtMatrix[1].weightIn

    # getting all xforms caused variably by normals/tangents
    # and ctrl rotations into ONE matrix decompose it
    # autoSwitch[0] * cg.inv[1] * c.m[2] * parConG.m[3] * cg.m[4]
    parGrp = ctrl.getParent()
    jntRot = mu.xformFromSpaces(
        [autoSwitch.matrixSum, ctrlGrp.im, ctrl.m, parGrp.m, ctrlGrp.m], 
        n.format(type="xforms"), rotOrder)
    dynPosi.position >> jnt.translate
    jntRot.outputRotate >> jnt.rotate


def addRigJnt(surf, n, names, rotOrder):
    """Make geoConstrained rig joint, follicle and ClosestPointOnSurface.
    User moves joint around and follicle follows, to preserve params.
    At rig time, connection is removed and joint is parented under foll"""

    # need the transform
    if isinstance(surf, pmc.nt.NurbsSurface):
        surf = surf.getTransform()
    elif not hasattr(surf, "layeredTexture"):
        pmc.warning("addRigJnt input requires a nurbs surface")
        return

    bkTools.mayaSceneUtil.displayTextures()
    # pmc.joint freaks out if selection is not perfect.
    # just clear it
    pmc.select(clear=True)

    grp = surf.getParent()
    # make radius dependent on size of the surface - 1/2 its square "side length"
    jnt = pmc.joint(n=n.format(type=names["joint"]), radius=surf.area() ** .5 / 2)
    jnt.setParent(grp)
    pmc.geometryConstraint(surf, jnt)
    cpos = pmc.nt.ClosestPointOnSurface(n=n.format(type="CPOS"))
    # cpos uses .ws, posi uses .local
    # before rigging, may have wierd results if xformed
    # but rigging inputs worldspace position to CPOS and it works out
    surf.ws.connect(cpos.inputSurface)
    jnt.translate.connect(cpos.inPosition)

    # ctrl should only be oriented according to normal, not U and V
    #ax = mu.getAxisForVector(self.follVec)
    ctrlGrp, posi = su.fakeFollicle(
        surf, name=n.format(type="stat{0}"), local=True, 
        axes=rotOrder[0], rotOrder=rotOrder)[0:2]
    ctrlGrp.setParent(surf.sCtrlsGrp.get())
    # follicles are percent based ONLY, the fuckers.
    # so the surface is normalized 0-1 in both u and v
    cpos.parameterU.connect(posi.u)
    cpos.parameterV.connect(posi.v)

    # so surf can find its jnts later
    jnt.message.connect(surf.unriggedJnts, nextAvailable=True)

    setupJntLimits(surf, jnt, posi, n)
    jnt.addAttr("mirror", at="message")

    pmc.select(jnt)
    return jnt


def setupJntLimits(srf, jnt, posi, name):
    """Setup limits and highlighted area at jnt-creation.
    then at rig-time, will need to connect cpos.param to jnt.preclamped
    and jnt.clamped to foll.param"""

    # attributes to jnt
    jnt.addAttr("SurfaceUV_LimitsOnJoint", at="bool", dv=1, k=False)
    jnt.SurfaceUV_LimitsOnJoint.showInChannelBox(True)
    jnt.addAttr("rangeV", min=0.0, max=0.999, dv=0.999, k=False)
    jnt.rangeV.showInChannelBox(True)
    jnt.addAttr("rangeU", min=0.0, max=0.999, dv=0.999, k=False)
    jnt.rangeU.showInChannelBox(True)
    jnt.addAttr("minMultLoop", dv=-.5, k=False, h=True)
    jnt.addAttr("minMultOpen", dv=-1.0, k=False, h=True)
    jnt.addAttr("preclampedU", k=False, h=True)
    jnt.addAttr("clampedU", k=False, h=True)
    jnt.addAttr("preclampedV", k=False, h=True)
    jnt.addAttr("clampedV", k=False, h=True)
    jnt.addAttr("activeAreaColor", type="float3", usedAsColor=True, k=False)
    jnt.activeAreaColor.showInChannelBox(True)

    uRamp, vRamp = setJntColor(srf, jnt, name)

    # return values depend on periodic state:
    # min + max floatCorrects for open,
    # min + max ramps, and isWrap floatLogic for periodic
    isLoopU = srf.formInU() == "periodic"
    isLoopV = srf.formInV() == "periodic"
    nodesU = hiliteDimension(posi.u, jnt.rangeU, uRamp, name+"U", isLoopU)
    nodesV = hiliteDimension(posi.v, jnt.rangeV, vRamp, name+"V", isLoopV)

    # create everything needed to limit joint params,
    # but final node (varies) needs cpos.param input and
    # foll.param output
    inAttrU, outAttrU = limitJntInDimension(posi.u, nodesU, name+"U", isLoopU)
    inAttrV, outAttrV = limitJntInDimension(posi.v, nodesV, name+"V", isLoopV)

    # proxy attrs on jnt for each in and out
    jnt.preclampedU >> inAttrU
    outAttrU >> jnt.clampedU
    jnt.preclampedV >> inAttrV
    outAttrV >> jnt.clampedV


def setJntColor(srf, jnt, name):
    """Determine color for the given joint, and create highlight connections:
    uRamp >> vRamp >> new layer on texture"""

    texture = srf.layeredTexture.get()
    # get good color with HSV and golden ratio
    gr = 0.618033988749895
    # dumb, two fields named inputs so hack it
    textureLayers = texture.attr("inputs")
    #i = len(textureLayers.getArrayIndices())
    # connect to last index
    #i = textureLayers.getArrayIndices()[-1]
    i = bkTools.mayaSceneUtil.nextAvailableIndex(textureLayers)
    # .54 means we start with a yellow
    # each index offsets hue by golden ratio
    hue = (.54 + (gr * i)) % 1.0
    #autoColor = pmc.dt.Color.hsvtorgb((hue, .7, .9))
    # add colors, more saturated and darker
    autoColor = pmc.dt.Color.hsvtorgb((hue, .9, .6))
    jnt.activeAreaColor.set(autoColor)

    uRamp = pmc.nt.Ramp(n=name.format(type="textureRampU"))
    uRamp.t.set(1)
    vRamp = pmc.nt.Ramp(n=name.format(type="textureRampV"))

    # each ramp is a strip limited in one dimension (u and v)
    # together activeAreaColor is trimmed to relevant square
    jnt.activeAreaColor >> uRamp.colorEntryList[0].color
    uRamp.outColor >> vRamp.colorEntryList[0].color

    # add this jnt's highlight color to layered texture
    vRamp.outColor >> textureLayers[i].color
    # make invisible if user checks LimitOnJoint attr off
    jnt.SurfaceUV_LimitsOnJoint >> textureLayers[i].isVisible
    # blend ADD
    textureLayers[i].blendMode.set(4)

    # blend mode is DESATURATE, which is the only option that works
    # well enough to blend multiple bright colors
    #textureLayers[i].blendMode.set(11)
    # add new blank
    #textureLayers[i+1].color.set(1, 1, 1)

    return uRamp, vRamp


def hiliteDimension(pOrig, pRange, ramp, name, periodic):
    """Use foll's parameter and param range to
    create min and max nodes, modulo (if periodic)
    and ramp nodes for highlighting jnt's range"""
    pmc.requires("lookdevKit", "1.0", nodeType="floatCorrect")

    mn = pmc.nt.FloatCorrect(n=name.format(type="min"))
    pOrig >> mn.offset
    pRange >> mn.inFloat
    jnt = pRange.node()

    # bkColor is BLACK, so that BLEND MODE can be set
    # to LIGHTEN
    bkColor = (0, 0, 0)

    mx = pmc.nt.FloatCorrect(n=name.format(type="max"))
    pOrig >> mx.offset
    pRange >> mx.inFloat

    nodes = [mn, mx]

    if periodic:
        jnt.minMultLoop >> mn.gain
        mx.gain.set(.5)

        # modulo the min and max, test for wrapping
        #mnMod = pmc.nt.Ramp(n=name.format(type="minMod"))
        #mn.outFloat >> mnMod.v
        mnMod = bkTools.mayaSceneUtil.quickModulo(name.format(type="minMod"))
        mn.outFloat >> mnMod.inputValue

        #mxMod = pmc.nt.Ramp(n=name.format(type="maxMod"))
        #mx.outFloat >> mxMod.v
        mxMod = bkTools.mayaSceneUtil.quickModulo(name.format(type="maxMod"))
        mx.outFloat >> mxMod.inputValue

        # float logic + blend colors so test can be reused later
        isWrap = pmc.nt.FloatLogic(n=name.format(type="isWrap"))
        # if min is greater than or equal to max, that means it's a wrap
        mnMod.outValue >> isWrap.floatA
        mxMod.outValue >> isWrap.floatB
        isWrap.operation.set(5)
        color = pmc.nt.BlendColors(n=name.format(type="color"))
        # True is color1, False color2
        isWrap.outBool >> color.blender
        colorSource = ramp.colorEntryList[0].color.inputs(plugs=True)[0]
        colorSource >> color.color1
        color.color2.set(bkColor)

        mnMod.outValue >> ramp.colorEntryList[0].position
        mxMod.outValue >> ramp.colorEntryList[1].position
        # beginning of ramp is highlight color IF
        # it's a wrap, otherwise background color
        color.output >> ramp.colorEntryList[2].color

        nodes = [mnMod, mxMod, isWrap]
    else:
        jnt.minMultOpen >> mn.gain
        mx.gain.set(1)

        # clamp min and max
        mn.clampOutput.set(True)
        mx.clampOutput.set(True)

        mn.outFloat >> ramp.colorEntryList[0].position
        mx.outFloat >> ramp.colorEntryList[1].position
        ramp.colorEntryList[2].color.set(bkColor)

    ramp.interpolation.set(0)

    # max ENDS allowed area, so back to background color
    ramp.colorEntryList[1].color.set(bkColor)
    ramp.colorEntryList[2].position.set(0)


    return nodes


def limitJntInDimension(pOrig, nodes, name, periodic):
    """Remap ctrl param to ensure the jnt stays inside allowed area.
    Return input and output attrs for connection at rig-time
    (cpos.param and foll.param, respectively)"""

    mn = nodes[0]
    mx = nodes[1]
    if periodic:
        isWrap = nodes[2]
        paramRemap = pmc.nt.RemapValue(n=name.format(type="paramRemap"))
        # remap needs 5 entries on the graph: min, max, 0, 1, & flip
        # max & flip are interp "none"
        mn.outValue >> paramRemap.value[0].value_Position
        mn.outValue >> paramRemap.value[0].value_FloatValue
        paramRemap.value[0].value_Interp.set(1)
        mx.outValue >> paramRemap.value[1].value_Position
        mx.outValue >> paramRemap.value[1].value_FloatValue
        paramRemap.value[1].value_Interp.set(0)

        # get flip value, put it on the remap graph with value min
        flipCond = pmc.nt.Condition(n=name.format(type="origAboveHalf"))
        pOrig >> flipCond.firstTerm
        flipCond.secondTerm.set(.5)
        flipCond.operation.set("Greater Than")
        flipCond.colorIfTrueR.set(-.5)
        flipCond.colorIfFalseR.set(.5)
        flip = pmc.nt.AddDoubleLinear(n=name.format(type="flipVal"))
        pOrig >> flip.input1
        flipCond.outColorR >> flip.input2
        flip.output >> paramRemap.value[2].value_Position
        mn.outValue >> paramRemap.value[2].value_FloatValue
        paramRemap.value[2].value_Interp.set(0)

        # remap needs values @ position 0 and 1, based on isWrap result
        loopData = pmc.nt.BlendColors(n=name.format(type="remapData"))
        isWrap.outBool >> loopData.blender
        # color1 is wrap: p0 val is 0, p1 val is 1, p0 interp is linear
        loopData.color1.set(0, 1, 1)
        # if NO wrap, position 0 and 1 values are based on pOrig value:
        # pOrig > .5 (flip val < .5), 0 val is max; pOrig < .5, 0 val is min
        mx.outValue >> flipCond.colorIfTrueG
        mn.outValue >> flipCond.colorIfFalseG
        flipCond.outColorG >> loopData.color2R
        flipCond.outColorG >> loopData.color2G
        loopData.color2B.set(0)

        paramRemap.value[3].value_Position.set(0)
        loopData.outputR >> paramRemap.value[3].value_FloatValue
        loopData.outputB >> paramRemap.value[3].value_Interp
        paramRemap.value[4].value_Position.set(1)
        loopData.outputG >> paramRemap.value[4].value_FloatValue

        return paramRemap.inputValue, paramRemap.outValue

    else:
        clamp = pmc.nt.Clamp(n=name.format(type="clamp"))
        mn.outFloat >> clamp.minR
        mx.outFloat >> clamp.maxR

        return clamp.inputR, clamp.outputR
