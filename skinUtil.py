import pymel.core as pmc
import logging

from pymel import core as pmc

"""
Utilities centered around Maya smooth bindings.
"""


def localize_skin():
    """
    Change selected object's skin to use local matrices instead of world
    :return:
    """
    sh = pmc.selected()[0]
    sc = sh.getShape().inputs(type="skinCluster")[0]
    for m, bpm in zip(sc.ma, sc.pm):
        j = m.inputs()[0]
        bpm.set(j.im.get())
        j.m >> m
        j.bindPose.set(j.m.get())
    sc.geomMatrix.set(sh.m.get())
    print("Success on {}".format(sc))


def convert_cage_to_bind_joints(cage):
    """Given a mesh, put a joint at every vertex."""
    for vtx in cage.vtx:
        print(vtx)
        vtx_pos = vtx.getPosition()
        for adj_vtx in vtx.connectedVertices():
            adj_pos = adj_vtx.getPosition()
            dist = pmc.dt.Vector(vtx_pos - adj_pos).length()
            print(dist)

        j = pmc.joint()
        pmc.select(cl=True)
        j.t.set(vtx_pos)


def weight_mesh_from_cage(mesh, cage):
    for i in cage.uvs.indices():
        u, v = cage.getUV(i)


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


def append_along_loop():
    # static sew edges
    edges = pmc.selected(flatten=True)
    obj = edges[0].node()
    verts = [v for e in edges for v in iter(e.connectedVertices())]
    uvs = [tuple(set(v.getUVIndices())) for v in verts]
    # select FIRST edge loop? maybe?
    uv_border = [obj.map[uv[0]] for uv in uvs]

    pmc.select(uv_border)

    # snap each uv from 2nd shell to match 1st shell
    # pmc.polyEditUV
    # pmc.polyMapSew


def skin_chain_to_tube(obj, jnts):
    # skin, and calculate average dropoff rate
    distances = [j.t.get().length() for j in jnts[1:]]
    dropoff = 1.0 / (sum(distances) / len(distances))
    # closest in hierarchy, neighbors weight dist
    pmc.skinCluster(jnts[0], obj, bindMethod=1, maximumInfluences=3,
                    weightDistribution=1, dropoffRate=dropoff)


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


def set_verts_to_jnt():
    """Select mesh components and joint to fix them to. Floods them with full weight."""
    sel = pmc.selected(flatten=True)
    j = sel.pop()
    sc = sel[0].node().inputs(type="skinCluster")[0]
    verts = []
    for f in sel:
        if isinstance(f, pmc.MeshVertex) or isinstance(f, pmc.NurbsCurveCV):
            verts.append(f)
        else:
            verts.extend(v for v in f.connectedVertices())

    pmc.skinPercent(sc, verts, tv=(j, 1))
