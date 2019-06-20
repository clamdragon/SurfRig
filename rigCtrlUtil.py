import pymel.core as pmc
from functools import partial

from bkTools.mayaSceneUtil import mergeShapes, addShapeToTrans, nextAvailableIndex,\
    get_selected_cb_attrs, readJson, writeJson

__author__ = "Brendan Kelly"
__email__ = "clamdragon@gmail.com"


"""
A collection of utilities for building better rig controls.
"""

child_cmpnts = lambda c: (o for o in pmc.container(c, q=True, nl=True) if isinstance(o, pmc.nt.Container))

def publish_to_asset(nodes=None, name=None):
    """
    Publish the given node to the given container.
    :param node: Node to publish
    :param asset: duh
    :param name: optional. if not given, just strip off ":" and "_ctrl"
    :return: None
    """
    if not nodes:
        nodes = pmc.selected(transforms=True)
    asset = pmc.container(q=True, fc=nodes[0])
    for node in nodes:
        name = node.replace(":", "").replace("_ctrl", "")
        if name == "global":
            name = "master"
        pmc.containerPublish(asset, publishNode=(name, ""))
        pmc.containerPublish(asset, bindNode=(name, node))


def set_guide_mode(state=True, cmpnts=None):
    """Enable or disable GUIDE mode for rig components."""
    if cmpnts is None:
        cmpnts = pmc.selected(type="container")
    for cmp in cmpnts:
        child_cmps = child_cmpnts(cmp)
        try:
            guide_node = cmp.guideNode.get()
        except AttributeError:
            # not a direct cmpnt, possibly parent container, just traverse down
            set_guide_mode(state, child_cmps)
            continue

        guide_node.visibility.set(state)
        # template/untemplate controls and rig
        for grp_name in ("controls", "rig"):
            try:
                pmc.PyNode(guide_node.name().replace("guide", grp_name)).template.set(state)
            except:
                pmc.warning("No {} group found, skipped template step.".format(grp_name))
        # guide_node.guideSourceAttrs.get()
        # guideSourceAttrs and guideDestAttrs are message arrays which
        # connect to all of the source and dest plugs (IN RIGID ORDER)
        # which are needed to guide the rig.
        for s, d in zip(guide_node.guideSourceAttrs.inputs(plugs=True),
                        guide_node.guideDestAttrs.inputs(plugs=True)):
            try:
                if state:
                    s >> d
                else:
                    s // d
                    d.set(s.get())
            except:
                pmc.warning("Problem with attribute pair {}: {}".format(s, d))
                continue
        else:
            print("Guide mode turned {} for {}".format(("off", "on")[state], cmp.name()))

        # pass on to child cmpnts
        set_guide_mode(state, child_cmps)


def mirror_guides(cmpnts=None, axis="x", behavior=True):
    """
    Entry point for mirroring cmpnt guides. Can either pass in cmpnts in blocks (will be split and zipped),
    or else it will find selected components or finally selected transforms.
    :param cmpnts: optional block list of components to mirror. form:[(all affected cmpnts), (all source cmpnts)]
    :param axis: string world axis over which to perform the mirroring
    :param behavior: bool of whether or not to flip the local orientation of the guide after world mirroring
    :return: None
    """
    # construct world reflection matrix
    ref_mtx = pmc.dt.Matrix()
    for i, ax in enumerate("xyz"):
        if ax in axis.lower():
            ref_mtx[i] *= -1

    behavior_mtx = pmc.dt.Matrix()
    if behavior:
        behavior_mtx[0] *= -1
        behavior_mtx[1] *= -1
        behavior_mtx[2] *= -1

    func = mirror_cmpnts
    if cmpnts is None:
        # look to selection instead
        cmpnts = pmc.selected(containers=True)
        if not cmpnts:
            # still no, to switch to transform mirroring
            cmpnts = pmc.selected(transforms=True)
            func = mirror_hierarchy_flat

    l = len(cmpnts) / 2
    func(zip(cmpnts[:l], cmpnts[l:]), ref_mtx, behavior_mtx)


