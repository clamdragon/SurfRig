# -*- coding: utf-8 -*-

""" Main class and associated functions for surface-based autorigger.
Creates NURBS surface "plates" from selected polygon mesh edges,
and allows for quick creation of rig joints which move like follicles
along the surface. """

# pylint: disable=locally-disabled, expression-not-assigned

from functools import partial
import pymel.core as pmc

import bkTools.mayaSceneUtil
import bkTools.skinUtil
from bkTools import (rigCtrlUtil as rcu, qtUtil as qtu,
                     matrixUtil as mu, surfaceUtil as su)
import surfRigUi, jointControls as jc, parentControls as pc, deformerControls as dc

# if mtoa is loaded prior to lookdevkit loading, floatCorrect nodes are fucked
# I think freeze was also involved in this floatCorrect trainwreck
__pluginRequirements__ = (
    ("mtoa", False),
    ("freeze", False),
    ("lookdevKit", True),
    ("matrixNodes", True))

# Used if no JSON file provided, or for any missing values
defaultNames = {
    "convention": "{name}_{type}_{num:02}",
    "surface": "surf",
    "rig group": "surfRigGrp",
    "control": "ctrl",
    "control group": "stickyCtrlGrp",
    "offset group": "offset",
    "parent": "par",
    "surface controls group": "surfCtrls",
    "joint": "stickyJnt",
    "joint group": "surfRigJnts"
}
controlName = "SurfaceRigger"


@qtu.SlotExceptionRaiser
def toggleVis(objType, allPanels=True):
    """Slot for button. Toggles visibility in last focused model editor"""
    if allPanels:
        panels = pmc.getPanel(type="modelPanel")
    else:
        panels = [pmc.getPanel(withFocus=True)]
    # turn string into a parameter name and value 
    typeArg = {objType: True}
    for curr in panels:
        try:
            typeArg[objType] = not pmc.modelEditor(curr, q=True, **typeArg)
            pmc.modelEditor(curr, e=True, **typeArg)
        except RuntimeError:
            pmc.warning("Ensure focus is on a model editor.")


@qtu.SlotExceptionRaiser
def focusCVs(obj=None, state=True):
    """Enable or disable CV edit selection mode"""
    if state:
        pmc.selectType(allComponents=False, cv=True)
        pmc.selectType(objectComponent=True, allComponents=False, cv=True)
        pmc.selectPriority(cv=100)
        pmc.selectMode(component=True)
        if not obj:
            obj = su.getSelectedSurfs(withAttr="layeredTexture")
        pmc.select(cl=True)
        surfs = su.getSelectedSurfs(withAttr="layeredTexture")
        if surfs:
            obj = surfs
        pmc.hilite(obj)
    else:
        # back to default
        pmc.selectType(allComponents=True)
        pmc.selectPriority(cv=5)
        pmc.selectMode(object=True)


@qtu.SlotExceptionRaiser
def syncSliderAndCtrl(slider, attr, mult, recentlyRigged, val):
    """Sliders are int-only, spin box is double.
    Have to use multiplier, and set the attribute 
    on logically determined surfaces"""
    slider.setValue(int(val*mult))
    # first choice: selected surfs - second choice: latest created
    surfs = su.getSelectedSurfs(withAttr="layeredTexture")
    if not surfs:
        ctrls = [s for s in pmc.ls(sl=True) if hasattr(s, "surface")]
        surfs = list(set([c.surface.get() for c in ctrls]))
    if not surfs:
        surfs = recentlyRigged

    with bkTools.mayaSceneUtil.MayaUndoChunkManager():
        for surf in surfs:
            try:
                surf.attr(attr).set(val)
            except AttributeError:
                continue


@qtu.SlotExceptionRaiser
def resetBindPose():
    """Slot for "reset bind pose" button, get selected transforms
    and pass to skinCluster editing function"""
    with bkTools.mayaSceneUtil.MayaUndoChunkManager():
        meshes = pmc.ls(sl=True, transforms=True)
        if not meshes:
            pmc.warning("Select skinned mesh objects to reset bind pose.")
            return
        
        ctrls = [c for c in pmc.ls(transforms=True) if hasattr(c, "controlGroup")]
        for c in ctrls:
            #pmc.makeIdentity(c)
            pmc.xform(c, t=(0, 0, 0), ro=(0, 0, 0), s=(1, 1, 1))

        for mesh in meshes:
            # ensure all control shapes are AT ZERO XFORMS,
            # ie nothing is posed according to the CONTROLS.
            skinJnts = mesh.history(type="joint")
            if not skinJnts:
                pmc.warning("Mesh {0} is not skin bound to any joints! "
                            "Skipped.".format(mesh.name()))
                continue

            bkTools.skinUtil.setBindPose(mesh)


"""
------------------------------------------------------------------------------

CONTEXT CLASS - SURFACE EDITOR

------------------------------------------------------------------------------
"""


class SurfaceEditor(object):
    """Context object for surface editing.
    Args are setting from the UI: mirror(bool), mirVec(vector), lockJnts(bool)."""
    def __init__(self, lockJnts, mirVec):
        self.lockJnts = lockJnts
        self.mirVec = mirVec

    def preDrag(self):
        """Ensure bind pose, then suspend the skinCluster (to adjust joints),
        create CPOS for joint lock"""        

        # just do ALL skinClusters in the scene.
        # requires everything be at bind pose, but that's an acceptable
        # trade off for better performance and ensuring
        # bind joints doesn't insulate a cluster
        skins = pmc.ls(type="skinCluster")
        jnts = {}
        surfs = su.getSelectedSurfs(withAttr="layeredTexture")
        for surf in surfs:
            jnts[surf] = []
            # first, get the skins and try to achieve in bind pose
            # by zeroing all controls
            #self.skins.update(getAffectedClusters(surf))
            for c in surf.controls.get():
                #pmc.makeIdentity(c)
                pmc.xform(c, t=(0, 0, 0), ro=(0, 0, 0), s=(1, 1, 1))

                try:
                    jnts[surf].append(c.rangeU.outputs()[0])
                except AttributeError:
                    pass

            mirSurf = surf.mirror.get()
            if self.mirVec and mirSurf:
                #self.skins.update(getAffectedClusters(mirSurf))
                for c in mirSurf.controls.get():
                    #pmc.makeIdentity(c)
                    pmc.xform(c, t=(0, 0, 0), ro=(0, 0, 0), s=(1, 1, 1))

        # ensure bind pose and disconnect skin
        safeSuspendSkins(skins)

        for surf in surfs:
            # now, ensure good surface components and lock joints
            mirSurf = surf.mirror.get()
            # if rebuild mirror is necessary, it must happen in PRE drag,
            # causes fatal error in post drag!
            if self.mirVec and mirSurf:
                mirrorSurfSpans(surf, mirSurf)

            if self.lockJnts:
                #jnts = [c.rangeU.outputs()[0] for c in surf.controls.get() 
                #        if hasattr(c, "rangeU")]
                for j in jnts[surf]:
                    # now attempt to keep the joint as close as possible to
                    # it's position when it was rigged (saved)
                    cpos = pmc.nt.ClosestPointOnSurface(skipSelect=True)
                    surf.ws >> cpos.inputSurface
                    cpos.inPosition.set(j.origPos.get())
                    j.paramU.unlock()
                    cpos.u >> j.paramU
                    j.paramV.unlock()
                    cpos.v >> j.paramV


    def postDrag(self):
        """Delete CPOS, mirror SURFACE and JOINT if necessary,
        and then LASTLY restore the skinClusters"""
        
        surfs = su.getSelectedSurfs(withAttr="layeredTexture")
        for surf in surfs:
            # mirror surf
            mirSurf = surf.mirror.get()
            if self.mirVec and mirSurf and mirSurf not in surfs:
                mirrorSurfCVs(surf, mirSurf, self.mirVec)
                
            ctrls = [c for c in surf.controls.get() if hasattr(c, "rangeU")]
            for c in ctrls:
                j = c.rangeU.outputs()[0]
                if self.lockJnts:
                    # unlock & mirror joints
                    cpos = j.paramU.inputs()[0]
                    pmc.delete(cpos)
                    j.paramU.lock()
                    j.paramV.lock()

                    # if lockJnts is off, don't need to mirror the jnt param
                    # because it didn't change
                    mirJ = j.mirror.get()
                    # joint AND mirJoint skins (could be different)
                    if self.mirVec and mirJ and c.mirror.get() not in ctrls:
                        # U is inverted
                        mirJ.paramU.unlock()
                        mirJ.paramU.set(1.0 - j.paramU.get())
                        mirJ.paramU.lock()
                        mirJ.paramV.unlock()
                        mirJ.paramV.set(j.paramV.get())
                        mirJ.paramV.lock()

        resetSkins(pmc.ls(type="skinCluster"))


