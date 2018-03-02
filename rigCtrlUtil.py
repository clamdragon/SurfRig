import pymel.core as pmc
from pymel.api import MDGMessage, MMessage
import unittest
import json
import os
from functools import partial
from difflib import SequenceMatcher


__author__ = "Brendan Kelly"
__email__ = "clamdragon@gmail.com"


"""
A collection of utilities for building better rig controls:
- MayaUndoChunkManager
- NodeOrganizer
- readFile
- avgMayaName
- nextAvailableIndex
- mergeShapes
- makeParGrp
- makeFkChain
- makeThickFkCtrl
- makeThickIkCtrl
- makePinCtrl
- addFKIKSwitchToCtrl
- addOrientsToCtrl
- makePVconstraint
- addBendyTwist
- setOvrColor
- colorGen
- findPluginForNode
- checkPlugins
- quickModulo
"""


# credit to Rob Galanakis on TAO,
# this SAFELY manages the Maya undo queue so that
# any large, multi-step operation 
# is a single entry in the Maya undo queue
#
class MayaUndoChunkManager(object):
    """Context manager to be able to safely do lots off stuff
    and undo the entire chunk at once.
    e.g., with MayaUndoChunkManager(): *do hecka stuff*"""
    def __enter__(self):
        # for safety, reset tool context
        pmc.setToolTo("selectSuperContext")
        pmc.undoInfo(openChunk=True)
    def __exit__(self, *args):
        pmc.undoInfo(closeChunk=True)


class NodeOrganizer(object):
    """Context manager to organize newly created nodes. Args:
    - func: the function you want to run when a new node is made, which
    it must accept 2 args from callback: MObject (the new node), and data."""
    def __init__(self, func):
        self.func = func
        self.cbid = None 

    def __enter__(self):
        self.cbid = MDGMessage.addNodeAddedCallback(self.func)

    def __exit__(self, *args):
        MMessage.removeCallback(self.cbid)
    """
    inefficient
    def __enter__(self):
        self.pre = set(pmc.ls(intermediateObjects=True))

    def __exit__(self, *args):
        post = set(pmc.ls(intermediateObjects=True))
        new = post - self.pre
        pmc.container(self.container, e=True, addNode=new)
    """


def addNodeToAssetCB(container):
    """Decorator to return an "add to this container" function which can then
    be passed into NodeOrganizer. Args:
    - container: a string or PyNode of the container that the resulting function
    should add things to."""
    def addIntermediateNode(node, data):
        """The function to be passed into the callback."""
        node = pmc.PyNode(node)
        if isinstance(node, pmc.nt.DagNode):
            # ignore DAG objects
            return
        pmc.container(container, e=True, addNode=node)

    return addIntermediateNode


def mergeRelPath(start, end):
    """Squish two parts of a relative path together. Chops off
    the filename from first arg and replaces it with second arg. Args:
    - start: string of a valid file path
    - end: string of the file name you want in start's directory.
    e.g., mergeRelPath(__file__, data.json)"""
    return os.path.dirname(start) + os.sep + end


def readFile(f):
    """Simple read file and return string contents. Args:
    - f: a valid file path"""
    try:
        with open(f, "r") as openF:
            data = openF.read()
        return data
    except IOError:
        return ""


def readJson(f):
    """Read a jason file and return the data. Args:
    - f: a valid json file path."""
    try:
        with open(f, "r") as jf:
            jData = json.load(jf)
        return jData
    except IOError:
        return {}


def formatDict(d, indent=2):
    """Return a formatted string of the given JSON data. Args:
    - d: valid JSON data
    - indent: the desired indentation for each level in the data. Default=2."""
    return json.dumps(d, indent=indent)


def avgMayaName(objList):
    """Get a string of what several Maya objects name's have in common. Args:
    - objList: a list of PyNodes or strings."""
    objSet = list(set(objList))
    if not objSet:
        pmc.warning("No objects to get average name of!")
        return
    name = objSet[0]
    for s in objSet[1:]:
        matches = SequenceMatcher(None, name, s).get_matching_blocks()
        name = "_".join([name[i:i+n].strip("_") for i, _, n in matches if n])
    return name.strip("_0")