def mirror_cmpnts(cmpnts, ref_mtx, behavior_mtx):
    """
    Traverse container objects to find their guides and all nested cmpnts.
    :param cmpnt: component which will be affected by this mirroring
    :param target_cmpnt: component which will be targeted for worldspace mirroring
    :param axis: world axis (combo) over which to reflect
    :param behavior: whether or not to apply a local fix to the guides to mirror rotations over translation
    :return:
    """
    for cmpnt, target_cmpnt in cmpnts:
        try:
            objs = ((cmpnt.guideNode.get(), target_cmpnt.guideNode.get()),)
        except AttributeError:
            # could be DAG container and not an actual cmpnt. continue traversal.
            pass
        else:
            mirror_hierarchy_flat(objs, ref_mtx, behavior_mtx)

        mirror_cmpnts(zip(child_cmpnts(cmpnt), child_cmpnts(target_cmpnt)), ref_mtx, behavior_mtx)


def mirror_hierarchy_flat(objs, ref_mtx, behavior_mtx):
    """
    Flat mirroring - siblings first, THEN children.
    :param children: zipped list of guide transforms which will be mirrored onto, and mirroed from
    :param ref_mtx: reflection matrix. default x axis reflection
    :param behavior_mtx: local fix matrix, to flip the axes for mirrored rotation over translation
    :return: None
    """
    for obj, targ_obj in objs:
        mirror_obj(obj, targ_obj, ref_mtx, behavior_mtx)

    for ch, targ_ch in objs:
        next_level = zip(ch.getChildren(), targ_ch.getChildren())
        mirror_hierarchy_flat(next_level, ref_mtx, behavior_mtx)


def mirror_obj(this, mir, ref_mtx, behavior_mtx):
    """Perform a reflection about given matrix on t and its children with respect to mir.
    Also copies user-defined attribute values."""

    try:
        reflected_target = pmc.dt.TransformationMatrix(behavior_mtx * mir.wm.get() * ref_mtx)
        reflected_target.setScale((1, 1, 1), space="transform")
        this.setMatrix(reflected_target, ws=True)
        # refresh (cause maya can be dumb)
        pmc.dgdirty(this)
    except AttributeError:
        pass
    except:
        raise

    # user-defined, numeric attrs
    # NOPE, flip_orientation should be ignored
    # for a, ta in zip(this.listAttr(ud=True, o=True), mir.listAttr(ud=True, o=True)):
    #     a.set(ta.get())

def save_guide_xforms(n=None):
    """Read guide xform values from the current sceneand save to file."""
    if not n:
        # n = pmc.sceneName()
        n = pmc.fileDialog2(ff="*.json")[0]
    guide_pars = [c.guideNode.get() for c in pmc.ls(containers=True) if hasattr(c, "guideNode")]
    guide_data = {}
    for g in guide_pars:
        get_xform_data(g, guide_data)

    writeJson(guide_data, n)
    print("Saved guide xforms to {}".format(n))
    # return guide_data


def save_cvs(n=None):
    """Save the positions of all CVs of all ctrl shapes in the scene to json."""
    if not n:
        # n = pmc.sceneName()
        n = pmc.fileDialog2(ff="*.json")[0]

    cv_dict = {}
    ctrls = [o for o in pmc.ls(transforms=True) if "ctrl" in o.name()]
    for c in ctrls:
        for sh in c.getShapes():
            for cv in sh.cv:
                cv_dict[cv.name()] = pmc.xform(cv, q=True, t=True)

    writeJson(cv_dict, n)
    print("Saved shapes to {}.".format(n))


def load_guide_xforms(f=None):
    """Load guide xforms from the given file and attempt to
    match objects in the current scene to the saved values."""
    if not f:
        f = pmc.fileDialog2(ff="*.json", fileMode=1)[0]

    data = readJson(f)
    for obj, x in data.items():
        try:
            pmc.xform(obj, t=x["t"], ro=x["r"], s=x["s"])
        except:
            pmc.warning("Problem with {}. Skipped!".format(obj))
    else:
        print("Loaded guide xforms from {}".format(f))


def load_cvs(f=None):
    """Match cvs of matching names."""
    if not f:
        f = pmc.fileDialog2(ff="*.json", fileMode=1)[0]

    data = readJson(f)
    for cv, pos in data.items():
        try:
            pmc.xform(cv, t=pos)
        except:
            pmc.warning("Problem with {}. Skipped!".format(cv))
    else:
        print("Loaded shapes from {}".format(f))