def surfaceEditMode(state, orig):
    """Enter and exit surface edit tool -
    set CV focus state and show/hide intermediate shapes"""
    focusCVs(state=state)
    if orig:
        su.origShapeMode(su.getAllSurfs(withAttr="layeredTexture"), state)


def safeSuspendSkins(skinClusters):
    """Ensure that the skinClusters are all at their bind poses.
    If they are, suspenct them all."""
    for sc in skinClusters:
        bp = sc.bindPose.get()
        notAtPose = bp.getAtPose()
        if notAtPose:
            # returns joints which are NOT at bind pose. abort.
            raise AssertionError(
                "Bind pose could not be achieved for {0}! Ensure "
                "all controls are zeroed. The following joints "
                "are transformed:\n{1}".format(sc, notAtPose))
            pmc.select(cl=True)
    for sc in skinClusters:                
        sc.moveJointsMode(True)


def resetSkins(skinClusters):
    """Reset the bind pose on the given skinClusters"""
    for sc in pmc.ls(type="skinCluster"):
        # reset skinCluster
        sc.moveJointsMode(False)
        sc.recacheBindMatrices()
        jnts = sc.matrix.inputs()
        pmc.dagPose(jnts, name=sc.bindPose.get(), reset=True)


"""
------------------------------------------------------------------------------
------------------------------------------------------------------------------
------------------------------------------------------------------------------

MAIN CLASS - UI AND SURFACE RIGGING METHODS

------------------------------------------------------------------------------
------------------------------------------------------------------------------
------------------------------------------------------------------------------
"""


