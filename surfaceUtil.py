import pymel.core as pmc
import matrixUtil as mu


__author__ = "Brendan Kelly"
__email__ = "clamdragon@gmail.com"


"""Functions relating to surface-based rigging"""


"""
getAllSurfs
getSelectedSurfs
fakeFollicle
makeFakeFollMatrix
getSelPolyEdges
getSymSelection
makeNiceCurveFromEdges
makeSurfFromEdges
makeOpenSurf
orientSurf
makeSimpleSurf
flattenComponents
getConnectedCmpnts
getPolyAvgNormal
getMirrorParam
closestOnSurf
avgSurfVectors
makeOrigShape
origShapeMode
mirrorSurfWeights
makeFollOnSel
makeFollicle
matchFollToObj
resetMuscleCtrls
resetMuscleCtrlsToSel
makeRibbon
makeRibbonSpline
"""



def getAllSurfs(withAttr=None):
    """Return list of all transforms in the scene which are nurbs surfaces,
    optionally only ones with the given attribute"""
    surfs = list(set([s.getTransform() for s in pmc.ls(type="nurbsSurface")]))
    if withAttr:
        return [s for s in surfs if hasattr(s, withAttr)]
    else:
        return surfs


def getSelectedSurfs(withAttr=None):
    """Return list of selected transforms which are nurbs surfaces,
    optionally only ones with the given attribute"""
    # if CVs are selected get their surface
    surfs = [s.node().getTransform() for s in pmc.ls(sl=True, type="double3")]
    surfs.extend(pmc.ls(sl=True, transforms=True))
    if withAttr:
        return list(set(s for s in surfs if hasattr(s, withAttr)))
    else:
        return list(set(surfs))


def fakeFollicle(srf, name=None, local=False, axes="xyz", rotOrder="xyz"):
    """A less expensive "follicle", made by combination of a
    pointOnSurfaceInfo and decomposed FourByFourMatrix node."""
    pmc.requires("matrixNodes", "1.0", nodeType="decomposeMatrix")

    # create a name with frame padding
    if not name:
        name = srf.name() + "_{0}" + "_#"

    g = pmc.nt.Transform(n=name.format("FOLLICLE"))
    posi = pmc.nt.PointOnSurfaceInfo(n=name.format("posi"))
    if local:
        srf.local.connect(posi.inputSurface)
    else:
        srf.ws.connect(posi.inputSurface)

    mat = makeFakeFollMatrix(posi, name.format("follMatrix"), axes, rotOrder)
    rot = pmc.nt.DecomposeMatrix(n=name.format("orient"))
    # Due to Maya bug, currently only XYZ works
    rot.inputRotateOrder.set(rotOrder)
    mat.output >> rot.inputMatrix

    posi.position >> g.t
    rot.outputRotate >> g.r

    return g, posi, rot


def makeFakeFollMatrix(posi, name, axes, rotOrder):
    """Sift through rotationOrder and axis arguments to get the matrix which
    powers POSI style fake follicle. Twist axis is always first axis in rotateOrder.
    So POSI's normal, U and V correspond to [0], [1] and [2] in rotOrder.
    Also, axes argument may pare them down to only certain ones."""
    
    # default all-axes matrix is as follows
    # pare down so "axes" argument affects matrix correctly
    kwargs = {
        rotOrder[0]: posi.normalizedNormal,
        rotOrder[1]: posi.normalizedTangentU,
        rotOrder[2]: posi.normalizedTangentV}
    for ax in "xyz":
        if ax not in axes:
            kwargs.pop(ax)
    return mu.matrixFromVectors(name, **kwargs)


def getSelPolyEdges():
    """ "Flatten" the list of selected edges"""

    # MeshEdges are "float3"s according to maya type strings
    sel = pmc.ls(sl=True, exactType="float3", flatten=True)
    for s in sel:
        if not isinstance(s, pmc.MeshEdge):
            pmc.warning("Select only mesh edges.")
            return []
    return sel


def getSymSelection():
    """If symmetry is on, edge loop's mirrored edges are also selected.
    However, user may WANT a cross-seam edge loop.
    Determine if this is the case by testing if selection
    is "along the seam", ie symSeam flag on filterExpand"""

    sel = getSelPolyEdges()
    if not sel:
        return
    # 32 masks edges, 31 masks verts - if there is anything along the seam,
    # assume user wants both sides and don't change selection
    if pmc.filterExpand(sel, sm=32, symSeam=True) or pmc.filterExpand(
            getConnectedCmpnts(sel, "Vertices"), sm=31, symSeam=True):
        return sel

    # nothing along seam: filterExpand to isolate "active" symmetry side
    pmc.select(pmc.filterExpand(sel, selectionMask=32, symActive=True))
    # refresh selection with filter
    return getSelPolyEdges()


