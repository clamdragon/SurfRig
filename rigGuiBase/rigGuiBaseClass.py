import bkTools.mayaSceneUtil
from bkTools.Qt import QtCore, QtGui, QtWidgets
from bkTools import rigCtrlUtil as rcu, animUtil as au
import maya.OpenMaya as om
import os
import pymel.core as pmc
from functools import partial
try:
    import shiboken2
except ImportError:
    import shiboken as shiboken2
import maya.OpenMayaUI as mui
# compiled ui designer code
import rigGuiBaseQt


__author__ = "Brendan Kelly"
__email__ = "clamdragon@gmail.com"


"""
RigGuiBase: Generic rig gui functionality. 
Class inherits QT designer widget, Ui_RigGuiBaseQt, for visuals
DEPENDS ON SPECIFICALLY FORMATTED RIG DATA:
REQUIRED DICTIONARIES:
  self.ctrlDict
  self.fkikDict
"""


"""
 .d8888b. 888     8888888888   888888b.         d8888 .d8888b. 8888888888 
d88P  Y88b888     888  888     888  "88b       d88888d88P  Y88b888        
888    888888     888  888     888  .88P      d88P888Y88b.     888        
888       888     888  888     8888888K.     d88P 888 "Y888b.  8888888    
888  88888888     888  888     888  "Y88b   d88P  888    "Y88b.888        
888    888888     888  888     888    888  d88P   888      "888888        
Y88b  d88PY88b. .d88P  888     888   d88P d8888888888Y88b  d88P888        
 "Y8888P88 "Y88888P" 8888888   8888888P" d88P     888 "Y8888P" 8888888888 
 """