def quickModulo(name="modulus"):
    """A remapValue node that functions as modulo for values between -1 and 2"""
    rm = pmc.nt.RemapValue(n=name)
    rm.value[0].set(-1, 0, 1)
    rm.value[1].set(0, 1, 0)
    rm.value[2].set(.001, .001, 1)
    rm.value[3].set(1, 1, 0)
    rm.value[4].set(1.001, .001, 1)
    rm.value[5].set(2, 1, 0)
    return rm


def nextAvailableIndex(attr):
    """Return first unconnected index of a multi attribute, up to 1000. Args:
    - attr: a valid multi attribute."""
    for i in range(1000):
        isConnected = attr[i].isConnected()
        if attr.isCompound():
            isConnected = isConnected or attr[i].numConnectedChildren()
        if not isConnected:
            return i


def displayTextures():
    # turn on hardware shading for all model panels
    # (for color-coded joint limits)
    panels = pmc.getPanel(type="modelPanel")
    for p in panels:
        pmc.modelEditor(p, e=True, displayTextures=True)


# DOES NOT FREEZE TRANSFORMATIONS
# XFORMS NEED TO BE EQUAL FOR PREDICTABLE RESULTS
#
def mergeShapes(hierarchy=False, removeOld=True):
    """Merge the shapes of all selected transform nodes into the last selected.
    Transforms' worldspaces should be identical for predictable results. Args:
    - hierarchy: bool of whether or not to merge all shapes in each
    transform's hierarchy as well. Default=False.
    - removeOld: delete transforms after their shapes have been removed. Default=True."""
    sel = pmc.ls(selection=True, transforms=True)
    if len(sel) < 2:
        pmc.warning("Select more than one transform.")
        return
    par = sel.pop()
    for s in sel:
        parentChildShapes(s, par, hierarchy)
        if removeOld:
            pmc.delete(s)
    pmc.select(par)
    return par


def parentChildShapes(obj, par, hierarchy=False):
    """Move the shapes from one transform to another. Args:
    - obj: the source transform
    - par: the new parent for obj's shapes
    - hierarchy: bool of whether or not to merge all shapes in each
    transform's hierarchy as well. Default=False."""
    for s in obj.getShapes():
        s.setParent(par, relative=True, shape=True)
    # other children: only if hierarchy
    if hierarchy:
        for c in obj.getChildren():
                parentChildShapes(c, par)


def makeParGrp(obj=None):
    """Make a parent group for given object, transferring the object's
    xforms to the parent and zeroing its own. Args:
    - obj: the object to make a parent for. Default=None, selection is used."""
    if not obj:
        obj = pmc.ls(sl=True)[0]
    grp = pmc.group(empty=True, n=obj.name()+"GRP")
    grp.setParent(obj.getParent())
    grp.setMatrix(obj.getMatrix())
    obj.setParent(grp)
    return grp


def makeFkChain():
    """Select joints in an FK chain starting with the root.
    This creates a simple FK chain of controls for it."""
    prev = None
    for s in pmc.selected():
        n = s.name().replace("rig", "{0}")
        ctrl = pmc.circle(nr=(1, 0, 0), n=n.format("ctrl"), ch=0)[0]
        ctrlGrp = pmc.group(n=n.format("ctrlGrp"))
        ctrlGrp.setParent(prev)
        prev = ctrl
        ctrlGrp.setTranslation(s.getTranslation(ws=True), ws=True)
        ctrlGrp.setRotation(s.jo.get())
        ctrlGrp.ry.set(0)
        pmc.orientConstraint(ctrl, s, mo=True)