class SurfaceRigger(object):
    """Class for keeping track of UI and naming conventions."""

    def __init__(self):
        # ensure that the required built-in plugins are enabled OR disabled!
        unknownPlugins = bkTools.mayaSceneUtil.checkPlugins(__pluginRequirements__)
        if unknownPlugins:
            pmc.warning("The following required plugins are missing:\n"
                        "{0}".format("\n".join(unknownPlugins)))

        # things which need to be kept track of between user actions
        self.lastSurf = None
        self.recentlyRigged = []
        self.names = {}
        # BUG makes DecomposeMatrix nodes UNABLE to output anything but XYZ
        # rotation order. While this is the case, twistAxis X is required.
        self.rotOrder = "xyz"

        # UI
        SurfWin = qtu.buildClass(surfRigUi.Ui_SurfRigWindow, "QMainWindow")
        #SurfDock = qtu.buildMayaDock(SurfWin)
        #self.ui = SurfDock()
        # for PySide/PySide2 compatibility
        self.ui = qtu.makeNewDockGui(SurfWin, name=controlName)
        #self.ui = qtu.loadFromUi(relpath+"surfRigUi.ui")
        # connect self.ui's signals to this object's methods
        self.ui.symAxis.currentIndexChanged.connect(
            self.ui.mirrorGrp.setChecked)
        self.ui.nameButton.clicked.connect(self.updateNameDict)
        self.ui.newSurfButton.clicked.connect(
            partial(self.makeNewSurf, simple=False))
        self.ui.simpleSurfButton.clicked.connect(
            partial(self.makeNewSurf, simple=True))
        self.ui.initSurfButton.clicked.connect(self.initUserSurf)

        self.ui.selectCVsButton.clicked.connect(
            lambda: focusCVs(obj=self.lastSurf))
        self.ui.toggleJntsButton.clicked.connect(
            partial(toggleVis, "joints"))
        self.ui.toggleSurfsButton.clicked.connect(
            partial(toggleVis, "nurbsSurfaces"))
        self.ui.newJntButton.clicked.connect(self.addRigJntToSel)

        self.ui.rigButton.clicked.connect(self.rigSurfs)
        self.ui.rigAllButton.clicked.connect(partial(self.rigSurfs, True))
        # int vs double for slider vs spin box
        self.ui.sizeEdit.valueChanged.connect(partial(
            syncSliderAndCtrl, self.ui.sizeSlider, "controlSize", 100, 
            self.recentlyRigged))
        self.ui.sizeSlider.sliderMoved.connect(
            lambda val: self.ui.sizeEdit.setValue(val/100.0))
        self.ui.distanceEdit.valueChanged.connect(partial(
            syncSliderAndCtrl, self.ui.distanceSlider, "controlDistance", 10,
            self.recentlyRigged))
        self.ui.distanceSlider.sliderMoved.connect(
            lambda val: self.ui.distanceEdit.setValue(val/10.0))

        self.ui.newParButton.clicked.connect(self.parentSelected)
        self.ui.parExistingButton.clicked.connect(self.addSelectedToParent)
        self.ui.mirParButton.clicked.connect(self.mirrorParent)
        self.ui.unparentButton.clicked.connect(pc.unparentControl)

        self.ui.resetBindPoseButton.clicked.connect(resetBindPose)
        self.ui.fixOrientsButton.clicked.connect(self.fixOrientsForSel)
        self.ui.surfaceEditButton.clicked.connect(self.safeEditSurf)
        #self.ui.newSoftClusterButton.clicked.connect(self.makeSoftCluster)
        #self.ui.newSoftModButton.clicked.connect()
        self.ui.clusterHandleButton.clicked.connect(self.makeHandleCtrl)
        self.ui.setupBlendshapesButton.clicked.connect(dc.ctrlBlendshapes)
        self.ui.mergeBlendshapesButton.clicked.connect(dc.mergeBlendshapes)

        # apply "valid Maya character" name validator to 
        v = qtu.mayaNameValidator(parent=self.ui)
        self.ui.surfNameEdit.setValidator(v)
        self.ui.jntNameEdit.setValidator(v)
        self.ui.searchEdit.setValidator(v)
        self.ui.replaceEdit.setValidator(v)

        pmc.requires("lookdevKit", "1.0", nodeType="floatCorrect")
        pmc.requires("matrixNodes", "1.0", nodeType="decomposeMatrix")

        # read the user-editable json and set object name dict to
        # defaults + json, priority json (2nd item in list add)
        names = bkTools.mayaSceneUtil.readJson(bkTools.mayaSceneUtil.mergeRelPath(__file__, "names.json"))
        self.updateNameDict(dict(defaultNames.items() + names.items()))
        self.ui.show()

    @qtu.SlotExceptionRaiser
    def updateNameDict(self, data=None):
        """Slot for load JSON button.
        Open file dialog to load a JSON file and read it for relevant keys"""
        if not data:
            f = qtu.getUserFiles(description="Naming Conventions", ext=".json")[0]
            data = bkTools.mayaSceneUtil.readJson(f)
            # might have lots of unnecessary keys, but who cares
        
        self.names.update(data)
        # update the load JSON button
        self.ui.nameButton.setToolTip(
            "Current name dictionary is:\n" + bkTools.mayaSceneUtil.formatDict(self.names) +
            "\nLoad a different JSON to change values for any/all keys.")

        print("Name conventions set.")

    def getTypeBaseName(self, objName, t):
        """Convenience method to mostly determine whether or not
        the object needs to use the {num} field in the naming convention.
        Return value is a string with "{type}" as the only format arg in it."""
        conv = self.names["convention"]
        objName = objName.replace("__", "_").strip("_")
        t = t.replace("__", "_").strip("_")
        if "{num" not in conv:
            # user may have removed {num} argument
            return conv.format(name=objName, type="{type}")

        n = 1
        test = lambda num: pmc.objExists(conv.format(
            name=objName, type=t, num=num))
        if test(n):
            while test(n):
                n += 1
            # at this point n is the first numbered object that doesn't exist
            return conv.format(name=objName, type="{type}", num=n)

        # NO numbered object exists, now test for numberless
        halves = conv.split("{num")
        # remove any trailing bits from argument, eg :02}
        halves[1] = halves[1].split("}", 1)[1]
        noNumConv = "".join(halves).replace("__", "_").strip("_")
        # check existence for numberless obj with same objName
        obj = noNumConv.format(name=objName, type=t)
        if pmc.objExists(obj):
            pmc.rename(obj, conv.format(name=objName, type=t, num=1))
            """
            for v in self.names.values():
                try:
                    # forget sub nodes, just name rename the visible ones
                    obj = pmc.PyNode(noNumConv.format(name=objName, type=v))
                    obj.rename(conv.format(name=objName, type=v, num=1))
                except pmc.MayaNodeError:
                    # invalid entry or nonexistant node, ignore
                    continue
            """
            return conv.format(name=objName, type="{type}", num=2)

        else:
            return noNumConv.format(name=objName, type="{type}")

    def getBaseNameFromObj(self, obj, t):
        """Given an object and what type it is, return a formattable string"""
        n = obj.name().replace(self.names[t], "{type}")
        if "{type}" not in n:
            pmc.warning("Unexpected naming convention changes.")
            n = obj.name() + "_{type}"
        return n

    @qtu.SlotExceptionRaiser
    def makeNewSurf(self, simple=False):
        """Slot method for BOTH "new surface" buttons.
        "Simple" arg indicates simple ie 2x3 nurbs plane, otherwise
        it's a full edge-guided surface."""

        with bkTools.mayaSceneUtil.MayaUndoChunkManager():
            objName = self.ui.surfNameEdit.text()
            if not objName:
                pmc.warning(
                    "No name provided for surface! Default name applied.")
                objName = "untitled_surface"
            # convention is the formattable base string
            n = self.getTypeBaseName(objName, self.names["surface"])

            if simple:
                surf = su.makeSimpleSurf(name=n.format(type=self.names["surface"]))
            else:
                symAx = self.ui.symAxis.currentText()
                symVec = mu.getVectorForAxis(symAx)

                surf = su.makeSurfFromEdges(
                    name=n.format(type=self.names["surface"]), symVec=symVec)

            if not surf:
                return

            self.initExistingSurf(surf, n)

            # set the tool symmetry settings to make editing surface easier
            #pmc.symmetricModelling(about="world", axis=symAx)

    @qtu.SlotExceptionRaiser
    def initUserSurf(self):
        """Get selected user surfaces and pass along to initExisting"""
        with bkTools.mayaSceneUtil.MayaUndoChunkManager():
            surfs = [t for t in pmc.ls(sl=True, transforms=True) if isinstance(
                t.getShape(), pmc.nt.NurbsSurface)]
            for surf in surfs:
                if hasattr(surf, "layeredTexture"):
                    pmc.warning(
                        "Surface {0} is already initialized! Skipped.".format(
                            surf.name()))
                    continue
                # ensure parametrization is 0-1
                if any(p for p in surf.getKnotDomain() if p > 1.0):
                    pmc.rebuildSurface(
                        rebuildType=0, keepControlPoints=True, keepRange=0, ch=0)
                self.initExistingSurf(surf)

    def initExistingSurf(self, surf, n=None):
        """Take existing surf add attributes required for it to work with this
        surf rigging system. It gets message attrs for keeping track of shit:
        jnts, controls, hierarchy groups, and driver attributes for blendshapes
        and control size and distance"""
        if not n:
            n = self.getBaseNameFromObj(surf, "surface")
        surf.addAttr(
            "unriggedJnts", at="message", multi=True, indexMatters=False)
        surf.addAttr(
            "riggedClusters", at="message", multi=True, indexMatters=False)
        surf.addAttr(
            "controls", at="message", multi=True, indexMatters=False)
        surf.addAttr("sCtrlsGrp", at="message")
        surf.addAttr("jntGrp", at="message")
        surf.addAttr("layeredTexture", at="message")
        surf.addAttr("blendDriver", at="message")
        surf.addAttr("mirror", at="message")
        surf.addAttr("container", at="message")
        surf.addAttr("controlSize", k=False, dv=1.0)
        surf.addAttr("controlDistance", k=False, dv=1.0)
        surf.addAttr("controlsFlipped", at="bool", k=False)

        # delete shape history
        pmc.delete(surf, ch=True)
        # make sure all transforms are happening via CVs
        pmc.makeIdentity(surf, apply=True)
        surf.setPivots((0, 0, 0))
        rcu.setAttrChannelBox(surf, ["t", "r", "s"], False)
        surf.addAttr("TRANSFORM_SURFACE_VIA_CVS", at="enum", en=" ", k=True)
        surf.TRANSFORM_SURFACE_VIA_CVS.lock()

        self.setupSurfHierarchy(surf, n)
        self.lastSurf = surf

        pmc.select(surf)

    def setupSurfHierarchy(self, surf, n):
        """create rigGrp and ctrlGrp, as well as shading nodes for layered
        textures requires certain attributes to already exist on the surface"""

        srfGrp = pmc.nt.Transform(n=n.format(type=self.names["rig group"]))
        sCtrlsGrp = pmc.nt.Transform(
            n=n.format(type=self.names["surface controls group"]))
        #pmc.parentConstraint(sCtrlsGrp, srfGrp, mo=False)
        sCtrlsGrp.t >> srfGrp.t
        sCtrlsGrp.r >> srfGrp.r
        sCtrlsGrp.s >> srfGrp.s
        jntGrp = pmc.nt.Transform(
            n=n.format(type=self.names["joint group"]), p=srfGrp)
        surf.setParent(srfGrp)

        # create asset container for this surface
        container = pmc.container(name=n.format(type="RIG_NODES"))
        container.addAttr("surface", at="message")
        surf.container >> container.surface

        # ensure surface is aware of its related groups
        sCtrlsGrp.message >> surf.sCtrlsGrp
        jntGrp.message >> surf.jntGrp

        with bkTools.mayaSceneUtil.NodeOrganizer(bkTools.mayaSceneUtil.addNodeToAssetCB(container)):
            shape = rcu.createBlankShape(n.format(type="blendshapes"))
            shape.message >> surf.blendDriver
            shape.getTransform().setParent(surf.sCtrlsGrp.get())

            # create layered texture for surf
            texture = pmc.nt.LayeredTexture(n=n.format(type="layeredTexture"))
            texture.message >> surf.layeredTexture
            # [0] is non-existent at this point, have to initialize
            texture.attr("inputs")[0].color.set(1, 1, 1)
            #background = texture.attr("inputs")[0]
            #background.isVisible.set(False)

            # create shading stuff, for user feedback
            # of jnt UV limits (highlighted area)
            shader, sg = pmc.createSurfaceShader(
                "lambert", name=n.format(type="shader"))
            pmc.sets(sg, forceElement=surf)
            texture.outColor >> shader.color

            # control flipping nodes
            flip = pmc.nt.FloatCondition(n=n.format(type="FLIPCTRLS"))
            flip.floatA.set(-1)
            flip.floatB.set(1)
            surf.controlsFlipped >> flip.condition
            # flipDist = pmc.nt.MultDoubleLinear(n=n.format(type="FLIPDIST"))
            # flip.outFloat >> flipDist.input1
            # surf.controlDistance >> flipDist.input2   

    @qtu.SlotExceptionRaiser
    def addRigJntToSel(self):
        """Called by button press, collect args and run"""

        try:
            surf = su.getSelectedSurfs(withAttr="layeredTexture")[0]
        except IndexError:
            pmc.warning("Select a surface to add joint to.")
            return
        objName = self.ui.jntNameEdit.text()
        if not objName:
            pmc.warning("Rig joint not named. Default name applied.")
            objName = surf.name().replace(self.names["surface"], "")

        with bkTools.mayaSceneUtil.MayaUndoChunkManager():
            addTo = bkTools.mayaSceneUtil.addNodeToAssetCB(surf.container.get())
            with bkTools.mayaSceneUtil.NodeOrganizer(addTo):
                n = self.getTypeBaseName(objName, self.names["joint"])
                jnt = jc.addRigJnt(surf, n, self.names, self.rotOrder)
                print("Joint {0} successfully added to surface!".format(
                    jnt.name()))
                pmc.select(jnt)

    @qtu.SlotExceptionRaiser
    def makeHandleCtrl(self):
        """Slot for button press, clusterHandleButton.
        Get selection and determine type, pass off to correct
        control creation method."""

        with bkTools.mayaSceneUtil.MayaUndoChunkManager():
            sel = pmc.ls(sl=True, type="transform")
            new = False
            deformers = {
                "cluster": dc.rigCluster,
                "softMod": dc.rigSoftMod}
            for t, rig in deformers.items():
                for h in sel:
                    # many steps must be taken for either one, complete them
                    # here before passing off to specialized methods
                    try:
                        d = h.outputs(type=t)[0]
                    except IndexError:
                        # not the right type, ignore
                        continue

                    if not d.relative.get():
                        pmc.warning("Deformer must be in relative mode! "
                                    "{0} is not.".format(d.name()))
                        continue

                    # uvs is a descending weight list of (wt, surf, u, v)
                    uvs = dc.getSurfUvAndWeight(d)
                    if not uvs:
                        pmc.warning("Handle {0} doesn't seem to affect "
                                    "anything. Skipped.".format(h.name()))
                        continue

                    if d.name().strip("0123456789") == t:
                        # not user named, get surface name
                        pmc.warning(
                            "Default name applied based on affected surfaces.")
                        # average the names of the highest weighted surfaces
                        surfList = [j[1].replace(self.names["surface"], "") 
                                    for j in uvs]
                        n = bkTools.mayaSceneUtil.avgMayaName(surfList)
                        n = self.getTypeBaseName(n, t)
                        h.rename(n.format(type=t))
                    else:
                        # user has named it, use that instead
                        n = self.getTypeBaseName(h.name(), t)

                    addTo = bkTools.mayaSceneUtil.addNodeToAssetCB(uvs[0][1].container.get())
                    with bkTools.mayaSceneUtil.NodeOrganizer(addTo):
                        ctrl = rig(h, uvs, self.rotOrder, n, self.names)

                    ctrl.addAttr("strength", min=-2.0, max=2, k=True, dv=1.0)
                    ctrl.strength >> d.envelope
                    h.visibility.set(0)
                    rcu.setAttrChannelBox(
                        h, ["translate", "rotate", "scale"], False)

                    new = True
                    print("{0} successfully rigged!".format(h.name()))

            if not new:
                pmc.warning("Nothing rigged. Select relative softMod/cluster "
                            "handles to rig.")


    # ------------------------------------------------------------------------


    @qtu.SlotExceptionRaiser
    def rigSurfs(self, rigAll=False):
        """Slot for both rig selection and rig all.
        Get surfs & data then mirror & rig accordingly"""
        with bkTools.mayaSceneUtil.MayaUndoChunkManager():

            if rigAll:
                surfs = [s for s in pmc.ls(type="transform") if hasattr(
                    s, "unriggedJnts")]
            else:
                surfs = su.getSelectedSurfs(withAttr="layeredTexture")
            
            if not surfs:
                pmc.warning("No surfaces to rig.")
                return

            # get symmetry settings for rigging
            symAx = self.ui.symAxis.currentText()
            if symAx == "None":
                mirArgs = (None, None, None, None, None)
            else:
                mirSrf = self.ui.mirrorBoth.isChecked()
                mirJnts = mirSrf or self.ui.mirrorJnts.isChecked()
                mirArgs = (
                    mu.getVectorForAxis(symAx), mirJnts, mirSrf,
                    self.ui.searchEdit.text(), self.ui.replaceEdit.text())

            self.recentlyRigged = []
            for s in surfs:
                # mirrorRig returns list of surfs (including any new ones)
                mirrored = self.mirrorRig(s, mirArgs)
                for side in mirrored:
                    # each surface will have its own container
                    addTo = bkTools.mayaSceneUtil.addNodeToAssetCB(side.container.get())
                    with bkTools.mayaSceneUtil.NodeOrganizer(addTo):
                        self.rigSurf(side)

    def mirrorRig(self, s, mirArgs):
        """Perform mirroring as required by mirArgs, a list of
        symmetry vector, desired mirroring operations, and replace strings"""

        surfs = [s]
        if not self.ui.mirrorGrp.isChecked():
            return surfs
        mirVec, mirJnts, mirSrf, src, tar = mirArgs
        source = {"surf": s, "side": src}
        target = {"surf": s, "side": tar}
        if mirSrf:
            # mirror BOTH
            mirS = self.mirrorSurface(s, src, tar, mirVec)
            target["surf"] = mirS
            self.mirrorJoints(source, target, mirVec)
            surfs.append(mirS)
        elif mirJnts:
            # SAME surface, mirror joints only
            self.mirrorJoints(source, target, mirVec)

        return surfs

    def mirrorSurface(self, surf, src, tar, mirVec):
        """Create a new surface which is the given surface
        mirrored across the given axis."""

        mirSurf = surf.mirror.get()
        if not mirSurf:
            srcN = self.getBaseNameFromObj(surf, "surface")
            n = srcN.replace(src, tar)
            if n == srcN:
                n = n.format(type="mir_{type}")

            mirSurf = pmc.duplicate(
                surf, n=n.format(type=self.names["surface"]))[0]
            surf.mirror >> mirSurf.mirror
            mirSurf.controlsFlipped.set(True)

            # create groups, shading stuff and relevant connections
            self.setupSurfHierarchy(mirSurf, n)

        mirrorSurfSpans(surf, mirSurf)
        mirrorSurfCVs(surf, mirSurf, mirVec)

        return mirSurf

    def mirrorJoints(self, source, target, mirVec):
        """Mirror all joints on source surface across given axis
        and onto target surface. Source and target surfaces may be
        the same or different."""
        
        surf, origStr = source["surf"], source["side"]
        mirSurf, mirStr = target["surf"], target["side"]

        jnts = surf.unriggedJnts.get()
        addTo = bkTools.mayaSceneUtil.addNodeToAssetCB(mirSurf.container.get())
        with bkTools.mayaSceneUtil.NodeOrganizer(addTo):
            for j in jnts:
                srcN = self.getBaseNameFromObj(j, "joint")
                n = srcN.replace(origStr, mirStr)
                if n == srcN:
                    # if no change to name, force one
                    n = n.format(type="mir_{type}")

                mirJ = mirrorJointAcross(
                    j, mirVec, (mirSurf, n, self.names, self.rotOrder))
                try:
                    print("Joint {0} successfully mirrored to {1}!".format(
                        j.name(), mirJ.name()))
                except AttributeError:
                    pass

    def rigSurf(self, surf):
        """Rig the given surface. At this point, the connections are as such:
        geo const -> jnt -> cpos -> posi
        And they are changed to:
        posi -> ctrl -> geo/pt con -> rigLoc -> cpos -> limit -> foll -> jnt"""

        jntGrp = surf.jntGrp.get()
        # .unriggedJnts is a multi-message attr connected to all of the jnts
        # which are NOT already rigged (they are disconnected herein)
        jnts = surf.unriggedJnts.get()
        for jnt in jnts:
            n = self.getBaseNameFromObj(jnt, "joint")
            ctrl = self.makeJntCtrl(surf, jnt, n)
            
            try:
                mirCtrl = jnt.mirror.get().rangeU.inputs()[0]
            except AttributeError:
                # jnt has no mirror, surf has no mirror
                pass
            except IndexError:
                # jnt is not rigged yet, ignore
                pass
            else:
                try:
                    ctrl.mirror >> mirCtrl.mirror
                except RuntimeError:
                    # error "cannot connected to itself" means
                    # center object, connect just like the joint
                    ctrl.message >> ctrl.mirror

            # create dynamic "follicle" and other nodes to allow
            # ctrl to control rigjnt in a nice way
            jnt.setParent(jntGrp)
            jc.makeJntDynamic(surf, jnt, ctrl, self.rotOrder, n)
            # jntGrp is child of rigGrp, which is parConstrained by sCtrlsGrp
            # which can be assumed to be parented to head ctrl

            # remove from srf's connected multi of jnts yet to be rigged
            jnt.message.disconnect()
            # add control to surf's message list
            ctrl.surface.connect(surf.controls, nextAvailable=True)
            print("Joint {0} successfully rigged!".format(jnt.name()))

        if not jnts:
            pmc.warning("Nothing to rig on surface {0}!".format(surf.name()))
        else:
            surf.controlDistance.set(self.ui.distanceEdit.value())
            surf.controlSize.set(self.ui.sizeEdit.value())
            self.recentlyRigged.append(surf)

    def makeJntCtrl(self, surf, jnt, n):
        """Kill old "placement" connections, expose jnt param-limit attrs
        create control groups, ctrl, loc and cpos
        create blend node to allow for turning OFF follicle-style rotations"""

        cpos = jnt.translate.outputs()[0]
        posi = cpos.u.outputs()[0]

        # kill old connections
        cpos.u.disconnect(posi.u)
        cpos.v.disconnect(posi.v)
        jnt.translate.disconnect()
        pmc.delete(jnt.geometry.inputs())

        # just to make original U/V a bit more accessible
        jnt.addAttr("paramU", min=0.0, max=1.0, dv=posi.u.get(), k=False)
        jnt.paramU >> posi.u
        jnt.paramU.lock()
        jnt.addAttr("paramV", min=0.0, max=1.0, dv=posi.v.get(), k=False)
        jnt.paramV >> posi.v
        jnt.paramV.lock()
        jnt.addAttr("origPos", type="float3", uac=False)
        jnt.origPos.set(jnt.getTranslation(ws=True))
        jnt.origPos.lock()

        # make ctrl and setup its orientation,
        # add attributes which drive the jnt's limit attrs
        twistAxis = self.rotOrder[0]
        ctrlGrp = posi.position.outputs(type="transform")[0]
        ctrl, ctrlGrp, offsetGrp = jc.makeFollCtrl(
            n, ctrlGrp, typeDict=self.names, rotOrder=self.rotOrder)
        ctrl.addAttr("rangeU", min=0.0, max=0.999, k=False)
        ctrl.rangeU.set(jnt.rangeU.get())
        ctrl.rangeU >> jnt.rangeU
        ctrl.addAttr("rangeV", min=0.0, max=0.999, k=False)
        ctrl.rangeV.set(jnt.rangeV.get())
        ctrl.rangeV >> jnt.rangeV
        ctrl.addAttr("SurfaceUV_LimitsOnJoint", at="bool", k=False)
        ctrl.SurfaceUV_LimitsOnJoint.set(jnt.SurfaceUV_LimitsOnJoint.get())
        ctrl.SurfaceUV_LimitsOnJoint >> jnt.SurfaceUV_LimitsOnJoint
        ctrl.addAttr("autoRotate", min=0.0, max=1.0, dv=1.0, k=True)
        ctrl.attr("t" + twistAxis).setLocked(True)
        rcu.setAttrChannelBox(ctrl, ["scale"], False)

        loc = makeStickyLoc(surf, ctrl, n, ctrlGrp, skipAxis=twistAxis)
        loc.setParent(ctrlGrp)

        # hook up cpos -> limit -> foll
        loc.worldPosition >> cpos.inPosition

        jc.connectSizeDistFlip(surf, ctrl, ctrlGrp, offsetGrp, self.rotOrder)

        # for ease of access later
        cpos.u >> jnt.preclampedU
        cpos.v >> jnt.preclampedV

        # final output of ctrl affected parameters (outputR and outputG)
        return ctrl

    @qtu.SlotExceptionRaiser
    def parentSelected(self):
        """Slot for make parent control button press (newParButton)
        Creates a parent control shape for each selected jnt/cluster control"""
        ctrls = [s for s in pmc.ls(sl=True) if hasattr(s, "parentControls")]
        if not ctrls:
            pmc.warning("No valid controls selected to parent!")
            return

        with bkTools.mayaSceneUtil.MayaUndoChunkManager():
            self.parentCtrls(ctrls)

    @qtu.SlotExceptionRaiser
    def mirrorParent(self):
        """Mirror each selected parent control. If the mirror exists, update
        the target's weight attributes. If not, create one."""
        pars = [p for p in pmc.ls(sl=True) if hasattr(p, "childControls")]
        if not pars:
            pmc.warning("No parent controls selected.")

        with bkTools.mayaSceneUtil.MayaUndoChunkManager():
            for p in pars:
                mirP = p.mirror.get()

                # the only controls I want are ones with mirror images
                ctrls = [c for c in p.childControls.outputs() if c.mirror.get()]
                if not mirP:
                    # create one!
                    mirCtrls = [c.mirror.get() for c in ctrls]
                    if set(ctrls) == set(mirCtrls):
                        pmc.warning("Selected parent {0} is already "
                                    "symmetrical! Skipped.".format(p.name()))
                        continue

                    mirP = self.parentCtrls(mirCtrls)
                    p.mirror >> mirP.mirror

                # update all of the mirP weights and custom attrs
                for c in ctrls:
                    mirC = c.mirror.get()
                    attr = pc.getParWtAttr(c, p)
                    mirAttr = pc.getParWtAttr(mirC, mirP)
                    
                    if not mirAttr:
                        # mirP is NOT a parent of mirC! Add it.
                        n = self.getBaseNameFromObj(mirC, "control")
                        pc.parentCtrlTo(mirC, mirP, n, self.rotOrder)
                        mirAttr = pc.getParWtAttr(mirC, mirP)

                    mirAttr.set(attr.get())

                mirP.rotateChildren.set(p.rotateChildren.get())
                mirP.showChildControls.set(p.showChildControls.get())
                # update SHAPE as well
                mirVec = [-1 if c else 1 for c in mu.getVectorForAxis(
                    self.ui.symAxis.currentText())]
                for i in range(p.numCVs()):
                    mirPos = p.cv[i].getPosition(space="world") * mirVec
                    mirP.cv[i].setPosition(mirPos, space="world")

                print("Parent control {0} mirrored to {1}".format(p, mirP))

    def parentCtrls(self, ctrls):
        """Get UVs list and other data needed to create a new weighted ctrl.
        Then create matrix-based parent relationship for arg ctrls."""

        n = bkTools.mayaSceneUtil.avgMayaName(
            [s.replace(self.names["control"], "") for s in ctrls])
        n = self.getTypeBaseName(
            n, self.names["parent"] + "_" + self.names["control"]).format(
                type=self.names["parent"] + "_{type}")

        surfs = [c.surface.get() for c in ctrls]
        domSurf = sorted(surfs, key=surfs.count)[-1]
        addTo = bkTools.mayaSceneUtil.addNodeToAssetCB(domSurf.container.get())
        with bkTools.mayaSceneUtil.NodeOrganizer(addTo):

            parCtrl = pc.makeParentCtrl(domSurf, n, self.names, self.rotOrder)

            for ctrl in ctrls:
                n = self.getBaseNameFromObj(ctrl, "control")
                pc.parentCtrlTo(ctrl, parCtrl, n, self.rotOrder)

        return parCtrl

    @qtu.SlotExceptionRaiser
    def addSelectedToParent(self):
        """Slot for add selection to parent (parExistingButton)
        Selection order MATTERS here. First x are child controls,
        last selected is the parent control"""
        ctrls = [s for s in pmc.ls(sl=True) if hasattr(s, "parentControls")]
        if len(ctrls) < 2:
            pmc.warning("Select at least one child (joint or cluster control)"
                        " and exactly one parent control.")
            return

        par = ctrls.pop()
        # have to adjust parent's wtPosi, so get entire list of ctrls affected
        # and just re-do it from scratch
        try:
            alreadyAffected = par.childControls.outputs()
        except AttributeError:
            # not a valid parent object.
            pmc.warning("Last selected object {0} is not a valid parent "
                        "control.".format(par.name()))
            return

        with bkTools.mayaSceneUtil.MayaUndoChunkManager():
            addTo = bkTools.mayaSceneUtil.addNodeToAssetCB(par.surface.get().container.get())
            with bkTools.mayaSceneUtil.NodeOrganizer(addTo):
                for ctrl in ctrls:
                    if ctrl in alreadyAffected:
                        pmc.warning("{0} is already parented to {1}.".format(
                            ctrl.name(), par.name()))
                        continue

                    n = self.getBaseNameFromObj(ctrl, "control")
                    pc.parentCtrlTo(ctrl, par, n, self.rotOrder)

    @qtu.SlotExceptionRaiser
    def fixOrientsForSel(self):
        """Get surfaces and arguments to fix the orientation of surf controls"""
        surfs = su.getSelectedSurfs(withAttr="layeredTexture")
        if not surfs:
            pmc.warning("No surfaces selected.")
            return
            
        allAxes = (
            pmc.dt.Vector.xAxis, pmc.dt.Vector.xNegAxis, pmc.dt.Vector.yAxis, 
            pmc.dt.Vector.yNegAxis, pmc.dt.Vector.zAxis, pmc.dt.Vector.zNegAxis)
        
        with bkTools.mayaSceneUtil.MayaUndoChunkManager():
            for surf in surfs:
                fixSurfaceOrients(surf, allAxes, self.rotOrder)

    @qtu.SlotExceptionRaiser
    def safeEditSurf(self):
        """Slot for Edit Surface button.
        Create a new SurfaceEditor context and enter it.
        Seems kinda dangerous still if all CVs are unlocked."""
        if self.ui.editMirCheck.isChecked():
            mirVec = mu.getVectorForAxis(self.ui.symAxis.currentText())
        else:
            mirVec = None
        lockJnts = self.ui.editLockCheck.isChecked()
        orig = self.ui.editOrigCheck.isChecked()
        srfEdit = SurfaceEditor(lockJnts, mirVec)

        manipContext = pmc.manipMoveContext
        
        ctxArgs = {
            "preCommand": lambda: surfaceEditMode(True, orig),
            "preDragCommand": [srfEdit.preDrag, pmc.nt.NurbsSurface],
            "postDragCommand": [srfEdit.postDrag, pmc.nt.NurbsSurface],
            "postCommand": lambda: surfaceEditMode(False, orig),
            "image1": "surfaceEditor.png"}

        # perhaps edit default move/rot/scale tools?
        #pmc.manipMoveContext("Move", e=True, preDragCommand=boop)
        # if I edit default tools, how to ensure that they are returned
        # to normal?
        # I could just write the callbacks so that they are safe, but
        # that's just too smelly.
        # kinda just leaning towards doing translate only...
        #
        # EVEN IF I stick with trans only...
        # what if I enter the tool and then SAVE the scene?
        # is the tool __exit__ called before saving??
        # I may just need to make the tool safer in general,
        # ie only selection (ui) changes, no templating etc

        surfEditCtx = manipContext(**ctxArgs)
        pmc.setToolTo(surfEditCtx)