# GuiBase contains all of the generic methods which another class
# can make use of. FK-IK, selection, mirroring.
# The rig-specific data must be organized in a specific way,
# mostly dictionaries.
# class GuiBase(RigGuiOutline, QtGui.QMainWindow):
class RigGuiBase(rigGuiBaseQt.Ui_RigGuiBaseQt, QtWidgets.QWidget):
    # QMainWindow needs __init__, so just rename initialization method
    # GuiBase should inherit the generic compiled gui - the ref picker,
    # flip and selection tools - 
    # everything but the tabwidget with rig-specific controls
    #
    def __init__(self, parent=None):
        self.base = super(RigGuiBase, self)
        # to QMainWindow
        self.base.__init__(parent)
        # compiled generic gui
        self.setupUi(self)

        # Expected fields for heirs
        self.ns = ":"
        self.toolMode = "body"
        #self.toolCheckBody.setChecked(True)
        self.callbackIDs = []
        self.selCBID = None

        # for driven key poses
        self.poseNode = None
        self.poseSliders = []

        self.fkikDict = {}
        self.ctrlDict = {}

        """
        # create selection callback, not in self.callbackIDs
        # because it functions across references
        self.selCBID = om.MEventMessage.addEventCallback(
                "SelectionChanged", self.mayaSelectionChanged)
        """

    # connectinos - first generic, then rig-specific
    # called at the end of specific rig's __init__ method, 
    # AFTER its data has been created
    #
    def setupConnections(self):
         # change tool mode
        self.toolCheckBody.toggled.connect(
                                    partial(self.changeToolMode, "body"))
        self.toolCheckFace.toggled.connect(
                                    partial(self.changeToolMode, "face"))
        self.toolCheckBoth.toggled.connect(
                                    partial(self.changeToolMode, "both"))

        # non-rig dependent signal connections
        # references
        self.refPicker.currentIndexChanged.connect(self.changeActiveRef)
        self.newRefBut.clicked.connect(self.addRef)
        self.delRefBut.clicked.connect(self.removeRef)
        #
        self.changeActiveRef(-1)        

        # Tools
        self.selectAll.clicked.connect(self.selectAllTool)
        self.resetSelection.clicked.connect(self.resetSelectionTool)
        self.invertSelection.clicked.connect(self.invertSelectionTool)
        self.selectUnkeyed.clicked.connect(self.selectUnkeyedTool)
        self.flipPose.clicked.connect(
                        partial(self.reflectPoseTool, "left", "right", True))
        self.mirrorPoseLtR.clicked.connect(
                        partial(self.reflectPoseTool, "left", "right", False))
        self.mirrorPoseRtL.clicked.connect(
                        partial(self.reflectPoseTool, "right", "left", False))


        # connect buttons to function to get ctrl name
        for k in self.ctrlDict:
            k.clicked.connect(partial(self.selectCtrl, k))
            # save bg color, because selection highlighting changes stylesheet
            k.setProperty("defaultBG", k.styleSheet())


        # fk ik buttons - connect them to setFkIkMode method
        for k in self.fkikDict:
            ld = self.fkikDict[k]
            ld["fkButton"].clicked.connect(partial(self.setFkIkMode, k, "fk"))
            ld["ikButton"].clicked.connect(partial(self.setFkIkMode, k, "ik"))


        # get all fkikcontrols (without reflector) into self.fkikDict["all"],
        # which makes it easy to access for the mirroring functions
        for limb in self.fkikDict:
            allCtrls = []
            joints = self.fkikDict[limb]["handles"]
            for j in joints:
                # joints[j][0][0], [1][0] are the ctrls
                allCtrls.append(joints[j][0][0])
                allCtrls.append(joints[j][1][0])
            self.fkikDict[limb]["all"] = allCtrls

        # set off the active ref for initialization of ns and callbacks
        self.refPicker.currentIndexChanged.emit(self.refPicker.currentIndex())

    # remove all old callbacks, reset list
    def clearCallbacks(self):
        for c in self.callbackIDs:
            try:
                om.MMessage.removeCallback(c)
            except RuntimeError:
                pass
        # clear the list
        self.callbackIDs = []

    # try to make sure callbacks don't last beyond rigGui
    def closeEvent(self, event):
        self.clearCallbacks()
        self.base.closeEvent(event)

    def loadRig(self):
        """Load data from rig. Looks for two files in the rig's directory:
        - rigGuiData.json
        - rigGui.ui
        Uses these two files to create the functionality and GUI picker."""
        pass

    def sizeHint(self):
        return QtCore.QSize(380, 250)


    """
    8888888888888    d8P    8888888888    d8P  
    888       888   d8P       888  888   d8P   
    888       888  d8P        888  888  d8P    
    8888888   888d88K         888  888d88K     
    888       8888888b        888  8888888b    
    888       888  Y88b       888  888  Y88b   
    888       888   Y88b      888  888   Y88b  
    888       888    Y88b   8888888888    Y88b
    """



    def getActiveFkIkCtrl(self, limb, joint):
        # Use to check rig's current fk/ik mode on given side,
        # and return appropriate control
        ld = self.fkikDict[limb]
        try:
            switch = pmc.PyNode(self.ns + ld["ctrl"])
            fkikVal = getattr(switch, ld["attr"]).get()
        except:
            pmc.warning("Problem getting FKIK ctrl from JSON data")
            return [None, None]

        return ld["handles"][joint][int(round(fkikVal))]

    def getFkIkCtrl(self, limb, joint, mode):
        # return the namespaced pynode on its own
        ld = self.fkikDict[limb]
        ctrl = ld["handles"][joint][ld[mode+"Val"]][0]
        try:
            return pmc.PyNode(self.ns + ctrl)
        except TypeError:
            return [None, None]


    # Callback function, triggered when FKIK ctrl attributes change value
    # Make sure it's the right FKIK switch attribute, then
    # Change button colors, hide and show buttons(?)
    def updateFkIk(self, msg, plug, other, limb):
        ld = self.fkikDict[limb]
        attr = ld["attr"]
        if plug.partialName() == attr:
            ikBut = ld["ikButton"]
            fkBut = ld["fkButton"]
            val = plug.asInt()
            if val == ld["ikVal"]:
                ikBut.setStyleSheet("background-color: white; color: black")
                ikBut.setEnabled(False)
                fkBut.setStyleSheet("")
                fkBut.setEnabled(True)
            elif val == ld["fkVal"]:
                fkBut.setStyleSheet("background-color: white; color: black")
                fkBut.setEnabled(False)
                ikBut.setStyleSheet("")
                ikBut.setEnabled(True)


    # Check for matching, and forward to stuff
    def setFkIkMode(self, limb, mode):
        ld = self.fkikDict[limb]
        ctrl = ld["ctrl"]
        match = ld["match"]
        val = ld[(mode + "Val")]
        attr = ld["attr"]
        if not pmc.objExists(self.ns + ctrl):
            pmc.warning("FK-IK Ctrl not found.")
            return

        # check to see if desired fk-ik state is already set
        node = pmc.PyNode(self.ns + ctrl + "." + attr)
        curr = node.get()
        if curr == val:
            return

        # make a single chunk in maya undo queue
        with bkTools.mayaSceneUtil.MayaUndoChunkManager():
            if match.isChecked():
                if mode == "fk":
                    self.matchFkToIk(limb)
                elif mode == "ik":
                    self.matchIkToFk(limb)

            # set the driving attribute inside of maya
            node.set(val)


    # To be reimplemented in rig info class
    # since method of matching may vary widely
    #
    # This one matches the FK controls to the IK rig's current position
    def matchFkToIk(self, limb):
        pass

    # To be reimplemented in rig info class
    # since method of matching may vary widely
    #
    # This one matches the IK controls to the FK rig's current position
    def matchIkToFk(self, limb):
        pass



    """
    8888888b. 88888888888888888888 .d8888b.  
    888   Y88b888       888       d88P  Y88b 
    888    888888       888       Y88b.      
    888   d88P8888888   8888888    "Y888b.   
    8888888P" 888       888           "Y88b. 
    888 T88b  888       888             "888 
    888  T88b 888       888       Y88b  d88P 
    888   T88b8888888888888        "Y8888P"  
    """



    # Change up which reference is active
    # Slot called by comboBox
    def changeActiveRef(self, newIndex):
        if newIndex == -1:
            # empty! disable for safety
            self.ns = ""
            self.selectionLayout.setEnabled(False)
            self.toolsLayout.setEnabled(False)
            return
        else:
            self.selectionLayout.setEnabled(True)
            self.toolsLayout.setEnabled(True)

        ns = self.refPicker.itemText(newIndex)
        if not pmc.namespace(exists=ns) or not self.isRigInNamespace(ns):
            self.deadRef(ns, newIndex)
            return
        self.ns = ns

        # run method to take care of FK-IK callbacks
        self.changeActiveCallbacks()


    def changeActiveCallbacks(self):
        self.clearCallbacks()

        # make new dirty plug callbacks for each 
        # FK/IK thing that needs one
        sL = om.MSelectionList()
        for s in self.fkikDict:
            ld = self.fkikDict[s]
            ctrl = self.ns + ld["ctrl"]
            if not pmc.objExists(ctrl):
                if self.ns != ":":
                    pmc.warning("FKIK ctrl not found in namespace"
                                                " \"{0}\"".format(self.ns))
                return

            sL.add(ctrl)
            n = om.MObject()
            sL.getDependNode(0, n)
            # attributeChangedCallback, dirtyPlugCallback provides dirty data
            callbackID = om.MNodeMessage.addAttributeChangedCallback(
                                                    n, self.updateFkIk, s)
            sL.remove(0)
            self.callbackIDs.append(callbackID)
            # force update
            pmc.dgdirty(ctrl)



    def deadRef(self, ns, index):
        win = QtWidgets.QMessageBox(self)
        win.setText("Namespace {0} not found in scene, or"
                    "\nrig not found in namepsace."
                    "\n\nRemoving from list.".format(ns))
        win.exec_()
        self.refPicker.removeItem(index)
        win.setParent(None)


    # addRef adds the namespace of current selection to refPicker,
    # as long as it's unique and at least one ctrl in ctrlDict
    # exists in that namespace
    #
    def addRef(self):
        ns = self.getNamespaceOfSelection()
        if not ns or not self.isRigSelected(ns):
            pmc.warning("Select a rig ctrl in the namespace you wish to add.")
            return
        c = self.refPicker.count()
        for i in xrange(c):
            if ns == self.refPicker.itemText(i):
                pmc.warning("Reference already loaded.")
                return

        self.refPicker.addItem(ns)
        self.refPicker.setCurrentIndex(c)


    # return namespace of current selection
    #
    def getNamespaceOfSelection(self):
        sel = pmc.ls(selection=True)
        # ensure selection is valid for querying namespace
        try:
            ns = sel[0].namespace()
        except:
            return None
        if not ns:
            # empty, needs to be ":" just for clarity
            ns = ":"
        return ns

    # verifies if selection is a control defined in ctrlDict
    # (temporarily altering self.ns to achieve this)
    #
    def isRigSelected(self, ns):
        old = self.ns
        self.ns = ns
        ctrls = [self.getCtrlForButton(b) for b in self.ctrlDict]
        sel = pmc.ls(selection=True)
        if not sel or sel[0] not in ctrls:
            self.ns = old
            return False
        else:
            self.ns = old
            return True

    # checks if a the first control in ctrlDict exists in
    # the given namespace
    #
    def isRigInNamespace(self, ns):
        if not self.ctrlDict:
            return False
        # neat python thing, next iterates over the generator (x) to find first match of condition
        randomCtrl = next(c[0] for c in self.ctrlDict.values() if isinstance(c, list))
        return pmc.objExists(ns+randomCtrl)


    # safe to do even with empty list
    def removeRef(self):
        self.refPicker.removeItem(self.refPicker.currentIndex())



    """
     .d8888b.888888888888888888b. 888     .d8888b.  
    d88P  Y88b   888    888   Y88b888    d88P  Y88b 
    888    888   888    888    888888    Y88b.      
    888          888    888   d88P888     "Y888b.   
    888          888    8888888P" 888        "Y88b. 
    888    888   888    888 T88b  888          "888 
    Y88b  d88P   888    888  T88b 888    Y88b  d88P 
     "Y8888P"    888    888   T88b88888888"Y8888P"  
    """                                                


    # slot for the clicked buttons
    # access ctrl dictionary and get name
    #
    # IF THE CONTROL DOESN'T EXIST, RETURN NONE!
    def getCtrlForButton(self, button, reflect=False):
        if not button in self.ctrlDict:
            pmc.warning("Invalid key for ctrlDict")
            return
        n = self.ctrlDict[button]
        if hasattr(n, "__call__"):
            n = n()
        nsCtrl = None
        if n and n[0]:
            # this way, method will return either the fully
            # workable ctrl name or None (no concantenation issues)
            nsCtrl = self.ns + n[0]
            if not pmc.objExists(nsCtrl):
                nsCtrl = None
        # most of the time, we only want the name of the control,
        # which is n[0]. n[1] is the reflection matrix
        if reflect:
            return [nsCtrl, n[1]]
        else:
            return nsCtrl


    # name is a string - the Maya ctrl
    def selectCtrl(self, button):
        ctrl = self.getCtrlForButton(button)
        if ctrl:
            alreadySelected = ctrl in pmc.ls(selection=True)
            mods = pmc.getModifiers()
            # shift is 1 bit, ctrl is 4 bit
            addMod = mods & 1 or mods & 4
            # deselect instead of adding if ctrl or shift, AND
            # target is already selected
            desel = alreadySelected and addMod
            pmc.select(ctrl, deselect=desel, add=addMod)
        else:
            pmc.warning("Ctrl doesn't exist")


    # Filter defines all objects which begin with namespace
    # minus a couple
    def getAllControls(self):
        #filt = pmc.itemFilter(byName=(self.ns+"*CTRL"))
        #allCtrls = pmc.lsThroughFilter(filt)
        
        # filter out None values in list comp of all ctrls
        # from ctrlDict, and no baseCtrl
        allCtrls = list(set([c for c in 
                        [self.getCtrlForButton(a) for a in self.ctrlDict 
                                    if a is not self.baseCtrl]
                        if c]))

        return allCtrls


    # return list of controls for the body
    # obtained by comparing self.ctrlDict and self.bodySelect.children()
    # and returning a list of all non-None values
    def getBodyControls(self):
        bodyCtrls = [c for c in 
                        [self.getCtrlForButton(b) for b in 
                            self.bodySelect.children() if 
                                b in self.ctrlDict and b is not self.baseCtrl]
                        if c]
        return bodyCtrls


    # return list of face controls
    # find eye ctrl's orient attribute to
    # determine if it should be included in the list(?)
    def getFaceControls(self):
        # Face controls are already separated by virtue of tabWidget
        # so each entry in self.ctrlDict is used IF it is a child of 
        # self.faceSelect
        faceCtrls = [c for c in 
                        [self.getCtrlForButton(b) for b in 
                            self.faceSelect.children() if b in self.ctrlDict]
                        if c]
        return faceCtrls


    # Callback function for selection changes. It's a shame that
    # the whole dict has to be iterated, but "SelectionChanged" is
    # a vague callback.
    def mayaSelectionChanged(self, data):
        sel = pmc.ls(selection=True)
        for k in self.ctrlDict:
            c = self.getCtrlForButton(k)
            c = self.ns + c[0]
            # highlight if selected, revert to saved color if not.
            if c in sel:
                k.setStyleSheet("background-color: rgb(255, 255, 255)")
                #self.selected.append(k)
            else:
                k.setStyleSheet(k.property("defaultBG"))


    """
    88888888888 .d88888b.  .d88888b. 888     .d8888b.  
        888    d88P" "Y88bd88P" "Y88b888    d88P  Y88b 
        888    888     888888     888888    Y88b.      
        888    888     888888     888888     "Y888b.   
        888    888     888888     888888        "Y88b. 
        888    888     888888     888888          "888 
        888    Y88b. .d88PY88b. .d88P888    Y88b  d88P 
        888     "Y88888P"  "Y88888P" 88888888"Y8888P"  
    """


    
    def changeToolMode(self, mode, state):
        if state:
            self.toolMode = mode

    # Method to get ALL controls for the current mode
    def getModeCtrls(self):
        if self.toolMode == "face":
            return self.getFaceControls()
        elif self.toolMode == "body":
            return self.getBodyControls()
        elif self.toolMode == "both":
            return self.getAllControls()
        return None


    def selectAllTool(self):
        ctrls = self.getModeCtrls()
        pmc.select(ctrls)


    # Make sure it only works for selected items IN THE RIG.
    def resetSelectionTool(self):
        sel = pmc.ls(selection=True)
        allCtrls = self.getAllControls()
        sel = [c for c in sel if c in allCtrls]
        # make resetting ALL a single undo operation
        with bkTools.mayaSceneUtil.MayaUndoChunkManager():
            for s in sel:
                au.resetCtrl(s)


    def invertSelectionTool(self):
        ctrls = self.getModeCtrls()
        sel = pmc.ls(selection=True)
        inverse = [c for c in ctrls if c not in sel]
        pmc.select(inverse)


    def selectUnkeyedTool(self):
        ctrls = self.getModeCtrls()
        unkeyed = []
        t = pmc.currentTime(query=True)
        for c in ctrls:
            # query if any attributes are keyed at current frame
            # empty list means nothing is keyed
            keys = pmc.keyframe(c, q=True, time=(t, t))
            if not keys:
                unkeyed.append(c)
        pmc.select(unkeyed)


    # Stage 1 of reflection process. Called by each button, with different
    # arguments. This part organizes all relevant ctrls, creates a
    # current-namespace dictionary of ctrls: reflection multipliers,
    # and matches target's FK/IK state to source
    #
    def reflectPoseTool(self, source, target, flip):
        modeCtrls = self.getModeCtrls()
        sel = pmc.ls(selection=True)
        # only selected - but only one side needs to be selected,
        # other side is inferred
        #ctrls = [c for c in sel if c in modeCtrls]
        ctrls = [c for c in modeCtrls if c in sel]

        with bkTools.mayaSceneUtil.MayaUndoChunkManager():
            # find out if any ctrls selected are FK/IK controls
            # if so, just add the switch ctrl object to the selection list
            # so its values are flipped along with S/R/T
            for k in self.fkikDict:
                ld = self.fkikDict[k]
                for c in ld["all"]:
                    if c and self.ns + c in ctrls:
                        switch = self.ns + ld["ctrl"]
                        ctrls.append(switch)
                        # done with limb, break to outer loop of other limbs
                        break

            au.reflectSelection(ctrls, source, target, flip)
    


    """
    8888888b.  .d88888b.  .d8888b. 8888888888 .d8888b.  
    888   Y88bd88P" "Y88bd88P  Y88b888       d88P  Y88b 
    888    888888     888Y88b.     888       Y88b.      
    888   d88P888     888 "Y888b.  8888888    "Y888b.   
    8888888P" 888     888    "Y88b.888           "Y88b. 
    888       888     888      "888888             "888 
    888       Y88b. .d88PY88b  d88P888       Y88b  d88P 
    888        "Y88888P"  "Y8888P" 8888888888 "Y8888P"  
    """


    # Zero out POSE SLIDERS
    #
    def resetPoses(self):
        for s in self.poseSliders:
            s.setValue(0)
    
    
    # Method to create a new pose based on the selected controls,
    # and make a slider for controlling 
    #
    def createNewPose(self, poseAttr=None):
        if not self.poseNode:
            pmc.warning("SDK pose node not defined!")
            return
        ctrls = self.getAllControls()
        sel = pmc.ls(selection=True)
        ctrls = list(set(ctrls) & set(sel))
        
        # if not passed an attribute (on the pose node) to RE-connect, 
        # create in-scene single-value node 
        # which drives ctrls
        if not poseAttr:
            a = pmc.addAttr(self.poseNode, at="float", ln="newPose")
            poseAttr = pmc.pyNode(self.poseNode + "." + a)
            poseAttr.set(1)
            # setDrivenKey ALL values on ALL ctrls
            # with poseAttr @ 1 and ctrl @ their current values
            pmc.setDrivenKeyframe(ctrls, currentDriver=poseAttr)
            # reset poseAttr THEN reset ctrls
            poseAttr.set(0)
            for c in ctrls:
                au.resetCtrl(c)
            pmc.setDrivenKeyframe(ctrls, currentDriver=poseAttr)
        
        # make connected slider
        slider = MayaFloatSlider(self, poseAttr)
        self.poseSliders.append(slider)
        slider.setValue(1)
        #self.verticalLayout.addWidget(slider)