def attachToMotionPath(path, control, numJnts, frontAxis="Z", upAxis="X", wuo=None, wuv=(1, 0, 0)):
    """Given a path object and a set of joints, create motion path nodes
    which distribute them evenly along the path and are driven by 'tread'
    attribute on control."""
    control.addAttr("tread", at="float", k=True)
    for i in xrange(numJnts):
        pmc.select(cl=True)
        j = pmc.joint()
        mp = pmc.nt.MotionPath()
        # this shows in AE as ParametricLength = False
        mp.fractionMode.set(True)
        if wuo:
            # world up object mode
            mp.worldUpType.set(2)
            wuo.wm >> mp.worldUpMatrix
        else:
            # vector mode
            mp.worldUpType.set(3)
        mp.worldUpVector.set(wuv)
        mp.frontAxis.set(frontAxis)
        mp.upAxis.set(upAxis)
        path.ws >> mp.geometryPath
        param = pmc.nt.AddDoubleLinear()
        path.tread >> param.input1
        param.input2.set(float(i) / numJnts)
        mod = pmc.nt.Ramp()
        param.output >> mod.u
        mod.t.set(1)
        mod.outColorR >> mp.u
        mp.ac >> j.t
        mp.r >> j.r
        mp.ro >> j.ro


def makeThickFkCtrl(radius=1.0, name="FK_CTRL"):
    """Creates a quad-circle shape as a ctrl. Args:
    - radius: the ctrls' radius. Default=1.0
    - name: the name of the object. Default='FK_CTRL'"""
    offset = (radius*1.05) - radius
    c1 = pmc.circle(r=(radius*1.05), nr=(1, 0, 0))
    c2 = pmc.circle(r=(radius*0.95), nr=(1, 0, 0))
    c3 = pmc.circle(r=radius, nr=(1, 0, 0))
    pmc.move(offset, 0, 0)
    pmc.makeIdentity(apply=True)
    pmc.xform(c3, sp=(0, 0, 0), rp=(0, 0, 0), ws=True)
    c4 = pmc.circle(r=radius, nr=(1, 0, 0))
    pmc.move(-offset, 0, 0)
    pmc.makeIdentity(apply=True)
    pmc.xform(c4, sp=(0, 0, 0), rp=(0, 0, 0), ws=True)

    pmc.select(c4, c3, c2, c1)
    ctrl = mergeShapes()
    ctrl.rename(name)
    return ctrl


def makeThickIkCtrl(width=1.0, name="IK_CTRL", lines=1):
    """Creates a nested cube shape as a ctrl. Args:
    - width: the size of the ctrl. Default=1.0
    - name: the name of the object. Default='IK_CTRL'
    - lines: the number of nested cubes. Default=1"""
    if lines > 10:
        lines = 10
    shapes = []
    for _ in range(lines):
        for v in [(width/2, 0, 0), (-width/2, 0, 0), (0, width/2, 0),
                    (0, -width/2, 0), (0, 0, width/2), (0, 0, -width/2)]:
            sh = pmc.nurbsSquare(nr=v, c=v, sl1=width, sl2=width)[0]
            shapes.append(sh)
        # increase side length
        width *= 1.05

    g = pmc.group(empty=True, name=name)
    pmc.select(shapes, g)
    ctrl = mergeShapes(hierarchy=True)
    return ctrl


def makePinCtrl(h=0.5, name="PIN_CTRL", axis=(0, 0, 1)):
    """Creates a simple cone control shape - good for controlling
    stretchy splines and the like. Args:
    - h: height of the ctrl. Default=0.5
    - name: name of the object. Deault='PIN_CTRL'
    - axis: the local top-bottom axis of the cone. Default=(0, 0, 1)"""

    #v = pmc.dt.Vector(axis)
    #cone = pmc.cone(d=1, sections=4, pivot=(-h/2*axis), 
    #                       ax=axis, r=h/4, hr=4)
    
    pts = ((0, 0, 0), (h/4, 0, h), (-h/4, 0, h), 
            (0, h/4, h), (0, -h/4, h))

    curves = []
    for i in range(len(pts)):
        for n in range(i+1, len(pts)):
            ps = (pts[i], pts[n])
            c = pmc.curve(d=1, p=ps)
            curves.append(c)

    pmc.select(curves)
    ctrl = mergeShapes()
    ctrl.rename(name)
    # edit orientation
    a = pmc.angleBetween(euler=True, v1=(0, 0, 1), v2=axis)
    ctrl.rotate.set(a)
    pmc.makeIdentity(ctrl, apply=True, r=True)
    return ctrl


