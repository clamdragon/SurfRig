"""Older functions related to surface-based rigging."""
import pymel.core as pmc



def getAffectedClusters(surf):
    """Best compromise I've found so far for finding affected skin clusters. 
    WILL find clusters affected by BIND joints which have some kind of
    DIRECT connection to rig joints, but indirect constraints may not work."""
    return set([sc for j in surf.future(af=True) if isinstance(j, pmc.nt.Joint)
                for sc in j.lockInfluenceWeights.outputs()])


def getSelectedSurfs():
    """return the TRANSFORM node"""
    surfs = [s for s in pmc.ls(sl=True, transforms=True) if
             isinstance(s.getShape(), pmc.nt.NurbsSurface)]

    return surfs


def organizeNodes():
    """Make containers for each surface in the scene and add
    all DG (NOT DAG) nodes to it for scene organization"""
    surfs = [s for s in pmc.ls(type="transform") if hasattr(s, "layeredTexture")]
    for s in surfs:
        nodes = set(s.future(allFuture=True))
        # also need some nodes connected to ctrls and joints
        ctrls = s.controls.get()
        for c in ctrls:
            j = c.rangeU.outputs()[0]
            nodes.update(c.history(), j.future(), j.history())
        nodes = [n for n in nodes if not isinstance(n, pmc.nt.DagNode)]
        pmc.container(name=s.name()+"_assets", addNode=nodes)


# trying to reduce complex edge sort to just True/False
#
def polyEdgeSort(self, other, direc, sel):
    # vertices for the edge being compared to
    vts = [v for v in iter(other.connectedVertices())]
    # conn = [e for e in getConnectedCmpnts([vts[direc]], "Edges") if e != self]
    # get all of the edges flowing from either the [0] or [1] vert
    conn = [e for e in iter(vts[direc].connectedEdges()) if e != other]
    # get overlap between selection and conn...
    # should be exactly one edge
    try:
        nex = list(set(conn) & set(sel))[0]
    except IndexError:
        # no edges flowing from vert are in selection
        # usually means end of selected edge arc
        # can I assume that this means it's in the
        # other direction?
        return not bool(direc)
    else:
        # loop continues in this direc, see if it's target
        if self == nex:
            return bool(direc)
        else:
            # next up
            return polyEdgeSort(self, nex, direc, sel)


def getFacePerimeterCurve(faces):
    pmc.select(faces)
    pmc.evalContinue("ConvertSelectionToEdgePerimeter")
    return pmc.PyNode(pmc.polyToCurve()[0])


def polyQuadToNurbs(f):
    pts = f.getPoints()
    # must rearrange pts - they come in in clockwise fashion,
    # indeces 2 and 3 must be swapped
    pts[2], pts[3] = pts[3], pts[2]
    pl = pmc.nurbsPlane(d=1, ch=0)[0]
    pl.setCVs(pts)
    pl.updateSurface()
    return pl

def setMode(m):
    ipts = [i for i in lt.attr("inputs")]
    for i in ipts[:-1]:
        i.blendMode.set(m)


def getEndEdges(sel):
    edges = []
    for edge in sel:
        edges.extend([e for e in iter(edge)])

    ends = {}
    for e in edges:
        vts = [v for v in iter(e.connectedVertices())]
        for v in vts:
            try:
                # if it exists, it's a double-occurrence vert, remove
                ends.pop(v)
            except KeyError:
                # otherwise, remember it
                ends[v] = e
    return ends


def fixStaticOffset():
    """Old way to get offset for ctrl->jnt orientConstraint was
    foll.rotate - ctrl.rotate,
    because at dyn = static param, dynRot = statRot.
    But blendshapes and clusters can change that."""
    sel = pmc.ls(sl=True)
    oc = sel[0]
    for oc in sel:
        n = oc.name().replace("_ctrlJntRot", "{0}")
        jnt = oc.constraintRotate.outputs()[0]
        inv = oc.cpim.inputs()[0]
        ctrl = oc.target[0].targetRotate.inputs()[0]
                
        offsetMat = pmc.nt.MultMatrix(n=n.format("_offsetMatrix"))
        ctrl.parentMatrix >> offsetMat.matrixIn[0]
        inv.outputMatrix >> offsetMat.matrixIn[1]
        offsetRot = pmc.nt.DecomposeMatrix(n=n.format("_offsetRot"))
        offsetMat.matrixSum >> offsetRot.inputMatrix
        offsetFix = pmc.nt.MultiplyDivide(n=n.format("_offsetFix"))
        offsetRot.outputRotate >> offsetFix.input1
        offsetFix.input2.set(-1, -1, -1)
        offsetFix.output >> oc.offset
        #offsetRot.outputRotate >> oc.offset
        oc.setParent(jnt)


