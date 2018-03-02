import pymel.core as pmc


__author__ = "Brendan Kelly"


"""Matrix Utilities for Maya"""

"""
getVectorForAxis
getAxisForVector
arbitraryOrthoVec
rotMat
matrixFromVectors
xformFromSpaces
orientConstInOtherSpace
printMatrix
"""


def getVectorForAxis(axis):
    return pmc.dt.Vector(float(a == axis.lower()) for a in ["x", "y", "z"])


def getAxisForVector(vector):
    vector = pmc.dt.Vector(vector).normal()
    if vector[0] > .99:
        return "x"
    elif vector[1] > .99:
        return "y"
    elif vector[2] > .99:
        return "z"
    else:
        pmc.warning("Vector passed in is not a standard basis vector!")


def arbitraryOrthoVec(v):
    """Get a vector which is orthogonal to the given vector"""
    if v.x or v.y:
        return pmc.dt.Vector(v.y, -v.x, 0)
    else:
        return pmc.dt.Vector(0, v.z, -v.y)


def rotMat(inMat):
    """Return rotations-only matrix of given matrix"""
    return pmc.dt.TransformationMatrix(inMat.get()).asRotateMatrix()


def angleBetween(v1, v2, rotOrd="XYZ"):
    """Just like Maya's build in angleBetween command but accepts
    a rotOrder arg for different rotation orders. Locked to Euler results."""
    # ensure v1 and v2 are valid vector types
    v1, v2 = pmc.dt.Vector(v1), pmc.dt.Vector(v2)
    q = v1.rotateTo(pmc.dt.Vector(v2))
    e = pmc.dt.EulerRotation(q)
    e.reorderIt(rotOrd)
    e.setDisplayUnit("degrees")

    return e.x, e.y, e.z


def matrixFromVectors(name="customMatrix", x=None, y=None, z=None, pos=None):
    """Create and return the matrix nodes for a fake follicle."""

    mat = pmc.nt.FourByFourMatrix(n=name)
    if x:
        xx, xy, xz = x.children()
        xx >> mat.in00
        xy >> mat.in01
        xz >> mat.in02
    if y:
        yx, yy, yz = y.children()
        yx >> mat.in10
        yy >> mat.in11
        yz >> mat.in12
    if z:
        zx, zy, zz = z.children()
        zx >> mat.in20
        zy >> mat.in21
        zz >> mat.in22
    if pos:
        px, py, pz = pos.children()
        px >> mat.in30
        py >> mat.in31
        pz >> mat.in32

    return mat


def xformFromSpaces(matList, n, rotOrder):
    """Given a list of matrices (IN MULTIPLICATION ORDER), return
    the decompose node for their xforms. Matrix arguments in attribute form
    will be connected, static data matrices will be set."""
    pmc.requires("matrixNodes", "1.0", nodeType="decomposeMatrix")
    mult = pmc.nt.MultMatrix(n=n+"Mat")
    for i, mat in enumerate(matList):
        if isinstance(mat, pmc.Attribute):
            #Live, connect it
            mat >> mult.matrixIn[i]
        elif isinstance(mat, pmc.dt.Matrix):
            #Static data, set
            mult.matrixIn[i].set(mat)
        else:
            pmc.warning("Invalid matrix provided:\n{0}".format(mat))
            continue
    xform = pmc.nt.DecomposeMatrix(n=n)
    xform.inputRotateOrder.set(rotOrder)
    mult.matrixSum >> xform.inputMatrix
    return xform


def orientConstInOtherSpace(src, tar, otherMatrix, n=None, activeOffset=False):
    """Create an orientConstraint for target
    as though target had otherMatrix as parentMatrix.
    Offset by other's rotations minus parentGrp's rotations"""
    if not n:
        n = tar.name() + "{0}"
    oc = pmc.createNode("orientConstraint", n=n.format("_otherSpace_orientConstraint"))
    src.rotate >> oc.target[0].targetRotate
    src.parentMatrix >> oc.target[0].targetParentMatrix
    oc.target[0].targetWeight.set(1)
    inv = pmc.nt.InverseMatrix(n=n.format("_invOtherMatrix"))
    #statMat.output >> inv.inputMatrix
    otherMatrix >> inv.inputMatrix
    inv.outputMatrix >> oc.constraintParentInverseMatrix
    # offset is the difference between all axis and single axis static
    # done with matrices instead of eulers for improved stability
    if activeOffset:
        offsetMat = pmc.nt.MultMatrix(n=n.format("_offsetMatrix"))
        src.parentMatrix >> offsetMat.matrixIn[0]
        inv.outputMatrix >> offsetMat.matrixIn[1]
        offsetRot = pmc.nt.DecomposeMatrix(n=n.format("_offsetRot"))
        offsetMat.matrixSum >> offsetRot.inputMatrix
        #offsetRot.outputRotate >> oc.offset
        offsetFix = pmc.nt.MultiplyDivide(n=n.format("_offsetFix"))
        offsetRot.outputRotate >> offsetFix.input1
        offsetFix.input2.set(-1, -1, -1)
        offsetFix.output >> oc.offset

    oc.constraintRotate >> tar.rotate
    oc.setParent(tar)

    return oc


def printMatrix(m):
    """Print matrix in an easy-to-read way"""
    print("\n{0}".format(m.nodeName()))
    print(m.longName())
    for r in m.get():
        t = []
        for c in r:
            t.append(float("{0:.3f}".format(c)))
        print(t)
