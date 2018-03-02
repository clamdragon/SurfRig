import pymel.core as pmc
from bkTools import rigCtrlUtil as rcu, matrixUtil as mu, surfaceUtil as su
import jointControls as jc


"""
Deformer-related functions for surfRig:
getSurfUvAndWeight
sortAndPruneUvs
getUvFromCtrl
makeWeightedCtrl
weightPosi
rigCluster
rigSoftMod
makeBulgeCtrl
ctrlBlendshapes
addBlendshapesToCtrls
matchBlendshapeInputs
connectAttrTo
mergeBlendshapes
"""


def getSurfUvAndWeight(c, tol=0.1):
    """Given a cluster, return a list of tuples for each surface containing
    the surface weight, the surf, and the average and weighted UV position"""
    objSet = c.message.outputs(type="objectSet")[0]
    cpos = pmc.nt.ClosestPointOnSurface()
    uvs = []
    totalWt = sum(pmc.percent(c, objSet, q=True, v=True))

    for surf in objSet:
        shape = surf.node().getTransform()
        shape.local >> cpos.inputSurface
        surfWt = sum(pmc.percent(c, surf, q=True, v=True))
        if uvs and surfWt < (totalWt * tol):
            # if surface consists of less than 10% (default) of total
            # weight, forget about it (as long as UVs isn't empty)
            continue
        pos = pmc.dt.Vector()
        for cv in surf:
            cvWt = pmc.percent(c, cv, q=True, v=True)[0]
            ind = cv.indices()[0]
            cpos.inPosition.set(shape.getCV(*ind))
            pos += cpos.position.get() * cvWt
        avgPos = pos / surfWt
        cpos.inPosition.set(avgPos)
        uvs.append((surfWt, shape, cpos.u.get(), cpos.v.get()))
    pmc.delete(cpos)

    return sortAndPruneUvs(uvs)


def sortAndPruneUvs(uvs, threshold=0.25):
    """Massage the UVs list to sort in descending order
    and remove small weights"""
    
    uvs.sort(reverse=True)
    try:
        # further prune list of low weights
        # any surf which has less than 1/4 the influence of the strongest
        minWt = uvs[0][0] * threshold
    except IndexError:
        # empty list, something went wrong
        return []
    prunedUVs = [d for d in uvs if d[0] > minWt]
    # now normalize wts
    wtSum = sum(d[0] for d in prunedUVs)
    uvs = [(w / wtSum, s, u, v) for w, s, u, v in prunedUVs]

    return uvs


def getUvFromCtrl(ctrl, wt=1.0):
    """Given a single control, get the list(s) of wt, surf, u, v for
    making weighted controls."""
    try:
        posi = ctrl.controlGroup.get().t.inputs()[0]
    except IndexError:
        #softmod or otherwise non-sticky control
        return [None, None, None, None]
    if posi.type() == "pointOnSurfaceInfo":
        return [wt, ctrl.surface.get(), posi.u.get(), posi.v.get()]
    elif posi.type() == "avgSurfacePoints":
        # only take the first entry. no need to go crazy.
        return [wt, posi.inputSurfaces[0].inputs()[0], 
                posi.u[0].get(), posi.v[0].get()]


