from os.path import (
    exists,
    join,
    expanduser,
    isdir,
    isfile
)
from shutil import (
    copyfile,
    move
)
from os import (
    sep,
    mkdir,
    listdir,
    remove
)
from pprint import (
    PrettyPrinter
)
from threading import (
    Lock,
    Thread
)
from queue import (
    Empty,
    Queue
)
from traceback import (
    print_exc,
    format_exc
)
from time import (
    time
)
from re import (
    compile
)
from sys import (
    stdout
)
from subprocess import (
    Popen
)


try:
    from wx import (
        App,
        Frame,
        EVT_CLOSE,
        StaticText,
        TextCtrl,
        BoxSizer,
        HORIZONTAL,
        VERTICAL,
        EXPAND,
        Button,
        EVT_BUTTON,
        DirDialog,
        DD_DEFAULT_STYLE,
        DD_DIR_MUST_EXIST,
        ID_OK,
        MessageDialog,
        YES_NO,
        ID_NO,
        MenuBar,
        Menu,
        ID_ABOUT,
        CheckBox,
        EVT_CHECKBOX,
        EVT_MENU
    )
except ImportError:
    print_exc()
    print("try python -m pip install --upgrade wxPython")
    exit(-1)

try:
    from git import (
        Repo,
        InvalidGitRepositoryError
    )
except ImportError:
    print_exc()
    print("try python -m pip install --upgrade gitpython")
    exit(-1)

# Windows
#########
try:
    from win32file import (
        CreateFile,
        FILE_SHARE_READ,
        FILE_SHARE_WRITE,
        OPEN_EXISTING,
        OPEN_EXISTING,
        ReadDirectoryChangesW,
        CloseHandle
    )
    from win32con import (
        FILE_NOTIFY_CHANGE_FILE_NAME,
        FILE_NOTIFY_CHANGE_DIR_NAME,
        FILE_NOTIFY_CHANGE_SIZE,
        FILE_NOTIFY_CHANGE_LAST_WRITE,
        FILE_FLAG_BACKUP_SEMANTICS
    )
except ImportError:
    print_exc()
    print("try python -m pip install --upgrade pywin32")
    exit(-1)

FILE_LIST_DIRECTORY = 0x0001
ACTIONS = {
  1 : "Created",
  2 : "Deleted",
  3 : "Updated",
  4 : "Renamed from something",
  5 : "Renamed to something"
}

def open_directory_in_explorer(path):
    Popen('explorer "%s"' % path)

# Generic
#########

logLock = Lock()


def log(*messages):
    with logLock:
        stdout.write(" ".join(messages))
        stdout.write("\n")


class Settings(object):

    def __init__(self):
        self.path = expanduser(join("~", "savemon.settings.py"))
        self.saves = []

    def __enter__(self, *_):
        try:
            with open(self.path, "r") as f:
                code = f.read()
        except:
            pass
        else:
            glob = dict()
            try:
                exec(code, glob)
            except:
                print_exc()
            else:
                for k, v in glob.items():
                    setattr(self, k, v)

        return self

    def __exit__(self, *exc):
        if exc[0]:
            return

        pp = PrettyPrinter(indent = 4)

        code = "\n".join(
            ("%s = %s" % (a, pp.pformat(getattr(self, a)))) for a in [
                "saves",
            ]
        )
        try:
            with open(self.path + ".tmp", "w") as f:
                f.write(code)
        except:
            print_exc()
        else:
            move(self.path + ".tmp", self.path)