def get_xform_data(obj, data):
    """Return a dict of basic transform data. {"t": (xyz), "r": {xyz}, "s": {xyz}}"""
    data[obj.name()] = {"t": tuple(obj.t.get()),
                        "r": tuple(obj.r.get()),
                        "s": tuple(obj.s.get())}

    for c in (o for o in obj.getChildren() if isinstance(o, pmc.nt.Transform)):
        get_xform_data(c, data)


def copy_enums():
    """Copy enum dict from first selected object to the second.
    Works for "parent", "rotation_space", "fk_rotation_space"."""
    enums = ("parent", "rotation_space", "fk_rotation_space")
    s, d = pmc.selected()

    for en in enums:
        try:
            sa = s.attr(en)
            da = d.attr(en)
        except pmc.MayaAttributeError:
            continue
        else:
            # ed = dict(sa.getEnums())
            da.setEnums(sa.getEnums())


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


def get_avg_pos():
    cmpnts = pmc.selected(flatten=True)
    verts = set(v for c in cmpnts for v in c.connectedVertices())
    return sum(v.getPosition(space="world") for v in verts) / len(verts)


def make_jnt_at_avg_pos():
    pos = get_avg_pos()
    pmc.select(clear=True)
    j = pmc.joint()
    j.setTranslation(pos, ws=True)
    return j

def add_parallel_driver():
    """
    Kind of a multi-effect, math-node-based driven key. Hooks into whatever is downstream of selected
    channel box attributes. Dialog opens to ask for
    SelectedFirst stage: select driver attribute in channelBox.
    Next: select driven chains. Creates nodes to scale the driver's value to the driven's value,
    then adds them together and reconnects to any and all driven outputs.
    :return: None
    """
    result = make_dialog("Enter full name of driver attribute.")
    try:
        driver_attr = pmc.PyNode(result)
    except pmc.MayaNodeError:
        raise pmc.MayaNodeError(result)

    d_name = driver_attr.attrName().replace("_", " ").title().replace(" ", "")
    # what I want to do is... scale the driver's value to attr's current value
    # THEN add them together and reconnect - floatCorrect node is perfect
    for attr in get_selected_cb_attrs():
        # have to get the driven attr's outputs BEFORE connecting them to the offset channel
        a_name = attr.attrName()
        pre_outputs = attr.outputs(plugs=True)
        if not pre_outputs or attr.isLocked() or attr.get() == 0:
            # just make it a bit easier to mass-select stuff
            # by having this ignore irrelevant stuff
            continue

        a_name = a_name.replace("_", " ").title().replace(" ", "")
        scale_driver = pmc.nt.MultDoubleLinear(n="scale{}To{}_scalar".format(d_name, a_name))
        add_driver = pmc.nt.AddDoubleLinear(n="add{}To{}_scalar".format(d_name, a_name))
        driver_attr >> scale_driver.input1
        scale_driver.input2.set(attr.get() / driver_attr.get())
        scale_driver.output >> add_driver.input1
        attr >> add_driver.input2
        for result_plug in pre_outputs:
            add_driver.output >> result_plug
        print("{} has been added as a parallel driver to {}".format(d_name, a_name))


def makeFkChain(jnts=None):
    """Select joints in an FK chain starting with the root.
    This creates a simple FK chain of controls for it."""
    prev = None
    ctrls = []
    if not jnts:
        jnts = pmc.selected(type="joint")
    for j in jnts:
        n = j.split("_")
        n[-1] = "{0}"
        n = "_".join(n)
        ctrl = pmc.circle(nr=(1, 0, 0), n=n.format("ctrl"), ch=0)[0]
        ctrls.append(ctrl)
        ctrlGrp = pmc.group(n=n.format("offset"))
        ctrlGrp.setParent(prev)
        prev = ctrl
        pmc.matchTransform(ctrlGrp, j)
        mm = pmc.nt.MultMatrix(n=n.format("fkMtx"))
        ctrl.wm >> mm.i[0]
        ctrlGrp.pim >> mm.i[1]
        dm = pmc.nt.DecomposeMatrix(n=n.format("fkXform"))
        mm.o >> dm.imat
        dm.outputTranslate >> j.t
        dm.outputRotate >> j.r

        #
        j.addAttr("control", at="message")
        ctrl.addAttr("joint", at="message")
        ctrl.joint >> j.control
        j.addAttr("fk_xforms", at="message")
        dm.message >> j.fk_xforms

    return ctrls