def makeWeightedCtrl(surfs, n, rotOrder, names, shape="diamond"):
    """Multiple surfaces are possible for clusters & such, this method
    takes an ordered list of (wt, surf, u, v) and makes a weighted foll
    which sticks to several weighted points on surfaces. Orientation is
    FIXED, based on initial normal, as a connection will set off cyclecheck."""
    
    # need weighted add of multiple UVs for dynamic position
    # and static (initial) orientation
    domSurf = surfs[0][1]
    if len(set(e[1] for e in surfs)) == 1:
        # single-surface deformers get put with other surf ctrls
        par = domSurf.sCtrlsGrp.get()
        wtPar = False
    else:
        # multi-surf deformers get their own ctrlsGrp
        par = pmc.nt.Transform(
            n=n.format(type="wt_" + names["control group"]), 
            p=domSurf.sCtrlsGrp.get().getParent())
        wtPar = par
    ctrlGrp = pmc.nt.Transform(p=par)

    wtAvgPosi = pmc.nt.AvgSurfacePoints(n=n.format(type="multiPOSI"))
    weightPosi(wtAvgPosi, surfs, wtPar=wtPar)
    wtAvgPosi.position >> ctrlGrp.translate
    ctrl, ctrlGrp, offsetGrp = jc.makeFollCtrl(
        n, ctrlGrp, typeDict=names, rotOrder=rotOrder, shape=shape)
    ctrl.surface.connect(domSurf.controls, nextAvailable=True)

    # no active connection due to cycling.
    # need to ensure the posi normal goes into the right row (x, y, z)
    rm = pmc.dt.TransformationMatrix()
    rm["xyz".index(rotOrder[0])] = wtAvgPosi.n.get()
    ctrlGrp.setRotation(rm.getRotationQuaternion())

    jc.connectSizeDistFlip(domSurf, ctrl, ctrlGrp, offsetGrp, rotOrder)

    return ctrl, ctrlGrp


def weightPosi(wtAvgPosi, surfs, wtPar=None):
    """Created the weighted POSI node and forge connections
    between formatted surfs dict: (surf weight, surf, wtAvgU, wtAvgV)"""
    for i, (wt, surf, u, v) in enumerate(surfs):
        #i = wtAvgPosi.inputSurfaces.numElements()
        surf.local >> wtAvgPosi.inputSurfaces[i]
        wtAvgPosi.u[i].set(u)
        wtAvgPosi.v[i].set(v)
        wtAvgPosi.weight[i].set(wt)
        if wtPar:
            # multi-surf deformers have weighted parent space
            # so affect the wtParGrp with all surf grps
            pc = pmc.parentConstraint(surf, wtPar)
            pc.interpType.set(0)
            # connect weight to top
            wtAvgPosi.weight[i] >> pc.getWeightAliasList()[-1]


def rigCluster(handle, uvs, rotOrder, n, names):
    """Control creation method for surface clusters"""
    ctrl, ctrlGrp = makeWeightedCtrl(uvs, n, rotOrder, names)
    handle.setParent(ctrlGrp.getParent())

    # (initial) ctrlGrp.mat * ctrl.m * parGrp.m * (initial) ctrlGrp.invMat
    # is how we get ctrl rots into surface (and presumably handle) space
    cgm = mu.rotMat(ctrlGrp.matrix)
    handleXform = mu.xformFromSpaces(
        [cgm.inverse(), ctrl.m, ctrl.getParent().m, cgm], 
        n.format(type="xforms"), rotOrder)
    handleXform.outputTranslate >> handle.t
    handleXform.outputRotate >> handle.r
    handleXform.outputScale >> handle.s

    # invert double translations for ctrl and parGrp
    for xfm in (ctrl.getParent(), ctrl):
        xn = xfm.name()
        grp = pmc.group(xfm, p=xfm.getParent(), n=xn+"_DBL_XFM_GRP")
        invTrans = pmc.nt.MultiplyDivide(n=xn+"_INV_XFM")
        xfm.t >> invTrans.input1
        invTrans.input2.set(-1, -1, -1)
        invTrans.output >> grp.t

    return ctrl