def makeNiceCurveFromEdges(sel, symVec=None, numSpans=None):
    """Take selection of poly edges and turn into
    nice nurbs curve with seam along axis of sym (if relevant)"""

    # how many spans?
    if not numSpans:
        # clamp it to 1-8; over 8 is excessive and numSpans arg of 0 is ignored
        #numSpans = max(1, min(8, (len(sel) / 8) * 2))
        numSpans = max(1, min(8, len(sel) / 4))

    # form 2 is "best guess", pretty reliable for
    # distinguishing periodic vs open
    crv = pmc.PyNode(pmc.polyToCurve(dg=3, f=2, ch=0)[0])
    pmc.xform(crv, centerPivots=True)

    if symVec and crv.form() != "open":
        # move seam to along axis, so that
        # rebuilding the curve doesn't result in unexpected asymmetry
        intPt = getMirrorParam(crv, symVec)
        # IF it actually crosses the axis
        try:
            intPt = float(intPt.split(" ")[0])
            pmc.select(crv.u[intPt])
            pmc.mel.eval("moveNurbsCurveSeam")
        except (AttributeError, pmc.MelError):
            # AttributeError means there is no good mnirror seam.
            # could be intentional, so no warning.
            # MelError means seam is already at the best point.
            pass

    # rebuilding surface instead of curve keeps weird all-0-cv bugs away
    #
    # try rebuild curve instead of surface to help w/ recurring asym issue
    # or wait wasn't that solved by kc=0?
    #
    pmc.rebuildCurve(
        crv, rebuildType=0, keepRange=0, spans=numSpans, ch=0, rpo=True)

    return crv


def makeSurfFromEdges(name="untitled_SURF_RIG", symVec=None, numSpans=None):
    """Create a surface based on the selected mesh edges"""

    sel = getSymSelection()
    if not sel or len(sel) < 2:
        pmc.warning("Surface not created. Select two or more mesh edges.")
        return
    crv = makeNiceCurveFromEdges(sel, symVec, numSpans)

    # find distance to offset curve by
    if crv.form() == "open":
        surf = makeOpenSurf(crv, sel[0].node(), name)
    else:
        crv2 = pmc.duplicate(crv)[0]
        # loops get scaled
        pmc.scale(crv, .5, .5, .5)
        pmc.scale(crv2, 1.5, 1.5, 1.5)
        surf = pmc.loft(crv, crv2, uniform=True, n=name, ch=0)[0]
        pmc.delete(crv2)

    """
    # how many spans?
    if not numSpans:
        # (x/8)*2 ensures even numSpans rather than /4
        numSpans = min(8, (len(sel)/8)*2)

    # rebuild: u is the lofted direction, v is the length direction
    # debug time - rebuild can drastically change the curvature.
    # perhaps there is a better way along the lines of mirroring CVs?
    # even though neither side is probably great if the rebuild is so
    # dependant upon seam placement...

    # or maybe not - was that just a temporary thing from debugging it?
    # keepCorners=0 to avoid weird UV texture/normal issues
    pmc.rebuildSurface(surf, rebuildType=0, rpo=1, keepRange=0, dir=2, kc=0,
                            spansU=1, spansV=numSpans, ch=0)
    """

    # determine if its normal is "backwards" - get normal of random vert,
    # then normal of surf at the closest point to that vert
    surf = orientSurf(surf, sel)
    pmc.delete(crv)

    return surf


def makeOpenSurf(crv, mesh, name):
    """New method for making the surface for OPEN curves
    make profile curve with 1/4 length of path curve
    extrude profile along path with tube method"""

    crv.cv[0].getPosition()
    pos = crv.cv[0].getPosition()
    # get vector for profile curve for extrusion along path
    norm = mesh.getClosestNormal(pos, "world")[0]
    tan = crv.tangent(0)
    profVec = norm.cross(tan)
    profVec.normalize()
    profVec *= (crv.length() / 8.0)

    profCrv = pmc.curve(d=3, p=(
        -profVec, -(profVec / 3), (profVec / 3), profVec))
    # for extrude's "component pivot" mode
    profCrv.setTranslation(pos, ws=True)
    surf = pmc.extrude(profCrv, crv, extrudeType=2, fixedPath=True, n=name, rsp=1,
                       useProfileNormal=True, useComponentPivot=1, ch=0)[0]
    pmc.delete(profCrv)

    return surf


