import pymel.core as pmc
from bkTools import rigCtrlUtil as rcu, matrixUtil as mu
import jointControls as jc


"""
Parent control related functions for surfRig:
makeParentCtrl
parentCtrlTo
getParWtCtrl
setParentStickyGrp
getInvMat
connectParentXforms
connectParentVis
unparentControl
getCtrlGrpIndexFromWtMat
"""


def makeParentCtrl(domSurf, n, names, rotOrder):
    """For the selected control shapes, make a parent control object
    whose effects and position are weighted based on distance (optionally?)"""

    parGrp = pmc.nt.Transform(
        n=n.format(type=names["control group"]), p=domSurf.sCtrlsGrp.get())

    parCtrl, parGrp, offsetGrp = jc.makeFollCtrl(
        n, parGrp, typeDict=names, rotOrder=rotOrder)

    parCtrl.surface.connect(domSurf.controls, nextAvailable=True)
    jc.connectSizeDistFlip(domSurf, parCtrl, parGrp, offsetGrp, rotOrder)

    # rather than making a whole new (slow) mutliPosi, just basically
    # average all of the children ctrlGrps' matrices
    # weightedly add child matrices, then scale by (1.0 / total weight)
    wtMat = pmc.nt.WtAddMatrix(n=n.format(type="mat"))
    wtTotal = pmc.nt.PlusMinusAverage(n=n.format(type="totWt"))
    wtDiv = pmc.nt.FloatMath(n=n.format(type="wt"))
    wtDiv.operation.set(3)
    wtTotal.output1D >> wtDiv.floatB
    sclMat = pmc.nt.PassMatrix(n=n.format(type="sclMat"))
    wtMat.matrixSum >> sclMat.inMatrix
    wtDiv.outFloat >> sclMat.inScale
    wtXform = pmc.nt.DecomposeMatrix(n=n.format(type="xforms"))
    sclMat.outMatrix >> wtXform.inputMatrix
    wtXform.outputTranslate >> parGrp.t
    wtXform.outputRotate >> parGrp.r

    parCtrl.addAttr("rotateChildren", k=True, min=0.0, max=1.0, dv=1.0)
    parCtrl.addAttr("showChildControls", k=True, at="bool")
    parCtrl.addAttr("childControls", at="message")
    parCtrl.addAttr("wtMat", at="message")
    wtMat.message >> parCtrl.wtMat

    return parCtrl


def parentCtrlTo(ctrl, parCtrl, n, rotOrder):
    """Forge the connections between a parent control and the ctrl
    it will be affecting."""

    # affect the parent's sticky location before parent relationship
    setParentStickyGrp(ctrl, parCtrl, n, rotOrder)
    
    parGrp = parCtrl.controlGroup.get()
    ctrlGrp = ctrl.controlGroup.get()
    # parent controls can have parents affecting them too!
    parPar = parCtrl.getParent()
    # parCtrl xforms UNDONE by its own grp (as always),
    # but re-spaced into target ctrl grp 
    matList = [ctrlGrp.m, parGrp.im, parCtrl.m, parPar.m, parGrp.m, ctrlGrp.im]
    
    constGrp = ctrl.getParent()
    if ctrl.listConnections(type="cluster"):
        if parGrp.r.isConnected():
            pmc.warning(
                "While possible, parenting both joint and cluster controllers "
                "together can have odd results. Recommended use is joints only.")
            parGrp.r.disconnect()
        # have to tiptoe around deformer controls to avoid creating a cycle
        constGrp = constGrp.getParent()
        # solidify the space transforming "bookend" matrices
        # ie not actual controlling ones
        for i, m in enumerate(matList):
            if m not in (parCtrl.m, parPar.m):
                matList[i] = m.get()

    constXform = mu.xformFromSpaces(matList, n.format(type="xforms"), rotOrder)

    connectParentXforms(parCtrl, constGrp, constXform, n)
    connectParentVis(parCtrl, constGrp, n)

    parCtrl.childControls.connect(ctrl.parentControls, nextAvailable=True)

    print("Control {0} successfully parented to {1}.".format(
        ctrl.name(), parCtrl.name()))    