def createBlankShape(name="dummy"):
    """Create and return an invisible shape node with no
    channel box attributes. Args:
    - name: name of the SHAPE (not its transform)! Default='dummy'"""
    l = pmc.spaceLocator(n=name+"_DAG")
    shape = l.getShape()
    shape.rename(name)
    shape.setAttr("visibility", False)
    l.setAttr("visibility", False)
    for a in shape.listAttr(cb=True):
        a.set(channelBox=False)

    return shape


def addShapeToTrans(shape, transform):
    """Add a shape to a transform node, and make it appear at the top of other shapes
    in the channel box. DOES NOT remove the shape from its current transform -
    shapes can have any number of  transforms of this kind. Args:
    - shape: the shape node to be added.
    - transform: the transform to receive the shape as an input."""
    shape.setParent(transform, add=True, shape=True)
    # shape is explicitly under original transform,
    # so to reorder need the lastest shape under ctrl
    ctrlShape = transform.getShapes()[-1]
    pmc.reorder(ctrlShape, front=True)
    print("Successfully added {0} to {1}".format(shape, transform))


def addFKIKSwitchToCtrls(ctrls=None, shape=None, name="FK_IK_Switcher"):
    """Allow for multiple ctrls to access and set the
    same 'FK_IK_Switch' attribute, on an instanced locator. Args:
    - ctrls: list of transforms (PyNodes) which want to access the
    switch. Default=None, selection is used.
    - shape: the shape with the FKIK switch attribute, to be added to ctrls.
    Default=None, new shape is created.
    - name: name for the FKIK switch shape node. Only used if shape=None.
    Default='FK_IK_SWITCHER'"""

    # normalize the ctrls input a bit
    # make usable with just selection
    if not ctrls:
        ctrls = pmc.ls(sl=True, transforms=True)
    elif not hasattr(ctrls, "__iter__"):
        ctrls = [ctrls]

    if not shape:
        # create the thing if it's not passed in
        shape = createBlankShape(name=name)
        shape.addAttr("FK_IK_Switch", at="float", 
                        keyable=True, min=0, max=1.0)

    for ctrl in ctrls:
        addShapeToTrans(shape, ctrl)
    
    return shape


def addOrientsToCtrl(const="parent"):
    """Add space switching to an object. First X selected transforms are the target
    spaces (plus 'world'), and last object gets an enum to switch between them. Args:
    - const: type of constraint to use for the space controller. Valid inputs are:
    'parent', 'orient' and 'point'. Default='parent'."""
    if const == "parent":
        func = pmc.parentConstraint
    elif const == "orient":
        func = pmc.orientConstraint
    elif const == "point":
        func = pmc.pointConstraint
    else:
        pmc.error("Unknown constraint type: {0}".format(const))
    sel = pmc.ls(selection=True)
    # make sure selection is valid
    if len(sel) < 2:
        pmc.error("Select more shit.")
        return
    for s in sel:
        if s.type() != "transform":
            pmc.error("Invalid selection: {0}".format(s))
            return

    target = sel[-1]
    sources = sel[0:-1]
    par = target.getParent()
    spaceGroup = pmc.group(empty=True, name=target+"_Space_RIG_GRP")
    spaceGroup.setParent(par)
    pmc.makeIdentity(spaceGroup)
    target.setParent(spaceGroup)

    # Create a world object to constrain to
    # User must choose how to organize this new group
    worldLoc = pmc.spaceLocator(n=target+"_WorldOrientLoc_RIG")
    pmc.delete(pmc.parentConstraint(spaceGroup, worldLoc, mo=False))
    # currently maintainOffset is on - is this right?
    pCon = func(worldLoc, spaceGroup, mo=True)
    # create string of enum options
    spaces = "World"
    for s in sources:
        # this is the format that enumNames wants
        spaces += ":"+s.name()
        # create parent constraint
        func(s, spaceGroup, mo=True)

    target.addAttr("Orient", at="enum", keyable=True, enumName=spaces)

    # need to wait to set driven keys until ALL constraints have been added
    weights = pCon.getWeightAliasList()
    for i, w in enumerate(weights):
        """
        # w is the weight attr itself
        # set enum, and match attributes to correct 0 or 1 values
        target.Orient.set(i)
        for x in weights:
            if w == x:
                x.set(1)
            else:
                x.set(0)
            # SDK to connect the enum to parent constraint weight
            pmc.setDrivenKeyframe(x, currentDriver=target.Orient)
            """

        # condition node rather than SDK
        cond = pmc.nodetypes.Condition(name=target+"_space_condition_RIG")
        target.Orient.connect(cond.firstTerm)
        cond.secondTerm.set(i)
        cond.colorIfTrue.set(1, 1, 1)
        cond.colorIfFalse.set(0, 0, 0)
        cond.outColorR.connect(w)