"""
------------------------------------------------------------------------------
------------------------------------------------------------------------------
------------------------------------------------------------------------------

SUPPORT FUNCTIONS

------------------------------------------------------------------------------
------------------------------------------------------------------------------
------------------------------------------------------------------------------
"""





def makeStickyLoc(surf, ctrl, n, ctrlGrp, skipAxis=None):
    """Create a locator which is geoConstrained to the given surface
    but moves with the given ctrl. Optional argument skipAxis allows 
    "height" transforms on the ctrl to be ignored."""
    loc = pmc.spaceLocator(n=n.format(type="RIG_LOC"))
    loc.setParent(ctrlGrp)
    loc.visibility.set(False)
    pmc.makeIdentity(loc)

    pmc.geometryConstraint(surf, loc)
    # direct connect just as good as pointCon since loc is
    # in same non-follVec space
    """
    for a in "xyz":
        if a != skipAxis:
            ctrl.attr("t" + a) >> loc.attr("t" + a)
    """
    pmc.pointConstraint(ctrl, loc, skip=skipAxis)

    return loc


def mirrorJointAcross(jnt, mirVec, addJntArgs, tol=.01):
    """Given two joints and an axis, mirror the first joint across the axis"""

    # now, get inverted ws translate
    pos = jnt.getTranslation(ws=True)
    if abs(pos[mirVec.index(1)]) < tol:
        # close enough to axis of reflection, consider a "middle" jnt
        jnt.message >> jnt.mirror
        return
    
    mirJnt = jc.addRigJnt(*addJntArgs)

    mirJnt.SurfaceUV_LimitsOnJoint.set(jnt.SurfaceUV_LimitsOnJoint.get())
    mirJnt.rangeU.set(jnt.rangeU.get())
    mirJnt.rangeV.set(jnt.rangeV.get())
    jnt.mirror >> mirJnt.mirror
    # reflection of pos across mirVec
    inv = pos - 2 * pos.dot(mirVec) * mirVec

    mirJnt.setTranslation(inv, ws=True)
    return mirJnt


