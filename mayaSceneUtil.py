"""
General scene utilities for Maya.
File operations, scene organization and management. Function list:
- MayaUndoChunkManager
- NodeOrganizer
- readFile
- avgMayaName
- nextAvailableIndex
- mergeShapes
- findPluginForNode
- checkPlugins
- quickModulo
- getObjectUnderCursor
"""

__author__ = "Brendan Kelly"
__email__ = "clamdragon@gmail.com"

import json
import os
from difflib import SequenceMatcher
import pymel.core as pmc
from Qt import QtWidgets, QtGui
from maya.OpenMaya import MDGMessage, MMessage


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


class AutokeyDisabler(object):
    """Temporarily ensure autokey is off for a context"""
    def __enter__(self):
        self.state = pmc.autoKeyframe(q=True, state=True)
        pmc.autoKeyframe(state=False)

    def __exit__(self, *args):
        pmc.autoKeyframe(state=self.state)


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


def assetize_cmpnt(cmpnt=None, autoPublish=True):
    """Reads all DG nodes involved in the component given by
    either argument or only selected DAG object."""
    if not cmpnt:
        cmpnt = pmc.selected()[0]

    cmpNodes = {cmpnt}
    # prune set is objects which will later be removed from the component set
    prune = set()
    allDag = cmpnt.getChildren(allDescendents=True)
    for dag in allDag:
        cmpNodes.update(dag.history())
        cmpNodes.update(dag.future(af=True))
        # now prune input's history and output's future
        # perhaps not the most efficient but it's reliable
        # in an uncertain situation
        name = dag.longName()
        if "input" in name:
            prune.update(dag.history())
        elif "output" in name:
            prune.update(dag.future(af=True))

    cmpNodes -= prune
    contName = cmpnt.split("_")
    contName[-1] = "asset"
    contName = "_".join(contName)
    # ugly, but Maya seems to have no special way of considering layer nodes.
    cmpNodes = [n for n in cmpNodes if "layer" not in n.type().lower()]
    asset = pmc.container(addNode=cmpNodes, includeHierarchyBelow=True, name=contName)

    if autoPublish:
        publish_controls(asset)
        publish_inputs_outputs(asset)


def publish_controls(asset=None):
    """From a given asset, publish the control objects.
    Assumes any transform with a nurbsCurve shape is a control."""
    if not asset or not isinstance(asset, pmc.nt.Container):
        asset = pmc.selected(type="container")[0]
    all_nodes = pmc.container(asset, q=True, nodeList=True)
    is_ctrl = lambda obj: hasattr(obj, "getShape") and isinstance(obj.getShape(), pmc.nt.NurbsCurve)
    controls = [n for n in all_nodes if is_ctrl(n)]
    # need to find the names of the controls and cross-check them with each other
    for c in controls:
        name = c.shortName()
        if "|" in name:
            # "|" means shortName returned longName.
            # it happens, and it's just nice when it's caught and notifies
            pmc.warning("{0} is not uniquely named! This could be bad!".format(name))
        try:
            name = name.split("_")[2]
        except IndexError:
            # if it's gonna throw a fit then just use the whole name
            pass
        if hasattr(asset, name):
            print("Re-naming {0}.{1}".format(asset, name))
            # this tests for duplicate name and re-aliases if necessary
            attr = getattr(asset, name)
            existing = attr.publishedNode.get()
            # try all tokens except first and last (assert: side + identifier)
            existing_new_name = "_".join(existing.shortName().split("_")[1:-1])
            attr.setAlias(existing_new_name)

            name = "_".join(c.shortName().split("_")[1:-1])

        pmc.containerPublish(asset, publishNode=(name, ""))
        pmc.containerPublish(asset, bindNode=(name, c))