def make_dialog(text="Name?", default=""):
    """Pop open a Maya dialog for naming shit"""
    input = pmc.promptDialog(message=text, button=["OK", "Cancel"], text=default,
                             defaultButton="OK", cancelButton="Cancel")
    if input == "Cancel":
        return None

    return pmc.promptDialog(q=True, text=True)


def loop_to_joints(s=0.025):
    """Convert a mesh loop edge selection to a nurbs curve that has
    joints (w/ tweak controls) at each vertex. Opens dialog for naming."""
    edges = pmc.selected(flatten=True)
    cage = edges[0].node()

    try:
        n = make_dialog("Name of this curve/region?") + "{}"
    except TypeError:
        pmc.warning("Aborted.")
        return

    c = pmc.PyNode(pmc.polyToCurve(n=n.format("_rider"))[0])
    verts = set([v for e in edges for v in e.connectedVertices()])
    grp = pmc.group(em=True, n=n.format("_grp"))
    c.setParent(grp)
    jn = ""


    for i, v in enumerate(verts):
        pmc.select(c)
        pmc.selectMode(component=True)
        pmc.select(c.u[i])
        pmc.refresh()
        jn = make_dialog("Name of this joint?", jn)
        poci = pmc.nt.PointOnCurveInfo(n=n.format(jn+"_poci"))
        c.ws >> poci.inputCurve
        poci.parameter.set(i)
        ctrl_grp = pmc.group(em=True, n=n.format(jn+"_offset"))
        ctrl_grp.setParent(grp)
        ctrl = pmc.sphere(r=s, s=1, nsp=1, ch=0, n=n.format(jn+"_tweakCtrl"))[0]
        ctrl.setParent(ctrl_grp)
        j = pmc.joint(n=n.format(jn+"_rig"))
        j.setParent(ctrl)
        j.hide()

        poci.position >> ctrl_grp.translate
        nCon = pmc.normalConstraint(cage, ctrl_grp)
        poci.nt >> nCon.worldUpVector

        # remove graph cluster
        nCon.crp.disconnect()
        nCon.crt.disconnect()
        nCon.cro.disconnect()
        nCon.cpim.disconnect()
        nCon.ct.disconnect()

        poci.position >> nCon.constraintTranslate
        grp.wim >> nCon.cpim

    pmc.selectMode(object=True)


def make_hair_joint_chain(obj, step=5):
    """Create joint chain for selected hair tube object."""
    n = obj.name().split("_")
    n.append("rig{:02d}")
    pmc.select(cl=True)
    edge_indices = pmc.polySelect(obj, edgeLoop=0, noSelection=True)[::-step]
    jnts = []
    for ni, i in enumerate(edge_indices):
        ring = pmc.polySelect(obj, edgeRing=i, noSelection=True)
        vi = 0
        if len(ring) == 1:
            # see if its index-1 vertex is either the first or last
            # (pinch point breaks edge ring)
            if obj.e[ring[0]].connectedVertices()[1] in (obj.vtx[0], obj.vtx[-1]):
                vi = 1
        avg_pos = sum(obj.e[ri].getPoint(vi, space="world") for ri in ring) \
                  / len(ring)

        if ni:
            # get eulers that transform from default to aim vector (local)
            aim_mtx = pmc.dt.TransformationMatrix(j.wm.get())
            aim_mtx[0] = avg_pos - j.getTranslation(ws=True)
            local_aim_mtx = pmc.dt.TransformationMatrix(aim_mtx * j.pim.get())
            j.jo.set(pmc.dt.degrees(local_aim_mtx.euler))

        j = pmc.joint(p=avg_pos, n="_".join(n).format(ni + 1))
        jnts.append(j)

    jnts[-1].jo.set(0, 0, 0)

    return jnts


def make_curve_for_cards(cards=None, numCVs=5):
    """
    Create a guide curve which is the average of the given or selected
    hair cards.
    """
    if not cards:
        cards = pmc.selected()
    cvs = []
    for i in range(numCVs):
        total = sum(c.vtx[i*2].getPosition() + c.vtx[i*2+1].getPosition() for c in cards)
        avg = total / (len(cards) * 2.0)
        cvs.append(avg)

    return pmc.curve(d=3, p=cvs)