def mirrorSurfSpans(surf, mirSurf):
    """Precursor to CVs being mirrored - spans and knots must be identical"""
    # ensure same spans
    su, sv = surf.spansU.get(), surf.spansV.get()
    if mirSurf.spansU.get() != su or mirSurf.spansV.get() != sv:
        pmc.rebuildSurface(
            mirSurf.getShape(), su=su, sv=sv, keepCorners=True,
            replaceOriginal=True, rebuildType=0, endKnots=1)

    # now that spans are the same, ensure knots are placed correctly
    ku = [1.0 - k for k in surf.getKnotsInU()]
    mirSurf.setKnotsInU(reversed(ku), 0, len(ku) - 1)
    kv = surf.getKnotsInV()
    mirSurf.setKnotsInV(kv, 0, len(kv) - 1)
    

def mirrorSurfCVs(surf, mirSurf, mirVec):
    """Perform the CV mirroring across symAx action.
    First arg is orig surf, second is mirror surf, third is symmetry axis"""

    cvU = range(surf.numCVsInU())
    cvV = range(surf.numCVsInV())
    # rather than having to perform a (apparently unstable)
    # reverseSurface operation, just do it manually by
    # reversing U cvs and knots for mirror surface!
    for u, mirU in zip(cvU, reversed(cvU)):
        for v in cvV:
            pos = surf.getCV(u, v)
            mPos = pos * [-1 if c else 1 for c in mirVec]
            mirSurf.setCV(mirU, v, mPos)

    # fix display
    mirSurf.doubleSided.set(0)
    mirSurf.doubleSided.set(1)


