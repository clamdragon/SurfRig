import os
import sys
import xml.etree.ElementTree as xml
from cStringIO import StringIO
from functools import wraps
import traceback
from bkTools.Qt import QtCompat, QtWidgets, QtGui, QtCore, _loadUi #QtUiTools
import pymel.core as pmc
from maya.OpenMayaUI import MQtUtil
# from pyqt4topyqt5 import toPyside2
# import convert2pyside2
try:
    import shiboken2
    import pyside2uic
except ImportError:
    import shiboken as shiboken2
    import pysideuic as pyside2uic
try:
    from maya.app.general.mayaMixin import MayaQWidgetDockableMixin as MayaDock
except ImportError:
    MayaDock = QtWidgets.QDockWidget


__author__ = "Brendan Kelly"
__email__ = "clamdragon@gmail.com"


"""
Utilities for Maya-Pyside UI building
"""


def SlotExceptionRaiser(origSlot):
    """A decorator function for a PySide2 slot which will
    raise any errors encountered in execution to the console"""
    @wraps(origSlot)
    def wrapper(*args, **kwargs):
        try:
            origSlot(*args, **kwargs)
        except:
            print("\nUncaught Exception in PySide Slot!\n")
            traceback.print_exc()
            #traceback.format_exc()
    return wrapper


# Get maya main window for parenting
#
def getMayaMainWindow():
    # returns a QWidget wrapper for the main maya window,
    # to allow uiMaster to be parented to it
    mayaWin = MQtUtil.mainWindow()
    if mayaWin:
        return shiboken2.wrapInstance(long(mayaWin), QtWidgets.QMainWindow)


def minimizeSubWindows():
    main = getMayaMainWindow()
    for win in set(w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w != main):
        win.setWindowState(QtCore.Qt.WindowMinimized)


# Convenience function to get mainwindow child window of given name
# works with their window title or MayaMixin object name
#
def getChildWin(title, widgType=QtWidgets.QWidget):
    for w in getMayaMainWindow().children():
        if w.isWidgetType() and w.windowTitle() == title:
            return w
    else:
        ptr = MQtUtil.findControl(title)
        if not ptr:
            ptr = MQtUtil.findWindow(title)
        if not ptr:
            ptr = MQtUtil.findLayout(title)
        if not ptr:
            return
        return shiboken2.wrapInstance(long(ptr), widgType)



def compileUI(inFiles=None):  
    """compile .ui to .py - made easy.
    pass file as argument, or else a file browser opens
    for you to select one. Assumes same name for compiled .py"""
    if not inFiles:
        # File browser if no file given
        inFiles = getUserFiles("Qt Designer Files", ".ui")

    for inFile in inFiles:
        outFile = inFile.replace(".ui", ".py")
        s = StringIO()
        try:
            pyside2uic.compileUi(inFile, s, False, 4, False)
        except:
            print("Failed. Invalid file name:\n{0}".format(inFile))
            raise

        #text = s.getvalue().replace("from PySide2 import", "from Qt import")
        # fix PySide2/PySide issues
        text = "\n".join(QtCompat._convert(s.getvalue().split("\n")))
        with open(outFile, "w") as pyFile:
            pyFile.write(text)
        print("Success! Result: {0}".format(outFile))
        s.close()


def loadUiType(uiFile=None):
    """
    :author: Jason Parks
    Pyside lacks the "loadUiType" command, so we have to convert the ui 
    file to py code in-memory first
    and then execute it in a special frame to retrieve the form_class.
    """
    if not uiFile:
        try:
            uiFile = getUserFiles("Qt Designer Files", ".ui")[0]
        except IndexError:
            print("Invalid File.")
            return
    
    parsed = xml.parse(uiFile)
    widget_class = parsed.find('widget').get('class')
    form_class = parsed.find('class').text

    with open(uiFile, 'r') as f:
        o = StringIO()
        frame = {}

        pyside2uic.compileUi(f, o, indent=0)
        pyc = compile(o.getvalue(), '<string>', 'exec')
        exec pyc in frame

        # Fetch the base_class and form class based on their type in the xml from designer
        form_class = frame['Ui_%s' % form_class]
        base_class = getattr(QtWidgets, widget_class)
    return form_class, base_class