def orientSurf(surf, edges):
    """Determine if surface needs to be reversed.
    just a cosmetic issue, but is nice to get right"""

    # mesh normal
    plyNrm = getPolyAvgNormal(getConnectedCmpnts(edges, "Vertices"))
    # nurbs surface normal
    srfNrm = pmc.dt.Vector()
    # just get a sampling
    for u in [.1, .4, .6, .9]:
        for v in [.1, .4, .6, .9]:
            srfNrm += surf.normal(u, v, space="world")
    srfNrm.normalize()

    # negative dot product indicates they're pointing in *roughly*
    # opposite directions. Good enough to say it needs reversed.
    # only need to reverse one or swap. doesn't matter which.
    if srfNrm.dot(plyNrm) < 0:
        return pmc.reverseSurface(surf, d=0, rpo=True, ch=0)[0]
    return surf


def makeSimpleSurf(name="UNTITLED_SURF_RIG"):
    """Create a 2x3 span nurbs plane at the average position of selection
    with the average normal."""
    sel = getSymSelection()
    if sel:
        vts = getConnectedCmpnts(sel, "Vertices")
        normal = getPolyAvgNormal(vts)
        pos = sum(v.getPosition("world") for v in vts) / len(vts)
    else:
        pmc.warning("No guide edges selected, surface created at origin.")
        normal = (1, 0, 0)
        pos = (0, 0, 0)

    return pmc.nurbsPlane(u=3, v=2, ch=0, axis=normal, p=pos, n=name)[0]


def flattenComponents(cmpnts):
    """Pymel components sometimes are multi objects
    (internal array?), eg MeshEdge[96:111]
    this function makes the list pythonic"""

    pCmps = []
    for c in cmpnts:
        pCmps.extend([d for d in iter(c)])
    return pCmps


def getConnectedCmpnts(inComp, compType="Faces"):
    """Return Maya mesh components as a PYTHON list,
    not whatever kind of internal typed list it does by default"""

    outComp = set()
    inComp = flattenComponents(inComp)
    for c in inComp:
        getCmpnts = getattr(c, "connected{0}".format(compType))
        outComp.update(flattenComponents(getCmpnts()))
    return list(outComp)


def getPolyAvgNormal(faces):
    """For the list of MeshFaces, get the average normal vector"""
    v = pmc.dt.Vector()
    for f in faces:
        v += f.getNormal("world")
    v.normalize()
    return v


def getMirrorParam(crv, symVec):
    """Given a curve and a vector of symmetry, find the point on the curve 
    that passes through the plane described by the vector"""

    # v is the direction to project curve (to create plane)
    v = mu.arbitraryOrthoVec(symVec)
    v.normalize()
    # axCrvDr is curve's vector - orthogonal to both
    axCrvDr = symVec.cross(v)

    axCrv = pmc.curve(d=1, n="mirrorCurve", p=(100 * axCrvDr, -100 * axCrvDr))
    intPt = pmc.curveIntersect(crv, axCrv, useDirection=True, d=v)

    pmc.delete(axCrv)
    return intPt


def closestOnSurf(surf, pos, local=True, point=False):
    """Convenience function since nurbsSurface.closestPoint is bugged"""

    cpos = pmc.nt.ClosestPointOnSurface()
    if local:
        sa = surf.local
    else:
        sa = surf.ws
    sa >> cpos.inputSurface
    cpos.inPosition.set(pos)
    if point:
        result = cpos.position.get()
    else:
        result = cpos.u.get(), cpos.v.get()
    pmc.delete(cpos)
    return result


def avgSurfVectors(surf):
    """Given a surface, get the approximate average normal, tangentU and tangentV"""
    norm, tanU, tanV = pmc.dt.Vector(), pmc.dt.Vector(), pmc.dt.Vector()
    for u in range(10):
        u /= 10.0
        for v in range(10):
            v /= 10.0
            norm += surf.normal(u, v)
            tu, tv = surf.getTangents(u, v)
            tanU += tu
            tanV += tv

    return norm.normal(), tanU.normal(), tanV.normal()