def getParWtAttr(ctrl, par):
    """Given control and its parent, get the parent's attribute
    which controls the weight of the relationship."""
    wts = ctrl.parentWts.inputs(plugs=True)
    # None default argument to prevent StopIteration error
    return next((a for a in wts if a.node() == par), None)


def setParentStickyGrp(ctrl, parCtrl, n, rotOrder):
    """Connect the given ctrl's position to the parent control's sticky grp,
    via its ctrlGrp and the parGrp's wtAddMatrix"""
    # connect new ctrlGrp statPosi to parGrp
    parWtMat = parCtrl.wtMat.get()
    i = rcu.nextAvailableIndex(parWtMat.wtMatrix)

    ctrlMat = getInvMat(ctrl, parCtrl, n, rotOrder[-1])
    ctrlMat >> parWtMat.wtMatrix[i].matrixIn
    # ctrlGrp.matrix >> parWtMat.wtMatrix[i].matrixIn
    wtAttrName = n.format(type="Weight")
    parCtrl.addAttr(wtAttrName, min=0.0, max=1.0, dv=1.0)
    wtAttr = parCtrl.attr(wtAttrName)
    wtAttr >> parWtMat.wtMatrix[i].weightIn
    # get wtTotal from passMatrix's other input
    wtAttr >> parWtMat.o.outputs()[0].s.inputs()[0].inputs()[0].input1D[i]

    # attach weight attr to child control message, for access later on
    try:
        parWts = ctrl.parentWts
    except AttributeError:
        ctrl.addAttr("parentWts", at="message", multi=True, indexMatters=False)
        parWts = ctrl.parentWts

    wtAttr.connect(parWts, nextAvailable=True)


def getInvMat(ctrl, parCtrl, n, domAxis):
    """Create any necessary nodes to ensure
    parent control groups' orientations
    aren't messed up by child controls which are flipped."""
    parSurf = parCtrl.surface.get()
    cSurf = ctrl.surface.get()
    ctrlGrp = ctrl.controlGroup.get()
    if not parSurf == cSurf:
        # essentially, each surface will have a matrix which has
        # its "flip"  value (1, -1) in appropriate channel to invert domAxis
        parCtrlInvMat = pmc.nt.MultMatrix(n=n.format(type="parInvMat"))
        for i, surf in enumerate((parSurf, cSurf)):
            flip = surf.controlsFlipped.outputs()[0]
            try:
                flipMat = flip.outputs(type="fourByFourMatrix")[0]
            except IndexError:
                flipMat = pmc.nt.FourByFourMatrix(
                    n=n.format(type=cSurf.name() + "parInv"))
                axTarg = {"x": flipMat.in00, "y": flipMat.in11, "z": flipMat.in22}
                try:
                    flip.outFloat >> axTarg[domAxis]
                except KeyError:
                    pmc.warning("Problem getting ctrl {0} orientation!".format(
                        ctrl.name()))
                    return ctrlGrp.matrix

            flipMat.output >> parCtrlInvMat.matrixIn[i]
        # this will guarantee corret orientation on parCtrlGrp even if
        # it affects differently inverted surface controls
        ctrlGrp.matrix >> parCtrlInvMat.matrixIn[2]

        return parCtrlInvMat.matrixSum

    else:
        return ctrlGrp.matrix


