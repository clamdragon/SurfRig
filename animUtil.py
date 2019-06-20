import pymel.core as pmc
from bkTools import matrixUtil as mu, mayaSceneUtil as msu

__author__ = "Brendan Kelly"
__email__ = "clamdragon@gmail.com"


"""Utility functions for animation
Author: Brendan Kelly"""

"""
getUnkeyedInSel
resetCtrl
reflectSelection
reflectCtrl
"""


def keys_to_motion_path(objs=None, axis="x", up_axis="y", wuv=(0, 1, 0)):
    if not objs:
        objs = pmc.selected(transforms=True)
    with msu.MayaUndoChunkManager():
        for obj in objs:
            # curve from keys
            keys = sorted(set(pmc.keyframe(obj, q=True)))
            r = int(keys[0]), int(keys[-1]) + 1
            pts = (obj.t.get(t=f) for f in xrange(*r))
            c = pmc.curve(d=3, ep=pts)

            # to set motion path keys, need to link current keys to u param
            curve_keys = dict((k, c.getParamAtPoint(obj.t.get(t=k))) for k in xrange(*r))
            pmc.cutKey(obj, t=r, cl=True)
            mp = pmc.nt.MotionPath()
            c.ws >> mp.geometryPath
            mp.follow.set(True)
            mp.fa.set(axis.upper())
            mp.ua.set(up_axis.upper())
            mp.wu.set(wuv)
            mp.ac >> obj.t
            mp.r >> obj.r
            for t, v in curve_keys.items(): pmc.setKeyframe(mp.u, t=t, v=v)
            pmc.filterCurve(mp.u, f="simplify", tto=.05)

            # markers clutter and slow
            pmc.delete(mp.pmt.inputs())


def getUnkeyedInSel():
    """Return any unkeyed attributes in selection"""
    unKeyed = []
    for s in pmc.selected():
        for a in s.listAttr(k=True): 
            if not pmc.keyframe(a, q=True, t=pmc.currentTime()):
                unKeyed.append(a)

    if not unKeyed:
        print("Everything is keyed.")
    
    return unKeyed


def resetCtrl(ctrl):
    """Reset individual control to 0/default keyable attrs"""
    # xforms to 0
    pmc.xform(ctrl, t=(0, 0, 0), ro=(0, 0, 0), s=(1, 1, 1))
    custom = pmc.listAttr(ctrl, keyable=True, userDefined=True, unlocked=True)
    for c in custom:
        # query default value, set value to that
        default = pmc.attributeQuery(c, n=ctrl, listDefault=True)[0]
        pmc.setAttr(ctrl+"."+c, default)


def reflectSelection(sel, source, target, flip):
    """Stage 2 of reflection process. Iterates through the 
    passed ctrls to make sure they are all on the source side,
    then performs a reflection on each of those."""

    for ctrl in sel:
        # source and target at this point are "right" or "left"
        # So, if a selection is on the wrong side, it still counts,
        # just fudge the name so the right control is considered
        if target in ctrl:
            opp = ctrl.replace(target, source)
            if opp in sel:
                # if the corrected control already is in the selection,
                # do nothing because it'll get dealt with.
                continue
            else:
                ctrl = opp
        
        # all ctrls which get to this point are guaranteed source side
        src = pmc.PyNode(ctrl)
        tar = pmc.PyNode(ctrl.replace(source, target))
        if not flip and src == tar:
            # center controls are just reset in single-side mirror mode
            print("Center control {0} reset".format(src))
            resetCtrl(src)
        else:
            reflectCtrl(src, tar, flip)


def reflectCtrl(src, tar, flip):
    """Feflects values from src to tar, and possibly vice-versa.
    Safe and functional even if source and target 
    are the same (central ctrl).
    Relies on ctrls having "mirrorAxis" attribute
    ala Red9 specifying which axes' values should be inverted."""
    
    allAttrs = pmc.listAttr(tar, keyable=True, unlocked=True)
    try:
        reflectAttrs = src.mirrorAxis.get().split(",")
    except AttributeError:
        # ctrl not set up completely, or maybe it's a minor/custom ctrl
        # act as though there is no reflection
        reflectAttrs = []
        
    for a in allAttrs:
        try:
            srcAttr = getattr(src, a)
        except AttributeError:
            # provide warning and skip
            pmc.warning("Attribute {0} not found on {1}. Skipped.".format(a, src))
            continue
        tarAttr = getattr(tar, a)
        
        if tarAttr.isDestination():
            # if otherwise unsettable - locked or has incoming connections
            continue

        reflector = -1 if a in reflectAttrs else 1
        if flip:
            tVal = tarAttr.get()
            tarAttr.set(srcAttr.get() * reflector)
            srcAttr.set(tVal * reflector)
        else:
            tarAttr.set(srcAttr.get() * reflector)


def copyTangents():
    """nevermind, this is useless.
    just copy and paste the key in the graph editor
    and paste while at desired frame"""
    attrs = pmc.animCurveEditor("graphEditor1GraphEd", q=True, curvesShown=True)
    for attr in attrs:
        frames = pmc.keyframe(attrs, q=True, sl=True)
        if len(frames) != 2:
            pmc.error("Select a source key and a destination key")
        # must do angles BEFORE weights or there's weird behavior
        ia, oa = pmc.keyTangent(attr, q=True, t=frames[0], ia=True, oa=True)
        pmc.keyTangent(attr, e=True, t=frames[1], ia=ia, oa=oa)
        iw, ow = pmc.keyTangent(attr, q=True, t=frames[0], iw=True, ow=True)
        pmc.keyTangent(attr, e=True, t=frames[1], iw=iw, ow=ow)