def publish_inputs_outputs(asset=None):
    """From the given container, publish the DAG nodes
    under "input" and "output" transforms. Assumes this structure."""
    if not asset or not isinstance(asset, pmc.nt.Container):
        asset = pmc.selected(type="container")[0]
    all_nodes = pmc.container(asset, q=True, nodeList=True)
    attrs_to_publish = []
    is_edge = lambda obj, side: isinstance(obj, pmc.nt.DagNode) and obj.nodeName() == side
    for edge in ("inputs", "outputs"):
        for par in (t for t in all_nodes if is_edge(t, edge)):
            for i in par.getChildren():
                for attr in i.listAttr(k=True):
                    pubName = "_".join((edge, i.nodeName(), attr.longName()))
                    pmc.container(asset, e=True, publishAndBind=(attr, pubName))


def publish_joints(asset=None):
    """From the given container, publish the xform attributes for all joints."""
    if not asset or not isinstance(asset, pmc.nt.Container):
        asset = pmc.selected(type="container")[0]
    all_nodes = pmc.container(asset, q=True, nodeList=True)
    for j in (o for o in all_nodes if isinstance(o, pmc.nt.Joint)):
        for attr in (j.translate, j.rotate, j.scale):
            pubName = "_".join(("inputs", j.nodeName(), attr.longName()))
            pmc.container(asset, e=True, publishAndBind=(attr, pubName))


def migrate_to_parent_asset(containers=None):
    """Move all nodes from selected containers into their parent container
    and re-publish to parent any nodes which were published before."""
    if not containers:
        containers == pmc.selected(containers=True)
    for c in containers:
        all_nodes = pmc.container(c, q=True, nodeList=True)
        c_name = c.namespace().strip(":")
        pub_info = pmc.containerPublish(c, q=True, bindNode=True)
        par_c = pmc.container(c, q=True, parentContainer=True)
        if not par_c:
            pmc.warning("{} has no parent container! Skipped.".format(c))
            continue
        pmc.container(c, e=True, removeContainer=True)
        pmc.container(par_c, e=True, addNode=all_nodes)

        # publish to new parent container
        pub_iter = iter(pub_info)
        for pub_name in pub_iter:
            pub_name = "{}_{}".format(c_name, pub_name)
            pub_ctrl = pub_iter.next()
            pmc.containerPublish(par_c, publishNode=(pub_name, ""))
            pmc.containerPublish(par_c, bindNode=(pub_name, pub_ctrl))

        # fix node names, AFTER re-publishing
        for node in all_nodes:
            prefix, n = node.name().split(":")
            node.rename(prefix + n.title(), ignoreShape=True)


def get_selected_cb_attrs():
    """Return a list (in pymel attr form) of whatever attributes
    are selected in the main channel box."""
    # these are the different flags for channelBox function (for some reason)
    cb_types = ("sma", "ssa", "sha", "soa")
    sel_attrs = []
    for t in cb_types:
        sel = pmc.channelBox("mainChannelBox", q=True, **{t: True})
        if sel:
            sel_attrs.extend(sel)

    return find_cb_attrs(sel_attrs)


def find_cb_attrs(attr_names):
    attrs = []
    obj = pmc.selected()[-1]
    # attr could be on selected node or could be published to its asset
    c = pmc.container(q=True, fc=obj)
    if c:
        # bindAttr returns in wrong order, just reverse before making into dict
        pub_attrs = dict(((n, a) for a, n in pmc.container(c, q=True, bindAttr=True)))
    else:
        pub_attrs = {}

    for a in attr_names:
        try:
            attrs.append(obj.attr(a))
        except:
            # see if it's in published attributes
            if a in pub_attrs:
                attrs.append(pub_attrs[a])

    return attrs


def get_published_attrs(c):
    """Return attributes published to arg asset in {name: pymel attr} form."""
    try:
        return dict(((n, a) for a, n in pmc.container(c, q=True, bindAttr=True)))
    except TypeError:
        return {}


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
    if not os.path.exists(f):
        raise RuntimeError("No valid file selected")

    try:
        with open(f, "r") as openF:
            data = openF.read()
        return data
    except IOError:
        return ""