def buildClass(custom, base="QWidget"):
    """Factory Function to build a single class from the given combination.
    The second argument (base class) may be class or a string, to allow use 
    without importing QtWidgets from caller's frame.
    Used frequently with QtDesigner objects."""
    if isinstance(base, str):
        base = getattr(QtWidgets, base)
    class UiWidg(custom, base):
        """Qt object composed of compiled (form) class and base class"""
        def __init__(self, parent=None):
            super(UiWidg, self).__init__(parent)
            # the compiled .py file has the content,
            # this class provides the widget to fill
            self.setupUi(self)
    return UiWidg


class QtDockUi(QtWidgets.QDockWidget):
    """Inheriting from qdockwidget, a few convenience changes
    to make it usable in the same way as the newer mixin mDock"""
    def __init__(self, parent=None):
        self.base = super(QtDockUi, self)
        if not parent:
            parent = getMayaMainWindow()
        self.base.__init__(parent)
        self.topLevelChanged.connect(self.reFloat)
        self.setFloating(True)

    def show(self, *args, **kwargs):
        """Just make it so it doesn't throw an error when it gets args"""
        self.base.show()

    def reFloat(self, floating):
        """Restore window appearance when floating again"""
        if floating:
            self.setWindowFlags(QtCore.Qt.Window)
            self.resize(self.sizeHint())
            self.setProperty("savedSize", self.sizeHint())
            self.show()


def buildMayaDock(base):
    """Get a Maya-dockable UI from the given qwidget subclass.
    This is ONLY for 2017+, as MRO demands that mDock comes first, 
    but QDockWidget must come after any compiled designer class"""
    try:
        assert issubclass(base, QtWidgets.QWidget)
    except (TypeError, AssertionError):
        print("Base class argument {0} must inherit QWidget in "
              "order to be a Maya dock widget.".format(base))
        return

    class MayaDockUi(MayaDock, base):
        """Some dock signals are replaced by method stubs:
        - dockCloseEventTriggered
        - floatingChanged
        ALSO, .show() method has args the FIRST TIME it is called, by default:
            dockable=False, floating=True, area="left", allowedArea="all", 
            width=None, height=None, x=None, y=None"""
        def __init__(self, parent=None):
            super(MayaDockUi, self).__init__(parent=parent)

    return MayaDockUi


def makeNewDockGui(GuiClass, name=None):
    """Create a dockable instance of the given class.
    Different combo classes and MROs for PySide and PySide2."""
    if not name:
        name = GuiClass.__name__ + "Qt"
    main = getMayaMainWindow()
    ctrlName = name + "WorkspaceControl"

    if MayaDock is QtWidgets.QDockWidget:
        # pre-2017
        # object names: guts are default name, shell is ctrlName
        ui = GuiClass(main)
        ui.setObjectName(name)
        dock = QtDockUi()
        dock.setWidget(ui)
        dock.setObjectName(ctrlName)
        dock.setWindowTitle(ui.windowTitle())
        dock.setWindowFlags(QtCore.Qt.Window)
        # left and right
        dock.setAllowedAreas(3)
        dock.show()
    else:
        ui = buildMayaDock(GuiClass)()
        ui.setObjectName(name)
        ui.show(dockable=True)

    return ui


def dockGui(GuiClass, name=None, replace=False):
    """Return a dockable ui of the given type.
    Possibly one that already exists if it exists and replace arg is false."""
    ctrlName = name + "WorkspaceControl"
    if not replace and pmc.control(name, q=True, ex=True):
        # in this case, just find the controls/windows - show and return
        showUi(name)
        showUi(ctrlName)
        
        return getChildWin(name)

    deleteUi(name)
    deleteUi(ctrlName)

    return makeNewDockGui(GuiClass, name=name)