def makeOrigShape(obj):
    """Given a transform with some shape, create the basic foundation
    of deformation order, ie an "orig" shape."""
    try:
        shape = obj.getShape()
    except AttributeError:
        pmc.error("makeOrigShape argument must be a shape's transform node")
    orig = pmc.duplicate(shape, addShape=True, n=shape.name()+"Orig")[0]
    orig.ws >> shape.create
    # toggle this real quick to fix a texture bug
    orig.doubleSided.set(False)
    orig.doubleSided.set(True)
    orig.intermediateObject.set(True)


def origShapeMode(surfs, state):
    """Show/hide original shapes for all given surfaces and hide all others."""
    shadingArg = {True: "forceElement", False: "remove"}
    for surf in surfs:
        # history returns in order of depth, so last surface is original one
        shape = surf.getShape()
        origShape = surf.create.history(type="nurbsSurface").pop()
        if shape != origShape:
            shape.visibility.set(not state)
            origShape.intermediateObject.set(not state)
            origShape.dispCV.set(False)
            try:
                sg = shape.outputs(type="shadingEngine").pop()
                pmc.sets(sg, e=True, **{shadingArg[state]: origShape})
            except IndexError:
                pass


def mirrorSurfWeights(dfmType="cMuscleSplineDeformer"):
    """Mirror weights from one selected surface to the other,
    for easily collecting all necessary nodes when the surfaces
    and deformers are separate."""
    surf = pmc.selected()[0]
    dfm = surf.history(type=dfmType)[0]
    try:
        mirSurf = surf.mirror.get()
    except AttributeError:
        try:
            mirSurf = pmc.selected()[1]
        except IndexError:
            pmc.error("No surface to mirror to!")
            return

    mirDfm = mirSurf.history(type=dfmType)[0]
    pmc.copyDeformerWeights(ss=surf, ds=mirSurf, sd=dfm, dd=mirDfm, mm="YZ")


def makeFollOnSel():
    """Return a new follicle on selected surface"""
    try:
        s = getSelectedSurfs()[0]
    except IndexError:
        pmc.error("Select a surface to add follicle to.")
        return
    else:
        return makeFollicle(s, uPos=0.5, vPos=0.5)


def makeFollicle(oNurbs, uPos=0.0, vPos=0.0, pName=None, local=False):
    """pymel create single follicle script
    by Chris Lesage
    edition by Brendan Kelly"""

    # manually place and connect a follicle onto a nurbs surface.
    if oNurbs.type() == 'transform':
        oNurbs = oNurbs.getShape()
    elif oNurbs.type() == 'nurbsSurface':
        pass
    else:
        pmc.warning('Warning: Input must be a nurbs surface.')
        return False

    # create a name with frame padding
    if not pName:
        pName = '_'.join((oNurbs.name(), 'follicle', '#'.zfill(2)))

    oFoll = pmc.createNode('follicle', name=pName)
    if local:
        oNurbs.local.connect(oFoll.inputSurface)
    else:
        oNurbs.ws.connect(oFoll.inputSurface)
    # if using a polygon mesh, use this line instead.
    # (The polygons will need to have UVs in order to work.)
    # oMesh.outMesh.connect(oFoll.inMesh)

    # oNurbs.worldMatrix[0].connect(oFoll.inputWorldMatrix)
    oFoll.outRotate.connect(oFoll.getParent().rotate)
    oFoll.outTranslate.connect(oFoll.getParent().translate)
    oFoll.parameterU.set(uPos)
    oFoll.parameterV.set(vPos)
    oFoll.getParent().t.lock()
    oFoll.getParent().r.lock()

    return oFoll


def matchFollToObj(sel=None):
    """Select joint then follicle, and set the follicle's UVs to
    most closely match the joint's position.
    (Made when unable to mmb drag UV values.)"""

    if not sel:
        sel = pmc.ls(sl=True)
    try:
        j = sel[0]
        f = sel[1].getShapes()[0]
    except IndexError:
        pmc.error("Select target object then follicle.")
        return

    try:
        surf = f.inputSurface.listHistory(exactType="nurbsSurface")[0]
    except IndexError:
        pmc.error("Can't find surface of follicle.")

    # pymel bug in "\internal\factories.py"
    # surf.closestPoint(j.getTranslation(ws=True), space="world")

    cpos = pmc.nodetypes.ClosestPointOnSurface()
    surf.ws.connect(cpos.inputSurface)
    loc = pmc.spaceLocator()
    loc.translate.connect(cpos.inPosition)
    pmc.parentConstraint(j, loc, mo=False)
    f.pu.set(cpos.parameterU.get())
    f.pv.set(cpos.parameterV.get())
    pmc.delete(cpos, loc)