def readJson(fn=None):
    """Read a jason file and return the data. Args:
    - f: a valid json file path."""
    if not fn:
        fn = QtWidgets.QFileDialog.getOpenFileName(dir=pmc.workspace(q=True, rd=True), filter="*.json")[0]
    
    if not os.path.exists(os.path.dirname(fn)):
        pmc.warning("Invalid directory!")
    else:
        try:
            with open(fn, "r") as jf:
                jData = json.load(jf)
            return jData
        except IOError:
            return {}


def writeJson(data, fn=None):
    if not fn:
        fn = QtWidgets.QFileDialog.getSaveFileName(dir=pmc.workspace(q=True, rd=True), filter="*.json")[0]
    
    if not os.path.exists(os.path.dirname(fn)):
        pmc.warning("Invalid directory!")
    else:
        # just go ahead and ensure .json extension
        fn = os.extsep.join((fn.split(os.extsep)[0], "json"))
        with open(fn, "w") as open_file:
            json.dump(data, open_file)


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


def clone_attrs(attrs=None, targObj=None, connect=None):
    """Given a list of pymel attribute objects, re-create them
    on the targObj. Optional "connect" flag accepts string args:
    "forward", which connects the original attrs to the cloned ones;
    "reverse", which connects the cloned ones to the original ones; or
    "move", which bypasses the old object completely and reconnects the new attributes
     to any previous downstream plugs."""
    if not targObj:
        targObj = pmc.selected()[0]
    if not attrs:
        attrs = get_selected_cb_attrs()
    if not connect:
        connect = pmc.confirmDialog(title="Attribute Cloner", message="What kind of connections should be made?",
                                    button=("New > Old", "Old > New", "Replace", "None"))
    for a in attrs:
        kwargs = {"k": True, "at": a.type(), "ln": a.longName(), "sn": a.shortName()}

        args = (("max", a.getMax()), ("min", a.getMin()),
                ("smx", a.getSoftMax()), ("smn", a.getSoftMin()))
        for name, val in args:
            if val is not None:
                kwargs[name] =  val
        pmc.addAttr(targObj, **kwargs)

        targAttr = targObj.attr(a.attrName())
        targAttr.set(a.get())
        if connect == "New > Old":
            targAttr >> a
        elif connect == "Old > New":
            a >> targAttr
        elif connect == "Replace":
            for out_plug in a.outputs(plugs=True):
                targAttr >> out_plug
            # kill old attribute
            a.delete()


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


def getObjectUnderCursor():
    """Return a list of Maya objects under mouse pointer."""
    pos = QtGui.QCursor.pos()
    widg = QtWidgets.QApplication.widgetAt(pos)
    x, y = widg.mapFromGlobal(pos).toTuple()
    panel = pmc.getPanel(underPointer=True)
    try:
        return pmc.hitTest(panel, x, y)
    except RuntimeError:
        return []


def make_callback_script_node(cmd="", force=False):
    """Create a python script node which runs
    the (optional) given string cmd on scene load."""
    name = "bk_install_callbacks_on_load"
    if not force and pmc.objExists(name):
        pmc.warning("A callback setup script node already exists!"
                    "Set force flag to make another one anyway.")
        return
    scr = pmc.nt.Script(n=name)
    scr.scriptType.set("Open/Close")
    scr.sourceType.set("Python")
    scr.before.set(cmd)


def set_up_axis(ax):
    pmc.mel.setUpAxis(ax.lower())
    pmc.viewSet(p=True)


def remove_ref_edits_from_objs(objs=None):
    """
    Clean the edits made to given referenced objects
    """
    if not objs:
        objs = pmc.selected()
    refs = set(o.referenceFile() for o in objs if o.referenceFile())
    objs = [o.longName() for o in objs]
    for r in refs:
        r.unload()
    for o in objs:
        pmc.referenceEdit(o, removeEdits=True, scs=True, fld=True)
    for r in refs:
        r.load()

    return [pmc.PyNode(o) for o in objs]