"""
------------------------------------------------------------------------------
##############################################################################
------------------------------------------------------------------------------
"""





"""
 .d8888b. 888     88888888888888b. 88888888888888888b.  .d8888b.  
d88P  Y88b888       888  888  "Y88b888       888   Y88bd88P  Y88b 
Y88b.     888       888  888    888888       888    888Y88b.      
 "Y888b.  888       888  888    8888888888   888   d88P "Y888b.   
    "Y88b.888       888  888    888888       8888888P"     "Y88b. 
      "888888       888  888    888888       888 T88b        "888 
Y88b  d88P888       888  888  .d88P888       888  T88b Y88b  d88P 
 "Y8888P" 8888888888888888888888P" 8888888888888   T88b "Y8888P"  
""" 




"""
# MAKE MAYA SLIDER WIDGET
# Connect it to attr,
# THEN wrap as a QSlider and return it
# 
def connectedSlider(parent, attr):
    obj, a = attr.split(".")
    if pmc.attributeQuery(a, node=obj, minExists=True):
        sMin = pmc.attributeQuery(a, node=obj, min=True)[0]
    else:
        sMin = -10.0
    if pmc.attributeQuery(a, node=obj, maxExists=True):
        sMax = pmc.attributeQuery(a, node=obj, max=True)[0]
    else:
        sMax = 10.0

    tempW = pmc.window()
    tempC = pmc.columnLayout()
    slider = pmc.floatSlider(min=sMin, max=sMax)
    pmc.connectControl(slider, attr)
    ptr = mui.MQtUtil.findControl(slider)
    qSlider = shiboken.wrapInstance(ptr, QtGui.QSlider)
    qSlider.setParent(parent)
    pmc.deleteUI(tempW)
    return qSlider
"""


