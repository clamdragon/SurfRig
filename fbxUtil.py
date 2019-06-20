"""
Personal util for dealing with FBX files.
Import/export, scene cleanup, validation.
Some pyblish too - collection, validation, extraction, integration.
"""
from FBX_Scene import FBX_Class
import fbx
import FbxCommon

_practice_file = "C:/Users/Brendan/SkyDrive/3D/Mother/practice.fbx"


def print_fbx_contents(f):
    """Print EVERYTHING in the fbx file, and safely close it when done."""
    # if not f:
    #     f = QtWidgets.QFileDialog.getOpenFileName(dir=pmc.workspace(q=True, rd=True), filter="*.json")[0]
    fbx_file = FBX_Class(f)
    try:
        print(fbx_file.scene.GetGlobalSettings())
        print(fbx_file.scene.GetAnimationEvaluator())
        frame = fbx.FbxTime()
        frame.SetFrame(24)
        print_node(fbx_file.root_node, "{}")
        print("<<------------------- END ------------------->>")
    except:
        raise
    finally:
        fbx_file.close()


def rename_fbx_joints(fn, rename_dict, out_file=None):
    """
    Go through given fbx file and rename joints which match args
    :param f: fbx file
    :param rename_dict: dict of old_name: new_name pairs
    :param out_file:
    :return: None
    """
    if not out_file:
        out_file = fn.replace(".fbx", "_renamed.fbx")
    fbx_file = FBX_Class(fn)
    try:
        for node in fbx_file.get_scene_nodes():
            old_name = node.GetName()
            new_name = rename_dict.get(old_name)
            if new_name:
                node.SetName(new_name)
        fbx_file.save(filename=out_file)
    finally:
        fbx_file.close()


def print_node(node, formatted_line):
    """Print a node and all of its attributes """
    print("<<------------------- FBX NODE ------------------->>")
    print(formatted_line.format(node.GetName()))
    member = formatted_line.format("{} {}")
    # print(member.format("@", node.EvaluateLocalTransform(frame)))
    # print(member.format("@", node.EvaluateGlobalTransform()))

    for i in range(node.GetNodeAttributeCount()):
        print(member.format(".", node.GetNodeAttributeByIndex(i).GetName()))

    print_connections(node, member)

    for n in range(node.GetChildCount()):
        print_node(node.GetChild(n), formatted_line.format("    {}"))


def print_connections(obj, formatted_line):
    """Print a given object's connections."""
    # objects
    for so in range(obj.GetSrcObjectCount()):
        # this is the same thing as GetChild, except
        # for all FbxObjects instead of just FbxNodes
        print(formatted_line.format("[]<-", obj.GetSrcObject(so).GetName()))
    for do in range(obj.GetDstObjectCount()):
        print(formatted_line.format("->[]", obj.GetDstObject(do).GetName()))
    # properties
    for sp in range(obj.GetSrcPropertyCount()):
        print(formatted_line.format(".<-", obj.GetSrcProperty(sp).GetName()))
    for dp in range(obj.GetDstPropertyCount()):
        print(formatted_line.format("->.", obj.GetDstProperty(dp).GetName()))