def rigSoftMod(handle, uvs, rotOrder, n, names):
    """Control creation method for softMods. Creates two controls: 
    the first control affects the position of the deformer (falloff center),
    the second control affects the softMod handle itself."""

    sm = handle.outputs(type="softMod")[0]
    # control 1: circle for moving softMod falloffCenter
    # it is NOT sticky, as that sets off cyclecheck (and is limiting)
    n1 = n.format(type="POS_{type}")
    # make it a circle control by providing normal axis
    ctrCtrl, ctrCtrlGrp = makeWeightedCtrl(
        uvs, n1, rotOrder, names, shape="circle")
    #ctrlGrpRotMat = mu.rotMat(ctrCtrlGrp.matrix)
    handle.setParent(ctrCtrlGrp.getParent())
    # softMod CANNOT be parented
    ctrCtrl.deleteAttr("parentControls")
    """
    #THIS PART IS FOR CTRLS THAT MOVE WITH SURF DEFORMATIONS
    # falloffCenter is worldspace, always... so affect with:
    # surf local world mat, static ctrl grp mat, ctrl mat, ctrl grp inv rot mat
    ctrPos = mu.xformFromSpaces(
        [ctrlGrpRotMat.inverse(), ctrCtrl.matrix, ctrCtrlGrp.matrix.get()], 
        n1.format(type="xforms"), rotOrder)
    ctrPos.outputTranslate >> sm.falloffCenter
    """
    pmc.delete(ctrCtrlGrp.t.inputs()[0])
    worldLoc = pmc.spaceLocator(n=n1.format(type="worldLoc"))
    worldLoc.setParent(ctrCtrlGrp.getParent())
    pmc.makeIdentity(worldLoc)
    worldLoc.visibility.set(False)
    pmc.pointConstraint(ctrCtrl, worldLoc, maintainOffset=False)
    worldLoc.translate >> sm.falloffCenter
    
    # lock/hide scale
    rcu.setAttrChannelBox(ctrCtrl, ["scale"], False)

    hCtrl = makeBulgeCtrl(
        handle, ctrCtrl, n.format(type="BULGE_{type}"), names, rotOrder)
    
    hCtrl.addAttr("size", min=0.0, dv=sm.falloffRadius.get(), k=True)
    hCtrl.size >> sm.falloffRadius

    return hCtrl


def makeBulgeCtrl(handle, ctrCtrl, n, names, rotOrder):
    """Make inner control for softmod. Diamond for the softMod handle itself"""
    ctrlGrpRotMat = mu.rotMat(ctrCtrl.controlGroup.get().matrix)
    hCtrl = jc.makeCtrlShape(
        n.format(type=names["control"]), rotOrder, shape="diamond")
    for sh in hCtrl.getShapes():
        ctrCtrl.create.inputs()[0].radius >> sh.create.inputs()[0].radius
        pmc.scale(sh.cv, .8, .8, .8)
    hCtrl.setParent(ctrCtrl)
    pmc.makeIdentity(hCtrl)
    
    # handle xforms must be ctrl in ctrCtrlGrp AND ctrCtrl space but without
    # any of their actual xforms
    parGrp = ctrCtrl.getParent()
    handleXform = mu.xformFromSpaces([
        ctrlGrpRotMat.inverse(), ctrCtrl.inverseMatrix, parGrp.inverseMatrix,
        hCtrl.m, parGrp.matrix, ctrCtrl.matrix, ctrlGrpRotMat],
        n.format(type="xforms"), rotOrder)

    handleXform.outputTranslate >> handle.t
    handleXform.outputRotate >> handle.r
    handleXform.outputScale >> handle.s

    return hCtrl


def ctrlBlendshapes():
    """Slot for blendshapes setup button"""
    surfs = su.getSelectedSurfs(withAttr="layeredTexture")
    if not surfs:
        pmc.warning("No surfaces selected.")
        return
    for surf in surfs:
        addBlendshapesToCtrls(surf)


def addBlendshapesToCtrls(surf):
    """Initialize a surface for easy blendshape controlling"""
    with rcu.MayaUndoChunkManager():
        addTo = rcu.addNodeToAssetCB(surf.container.get())
        with rcu.NodeOrganizer(addTo):
            shape = surf.blendDriver.inputs(shapes=True)[0]

            #for bs in surf.create.inputs(type="blendShape"):
            for bs in surf.create.history(type="blendShape"):
                matchBlendshapeInputs(bs, shape)

            parents = shape.listRelatives(allParents=True)
            for ctrl in surf.controls.get():
                # .hasChild() is recursive across generations
                if ctrl not in parents:
                    rcu.addShapeToTrans(shape, ctrl)