class MonitorThread(Thread):

    def __init__(self, rootPath, onExit):
        super(MonitorThread, self).__init__(name = "Directory Monitor Thread")
        self.rootPath = rootPath
        self.onExit = onExit
        self._exit_request = False
        self.trigger_file = join(rootPath, ".savemon.trigger")
        self.changes = Queue()

    def run(self):
        root = self.rootPath
        log("Start monitoring of '%s'" % root)
        hDir = CreateFile(root, FILE_LIST_DIRECTORY,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None
        )
        while not self._exit_request:
            changes = ReadDirectoryChangesW(hDir, 1024, True,
                FILE_NOTIFY_CHANGE_FILE_NAME |
                    FILE_NOTIFY_CHANGE_DIR_NAME |
                    FILE_NOTIFY_CHANGE_SIZE |
                    FILE_NOTIFY_CHANGE_LAST_WRITE,
                None,
                None
            )
            for action, file in changes:
                changed = join(root, file)
                if changed == self.trigger_file:
                    continue
                self.changes.put((action, file))
                log(changed,
                    ACTIONS.get(action, "[unknown 0x%X]" % action)
                )

        log("Stop monitoring of '%s'" % root)
        CloseHandle(hDir)

        self.onExit()

    @property
    def exit_request(self):
        return self._exit_request

    @exit_request.setter
    def exit_request(self, val):
        self._exit_request = val
        if val:
            self.trigger()

    def trigger(self):
        assert not exists(self.trigger_file)
        with open(self.trigger_file, "w"): pass
        remove(self.trigger_file)


class BackUpThread(Thread):

    def __init__(self, saveDir, backupDir, changesQueue, filterOut = None):
        super(BackUpThread, self).__init__(name = "Backing Up Thread")

        self.saveDir = saveDir
        self.backupDir = backupDir
        self.qchanges = changesQueue
        self.exit_request = False
        self.filterOut = filterOut

        self.doCommit = []

    def commit(self):
        repo, doCommit = self.repo, self.doCommit
        if doCommit:
            log("Committing changes")
            for method, node in doCommit:
                if method == "add":
                    repo.index.add([node])
                elif method == "remove":
                    repo.index.remove([node], working_tree = True)
            message = " ".join(
                c[1] for c in doCommit[0 : min(5, len(doCommit))]
            )
            repo.index.commit(message)
            del doCommit[:]

    def check(self, relN):
        fullN = join(self.saveDir, relN)
        fullBackN = join(self.backupDir, relN)

        if isfile(fullN):
            if exists(fullBackN):
                with open(fullN, "rb") as f0:
                    with open(fullBackN, "rb") as f1:
                        doChanged = f0.read() != f1.read()
                if doChanged:
                    log("Replacing %s with %s" % (fullBackN, fullN))
                    copyfile(fullN, fullBackN)
                    self.doCommit.append(("add", relN))
            else:
                log("Copying '%s' to '%s'" % (fullN, fullBackN))
                copyfile(fullN, fullBackN)
                self.doCommit.append(("add", relN))
        else:
            if isfile(fullBackN):
                log("Removing '%s'" % fullBackN)
                self.doCommit.append(("remove", relN))

    def run(self):
        backupDir = self.backupDir
        saveDir = self.saveDir
        filterOut = self.filterOut

        try:
            self.repo = Repo(backupDir)
        except InvalidGitRepositoryError:
            log("Initializing Git repository in '%s'" % backupDir)
            self.repo = Repo.init(backupDir)

        log("Backing up current content of '%s'" % saveDir)
        stack = [""]
        while stack:
            cur = stack.pop()
            curSave = join(saveDir, cur)
            curBackup = join(backupDir, cur)
            toCheck = set(listdir(curSave) + listdir(curBackup))
            for n in toCheck:
                relN = join(cur, n)

                if filterOut and filterOut.match(relN):
                    log("Ignoring '%s' (Filter Out)" % relN)
                    continue

                fullN = join(saveDir, relN)
                fullBackN = join(backupDir, relN)

                if isdir(fullN):
                    if not exists(fullBackN):
                        log("Creating directory '%s'" % fullBackN)
                        mkdir(fullBackN)
                    stack.append(relN)
                    continue

                self.check(relN)

        self.commit()

        changes = set()

        lastChange = time()

        # Do not exit until detected changes are committed
        while not self.exit_request or changes:
            try:
                change = self.qchanges.get(timeout = 0.1)
            except Empty:
                # give game a chance to made save data consistent
                t = time()
                if changes and t - lastChange > 5.0:
                    log("Checking\n    %s" % "\n    ".join(
                        c[1] for c in changes)
                    )
                    for c in changes:
                        cur = c[1]
                        self.check(cur)

                    changes.clear()
                    self.commit()
                continue

            if filterOut and filterOut.match(change[1]):
                log("Ignoring '%s' (Filter Out)" % change[1])
                continue
            else:
                changes.add(change)
            lastChange = time()

        log("Stop backing up of '%s'" % saveDir)