def advSpaceSwitch():
    # COMPLEX SPACE SWITCHING

    r = pmc.sphere(n="rightHand")[0]
    l = pmc.cylinder(n="leftHand")[0]
    w = pmc.cone(n="weapon")[0]
    ws = pmc.spaceLocator(n="worldLoc")
    locs = [ws]
    grps = []
    names = ["World"]
    names.extend([s.name() for s in (r, l, w)])

    for s in (r, l, w):
        grps.append(pmc.group(s, n=s.name() + "_space"))
        l = pmc.spaceLocator(n=s.name() + "_ws")
        l.setParent(s)
        locs.append(l)
        spaces = ":".join([n for n in names if n != s.name()])
        s.addAttr("space", at="enum", k=True, enumName=spaces)

    targets
    for g in grps:
        spaceMat = pmc.nt.WtAddMatrix()
        spaceXform = pmc.nt.DecomposeMatrix()
        spaceMat.o >> spaceXform.inputMatrix
        spaceXform.ot >> g.t
        targets = [l for l in locs if not l.hasParent(g)]
        for i, t in enumerate(targets):
            driver = g.getChildren()[0]
            # uc = pmc.nt.UnitConversion()
            # t.wp >> uc.input

            # direct connection from l >> g,
            # modulated by enum value
            test = pmc.nt.FloatLogic()
            driver.space >> test.floatA
            test.floatB.set(i)
            cond = pmc.nt.FloatCondition()
            test.outBool >> cond.condition
            cond.floatA.set(0)
            cond.floatB.set(10)
            # cond.outFloat >> uc.nodeState
            hold = pmc.nt.HoldMatrix()
            t.wm >> hold.i
            cond.outFloat >> hold.nodeState
            # for second-round lookup
            # ensure no ping-ponging
            cond.message >> driver.childConditions
            cond.message >> t.getParent().parentConditions

            hold.o >> spaceMat.i[i].m
            test.outBool >> spaceMat.i[i].w

    # experiment with a "matching" attr (blend or switch?)
    # which turns on or off the residual influence of "previous"
    # spaces - as of now, the space still influences, but...

    # combine "opposing" condition nodes
    # via message attributes - on ctrl nodes
    # ctrl.addAttr("parentConditions", at="message")
    # ctrl.addAttr("childConditions", at="message")


def makePVconstraint():
    """function to create a pole vector
    constraint for an IK chain.
    Select ikHandle and control object to be used"""
    sel = pmc.ls(sl=True)
    if len(sel) is not 2:
        pmc.error("Select ikHandle and control object, in that order.") 
    h = sel[0]
    ctrl = sel[1]
    midJoint = h.getJointList()[-1]
    orient = abs(midJoint.jointOrient.get().normal())
    v = []
    for d in orient:
        if d > .99:
            v.append(0)
        else:
            v.append(1)
    v = pmc.datatypes.Vector(v)
    if orient != midJoint.jointOrient.get().normal():
        v = -v
    g = pmc.group(em=True, n=ctrl.name()+"_GRP")
    g.setParent(midJoint)
    ctrl.setParent(g)
    pmc.makeIdentity(g)
    pmc.makeIdentity(ctrl)
    g.translate.set(v)
    g.setParent(None)