def makeAssets():
    surfs = [s for s in pmc.ls(type="transform") if hasattr(s, "layeredTexture")]
    for s in surfs:
        nodes = set(s.future(allFuture=True) + s.future(leaf=False))
        # also need some nodes connected to ctrls and joints
        ctrls = s.controls.get()
        for c in ctrls:
            j = c.rangeU.outputs()[0]
            nodes.update(c.history(), j.future(), j.history())
        nodes = [n for n in nodes if not isinstance(n, pmc.nt.DagNode)]
        cont = pmc.container(name=s.name()+"_assets", addNode=nodes)
        s.addAttr("container", at="message")
        cont.addAttr("surface", at="message")
        s.container >> cont.surface


def makeMirrorable():
    ctrls = [c for c in pmc.ls() if 
        (hasattr(c, "parentControls") and not hasattr(c, "childControls"))]
    for c in ctrls:
        c.addAttr("mirror", at="message")
        mirC = c.rangeU.outputs()[0].mirror.get().rangeU.inputs()[0]
        try:
            c.mirror >> mirC.mirror
        except AttributeError:
            pass

    for p in pars:
        if not hasattr(p, "mirror"):
            p.addAttr("mirror", at="message")


def fixPosiWeights():
    parCtrls = [p for p in pmc.ls() if hasattr(p, "childControls")]
    parCtrls
    for p in parCtrls:
        wtPosi = p.controlGroup.get().t.inputs()[0]
        ind = wtPosi.u.getArrayIndices()
        print(p, ind)
        for ctrl in p.childControls.outputs():
            posi = ctrl.controlGroup.get().t.inputs()[0]
            for i in ind:
                if wtPosi.u[i].get() == posi.u.get() and wtPosi.v[i].get() == posi.v.get():
                    print(i, ctrl)
                    attr = p.attr(ctrl.replace("CTRL", "Weight"))
                    attr >> wtPosi.weight[i]


def fixJntAttr():
    jnts = [j for j in pmc.ls(type="joint") if hasattr(j, "rangeU")]
    for j in jnts:
        #j.addAttr("origPos", type="float3", uac=False)
        #j.origPos.set(j.getTranslation(ws=True))
        #j.origPos.lock()
        posi = j.rangeU.inputs()[0].controlGroup.get().t.inputs()[0]
        j.addAttr("paramU", min=0.0, max=1.0, k=False, dv=posi.u.get())
        j.paramU >> posi.u
        j.paramU.lock()
        j.addAttr("paramV", min=0.0, max=1.0, k=False, dv=posi.v.get())
        j.paramV >> posi.v
        j.paramV.lock()
        j.paramV.unlock()
        j.paramV.get()
        