def matchBlendshapeInputs(blendNode, driver):
    """Get all the blend shapes influencing this surface,
    and give controlling attributes to the dummy shape.
    Includes edge cases for merging, separating and renaming 
    source attributes."""
    for targName in blendNode.weight.elements():
        targAttr = blendNode.weight.attr(targName)
        try:
            srcAttr = targAttr.inputs(plugs=True)[0]
        except IndexError:
            # blend target has no source attribute - 
            # check to see if driver has attribute of the same name
            connectAttrTo(driver, targName, targAttr)

        else:
            # there IS a source attr, check if it
            # has expected name and node
            if srcAttr.node() != driver:
                pmc.warning("{0} blendshape has unknown incoming "
                            "connection! Skipped.".format(targName))
                continue

            elif srcAttr.attrName() == targName:
                continue
            
            # NAMES of source and target don't match - what to do about it?

            # check if ALL targets have been name changed. if not,
            # SPLIT the changed targets into a different srcAttr
            diffTargets = (
                a for a in srcAttr.outputs(plugs=True)
                if a.getAlias() != targName)
            if any(diffTargets):
                # srcAttr connects to differently named targs,
                # this is grounds to separate srcAttrs
                connectAttrTo(driver, targName, targAttr)
                continue

            # or maybe the driver already has an attr for the renamed target
            try:
                # effectively marge with existing srcAttr
                newSrc = getattr(driver, targName)
            except AttributeError:
                # driver doesn't have matching attr. make it so.
                pmc.renameAttr(srcAttr, targName)
            else:
                newSrc >> targAttr
                srcAttr.delete()


def connectAttrTo(node, name, destAttr):
    """Safely ensure a connection between attribute of given name on
    given node and the target attribute."""
    try:
        srcAttr = getattr(node, name)
    except AttributeError:
        node.addAttr(name, at="float", min=0, max=2, k=True)
        srcAttr = getattr(node, name)
        srcAttr.set(destAttr.get())

    srcAttr >> destAttr
    print("Successfully connected to {0}".format(name))


def mergeBlendshapes():
    """For selected surfaces, merge their blendshape driver objects into one,
    preserving all connections. If two targets have the SAME NAME, they are
    MERGED!"""
    surfs = su.getSelectedSurfs(withAttr="layeredTexture")
    if len(surfs) < 2:
        pmc.warning("Select at least two surfaces.")
        return
    # ensure no duplicate drivers
    drivers = list(set([s.blendDriver.inputs(shapes=True)[0] for s in surfs]))
    #newName = rcu.avgMayaName([d.name() for d in drivers])
    top = drivers.pop()
    with rcu.MayaUndoChunkManager():
        # top.getTransform().rename(newName+"_DAG")
        # top.rename(newName)
        for old in drivers:
            # output flag refers to numeric attributes
            for attr in old.listAttr(ud=True, output=True, k=True):
                outputs = attr.outputs(plugs=True)
                if not outputs:
                    # if it's not connected, ignore it...
                    continue

                n = attr.attrName()
                try:
                    topAttr = getattr(top, n)
                except AttributeError:
                    # if the user changed min/max before, they can do it again
                    top.addAttr(n, min=0, max=2, k=True)
                    topAttr = getattr(top, n)
                
                try:
                    i = attr.inputs(plugs=True)[0]
                except IndexError:
                    pass
                else:
                    if not topAttr.inputs():
                        i >> topAttr
                
                for o in outputs:
                    topAttr >> o

            # connect new driver shape to all surf message
            for oldSurf in old.message.outputs(type="transform"):
                top.message >> oldSurf.blendDriver

            for par in old.listRelatives(allParents=True):
                rcu.addShapeToTrans(top, par)

            pmc.delete(old)