def addBendyTwist(factor=0.5):
    """Add autotwist and a control to bicep twist joint.
    Select RIGJNT which is source of rotations then twist RIGJNT.
    E.G. For bicep: select shoulder RIGJNT then bicep RIGJNT and run.
    Assumes bicep and elbow are siblings and children of shoulder. Args:
    - factor: multiplier for how much the twist joint should move with
    main joint. 1.0 is 100%. Default=0.5"""    
    factor = 0.0 - factor
    # create correct hierarchy
    sel = pmc.ls(sl=True)
    j = sel[0]
    twistJnt = sel[1]
    tName = twistJnt.name().replace("_RIGJNT", "")
    grp = pmc.group(empty=True, 
                    n=j.name().replace("RIGJNT", "twist_RIGGRP"))
    twistGrp = pmc.group(empty=True, n=tName+"_autoTwist_RIGGRP")
    grp.setParent(j)
    pmc.makeIdentity(grp)
    ctrl = pmc.circle(r=0.5, n=tName+"_CTRL")[0]
    ctrl.setParent(twistGrp)
    twistGrp.setParent(twistJnt)
    pmc.makeIdentity(twistGrp)
    twistGrp.setParent(grp)
    kids = j.getChildren(type="joint")
    kids.remove(twistJnt)
    for k in kids:
        k.setParent(grp)
    twistJnt.setParent(ctrl)

    # re-forge connections -
    # take inputX away from j,
    # redirect it into grp
    try:
        inX = j.rotateX.inputs(plugs=True)[0]
    except IndexError:
        inAttr = j.rotate.inputs(plugs=True)[0]
        n = inAttr.node()
        if n.type() == "unitConversion":
            inAttr = n.input.inputs(plugs=True)[0]
        inX = inAttr.children()[0]
        inY = inAttr.children()[1]
        inZ = inAttr.children()[2]
        j.rotate.disconnect()
        inY.connect(j.rotateY)
        inZ.connect(j.rotateZ)
        inX.connect(grp.rotateX)
    else:
        inX.connect(grp.rotateX)
        j.rotateX.disconnect()

    # connect partial inverse twist to twistGrp
    mult = pmc.nodetypes.MultDoubleLinear(n=tName+"_scale_RIG")
    grp.rotateX.connect(mult.input1)
    mult.input2.set(factor)
    mult.output.connect(twistGrp.rotateX)

    # recreate orientConstraints if they exist
    cons = list(set(j.listConnections(source=True, type="constraint")))
    for c in cons:
        targ = c[0].getParent()
        pmc.delete(c)
        pmc.orientConstraint(j, targ, mo=False)


def setOvrColor(color=None, objs=None):
    """Sets shape override color on selected objects. Args:
    - color: RGB (float, float, float). Default=None, color picker window opens."""
    if not objs:
        objs = pmc.ls(sl=True)
    if not color:
        #main = qtu.getMayaMainWindow()
        #colorWin = QtWidgets.QColorDialog(main)
        #color = colorWin.getColor()
        pmc.colorEditor()
        color = pmc.colorEditor(q=True, rgb=True)
        
    for s in objs:
        try:
            shapes = s.getShapes()
        except AttributeError:
            pmc.warning("Object {0} has no shapes.".format(s))
            continue

        for sh in shapes:
            try:
                sh.overrideEnabled.set(True)
                sh.overrideRGBColors.set(True)
                #sh.overrideColorRGB.set(color.getRgbF())
                sh.overrideColorRGB.set(color)
            except RuntimeError:
                pmc.warning("{0} skipped due to existing connection.".format(sh))
                continue


def colorGen(hue=0.5, saturation=1.0, value=1.0, rgb=True):
    """A generator which spits out consistently unique and well-constrasting
    colors on .next() call. DO NOT ITERATE THROUGH ENTIRETY, WILL NOT STOP."""
    gr = 0.618033988749895
    while True:
        if rgb:
            yield pmc.dt.Color.hsvtorgb((hue, saturation, value))
        else:
            yield (hue, saturation, value)
        hue = (hue + gr) % 1.0


def moveWeightsToInfluence():
    """Take the skin weights from the first selected hierarchy,
    and transfer them to the second selected hierarchy.
    Attempts to find objects which are at the same place in worldspace.
    Influences without an equivalent worldspace counterpart are ignored.
    The first hierarchy ends up with zeroed weights."""
    sel = pmc.ls(sl=True)
    mesh = sel[0]
    j1 = sel[1]
    j2 = sel[2]
    # check if they're at the same place worldspace
    if j1.getMatrix(ws=True).isEquivalent(j2.getMatrix(ws=True), tol=.0001):
        cls = mesh.listHistory(type="skinCluster")[0]
        for v in mesh.vtx:
            weight = pmc.skinPercent(cls, v, transform=j1, q=True)
            if weight:
                pmc.skinPercent(cls, v, tv=((j1, 0), (j2, weight)))