def xformsToJnt():
    """Select DYN_FOLLs and use this to remove them and get ALL xforms onto rigJnt
    BONUS: xforms are more durable and more accurate!"""
    sel = pmc.ls(sl=True)
    for foll in sel:
        j = foll.getChildren()[0]
        posi = foll.t.inputs()[0]
        autoRot = foll.r.inputs(scn=True)[0]
        dynMat = autoRot.color1.inputs(scn=True)[0].inputs()[0]
        statTripMat = autoRot.color2.inputs(scn=True)[0].inputs()[0]
        ctrl = j.r.inputs()[0].target[0].targetRotate.inputs()[0]
        ctrlGrp = ctrl.getParent(generations=2)
        j.r.disconnect()
        j.setParent(foll.getParent())
        n = j.name().replace("_RIGJNT", "{0}")
        j.jointOrient.set(0, 0, 0)

        # (autoSwitch[0] * cg.inv[1])[0] * (c.m[0] * cg.m[1])[1]

        # wtAdd switches between autorotate along surf movements
        autoSwitch = pmc.nt.WtAddMatrix(n=n.format("_autoSwitch"))
        dynMat.output >> autoSwitch.wtMatrix[0].matrixIn
        ctrl.autoRotate >> autoSwitch.wtMatrix[0].weightIn
        statTripMat.output >> autoSwitch.wtMatrix[1].matrixIn
        flip = pmc.nt.Reverse()
        ctrl.autoRotate >> flip.inputX
        flip.outputX >> autoSwitch.wtMatrix[1].weightIn

        """
        # multiply autoMatrix by control group's inverse matrix, to get
        # into the same space as ctrl.m * cg.m
        spaceFixMat = pmc.nt.MultMatrix(n=n.format("_autoSpaceFix"))
        autoSwitch.matrixSum >> spaceFixMat.matrixIn[0]
        ctrlGrp.inverseMatrix >> spaceFixMat.matrixIn[1]
        # have to get ctrl rots relative to surf local space, since
        # autoRot has ctrlGrp.matrix "taken out" ( * inverseMatrix)
        ctrlMat = pmc.nt.MultMatrix(n=n.format("_ctrlRotMat"))
        ctrl.matrix >> ctrlMat.matrixIn[0]
        ctrlGrp.matrix >> ctrlMat.matrixIn[1]

        jntMat = pmc.nt.MultMatrix(n=n.format("_jntMat"))
        spaceFixMat.matrixSum >> jntMat.matrixIn[0]
        ctrlMat.matrixSum >> jntMat.matrixIn[1]
        """
        asm = autoSwitch.matrixSum.get()
        cgim = ctrlGrp.inverseMatrix.get()
        cm = ctrl.matrix.get()
        cgm = ctrlGrp.matrix.get()
        r1 = (asm * cgim) * (cm * cgm)
        r2 = asm * cgim * cm * cgm
        print(r1)
        print(r2)
        jntMat = pmc.nt.MultMatrix(n=n.format("_jntMat"))
        autoSwitch.matrixSum >> jntMat.matrixIn[0]
        ctrlGrp.inverseMatrix >> jntMat.matrixIn[1]
        ctrl.matrix >> jntMat.matrixIn[2]
        ctrlGrp.matrix >> jntMat.matrixIn[3]

        jntRot = pmc.nt.DecomposeMatrix(n=n.format("_jntRot"))
        jntMat.matrixSum >> jntRot.inputMatrix
        posi.position >> j.t
        jntRot.outputRotate >> j.r

def fixParentRots(wtMats):
    for sclMat in wtMats:
        mat, parCtrl = sclMat.inputs()
        wtAttr = sclMat.inScale.inputs(plugs=True)[0]
        xforms = sclMat.o.outputs()[0]
        transAttr = xforms.outputTranslate.outputs(scn=True, plugs=True)[0]
        blendRot = xforms.outputRotate.outputs(scn=True)[0]
        rotAttr = blendRot.output.outputs(plugs=True)[0]

        mat.matrixSum >> xforms.inputMatrix
        wtMult = pmc.nt.MultDoubleLinear()
        parCtrl.rotateChildren >> wtMult.input1
        wtAttr >> wtMult.input2
        sclTrans = pmc.nt.Premultiply()
        wtAttr >> sclTrans.inAlpha
        xforms.outputTranslate >> sclTrans.inColor
        sclTrans.outColor >> transAttr
        sclRot = pmc.nt.Premultiply()
        wtMult.output >> sclRot.inAlpha
        xforms.outputRotate >> sclRot.inColor
        sclRot.outColor >> rotAttr
        pmc.delete(blendRot, sclMat)