class SaveSettings(object):

    def __init__(self, master, saveDirVal = None, backupDirVal = None):
        self.master = master

        saveDirSizer = BoxSizer(HORIZONTAL)
        self.saveDir = TextCtrl(master,
            size = (600, -1)
        )
        if saveDirVal:
            self.saveDir.SetValue(saveDirVal)
        saveDirSizer.Add(StaticText(master, label = "Save directory"), 0,
            EXPAND
        )
        saveDirSizer.Add(self.saveDir, 1, EXPAND)
        selectSaveDir = Button(master, -1, "Select")
        saveDirSizer.Add(selectSaveDir, 0, EXPAND)
        master.Bind(EVT_BUTTON, self.OnSelectSaveDir, selectSaveDir)
        openSave = Button(master, label = "Open")
        saveDirSizer.Add(openSave, 0, EXPAND)
        master.Bind(EVT_BUTTON, self.OnOpenSaveDir, openSave)

        backupDirSizer = BoxSizer(HORIZONTAL)
        self.backupDir = TextCtrl(master)
        if backupDirVal:
            self.backupDir.SetValue(backupDirVal)
        backupDirSizer.Add(StaticText(master, label = "Backup directory"), 0,
            EXPAND
        )
        backupDirSizer.Add(self.backupDir, 1, EXPAND)
        selectBackupDir = Button(master, -1, "Select")
        master.Bind(EVT_BUTTON, self.OnSelectBackupDir, selectBackupDir)
        backupDirSizer.Add(selectBackupDir, 0, EXPAND)
        openBackup = Button(master, label = "Open")
        backupDirSizer.Add(openBackup, 0, EXPAND)
        master.Bind(EVT_BUTTON, self.OnOpenBackupDir, openBackup)

        filterOutSizer = BoxSizer(HORIZONTAL)
        filterOutSizer.Add(StaticText(master, label = "Filter Out"), 0, EXPAND)
        self.filterOut = TextCtrl(master)
        filterOutSizer.Add(self.filterOut, 1, EXPAND)

        self.cbMonitor = CheckBox(master, label = "Monitor")
        master.Bind(EVT_CHECKBOX, self.OnMonitor, self.cbMonitor)

        self.sizer = sizer = BoxSizer(VERTICAL)
        sizer.Add(saveDirSizer, 0, EXPAND)
        sizer.Add(backupDirSizer, 0, EXPAND)
        sizer.Add(filterOutSizer, 0, EXPAND)
        sizer.Add(self.cbMonitor, 0, EXPAND)

        self.settingsWidgets = [
            selectSaveDir,
            self.saveDir,
            self.backupDir,
            selectBackupDir,
            self.filterOut
        ]

    def OpenDir(self, path):
        if exists(path):
            open_directory_in_explorer(path)

    def OnOpenSaveDir(self, _):
        self.OpenDir(self.saveDir.GetValue())

    def OnOpenBackupDir(self, _):
        self.OpenDir(self.backupDir.GetValue())

    def OnSelectSaveDir(self, _):
        if not hasattr(self, "dlgSaveDir"):
            self.dlgSaveDir = DirDialog(self.master,
                "Choose directory of save data",
                "", DD_DEFAULT_STYLE | DD_DIR_MUST_EXIST
            )

        cur = self.saveDir.GetValue()
        if cur:
            self.dlgSaveDir.SetPath(cur)

        if self.dlgSaveDir.ShowModal() == ID_OK:
            self.saveDir.SetValue(self.dlgSaveDir.GetPath())

    def OnSelectBackupDir(self, _):
        if not hasattr(self, "dlgBackupDir"):
            self.dlgBackupDir = DirDialog(self.master,
                "Choose directory for backup",
                "", DD_DEFAULT_STYLE | DD_DIR_MUST_EXIST
            )

        cur = self.backupDir.GetValue()
        if cur:
            self.dlgBackupDir.SetPath(cur)

        if self.dlgBackupDir.ShowModal() == ID_OK:
            self.backupDir.SetValue(self.dlgBackupDir.GetPath())

    def EnableSettings(self):
        for w in self.settingsWidgets:
            w.Enable(True)

    def DisableSettings(self):
        for w in self.settingsWidgets:
            w.Enable(False)

    def OnMonitor(self, _):
        root = self.saveDir.GetValue()
        backup = self.backupDir.GetValue()
        root2threads = self.master.root2threads

        # See: http://timgolden.me.uk/python/win32_how_do_i/watch_directory_for_changes.html
        if self.cbMonitor.IsChecked():
            self.DisableSettings()

            if not root:
                dlg = MessageDialog(self.master, "Pleas select save directory",
                    "Error"
                )
                dlg.ShowModal()
                dlg.Destroy()
                self.cbMonitor.SetValue(False)
                self.EnableSettings()
                return
            if not backup:
                dlg = MessageDialog(self.master,
                    "Pleas select backup directory",
                    "Error"
                )
                dlg.ShowModal()
                dlg.Destroy()
                self.cbMonitor.SetValue(False)
                self.EnableSettings()
                return
            if root in root2threads:
                return # already monitored

            filterOutRe = None
            filterOut = self.filterOut.GetValue()
            if filterOut:
                try:
                    filterOutRe = compile(filterOut)
                except:
                    if filterOut:
                        dlg = MessageDialog(self.master,
                                "Incorrect filter expression"
                                " (use Python's re syntax)\n" + format_exc() +
                                "\nContinue without filter?",
                            "Filter Out Error",
                            YES_NO
                        )
                        res = dlg.ShowModal()
                        dlg.Destroy()
                        if res == ID_NO:
                            self.cbMonitor.SetValue(False)
                            self.EnableSettings()
                            return

            mt = MonitorThread(root, lambda : root2threads.pop(root))
            bt = BackUpThread(root, backup, mt.changes, filterOutRe)
            root2threads[root] = (mt, bt)
            mt.start()
            bt.start()
        else:
            self.EnableSettings()

            if root in root2threads:
                for t in root2threads[root]:
                    t.exit_request = True

    @property
    def saveData(self):
        return (
            self.saveDir.GetValue(),
            self.backupDir.GetValue(),
            self.filterOut.GetValue(),
        )