# Subclass of QSlider, which works with floats
# And is linked to the Maya object+attr given on
# instantiation
# Internal values are still ints, but divided by 100 when emitted
#
class MayaFloatSlider(QtWidgets.QSlider):
    def __init__(self, parent, attr):
        self.base = super(MayaFloatSlider, self)
        self.base.__init__(parent)
        if not pmc.objExists(attr):
            msg = "Maya attribute \"{0}\" not found".format(attr)
            raise(NameError(msg))
        self.mult = 100.0
        self.attr = attr
        self.setValue(pmc.getAttr(attr))
        
        # Find if maya object has min & max
        obj, a = attr.split(".")
        if pmc.attributeQuery(a, node=obj, minExists=True):
            sMin = pmc.attributeQuery(a, node=obj, min=True)[0]
        else:
            sMin = -10.0
        if pmc.attributeQuery(a, node=obj, maxExists=True):
            sMax = pmc.attributeQuery(a, node=obj, max=True)[0]
        else:
            sMax = 10.0
        self.setMinimum(sMin * self.mult)
        self.setMaximum(sMax * self.mult)
        
        self.valueChanged.connect(self.valueChangedConvert)
        self.floatValueChanged.connect(self.mayaAttrUpdate)
    
    
    # Custom signal, invoked by regular valueChanged
    floatValueChanged = QtCore.Signal(float)    
    
    # Slot to receive int valueChanged and re-emit as floatValueChanged
    #
    def valueChangedConvert(value):
        self.floatValueChanged.emit(value / self.mult)
    
    # Update the connected Maya attribute
    # Value received is ALREADY CONVERTED to float
    #
    def mayaAttrUpdate(self, value):
        pmc.setAttr(attr, value)
    
    # Float <--> int replacements for relevant base class methods
    #
    def value(self):
        return(self.base.value() / self.mult)
    
    def setValue(self, value):
        self.base.setValue(int(value * self.mult))
        
    def setMaximum(self, val):
        self.base.setMaximum(int(val * self.mult))
        
    def setMinimum(self, val):
        self.base.setMinimum(int(val * self.mult))
    
    