"""
# setup parameter limits at jnt-creation
# at rig-time, will need to 
def setupJntLimits(srf, ctrl, jnt, cpos, staticFoll, dynFoll, name):
    # attributes to jnt
    ctrl.addAttr("rangeV", min=0.0, max=1.0, dv=1)
    ctrl.rangeV >> jnt.rangeV
    ctrl.addAttr("rangeU", min=0.0, max=1.0, dv=1)
    ctrl.rangeU >> jnt.rangeU
    jnt.addAttr("minMultLoop", dv=-.5)
    jnt.addAttr("minMultOpen", dv=-1.0)

    if srf.form == "open":
        limitParamOpen(ctrl, cpos, statFoll, dynFoll, name, "V")
    else:
        limitParamLoop(ctrl, cpos, statFoll, dynFoll, name)

    # U direction is always open
    limitParamOpen(jnt, cpos, statFoll, dynFoll, name)


# working - 7 nodes
# requires attrs rangeV and minMultLoop (-.5 due to stupid floatCorrect nodes)
# offsets dynamicV to , then un-offsets after %
#
def limitParamLoop(ctrl, cpos, staticFoll, dynFoll, name):
    # Get min and max params 
    minV = pmc.nt.FloatCorrect(n=name.format("_minV"))
    staticFoll.pv >> minV.offset
    ctrl.rangeV >> minV.inFloat
    ctrl.minMultLoop >> minV.gain
    maxV = pmc.nt.FloatCorrect(n=name.format("_maxV"))
    staticFoll.pv >> maxV.offset
    ctrl.rangeV >> maxV.inFloat
    maxV.gain.set(.5)

    # Offset is the difference between origV and .5
    offset = pmc.nt.AddDoubleLinear(n=name.format("_offsetV"))
    staticFoll.pv >> offset.input1
    offset.input2.set(-.5)

    # Take current V, subtract offset,
    # mod the fuxxored current V then un-offset.
    # This remaps the dynamic parameter range to straddle origV
    inV = pmc.nt.FloatMath(n=name.format("_currV"))
    cpos.pv >> inV.floatA
    offset.output >> inV.floatB
    inV.operation.set(1)
    mod = pmc.nt.Ramp(n=name.format("_modCurrV"))
    offset.output >> mod.colorOffsetR
    inV.outFloat >> mod.v

    clamp = pmc.nt.Clamp(n=name.format("_clampV"))
    minV.outFloat >> clamp.minR
    maxV.outFloat >> clamp.maxR
    mod.outColorR >> clamp.inputR

    # Mod output so values wrap around to 0-1
    modOutput = pmc.nt.Ramp(n=name.format("_modResultV"))
    clamp.outputR >> modOutput.v
    modOutput.outColorR >> dynFoll.pv


# easy version for open directions of srf
# call: limitParamOpen(jnt, statFoll, dynFoll, name, "U")
#
def limitParamOpen(jnt, cpos, statFoll, dynFoll, name, param="U"):
    rngAttr = jnt.attr("range"+param)
    statParam = statFoll.attr("parameter"+param)
    ctrlParam = cpos.attr("parameter"+param)
    dynParam = dynFoll.attr("parameter"+param)

    # for p in ("U", "V"):
    minP = pmc.nt.FloatCorrect(n=name.format("_min"+param))
    minP.clampOutput.set(True)
    rngAttr >> minP.inFloat
    statParam >> minP.offset
    jnt.minMultOpen >> minP.gain

    maxP = pmc.nt.FloatCorrect(n=name.format("_max"+param))
    maxP.clampOutput.set(True)
    rngAttr >> maxP.inFloat
    statParam >> maxP.offset
    maxP.gain.set(1.0)

    clampP = pmc.nt.Clamp(n=name.format("_clamp"+param))
    minP.outFloat >> clampP.minR
    maxP.outFloat >> clampP.maxR
    ctrlParam >> clampP.inputR
    clampP.outputR >> dynParam



# TEMP arrangement just for visual feedback?
# or permanent to allow for flattened surfs?
# likely to be much slower than limitJnt simple-node solution
#
# duplcate srf curves to make subsurf with size given
# by jnt first, then later driven by ctrl
#
# if %min > %max:
# c1.max = 1
# c2.min = 0
# else:
# c1.max = orig
# c2.min = orig
# attach curves
# loft
# mtx = pmc.dt.Matrix([
[3.53336248542e-17, 0.0, -0.159128499727, 0.0], 
[0.0, 0.159128499727, 0.0, 0.0], 
[0.159128499727, 0.0, 3.53336248542e-17, 0.0], 
[0.372092039558, 17.2880912915, 1.22370245316, 1.0]])
#
def makeJntSrfLoop(srf, jnt, foll, name):
    minP = pmc.nt.FloatCorrect(n=name.format("_minV"))
    foll.pv >> minP.offset
    jnt.rangeV >> minP.inFloat
    jnt.minMultLoop >> minP.gain
    maxP = pmc.nt.FloatCorrect(n=name.format("_maxV"))
    foll.pv >> maxP.offset
    jnt.rangeV >> maxP.inFloat
    maxP.gain.set(.5)

    minM = pmc.nt.Ramp(n=name.format("_minModV"))
    minP.outFloat >> minM.v
    minM.interpolation.set(1)
    maxM = pmc.nt.Ramp(n=name.format("_maxModV"))
    maxP.outFloat >> maxM.v
    maxM.interpolation.set(1)

    cond = pmc.nt.Condition(n=name.format("_loopCondV"))
    minM.outColorR >> cond.firstTerm
    maxM.outColorR >> cond.secondTerm
    cond.operation.set(2)
    cond.colorIfTrueR.set(1)
    # auto G = 0
    foll.pv >> cond.colorIfFalseR
    foll.pv >> cond.colorIfFalseG

    minU = pmc.nt.FloatCorrect(n=name.format("_minU"))
    foll.pu >> minU.offset
    jnt.rangeU >> minU.inFloat
    jnt.minMultOpen >> minU.gain
    minU.clampOutput.set(True)
    maxU = pmc.nt.FloatCorrect(n=name.format("_maxU"))
    foll.pu >> maxU.offset
    jnt.rangeU >> maxU.inFloat
    maxU.gain.set(1.0)
    maxU.clampOutput.set(True)

    crvs = []
    for u in (minU.outFloat, maxU.outFloat):
        crv1 = pmc.nt.CurveFromSurfaceIso(n=name+"_cfs")
        srf.ws >> crv1.inputSurface
        crv1.idr.set("V")
        u >> crv1.iv
        minM.outColorR >> crv1.min
        cond.outColorR >> crv1.max

        crv2 = pmc.nt.CurveFromSurfaceIso(n=name+"_cfs")
        srf.ws >> crv2.inputSurface
        crv2.idr.set("V")
        u >> crv2.iv
        cond.outColorG >> crv2.min
        maxM.outColorR >> crv2.max

        #crv = pmc.createNode("attachCurve", n=name.format("_crv"))
        #crv1.outputCurve >> crv.inputCurve1
        #crv2.outputCurve >> crv.inputCurve2
        #crvs.append(crv)

        # breaks at attach step
        # try output to curveShape before attach?

        c1 = pmc.createNode("nurbsCurve")
        c2 = pmc.createNode("nurbsCurve")
        crv1.outputCurve >> c1.create
        crv2.outputCurve >> c2.create
        crvs.extend([c1, c2])
        # loft?

    # for visual feedback only during creation, 
    # curves are good enough
    return crvs
    #return subSrf
"""