def connectParentXforms(parCtrl, constGrp, constXform, n):
    """Create the weighting and rotation blending nodes
    for a new parent-child control relationship"""
    try:
        constT = constGrp.t.inputs(scn=True)[0]
        constR = constGrp.r.inputs(scn=True)[0]
    except IndexError:
        # just means it's the first parent added to this ctrl, make add nodes
        constT = pmc.nt.PlusMinusAverage(n=n.format(type="PARTRANS"))
        constT.output3D >> constGrp.t
        constR = pmc.nt.PlusMinusAverage(n=n.format(type="PARROT"))
        constR.output3D >> constGrp.r

    # OLD: scale matrix + blend rotations
    # NEW: wtMult (rotChildren * weight), 2x premultiply for trans/rot
    wtAttr = parCtrl.attr(n.format(type="Weight"))
    rotWt = pmc.nt.MultDoubleLinear(n=n.format(type="ROTWT"))
    rotScl = pmc.nt.Premultiply(n=n.format(type="SCLROT"))
    transScl = pmc.nt.Premultiply(n=n.format(type="SCLTRANS"))
    parCtrl.rotateChildren >> rotWt.input1
    wtAttr >> rotWt.input2
    rotWt.output >> rotScl.inAlpha
    constXform.outputRotate >> rotScl.inColor
    wtAttr >> transScl.inAlpha
    constXform.outputTranslate >> transScl.inColor

    i = rcu.nextAvailableIndex(constT.input3D)

    # now just add the weighted xforms to the pile
    rotScl.outColor >> constR.input3D[i]
    transScl.outColor >> constT.input3D[i]


def connectParentVis(parCtrl, constGrp, n):
    """Make the parent ctrl's showChildControls attribute
    affect the constGrp's visibility - along with ALL OTHER parents.
    This way, if ANY parent wants their children shown, they will be."""

    try:
        multiVis = constGrp.visibility.inputs()[0]
    except IndexError:
        multiVis = pmc.nt.PlusMinusAverage(n=n.format(type="vis"))
        multiVis.output1D >> constGrp.visibility

    i = rcu.nextAvailableIndex(multiVis.input1D)
    parCtrl.showChildControls >> multiVis.input1D[i]


def unparentControl():
    """Slot for unparent selected button. Deletes incoming matrix nodes
    and resets xforms. Also removes matrix entry from parent objects ctrlGrp"""
    ctrls = [s for s in pmc.ls(sl=True) if hasattr(s, "parentControls")]
    with rcu.MayaUndoChunkManager():
        for ctrl in ctrls:
            try:
                ctrlGrp = ctrl.controlGroup.get()
                parents = ctrl.parentControls.inputs()
            except pmc.MayaNodeError:
                # perhaps it was a parent itself which was deleted by a
                # previous iteration. Just continue.
                continue
            for par in parents:
                # get the index where this control connects to its parent,
                # so matrix and weight attributes can be removed
                wtMat = par.wtMat.get()
                i = getCtrlGrpIndexFromWtMat(ctrlGrp, wtMat)
                attr = wtMat.wtMatrix[i].weightIn.inputs(plugs=True)[0]
                wtTotal = attr.outputs(type="plusMinusAverage")[0]
                wtMat.wtMatrix[i].remove(b=True)
                wtTotal.input1D[i].remove(b=True)
                attr.delete()

                par.childControls.disconnect(
                    ctrl.parentControls, nextAvailable=True)
                # if this is the FINAL control affected by parent, KILL IT
                if not par.childControls.get():
                    pmc.delete(par.controlGroup.get())

            constGrp = ctrl.getParent()
            if ctrl.listConnections(type="cluster"):
                constGrp = constGrp.getParent()

            # remove PlusMinusAverage nodes for translate, rotate and vis
            pmc.delete(constGrp.inputs(scn=True))
            constGrp.t.set(0, 0, 0)
            constGrp.r.set(0, 0, 0)
            constGrp.visibility.set(True)

            ctrl.parentControls.disconnect()

            print("Control {0} successfully unparented.".format(ctrl.name()))


def getCtrlGrpIndexFromWtMat(ctrlGrp, wtMat):
    """Given a control group and a parent's weight add matrix,
    return the numerical index which connects the two."""
    for i in wtMat.wtMatrix.getArrayIndices():
        try:
            inMat = wtMat.wtMatrix[i].matrixIn.inputs()[0]
        except IndexError:
            # not connected? remove it.
            wtMat.wtMatrix[i].remove(b=True)
            continue
        
        if isinstance(inMat, pmc.nt.MultMatrix):
            # it's a ctrl grp flip matrix, get its input[2]
            inMat = inMat.matrixIn[2].inputs()[0]

        if inMat == ctrlGrp:
            break

    else:
        # control isn't found in parent weight matrix... some kinda problem
        pmc.warning("Problem removing control from parent orientations.")
        i = None

    return i