"""
# Slot for a slider group's valueChanged signal - 
# The maya object+attribute live in object.objectName(),
# So this serves as a connection
#
def connectSlider(object, value):
    attr = object.objectName()
    pmc.setAttr(attr, value)
"""



"""
------------------------------------------------------------------------------
##############################################################################
------------------------------------------------------------------------------
"""




"""
888b     d8888888888 .d8888b.  .d8888b.  
8888b   d8888  888  d88P  Y88bd88P  Y88b 
88888b.d88888  888  Y88b.     888    888 
888Y88888P888  888   "Y888b.  888        
888 Y888P 888  888      "Y88b.888        
888  Y8P  888  888        "888888    888 
888   "   888  888  Y88b  d88PY88b  d88P 
888       8888888888 "Y8888P"  "Y8888P"  
"""




# MAKE MAYA CAMERA WIDGET
# Namespace must have a camera named "guiCam" to connect the view to
# Wrap and return as QWidget
#
def makeCamWidget(parent, namespace):
    refNode = namespace[0:-1]+"RN"
    try:
        derWin = pmc.window()
        derForm = pmc.columnLayout()
        # if NOT referenced, there is no refNode
        #
        if namespace == ":":
            refList = pmc.ls(geometry=True)
        else:
            refList = pmc.referenceQuery(refNode, nodes=True)
        pmc.select(refList)
        derME = pmc.modelEditor(camera=namespace+guiCam, hud=False,
                                 viewSelected=True, addSelected=True)
        pmc.select(clear=True)
        
        ptr = mui.MQtUtil.findControl(derME)
        self.camBG = shiboken2.wrapInstance(long(ptr), QtWidgets.QWidget)
        self.camBG.setParent(parent)
        #self.camBG.setEnabled(False)
        pmc.deleteUI(derWin)
    except:
        pmc.warning("Could not connect to camera {0}.".format(namespace+guiCam))



"""
# construct a simple heirarchical structure for the rig controls...
# may be presumptuous, but I think flipping from the root up makes
# dynamic figuring out of reflection axis possible
# method: getRefMatrix is possible if controls are organized
# in a heirarchy... but it gets into worldspace xform matricies
class uiCtrlNode(object):
    def __init__(self, button, ctrl, axis, parent=None):
        self.button = button
        self.ctrl = ctrl
        self.axis = axis
        self.parent = parent
        self.children = []
        # add self to parent's children list
        if hasattr(parent, children):
            self.parent.children.append(self)
"""


"""
------------------------------------------------------------------------------
##############################################################################
------------------------------------------------------------------------------
"""