def showUi(name):
    """Maya is dumb. UI objects can be either controls or windows.
    Throw spaghetti at the wall and see what sticks"""
    try:
        pmc.control(name, e=True, vis=True)
    except:
        pass
    try:
        pmc.window(name, e=True, vis=True)
    except:
        pass


def deleteUi(name):
    """Iterative UI delete becuase duplicates are somehow possible"""
    while pmc.control(name, q=True, ex=True):
        pmc.deleteUI(name)
    while pmc.window(name, q=True, ex=True):
        pmc.deleteUI(name)


"""
# Utility to convert code in given file to PySide2
# imperfect
#
def convertToPyside2(inFiles=None, backwardsCompatible=False):
    if not inFiles:
        inFiles = getUserFiles()

    for inFile in inFiles:
        toPyside2.Main(inFile, backwardsCompatible=backwardsCompatible)
"""

def convertToPyside2(fileName=None):
	"""Use my included convert2pyside2. CAN BE SLOW FOR LARGE FILES.
	I recommend pyqt4topyqt5, which can be converted to PySide (instead of PyQt)
	with minimal effort."""
	convert2pyside2.convert2pyside2(fileName)


def getUserFiles(description="Python File", ext=".py"):
    """Create a file dialog and return user selected files.
    Args are string description and allowed file types."""
    fileWin = QtWidgets.QFileDialog(
        getMayaMainWindow(), filter="{0} (*{1})".format(description, ext))
    
    fileWin.setFileMode(QtWidgets.QFileDialog.ExistingFiles)
    
    if fileWin.exec_():
        inFiles = fileWin.selectedFiles()
    else:
        inFiles = []

    fileWin.setParent(None)

    return inFiles


def get_float_value(title="Enter value", label="Enter a float value"):
    r = QtWidgets.QInputDialog.getDouble(getMayaMainWindow(), title, label)
    if not r[1]:
        raise RuntimeError("No valid value entered!")
    else:
        return r[0]


# load a .py gui file
# undefined behavior for invalid files
def loadPyGui(f=None):
    if not f:
        files = getUserFiles("Python GUI", ".py")

    import __main__
    for g in files:
        name = os.path.basename(g).strip(".py")
        if name in sys.modules:
            exec("reload({0})".format(name), vars(__main__))
            continue

        d = os.path.dirname(g)
        sys.path.append(d)
        exec("import {0}".format(name), vars(__main__))


def loadRawGui(f=None):
    if not f:
        files = getUserFiles("Qt Designer UI", ".ui")

    for g in files:
        widg = loadFromUi(g)

def loadFromUi(f, parent=None):
    if not os.path.exists(f):
        print("Invalid file.")
        return

    #loader = QtUiTools.QUiLoader()
    loader = _loadUi()
    if not parent:
        parent = getMayaMainWindow()
    return loader.load(f, parent)


def mayaNameValidator(parent=None, rxString="\w+"):
    """Returns a QRegExpValidator pre-loaded with acceptable
    Maya name scheme, ie alphanumeric with space/underscore"""
    rx = QtCore.QRegExp(rxString)
    if not parent:
        parent = getMayaMainWindow()
    return QtGui.QRegExpValidator(rx, parent)


# convenience functions for saving/restoring UI settings to an .ini
#
def saveSetting(fileName, settingName, state):
    qSet = QtCore.QSettings(fileName, QtCore.QSettings.IniFormat)
    qSet.setIniCodec("UTF-8")
    if type(state) is bool:
        state = int(state)
    qSet.setValue(settingName, state)

# way to mass-read settings to minimize file access
def readSettings(fileName, settingNames):
    qSet = QtCore.QSettings(fileName, QtCore.QSettings.IniFormat)
    qSet.setIniCodec("UTF-8")
    # return dict of all requested settings
    result = {}
    for s in settingNames:
        result[s] = qSet.value(s, None)
    return result


def option_box(*args):
    """
    args must be tuples of (button_text, function)
    """
    win = QtWidgets.QMessageBox(getMayaMainWindow())
    for opt, func in args:
        but = win.addButton(opt, win.AcceptRole)
        but.clicked.connect(func)
    win.exec_()