def make_joints_for_cards(cards=None, head_jnt=None, numCVs=5, w=2):
    """
    Create a joint chain at the averaged position of each ring for the given hair cards.
    This joint chain can then be driven by FK controls which can themselves blend into
    riding along an nHair via motionPath. 
    FOR NOW, JUST DO JOINTS << MAKE JOINTS DYNAMIC THOUGH. TO TEST HOW IT LOOKS.
    Maybe rotate since that goes better with FK controls which are probably better for hair.
    """
    if not cards:
        cards = pmc.selected()
        if not head_jnt:
            head_jnt = cards.pop()
    
    # max influences = 1, to only head_jnt (not children)
    merged_cards = pmc.polyUnite(cards, muv=True)[0]
    sc = pmc.skinCluster(head_jnt, merged_cards, mi=1, tsb=True)
    j = head_jnt
    pmc.select(cl=True)
    for n in range(numCVs):
        # starting point is length step by width steps, step is total verts per card
        if n:
            pmc.skinCluster(sc, e=True, addInfluence=j, wt=0)
        verts = [v for i in range(w) for v in merged_cards.vtx[n*w+i::numCVs*w]]
        pmc.skinPercent(sc, verts, transformValue=(j, 1.0))
        avg_pos = sum(v.getPosition() for v in verts) / len(verts)
        j = pmc.joint(p=avg_pos, n="hairCurve{:02d}_bind".format(n+1))
        j.radius.set(.05)
        
    # merging objects & skinclusters is be one easy step
    return merged_cards


def make_joint_chains_dynamic(top_jnts=None, use_mesh=False, rig_grp=None):
    """
    Drive given joint chains with dynamic nHairs.
    top_jnts: the top_level joints in the hierarchy. Single-child chain is expected.
    mesh: optional collision mesh arg.
    """
    if not top_jnts:
        top_jnts = pmc.selected()

    if use_mesh:
        mesh = top_jnts.pop()
        n = mesh.name()
    else:
        mesh = None
        n = top_jnts[0].name()

    hair_system, nucleus = make_hair_system(n)
    n = n.split("_")
    n[-1] = "grp"
    n[-2] = "hairSystem"
    rig_grp = pmc.group(hair_system, nucleus, n="_".join(n))
    n[-2] = "hairSplineIk"
    output_grp = pmc.group(em=True, n="_".join(n))

    for i, top_jnt in enumerate(top_jnts):
        if not isinstance(top_jnt, pmc.nt.Joint):
            raise TypeError("Select only joints, or set use_mesh to True" \
                            "if a collision mesh is selected!")
        chain = top_jnt.getChildren(allDescendents=True)
        chain.append(top_jnt)
        n = top_jnt.name().split("_")
        n[-1] = "simStart"
        start_crv = pmc.curve(d=1, p=(j.getTranslation(ws=True) for j in reversed(chain)), n="_".join(n))
        # start_crv > dyn_crv > drive CVs? via fk, in place?

        # make individual follicles and connect em up to system
        n[-1] = "follicle"
        foll = pmc.nt.Follicle().getTransform()
        foll.rename("_".join(n))
        foll.setParent(rig_grp)
        start_crv.setParent(foll)
        # connecting worldMatrix allows startCurve to be put
        # in head space rig group and controlled however.
        # changes propogate to origin space output curves.
        # output_grp must be ID space, however. Oh well.
        start_crv.ws >> foll.startPosition
        if use_mesh:
            mesh.worldMesh >> foll.inputMesh
        foll.outHair >> hair_system.inputHair[i]
        hair_system.outputHair[i] >> foll.currentPosition

        # TODO find 0, .33, .66 positions of curve and skin curve??

        n[-1] = "simDyn"
        dyn_crv = pmc.duplicate(start_crv, n="_".join(n))[0]
        foll.outCurve >> dyn_crv.create
        n[-1] = "simIk"
        ik = pmc.ikHandle(sol="ikSplineSolver", ccv=False, n="_".join(n),
                          sj=top_jnt, ee=chain[0], c=dyn_crv)
        dyn_crv.setParent(output_grp)
        ik[0].setParent(output_grp)

    # pmc.select([ci["curve"] for ci in chain_info])
    # if use_mesh:
    #     pmc.select(mesh, add=True)
    # pmc.cmds.MakeCurvesDynamic()

    # for ci in chain_info:
    #     c = ci["curve"]
    #     dyn_crv = c.local.outputs()[0].outCurve.outputs()[0]
    #     n = c.name().split("_")
    #     n[-1] = "simDyn"
    #     dyn_crv.rename("_".join(n))