def fixSurfaceOrients(surf, allAxes, rotOrder):
    """Depending on the shape of an individual surface, the default 
    control orientation may have strange results, particularly if
    the control's X aligns closely with the local Y.
    This function fixes the controls' default orientations."""

    norm, tanU, tanV = su.avgSurfVectors(surf)
    # find the axis with which the surface's normal & tangents
    # are most closely aligned
    locX = max((norm.dot(ax), ax) for ax in allAxes)[1]
    if locX == mu.getVectorForAxis(rotOrder[0]):
        pmc.warning("Controls already have optimal orientation!")
        return
    
    locY = max((tanU.dot(ax), ax) for ax in allAxes)[1]
    locZ = max((tanV.dot(ax), ax) for ax in allAxes)[1]
    
    for c in [c for c in surf.controls.get() if not hasattr(c, "childControls")]:
        try:
            statMat = c.controlGroup.get().r.inputs()[0].inputs()[0]
        except IndexError:
            # special case for weighted controls
            fixWeightedOrients(c, rotOrder, locY, locZ)
        else:
            vecMap = {"x": (statMat.in00, statMat.in01, statMat.in02),
                      "y": (statMat.in10, statMat.in11, statMat.in12),
                      "z": (statMat.in20, statMat.in21, statMat.in22)}
            
            for val, plug in zip(locY, vecMap[rotOrder[1]]):
                plug.set(val)
                print("{0} set to {1}".format(plug, val))
            for val, plug in zip(locZ, vecMap[rotOrder[2]]):
                plug.set(val)
                print("{0} set to {1}".format(plug, val))

    print("{0} controls successfully re-oriented!".format(surf))



