from rigGuiBaseClass import RigGuiBase
from bkTools import qtUtil as qtu
import rigGuiBaseQt

def main(GuiClass=RigGuiBase, replace=False):
    """Show existing Rig Gui or create new one. Pass subclass in too"""
    qtu.makeNewDockGui(GuiClass, replace)

if __name__ == "__main__":
    main()