def make_hair_system(n):
    """
    Initialize a new hairSystem and nucleus nodes. Return hairSystem.
    """
    n = n.split("_")
    n[-1] = "nucleus"
    nuc = pmc.nt.Nucleus(n="_".join(n))
    nuc.useTransform.set(False)
    n[-1] = "hairSystem"
    hair_system = pmc.nt.HairSystem(n="_".join(n)).getTransform()
    nuc.startFrame >> hair_system.startFrame
    t = pmc.PyNode("time1")
    t.outTime >> nuc.currentTime
    t.outTime >> hair_system.currentTime
    hair_system.currentState >> nuc.inputActive[0]
    hair_system.startState >> nuc.inputActiveStart[0]
    nuc.outputObjects[0] >> hair_system.nextState
    return hair_system, nuc


def aim_at_cage_poci(offset, center):
    """
    For use with FACE CAGE.
    Convert a mesh-riding NURBS curve joint to an aim-at-curve eystem.
    For eyes and such, to ensure the "sliding on top of" appearance.
    :param offset: the curve-riding offset grp.
    :param center: the parent group & location for the new aim joint.
    :return: the aim joint
    """
    n = offset.name().replace("offset", "{}")
    pmc.select(center)

    aim_jnt = pmc.joint(n=n.format("aim"))
    aim_const = pmc.createNode("aimConstraint")
    aim_const.setParent(aim_jnt)
    poci = offset.t.inputs()[0]
    poci.position >> aim_const.target[0].targetTranslate
    poci.nt >> aim_const.worldUpVector
    center.wim >> aim_const.cpim
    aim_const.constraintRotate >> aim_jnt.rotate

    pmc.delete(offset.rx.inputs())
    offset.t.disconnect()
    offset.setParent(aim_jnt)
    offset.r.set(0, 0, 0)

    return aim_jnt


def get_pv_pos(jnts):
    """Get a good worldspace pole vector control position. Works
    for a joint chain of any length (can be used with controls too)"""
    # function to fuxxor the length of a PV offset vector
    dist_func = lambda pv, mv: pv.normal() + mv.length() / 2.0

    start_pos = jnts[0].getTranslation(ws=True)
    end_pos = jnts[-1].getTranslation(ws=True)
    mid_pos = (end_pos - start_pos) / 2.0 + start_pos

    mj_index = (len(jnts) - 1) / 2
    mj_pos = jnts[mj_index].getTranslation(ws=True)
    main_vec = end_pos - start_pos
    rp_normal = main_vec.cross(mj_pos - start_pos)
    # cross rotate plane normal with main vector (start to end)
    # to get vector orthogonal to main vector which points to valid pv position
    # (fuxxor its length a bit)
    pv_offset = dist_func(rp_normal.cross(main_vec))
    return (mid_pos + pv_offset)


def createPathFromSel():
    """Create a path curve object from selected transforms.
    SELECT THEM IN A PROPER ORDER. EPS ARE MADE IN ORDER OF SELETION."""
    trans = pmc.ls(sl=True, transforms=True)
    c = pmc.curve(d=3, ep=(s.getTranslation(ws=True) for s in trans))
    pmc.closeCurve(c, ch=0, rpo=True)
    return c