def fixWeightedOrients(ctrl, rotOrder, locY, locZ):
    """this is for weighted controls - wtAvgPosi is slightly different,
    and just need to set the shit AND where it is inverted as well"""

    ctrlGrp = ctrl.controlGroup.get()
    wtAvgPosi = ctrlGrp.t.inputs()[0]
    # set whichever rows are 2nd and 3rd in rotOrder
    # to align with fixed axes closest to tanU and tanV
    rm = pmc.dt.TransformationMatrix()
    rm["xyz".index(rotOrder[0])] = wtAvgPosi.n.get()
    rm["xyz".index(rotOrder[1])] = locY
    rm["xyz".index(rotOrder[2])] = locZ

    ctrlGrp.setRotation(rm.getRotationQuaternion())
    # since there is no active connection from ctrlGrp to orientation matrix,
    # need to explicitly write it so transforms work right
    orientMat = ctrl.m.outputs(type="multMatrix")[0]
    orientMat.matrixIn[0].set(rm.asMatrix().inverse())
    orientMat.matrixIn[3].set(rm)


"""
TO DO:
- replace floatCorrect nodes with addDoubleLinear + multDoubleLinear?
"""


def main(replace=False):
    """Create UI for easy surface rig creation. Shelf button."""
    dockName = controlName + "WorkspaceControl"
    if not replace and pmc.control(controlName, q=True, ex=True):
        qtu.showUi(controlName)
        qtu.showUi(dockName)
        return

    qtu.deleteUi(controlName)
    qtu.deleteUi(dockName)

    SurfaceRigger()



"""
------------------------------------------------------------------------------

CURRENTLY UNUSED - EXPERIMENTAL UTILITIES

------------------------------------------------------------------------------
"""


"""
    def makeSoftCluster(self):
        #Slot for button press, gather required selection data
        #and create a soft cluster for relevant CVs
        #with rcu.MayaUndoChunkManager():
            # CVs are "double3"
            origSel = pmc.selected(flatten=True, type="double3")
            if not origSel:
                pmc.warning(
                    "Select at least one surface CV with SoftSelection on.")
                return    
            surfs = pmc.selected(objectsOnly=True)
            for surf in surfs:
                surfCVs = [cv for cv in origSel if cv.node() == surf]
                name = surf.name() + "{0}"
                handle = makeSoftClusterOnSurf(surf, surfCVs, name)[1]
                if self.ui.clusterCtrlCheck.isChecked():
                    ctrl = self.makeHandleCtrl(surf, handle, name)
                    ctrl.surface.connect(surf.controls, nextAvailable=True)


def makeSoftClusterOnSurf(surf, origSel, n):
    #Create a cluster of CVs from a softselection
    if not origSel:
        pmc.warning(
            "Select one or more CVs and set softSelect distance as desired.")
        return None, None
    if pmc.softSelect(q=True, softSelectFalloff=True):
        # Volume mode is 0
        pmc.warning("Soft Select tool must be set to \"Volume\" mode.")
        return None, None
    if not pmc.softSelect(q=True, softSelectEnabled=True):
        pmc.warning(
            "Standard cluster created. Enable soft-select for a soft cluster.")
        return pmc.cluster(n=n.format(type="cluster"), relative=True)
    cluster, handle = pmc.cluster(
        surf.cv, n=n.format(type="softCluster"), relative=True)

    # find a good place for handle origin
    i = 0
    pos = pmc.dt.Vector(0, 0, 0)
    for cv in origSel:
        i += 1
        pos += surf.getCV(*cv.indices()[0])
    # already have ensured sel is non-empty so i can't be 0
    pos /= i
    handle.origin.set(pos)
    handle.origin >> handle.rotatePivot
    handle.origin >> handle.scalePivot
    
    # get soft select info
    #falloffType = pmc.softSelect(q=True, ssf=True)
    maxDist = pmc.softSelect(q=True, ssd=True)
    #uvDist = pmc.softSelect(q=True, sud=True)
    
    cvDistDict, removeList = getVolumeDistances(surf, origSel, maxDist)
    cSet = cluster.outputs(type="objectSet")[0]
    for cv in removeList:
        pmc.sets(cSet, remove=cv)
    setClusterWeights(cluster, cvDistDict, maxDist)

    print("Cluster {0} successfully created.".format(cluster.name()))

    return cluster, handle


def getVolumeDistances(surf, origSel, maxDist):
    #Return dict of CV: distance considered
    #from a direct vector subtraction.
    cvDistDict = {}
    removeList = []

    for cv in surf.cv:
        ind = cv.indices()[0]
        pos = surf.getCV(*ind)
        distList = []
        for o in origSel:
            # have to check distanc from each
            # originally selected CV smallest distance
            oInd = o.indices()[0]
            oPos = surf.getCV(*oInd)
            distList.append((oPos - pos).length())
        dist = min(distList)
        if dist < maxDist:
            cvDistDict[cv] = dist
        else:
            # PRUNE FROM MEMBERSHIP!!!
            removeList.append(cv)
    
    return cvDistDict, removeList


def setClusterWeights(cluster, cvDistDict, maxDist):
    #Given the CV: distance dict, set the 
    #cluster weights according to falloff

    # softSelect falloff curve query returns a comma-separated string of floats
    # have to massage the data to use it for remapValue node
    # make ints, make packets of 3, reverse position/value indices
    curveVals = [float(i) for i in pmc.softSelect(q=True, ssc=True).split(",")]
    remapVals = [
        [curveVals[i+1], curveVals[i], curveVals[i+2]]
        for i in range(0, len(curveVals), 3)]

    rv = pmc.nt.RemapValue()
    # automatically scales falloff curve to inputMax
    rv.inputMax.set(maxDist)
    for i, pt in enumerate(remapVals):
        rv.value[i].set(*pt)

    # run distance through curve remap to get weight
    for cv in cvDistDict:
        rv.inputValue.set(cvDistDict[cv])
        pmc.percent(cluster, cv, v=rv.outValue.get())
    
    pmc.delete(rv)
"""