def resetMuscleCtrlsToSel(mirror=False):
    """Prepare variables for muscle spline system resetting."""

    sel = [x for x in pmc.selected() if isinstance(x, pmc.NurbsSurfaceIsoparm)]
    try:
        surf = sel[0].node()
    except IndexError:
        pmc.error("Select at least two nurbs surface points.")

    pts = [[float(p.rstrip("]")) for p in pt.split("[")[1:]] for pt in sel]

    resetMuscleCtrls(surf, pts)

    if mirror:
        try:
            mirSurf = surf.getTransform().mirror.get()
            assert mirSurf != surf
        except (AttributeError, AssertionError):
            return
        mirPts = [[1.0 - pt[0], pt[1]] for pt in pts]
        resetMuscleCtrls(mirSurf, mirPts)


def resetMuscleCtrls(surf, pts):
    """Repositions the neutral pose for a muscle spline system on given surface.
    User selects surface points for each control object in the muscle setup, 
    and this moves and re-orients the controls to those points."""    
    
    try:
        dfm = surf.history(type="cMuscleSplineDeformer")[0]
        spl = surf.history(type="cMuscleSpline")[0]
    except IndexError:
        pmc.error(
            "Surface {0} has no muscle system associated with it.".format(
                surf.name()))

    # turn off deformer so I can move controls without the surface changing on me
    dfm.envelope.set(0)

    ctrls = [cd.insertMatrix.inputs()[0] for cd in spl.controlData]
    if len(ctrls) != len(pts):
        pmc.error(
            "Number of selected points must match the number of spline controls!")

    # must positions and normals BEFORE changing anything on the surface
    # zip an unpacked list comp - slick way to get two lists out of one comp
    positions, normals = zip(*[(surf.getPointAtParam(*pt, space="world"), 
                                surf.normal(*pt, space="world")) for pt in pts])

    for i, ctrl in enumerate(ctrls):
        ctrl.setTranslation(positions[i], space="world")

    # positions must all be finalized before orientation can be fixed
    for i, ctrl in enumerate(ctrls):
        print(pts[i], normals[i])
        print(positions[i], ctrl.getTranslation(space="world"))

        if i:
            # NOT first ctrl - negative aim vetor at previous
            aimObj = ctrls[i - 1]
            aimVec = (0, -1, 0)
        else:
            aimObj = ctrls[i + 1]
            aimVec = (0, 1, 0)


        pmc.delete(pmc.aimConstraint(
            aimObj, ctrl, aim=aimVec, u=(1, 0, 0), wut="vector", wu=normals[i]))

    # reset .controlDataBase and length
    pmc.mel.eval("cMS_resetSplineDefBasePose(\"{0}\")".format(dfm))
    l = spl.curLen.get()
    spl.lenDefault.set(l)
    spl.lenSquash.set(l / 2)
    spl.lenStretch.set(l * 2)

    dfm.envelope.set(1)


def makeRibbon(jnts=None, axis="z"):
    """create a lofted surface, and kill history...
    or not? just skin "curves" to joints 1:1?"""
    if not jnts:
        jnts = pmc.ls(sl=True)
    offset = pmc.datatypes.Vector(
        [float(a == axis.lower()) for a in ["x", "y", "z"]])
    curves = []
    for j in jnts:
        if j.type() != "joint":
            pmc.error("Invalid selection. Select joints only.")
        pos = j.getTranslation(ws=True)
        c = pmc.curve(d=1, p=[(pos + offset), (pos - offset)])
        curves.append(c)
        # pmc.skinCluster(j, c, maxInfluences=1)
    # loft = pmc.loft(curves)
    loft = pmc.loft(curves, ch=False)[0]
    pmc.delete(curves)
    # pmc.skinCluster(jnts, loft, maximumInfluences=1)
    return loft


def makeRibbonSpline(jnts=None, axis="z"):
    """Create a nurbs surface and populate with joints which
    are driven by follicles evenly spaced along the surface"""
    if not jnts:
        jnts = pmc.ls(sl=True)

    loft = makeRibbon(jnts=jnts, axis=axis)
    for i, j in enumerate(jnts):
        u = 1.0 * i / (len(jnts) - 1.0)
        foll = makeFollicle(loft, uPos=u, vPos=0.5)

        pmc.orientConstraint(foll.getParent(), j, mo=True)