def make_aim_spline(curve, t1, t2, poci1, poci2, guide=None, axis="x"):
    """
    Turn a pair of transforms into an efficient stretchy spline IK system.
    param poci1: motionPath node for the first transform's output
    param poci2: motionPath node for the second transform's output
    param t1: first (parent) transform object, is given inputs on its rotation
    param t2: second (child) transform object, is given inputs on its translation axis
    param axis: the primary axis of the joint chain
    """

    # deal with translate and distance first
    if isinstance(poci1, pmc.nt.MotionPath):
        pos_attr1 = poci1.allCoordinates
        pos_attr2 = poci2.allCoordinates
    elif isinstance(poci1, pmc.nt.PointOnCurveInfo):
        pos_attr1 = poci1.position
        pos_attr2 = poci2.position
    else:
        pmc.warning("Unknown POCI type!")
        return

    t = "t{}".format(axis)
    offset = pmc.nt.DistanceBetween()
    pos_attr1 >> offset.point1
    pos_attr2 >> offset.point2
    # GUIDE - DISCONNECT
    trans_attr1 = getattr(t2, t)
    offset.distance >> trans_attr1
    if guide:
        gi = nextAvailableIndex(guide.guideSourceAttrs)
        offset.distance >> guide.guideSourceAttrs[gi]
        trans_attr1 >> guide.guideDestAttrs[gi]
        gi+=1
    # else:
    #     trans_attr1.disconnect()
    #     trans_attr1.set(offset.distance.get())
    aim = pmc.createNode("aimConstraint")
    par = t1.getParent()
    aim.setParent(t1)
    if par:
        par.wim >> aim.constraintParentInverseMatrix
        try:
            # returns true if it's on, which is when
            assert t1.segmentScaleCompensate.get()
            par.scale >> aim.inverseScale
        except:
            pass
    else:
        curve.pim >> aim.constraintParentInverseMatrix
    pos_attr2 >> aim.target[0].targetTranslate
    curve.pm >> aim.target[0].targetParentMatrix

    # try to make it abstract, cause it's easy anyway
    # constraintTranslate
    # GUIDE - DISCONNET
    t_channels = [t1.t] + t1.t.children()
    ct_channels = [aim.ct] + aim.ct.children()
    for ch, aim_ch in zip(t_channels, ct_channels):
        ax_input = ch.inputs(plugs=True)
        if ax_input:
            if guide:
                ax_input[0] >> guide.guideSourceAttrs[gi]
                aim_ch >> guide.guideDestAttrs[gi]
                gi+=1
            ax_input[0] >> aim_ch

    # connect final rotation
    aim.constraintRotate >> t1.rotate
    return offset, aim


def make_scale_spline(t1, offset, guide=None, axis="x"):
    ax_i = ("x", "y", "z").index(axis)
    chnls = t1.scale.children()
    scl_ax = chnls.pop(ax_i)

    # length scale - current length / start length
    scale_dist = pmc.nt.FloatMath()
    scale_dist.operation.set(3)
    offset.distance >> scale_dist.floatA
    offset.distance >> scale_dist.floatB
    if guide:
        # GUIDE - DISCONNECT
        gi = nextAvailableIndex(guide.guideSourceAttrs)
        offset.distance >> guide.guideSourceAttrs[gi]
        scale_dist.floatB >> guide.guideDestAttrs[gi]
        gi+=1
    else:
        scale_dist.floatB.disconnect()
        scale_dist.floatB.set(offset.distance.get())
    stretch_multiplier = pmc.nt.AnimBlendNodeAdditiveScale()
    scale_dist.outFloat >> stretch_multiplier.inputA
    stretch_multiplier.inputB.set(1)
    # multiply, not add
    stretch_multiplier.accumulationMode.set(1)
    # weightA is control attribute
    stretch_multiplier.output >> scl_ax

    # now other axes for squash/stretch
    # 1 / length scale (so inverse)
    squash_stretch = pmc.nt.FloatMath()
    squash_stretch.operation.set(3)
    squash_stretch.floatA.set(1)
    stretch_multiplier.output >> squash_stretch.floatB
    for ch in chnls:
        squash_stretch.outFloat >> ch


def make_twist_spline(u, mid_u, aim, base, mid, end, i):
    mid_inv = 1.0 - mid_u
    blend = pmc.nt.BlendColors(n="spine_C_blend0{}Z_vector".format(i + 1))
    if u <= mid_u:
        base.output >> blend.color2
        mid.output >> blend.color1
        # low value biases towards input2, base
        blend.blender.set(u / mid_u)
    else:
        u_inv = u - mid_u
        # low value is closer to middle, so mid = input2
        blend.blender.set(u_inv / mid_inv)
        mid.output >> blend.color2
        end.output >> blend.color1

    aim.upVector.set(0, 0, 1)
    blend.output >> aim.worldUpVector