class SaveMonitor(Frame):

    def __init__(self):
        super(SaveMonitor, self).__init__(None,
            title = "Game Save Monitor"
        )

        menuBar = MenuBar()

        aboutMenu = Menu()
        aboutItem = aboutMenu.Append(ID_ABOUT,
            "&About", "Information about this program"
        )
        self.Bind(EVT_MENU, self.OnAbout, aboutItem)
        menuBar.Append(aboutMenu, "&About")

        self.SetMenuBar(menuBar)

        self.root2threads = {}
        self.settings = []

        self.mainSizer = mainSizer = BoxSizer(VERTICAL)

        mainSizer.SetSizeHints(self)
        self.SetSizer(mainSizer)

        self.Bind(EVT_CLOSE, self.OnClose, self)

    def add_settings(self, saveDirVal, backupDirVal, filterOutVal = None):
        settings = SaveSettings(self,
            saveDirVal = saveDirVal,
            backupDirVal = backupDirVal
        )
        if filterOutVal is not None:
            settings.filterOut.SetValue(filterOutVal)
        self.settings.append(settings)
        self.mainSizer.Add(settings.sizer, 0, EXPAND)
        self.mainSizer.SetSizeHints(self)

    def OnClose(self, e):
        for threads in list(self.root2threads.values()):
            for t in threads:
                t.exit_request = True

        self.saveData = [s.saveData for s in self.settings]
        e.Skip()

    def OnAbout(self, _):
        dlg = MessageDialog(self, "Monitors save directory and backs up"
                " changes to backup directory. Backup directory is under Git"
                " version control system.\n"
                "\n"
                "Author(s):\n"
                "Vasiliy (real) Efimov\n",
            "About")
        dlg.ShowModal()
        dlg.Destroy()


def main():
    app = App()

    with Settings() as s:
        mon = SaveMonitor()
        for save in s.saves:
            mon.add_settings(*save)

        mon.Show(True)

        app.MainLoop()

        s.saves[:] = mon.saveData


if __name__ == "__main__":
    main()