# STICKY LIPS


import pymel.core as pmc

jnts = pmc.selected()

h = len(jnts)/2
pairs = [(jnts[i], jnts[i+4]) for i in range(h)]
bsCtrl = jnts[0].rangeU.inputs()[0].getShapes()[1]
bsCtrl.addAttr("leftMouthZip", dv=0.0, min=0.0, max=1.0, k=True)
bsCtrl.addAttr("leftMouthZipPosition", dv=0.0, min=0.0, max=1.0, k=True)
bsCtrl.addAttr("rightMouthZip", dv=0.0, min=0.0, max=1.0, k=True)
bsCtrl.addAttr("rightMouthZipPosition", dv=0.0, min=0.0, max=1.0, k=True)


for up, low in pairs:
    upPosi = up.t.inputs()[0]
    upParam = upPosi.u.inputs()[0]
    lowPosi = low.t.inputs()[0]
    lowParam = lowPosi.u.inputs()[0]

    avg = pmc.nt.PlusMinusAverage()
    avg.op.set("Average")
    upParam.outputR >> avg.input2D[0].i2x
    upParam.outputG >> avg.input2D[0].i2y
    lowParam.outputR >> avg.input2D[1].i2x
    lowParam.outputG >> avg.input2D[1].i2y

    for j, posi, p in ((up, upPosi, upParam), (low, lowPosi, lowParam)):

        osVal = 1
        if "_L_" in j.name():
            env = bsCtrl.leftMouthZip
            pos = bsCtrl.leftMouthZipPosition
            if j is low:
                osVal = -1
        elif "_R_" in j.name():
            env = bsCtrl.rightMouthZip
            pos = bsCtrl.rightMouthZipPosition
            if j is up:
                osVal = -1
        else:
            pmc.warning("Unknown joint name {0}".format(j))
            break
        
        blendParam = pmc.nt.BlendColors()
        
        if "Corner" in j.name():
            osVal *= .04
            env >> blendParam.blender
        else:
            osVal *= .08
            # additional node
            mult = pmc.nt.MultDoubleLinear()
            env >> mult.input1
            pos >> mult.input2
            mult.output >> blendParam.blender
        
        offset = pmc.nt.AddDoubleLinear()
        avg.o2x >> offset.input1
        offset.input2.set(osVal)

        # color1: "on", or avg'd
        offset.output >> blendParam.color1R
        avg.o2y >> blendParam.color1G
        p.outputR >> blendParam.color2R
        p.outputG >> blendParam.color2G

        blendParam.outputR >> posi.u
        blendParam.outputG >> posi.v





jnts = pmc.selected()
jnts

