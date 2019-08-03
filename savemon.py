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
from itertools import (
    count
)


try:
    from wx import (
        EVT_SIZE,
        EVT_PAINT,
        AutoBufferedPaintDC, # is it cross-platform?
        BG_STYLE_CUSTOM,
        Dialog,
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


class Commit(object):

    cache = {}

    def __init__(self, backed):
        self.backed = backed
        self._parents = None

    @property
    def parents(self):
        ps = self._parents
        if ps is None:
            ps = []
            cache = Commit.cache
            for p in self.backed.parents:
                if p in cache:
                    pc = cache[p]
                else:
                    pc = Commit(p)
                    cache[p] = pc
                ps.append(pc)
            self._parents = ps
        return ps


class BackupManager(Dialog):

    def __init__(self, parent, backupDir):
        super(Dialog, self).__init__(parent,
            title = "Backup manager (%s)" % backupDir,
            size = (500, 500)
        )
        self.backupDir = backupDir
        self.scale, self.shift = 4, 8
        self.refresh_graph()

        self.Bind(EVT_SIZE, self.on_size)
        self.SetBackgroundStyle(BG_STYLE_CUSTOM)
        self.Bind(EVT_PAINT, self.on_paint)

    def on_size(self, event):
        event.Skip()
        self.Refresh()

    def refresh_graph(self):
        try:
            repo = Repo(self.backupDir)
        except:
            log("Cannot refresh backup")
            log(format_exc())
            return

        queue = []

        Commit.cache = {}
        self.graph = graph = {}

        for i, head in enumerate(repo.heads):
            c = Commit(head.commit)
            c._i = i
            c._j = 0
            queue.append(c)
            graph[(c._i, c._j)] = c

        self.g_height = width = i + 1

        J = list(count() for _ in range(width))

        self.lines = lines = []

        while queue:
            c = queue.pop(0)

            for p in c.parents:
                if not hasattr(p, "_i"):
                    pi, pj = c._i, next(J[c._i])
                    p._i = pi
                    p._j = pj
                    graph[(pi, pj)] = p
                    skip = False
                else:
                    skip = True

                lines.append([p._i, p._j, c._i, c._j])

                if not skip:
                    queue.append(p)

        self.g_width = max(next(j) for j in J)

        # adapt coordinates
        scale, shift = self.scale, self.shift
        for l in lines:
            l[0] += width
            l[2] += width
            for t in range(4):
                l[t] = (l[t] << scale) + shift

    def on_paint(self, _e):
        dc = AutoBufferedPaintDC(self)
        dc.Clear()

        for x1, y1, x2, y2 in self.lines:
            dc.DrawLine(x1, y1, x2, y2)
            dc.DrawCircle(x2, y2, 4)


class SaveMonitor(Frame):

    def __init__(self, saveDirVal = None, backupDirVal = None):
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

        saveDirSizer = BoxSizer(HORIZONTAL)
        self.saveDir = TextCtrl(self,
            size = (600, -1)
        )
        if saveDirVal:
            self.saveDir.SetValue(saveDirVal)
        saveDirSizer.Add(StaticText(self, label = "Save directory"), 0, EXPAND)
        saveDirSizer.Add(self.saveDir, 1, EXPAND)
        selectSaveDir = Button(self, -1, "Select")
        saveDirSizer.Add(selectSaveDir, 0, EXPAND)
        self.Bind(EVT_BUTTON, self.OnSelectSaveDir, selectSaveDir)
        openSave = Button(self, label = "Open")
        saveDirSizer.Add(openSave, 0, EXPAND)
        self.Bind(EVT_BUTTON, self.OnOpenSaveDir, openSave)


        backupDirSizer = BoxSizer(HORIZONTAL)
        self.backupDir = TextCtrl(self)
        if backupDirVal:
            self.backupDir.SetValue(backupDirVal)
        backupDirSizer.Add(StaticText(self, label = "Backup directory"), 0,
            EXPAND
        )
        backupDirSizer.Add(self.backupDir, 1, EXPAND)
        manage = Button(self, label = "Manage")
        self.Bind(EVT_BUTTON, self.OnManage, manage)
        backupDirSizer.Add(manage, 0, EXPAND)
        selectBackupDir = Button(self, -1, "Select")
        self.Bind(EVT_BUTTON, self.OnSelectBackupDir, selectBackupDir)
        backupDirSizer.Add(selectBackupDir, 0, EXPAND)
        openBackup = Button(self, label = "Open")
        backupDirSizer.Add(openBackup, 0, EXPAND)
        self.Bind(EVT_BUTTON, self.OnOpenBackupDir, openBackup)

        filterOutSizer = BoxSizer(HORIZONTAL)
        filterOutSizer.Add(StaticText(self, label = "Filter Out"), 0, EXPAND)
        self.filterOut = TextCtrl(self)
        filterOutSizer.Add(self.filterOut, 1, EXPAND)

        self.cbMonitor = CheckBox(self, label = "Monitor")
        self.root2threads = {}
        self.Bind(EVT_CHECKBOX, self.OnMonitor, self.cbMonitor)

        self.settingsWidgets = [
            selectSaveDir,
            self.saveDir,
            self.backupDir,
            manage,
            selectBackupDir,
            self.filterOut
        ]

        mainSizer = BoxSizer(VERTICAL)
        mainSizer.Add(saveDirSizer, 0, EXPAND)
        mainSizer.Add(backupDirSizer, 0, EXPAND)
        mainSizer.Add(filterOutSizer, 0, EXPAND)
        mainSizer.Add(self.cbMonitor, 0, EXPAND)
        mainSizer.SetSizeHints(self)
        self.SetSizer(mainSizer)

        self.Bind(EVT_CLOSE, self.OnClose, self)

    def OnManage(self, _):
        backupDir = self.backupDir.GetValue()
        if not isdir(backupDir):
            return
        BackupManager(self, backupDir).ShowModal()

    def OpenDir(self, path):
        if exists(path):
            open_directory_in_explorer(path)

    def OnOpenSaveDir(self, _):
        self.OpenDir(self.saveDir.GetValue())

    def OnOpenBackupDir(self, _):
        self.OpenDir(self.backupDir.GetValue())

    def OnSelectSaveDir(self, _):
        if not hasattr(self, "dlgSaveDir"):
            self.dlgSaveDir = DirDialog(self, "Choose directory of save data",
                "", DD_DEFAULT_STYLE | DD_DIR_MUST_EXIST
            )

        cur = self.saveDir.GetValue()
        if cur:
            self.dlgSaveDir.SetPath(cur)

        if self.dlgSaveDir.ShowModal() == ID_OK:
            self.saveDir.SetValue(self.dlgSaveDir.GetPath())

    def OnSelectBackupDir(self, _):
        if not hasattr(self, "dlgBackupDir"):
            self.dlgBackupDir = DirDialog(self, "Choose directory for backup",
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

        # See: http://timgolden.me.uk/python/win32_how_do_i/watch_directory_for_changes.html
        if self.cbMonitor.IsChecked():
            self.DisableSettings()

            if not root:
                dlg = MessageDialog(self, "Pleas select save directory",
                    "Error"
                )
                dlg.ShowModal()
                dlg.Destroy()
                self.cbMonitor.SetValue(False)
                self.EnableSettings()
                return
            if not backup:
                dlg = MessageDialog(self, "Pleas select backup directory",
                    "Error"
                )
                dlg.ShowModal()
                dlg.Destroy()
                self.cbMonitor.SetValue(False)
                self.EnableSettings()
                return
            if root in self.root2threads:
                return # already monitored

            filterOutRe = None
            filterOut = self.filterOut.GetValue()
            if filterOut:
                try:
                    filterOutRe = compile(filterOut)
                except:
                    if filterOut:
                        dlg = MessageDialog(self, "Incorrect filter expression"
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

            mt = MonitorThread(root, lambda : self.root2threads.pop(root))
            bt = BackUpThread(root, backup, mt.changes, filterOutRe)
            self.root2threads[root] = (mt, bt)
            mt.start()
            bt.start()
        else:
            self.EnableSettings()

            if root in self.root2threads:
                for t in self.root2threads[root]:
                    t.exit_request = True

    def OnClose(self, e):
        for threads in list(self.root2threads.values()):
            for t in threads:
                t.exit_request = True

        self.saveData = (
            self.saveDir.GetValue(),
            self.backupDir.GetValue(),
            self.filterOut.GetValue(),
        )
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
        mons = []
        for save in s.saves:
            mon = SaveMonitor(saveDirVal = save[0], backupDirVal = save[1])
            mon.filterOut.SetValue(save[2])
            mons.append(mon)

        if not s.saves:
            mons.append(SaveMonitor())

        [m.Show(True) for m in mons]

        app.MainLoop()
        del s.saves[:]
        for mon in mons:
            s.saves.append(mon.saveData)

if __name__ == "__main__":
    main()