def make_curve_jnt(curve, u, n, p, mode="poci"):
    """
    
    """
    j = pmc.joint(n=n.format("rig"))
    j.setParent(p)
    #joints are dumb
    j.jo.set(0, 0, 0)
    j.setMatrix(pmc.dt.Matrix())
    if mode == "poci":
        poci = pmc.nt.PointOnCurveInfo()
        poci.parameter.set(u)
        poci.turnOnPercentage.set(True)
        curve.l >> poci.inputCurve
    elif mode == "mp":
        poci = pmc.nt.MotionPath(n=n.format("poci"))
        curve.l >> poci.geometryPath
        poci.uValue.set(u)
        poci.fractionMode.set(True)
    else:
        pmc.warning("Unknown POCI type!")
        return
    return j, poci


def make_stretchy_spline(curve, guide=None, spans=4, n="cpoci_side_bendySpline{:02d}_{}", scale=True):
    j1, poci1 = make_curve_jnt(curve, 0.0, n.format(1, "{}"), curve.getParent())
    try:
        poci1.allCoordinates >> j1.t
    except AttributeError:
        poci1.position >> j1.t
    for i in xrange(spans):
        u = (i + 1.0) / spans
        j2, poci2 = make_curve_jnt(curve, u, n.format(i+2, "{}"), j1)
        offset, aim = make_aim_spline(curve, j1, j2, poci1, poci2, guide, "x")
        if scale:
            make_scale_spline(j1, offset, guide, "x")
        j1, poci1 = j2, poci2
        # twist add depends on controls - per control loop


def make_stretchy_spline_from_sel(guide=None, n="cpoci_side_bendySpline{:02d}_{}", scale=True):
    """
    Version of make stretchy spline that uses a selection of transforms to
    :param guide:
    :param n:
    :param scale:
    :return:
    """
    jnts = pmc.selected()
    crv = createPathFromSel()
    i = 1
    par = crv.getParent()
    npoc = pmc.nt.NearestPointOnCurve()
    pmc.select(cl=True)

    j1, mp1 = make_curve_jnt(crv, 0.0, n.format(i, "{}"), par, mode="mp")
    mp1.fractionMode.set(False)
    for oj in jnts[1:]:
        i += 1
        crv.ws >> npoc.inputCurve
        npoc.inPosition.set(oj.getTranslation(ws=True))
        u = npoc.parameter.get()
        j2, mp2 = make_curve_jnt(crv, u, n.format(i, "{}"), j1, mode="mp")
        mp2.fractionMode.set(False)
        offset, aim = make_aim_spline(crv, j1, j2, mp1, mp2)
        if scale:
            make_scale_spline(j1, offset, guide, "x")
        j1, mp1 = j2, mp2


def attachToMotionPath(path, control, numJnts, frontAxis="Z", upAxis="X", wuo=None, wuv=(1, 0, 0)):
    """Given a path curve and a set of joints, create motion path nodes
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


def make_ctrl_at_jnt(jnt=None, axis="x"):
    """
    Create a nurbs circle at the given or selected joint.
    :param jnt: (optional) Joint to match xforms to.
    :param axis: (optional) Joint primary axis.
    :return: the nurbs control
    """
    if not jnt:
        jnt = pmc.selected(type="joint")[0]

    n = jnt.name().split("_")
    n[-1] = "{}"
    n = "_".join(n)
    offset = pmc.group(em=True, n=n.format("offset"))
    axis = [1 if a == axis else 0 for a in "xyz"]
    ctrl = pmc.circle(n=n.format("ctrl"), nr=axis, r=1.0, s=12, d=1, ch=0)[0]
    ctrl.setParent(offset)
    ctrl.lineWidth.set(2)
    pmc.matchTransform(offset, jnt)

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


def bake_rots_to_jnt_orient(jnts=None):
    """
    Zero selected joints' rotation channels and bake its orientation to joint orient.
    :return:
    """
    if not jnts:
        jnts = pmc.selected()
    for s in jnts:
        m = s.m.get()
        s.jo.set(0, 0, 0)
        s.setMatrix(m)
        s.jo.set(s.r.get())
        s.r.set(0, 0, 0)


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