class skinDetacher(object):
    """Context manager to safely detach and reattach skin clusters.
    Problem is, it still requires a bind pose reset afterwards."""
    def __init__(self, scs):
        self.scs = [sc for sc in scs if isinstance(sc, pmc.nt.SkinCluster)]
        if not scs:
            pmc.warning("No skinClusters passed in to detach!")

    def __enter__(self):
        # ensure bind pose and detach
        safeSuspendSkins(self.scs)

    def __exit__(self, *args):
        # reattach and reset
        resetSkins(self.scs)


class jointMover(object):
    """Context manager to unlock and relock the paramU and paramV
    attributes of a surface joint."""
    def __init__(self, jnt):
        self.jnt = jnt
    
    def __enter__(self):
        self.jnt.paramU.unlock()
        self.jnt.paramV.unlock()
    
    def __exit__(self, *args):
        self.jnt.paramU.lock()
        self.jnt.paramV.lock()


class surfEditContext(object):
    """User-exposed context manager for performing any operations on
    rigging/skinned surfaces. Either pass in surface or have it selected.
    E.G. (with surface selected):
    with surfRig.surfEditContext(): rebuildSurface(args)"""
    def __init__(self, surf=None):
        if not surf:
            try:
                surf = su.getSelectedSurfs(withAttr="layeredTexture").pop()
            except IndexError:
                pmc.warning("Select a valid rig surface or pass one as argument.")
                raise RuntimeError
        elif not hasattr(surf, "layeredTexture"):
            # invalid arg surf
            pmc.warning("Argument {0} is not a valid rig surface.".format(surf))
            raise RuntimeError

        self.surf = surf
        # jnts is a dictionary of joint: starting position
        jnts = jc.getRiggedJnts(surf)
        self.jnts = dict.fromkeys(jnts)
        self.scs = list(set(
            [sc for j in jnts for sc in j.outputs(type="skinCluster")]))

    def __enter__(self):
        """Detach all skin clusters and save joint worldspace positions."""
        safeSuspendSkins(self.scs)

        for j in self.jnts:
            self.jnts[j] = self.surf.getPointAtParam(
                j.paramU.get(), j.paramV.get(), space="world")

    def __exit__(self, *args):
        """Ensure joints are back where they should be, and reattach skins."""
        for j, p in self.jnts.items():
            # worldspace!
            u, v = su.closestOnSurf(self.surf, p, local=False)
            with jointMover(j):
                j.paramU.set(u)
                j.paramV.set(v)

        resetSkins(self.scs)


def editJntParams(jnt, u, v, tryMir=True):
    """Safely dit base param values for given joint,
    and its mirror (if it has one)."""
    with skinDetacher(jnt.outputs(type="skinCluster")):
        with jointMover(jnt):
            jnt.paramU.set(u)
            jnt.paramV.set(v)
    mir = jnt.mirror.get()
    if tryMir and mir:
        editJntParams(mir, 1.0 - u, v, False)


def moveJointsToSurf(jnts, newSurf):
    """Given a list of joints and a target surface, "move" the joints
    from their old surface to the target (ie, slide along the new surface)"""

    # surface must be REBUILT to 0-1 params and INITIALIZED
    for jnt in jnts:
        ctrl = jnt.rangeU.inputs()[0]
        oldSurf = ctrl.surface.get()
        # replace surf.local inputs: statPosi, dynPosi
        statPosi = jnt.inputs(type="pointOnSurfaceInfo")[0]
        dynPosi = ctrl.controlGroup.get().inputs(type="pointOnSurfaceInfo")[0]
        newSurf.local >> statPosi.inputSurface
        newSurf.local >> dynPosi.inputSurface
        # replace surf.ws inputs: geoConst & cpos
        cpos = jnt.inputs(type="closestPointOnSurface")[0]
        geoCon = jnt.history(type="locator")[0].getTransform().inputs(
            type="geometryConstraint")[0]
        newSurf.ws >> cpos.inputSurface
        newSurf.ws >> geoCon.target[0].targetGeometry
        
        texAttr = newSurf.layeredTexture.get().attr("inputs")
        i = bkTools.mayaSceneUtil.nextAvailableIndex(texAttr)
        # remove from old layeredTexture, add to new
        for e in oldSurf.layeredTexture.get().attr("inputs"):
            if jnt in e.isVisible.inputs():
                ramp = e.color.inputs()[0]
                ramp.outColor >> texAttr[i].color
                jnt.SurfaceUV_LimitsOnJoint >> texAttr[i].isVisible
                e.remove(b=True)
                break
        
        ctrl.controlGroup.get().setParent(newSurf.sCtrlsGrp.get())
        jnt.setParent(newSurf.jntGrp.get())

        ctrl.surface.disconnect()
        ctrl.surface.connect(newSurf.controls, nextAvailable=True)


def copySubSurfs(jnt):
    """Given a surface joint, create a new surface
    for just its parametric range.
    This is a NO construction history operation!"""

    surf = jnt.rangeU.inputs()[0].surface.get()
    u, v = jnt.paramU.get(), jnt.paramV.get()
    ru, rv = jnt.rangeU.get(), jnt.rangeV.get()

    minU, maxU, subIndexU = getSubsurfRange(u, ru, surf.formInU())
    minV, maxV, subIndexV = getSubsurfRange(v, rv, surf.formInV())

    # output surface - if first param is 0, then [0] is correct surf
    # if first param is NOT 0, then surf[0] is the surf between 0 and it
    # and surf between params is [1].
    # this happens dynamically so if first param changes between 0 and non-zero,
    # output surfs change too. pretty dumb.
    subU = pmc.detachSurface(surf, d=1, p=(minU, maxU))
    mid = subU[subIndexU(minU)]
    subV = pmc.detachSurface(mid, d=0, p=(minV, maxV))
    pmc.delete(subU)

    jntSrf = subV.pop(subIndexV(minV))
    pmc.delete(subV)


def getSubsurfRange(p, r, form):
    """Given base parameter, range, and form for a given direction,
    return the range and function to get correct .outputSurface index"""
    if form == "periodic":
        # periodic range is halved
        r *= .5
        minP, maxP = (p - r) % 1.0, (p + r) % 1.0
        if minP > maxP:
            # min, max, negate min param value (for getting correct output surf)
            return maxP, minP, lambda x: not x
    else:
        minP, maxP = max(p - r, 0), min(p + r, 1)
    
    return minP, maxP, lambda x: bool(x)


"""SUB-SURF STYLE LIMITING -
SUPERIOR DUE TO RESTRICTING LOCATOR MOVEMENT AS WELL"""

"""
detU = pmc.createNode("detachSurface")
surf.ws >> detU.inputSurface
# CLAMP MINU to .001 - forces outputSurface[1] to be desired surf
minU >> detU.parameter[0]
maxU >> detU.parameter[1]
det2 = pmc.createNode("detachSurface")
det.outputSurface[1] >> detV.inputSurface
# same thing with minV
minV >> detV.parameter[0]
maxV >> detV.parameter[1]
subSurf = pmc.nurbsPlane(ch=0)[0]
detV.outputSurface[1] >> subSurf.create
"""

# LIVE connection is impractical, due to variables:
# example: .9-.5 range could change to .1-.3
# which would change desired .outputSurface from [0] (not not 0) to [1] (not 0)