def setBindPose(meshXform):
    """Set the current skeleton pose as the bind pose for a transform.
    All relevant sub-shapes will be fixed. Move joints BEFORE using this
    (so skin is deformed) and skin will reset. Args:
    - meshXForm: TRANSFORM node of the skincluster affectes mesh."""
    for shape in meshXform.getShapes():
        try:
            skinClus = shape.inputs(type="skinCluster")[0]
        except IndexError:
            # perhaps an "Orig" shape, or just generally bad argument
            # ignore it.
            continue
        
        jnts = skinClus.matrix.inputs()
        for i, j in enumerate(jnts):
            # skinCluster stores each joint's worldInverseMatrix
            # at its bind pose
            skinClus.bindPreMatrix[i].set(j.worldInverseMatrix.get())
        
        pmc.dagPose(jnts, n=skinClus.bindPose.get(), reset=True)

        print("Successfully reset bind pose on {0}".format(shape.name()))


def showHideAttr(vis, picker, arg):
    """Code to show/hide attrs via showHide dialog. Don't worry about it."""
    sel = pmc.ls(selection=True)
    pmc.layoutDialog(dismiss=True)
    curr = pmc.optionMenu(picker, q=True, v=True)
    for s in sel:
        for d in ["X", "Y", "Z"]:
            pmc.setAttr(s+"."+curr+d, k=vis, l=(not vis))


def setAttrChannelBox(obj, attrs, state):
    for attr in attrs:
        for a in obj.attr(attr).children():
            a.set(k=state, l=not state)


def dialogGuts():
    """Guts for the showHide layout dialog. Don't worry about it."""
    show = "Unlock and show"
    hide = "Lock and hide"
    form = pmc.setParent(q=True)
    p = pmc.formLayout(form, q=True, parent=True)
    pmc.setParent(p)
    pmc.deleteUI(form)
    col = pmc.columnLayout(width=250, height=150, columnAttach=("both", 20),
                            adj=True, rowSpacing=20)
    lab = "\nAction will be applied to all selected items."
    pmc.text(lab)
    picker = pmc.optionMenu(label="Apply to: ")
    pmc.menuItem("translate")
    pmc.menuItem("rotate")
    pmc.menuItem("scale")
    pmc.setParent(col)
    pmc.rowLayout(nc=2)
    pmc.button(l=show, c=partial(showHideAttr, True, picker))
    pmc.button(l=hide, c=partial(showHideAttr, False, picker))

def makeShowHideDialog():
    """A UI to show/hide channel box attributes for selected objects."""
    pmc.layoutDialog(ui=dialogGuts, title="Lock+Hide/Unlock+Show")


def findPluginForNode(n):
    """If given nodeType depends on a plugin, 
    return name of that plugin. Args:
    - n: nodeType string to query."""
    if not hasattr(pmc.nt, (n[0].upper() + n[1:])):
        return "Unknown node '%s'." %n
    for p in pmc.pluginInfo(q=True, listPlugins=True):
        nodes = pmc.pluginInfo(p, q=True, dependNode=True)
        if not nodes:
            continue
        elif n in nodes:
            return "Node '{0}' requires plugin '{1}'".format(n, p)
    else:
        return "No plugin dependency found for node '%s'." %n


def checkPlugins(plugins):
    """Ensure plugins are either enabled or disabled. Args:
    - plugins: list of (plugin (string), state (bool)) tuples."""
    unknown = []
    for p, compatible in plugins:
        loaded = pmc.pluginInfo(p, q=True, l=True)
        if compatible and not loaded:
            try:
                pmc.loadPlugin(p)
            except:
                pmc.warning("Unknown plugin: ", p)
                unknown.append(p)
        elif loaded and not compatible:
            pmc.unloadPlugin(p)

    return unknown