openCurve = pmc.circle(s=len(jnts)-1, ch=0)[0]
#pmc.closeCurve(openCurve, rpo=True, ch=0)
pmc.rebuildCurve(openCurve, rt=0, kcp=True, kr=0, rpo=True, ch=0)
closedCurve = pmc.duplicate(openCurve)[0]


for j, cv in zip(jnts, openCurve.cv):
    posi = j.t.inputs()[0]
    # create another posi which has input surface as pre-wire shape
    prewire = pmc.duplicate(posi, ic=True, n=posi.name().replace("dynposi", "prewire"))[0]
    prewire.position >> cv
    
for i in range(len(jnts)/2):
    j1 = jnts[i]
    j2 = jnts[-1-i]
    cv1 = closedCurve.cv[i]
    cv2 = closedCurve.cv[-1-i]
    
    posi1 = pmc.PyNode(j1.t.inputs()[0].replace("dynposi", "prewire"))
    posi2 = pmc.PyNode(j2.t.inputs()[0].replace("dynposi", "prewire"))
    
    avgPos = pmc.nt.PlusMinusAverage()
    avgPos.op.set("Average")
    posi1.p >> avgPos.input3D[0]
    posi2.p >> avgPos.input3D[1]
    avgPos.output3D >> cv1
    avgPos.output3D >> cv2

# this method will hinge on which surface is the .inputSurface for various surface nodes
# preclamped CPOS: pre-wire surf
# clamped dynPosi: post-wire surf
surfs = list(set(j.rangeU.inputs()[0].surface.get() for j in jnts))
for s in surfs:
    targs = [
        o for o in s.ws.outputs(plugs=True) + s.local.outputs(plugs=True)
        if "dynposi" not in o.name()]
    src = s.create.inputs(plugs=True)[0]
    for t in targs:
        src >> t

    
wire = pmc.wire(surfs)[0]
openCurve.l >> wire.baseWire[0]
closedCurve.l >> wire.deformedWire[0]

bd = surfs[0].blendDriver.inputs(shapes=True)[0]
bd.addAttr("stickyLipsStrength", min=0.0, max=1.0, k=True)
bd.addAttr("stickyLipsParam", min=0.0, max=1.0, k=True)
bd.stickyLipsParam >> wire.wireLocatorParameter[0]
bd.stickyLipsStrength >> wire.wireLocatorPercentage[0]
pmc.select(wire)

# base 0 means these are overlapping
pmc.select(closedCurve.u[.25])
pmc.select(closedCurve.u[.625])
# simplify input param to 0.0-0.5 since it loops around
# but wait, fuck, the parameter is applied to the initial curve,
# ie openCurve... hmm.
# perhaps there's a way to do it via position?




# TWO wires rather than periodic


# select rows
jnts = pmc.selected()
up = jnts[:4]
down = jnts[4:]

pts = [(0, 0, 0) for x in up]
upLip = pmc.curve(d=3, p=pts)
downLip = pmc.curve(d=3, p=pts)
    
for j, cv in zip(up, upLip.cv):
    posi = j.t.inputs()[0]
    # create another posi which has input surface as pre-wire shape
    prewire = pmc.duplicate(posi, ic=True, n=posi.name().replace("dynposi", "prewire"))[0]
    prewire.position >> cv
for j, cv in zip(down, downLip.cv):
    posi = j.t.inputs()[0]
    # create another posi which has input surface as pre-wire shape
    prewire = pmc.duplicate(posi, ic=True, n=posi.name().replace("dynposi", "prewire"))[0]
    prewire.position >> cv

surfs = list(set(j.rangeU.inputs()[0].surface.get() for j in jnts))
for s in surfs:
    targs = [
        o for o in s.ws.outputs(plugs=True) + s.local.outputs(plugs=True)
        if "dynposi" not in o.name()]
    src = s.create.inputs(plugs=True)[0]
    for t in targs:
        src >> t
    
avg = pmc.nt.AvgCurves()
upLip.l >> avg.inputCurve1
downLip.l >> avg.inputCurve2
wire = pmc.wire(surfs)[0]
upLip.l >> wire.baseWire[0]
downLip.l >> wire.baseWire[1]
avg.outputCurve >> wire.deformedWire[0]
avg.outputCurve >> wire.deformedWire[1]

pmc.select(wire)

bd = surfs[0].blendDriver.inputs(shapes=True)[0]
bd.addAttr("stickyLips", min=0.0, max=10, k=True)
conv = pmc.nt.UnitConversion()
bd.stickyLips >> conv.input
conv.output >> wire.dropoffDistance[0]
conv.output >> wire.dropoffDistance[1]