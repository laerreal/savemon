from os import (
    makedirs
)
from os.path import (
    dirname,
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
from datetime import (
    datetime
)


try:
    from wx import (
        EVT_MOTION,
        DEFAULT_DIALOG_STYLE,
        RESIZE_BORDER,
        EVT_MOUSEWHEEL,
        EVT_SIZE,
        EVT_PAINT,
        AutoBufferedPaintDC, # is it cross-platform?
        BG_STYLE_CUSTOM,
        Dialog,
        ID_NEW,
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


class lazy(tuple):

    def __new__(type, getter):
        ret = tuple.__new__(type, (getter,))
        return ret

    def __get__(self, obj, type = None):
        getter = self[0]
        val = getter(obj)
        obj.__dict__[getter.__name__] = val
        return val

"""
class Test(object):

    @lazy
    def test(self):
        return 1

t = Test()
print(t.test)
print(t.test)
print(t.test)
"""

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
                    # ensure a directory are always precede its files
                    toCheck = sorted(changes, key = lambda c : len(c[1]))

                    log("Checking\n    %s" % "\n    ".join(
                        c[1] for c in toCheck)
                    )
                    for c in toCheck:
                        cur = c[1]
                        fullN = join(self.saveDir, cur)
                        if isdir(fullN):
                            fullBackN = join(self.backupDir, cur)
                            if not exists(fullBackN):
                                log("Creating directory '%s'" % fullBackN)
                                mkdir(fullBackN)
                        else:
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

    def __new__(type, backed, *a, **kw):
        ret = type.cache.get(backed, None)
        if ret is None:
            ret = super().__new__(type)
            ret.backed = backed
            ret._parents = None
            type.cache[backed] = ret
        return ret

    @lazy
    def parents(self):
        ps = self._parents
        if ps is None:
            ps = []
            for p in self.backed.parents:
                pc = Commit(p)
                ps.append(pc)
            self._parents = ps
        return ps

    @lazy
    def committed_time_str(self):
        return self.backed.committed_datetime.strftime("%Y.%m.%d %H:%M:%S %z")

    @lazy
    def label(self):
        return self.committed_time_str + " | " + self.backed.message


class BackupManager(Dialog):

    def __init__(self, parent, backupDir):
        super(Dialog, self).__init__(parent,
            size = (700, 500),
            style = DEFAULT_DIALOG_STYLE | RESIZE_BORDER
        )
        self.SetMinSize((300, 300))

        self.backupDir = backupDir
        self.scale, self.shift = 4, 8
        self.text_offset_x = 8
        self.refresh_graph()

        self.Bind(EVT_SIZE, self._on_size)
        self.SetBackgroundStyle(BG_STYLE_CUSTOM)
        self.Bind(EVT_PAINT, self._on_paint)

        self.Bind(EVT_MOUSEWHEEL, self._on_mouse_wheel)

        self.Bind(EVT_MOTION, self._on_mouse_motion)

        self.scroll = 0

        self._hl = None

    @property
    def highlighted(self):
        return self._hl

    @highlighted.setter
    def highlighted(self, v):
        if v is self._hl:
            return
        self._hl = v
        self.Refresh()

    def _on_mouse_motion(self, e):
        x, y = e.GetPosition()
        mid = 1 << (self.scale - 1)
        i = (x + mid - self.shift) >> self.scale
        i = min(i, self.g_width - 1)
        j = (y + mid - self.scroll - self.shift) >> self.scale
        try:
            c = self.graph[(i, j)]
        except KeyError:
            self.highlighted = None
        else:
            self.highlighted = c

    def _on_mouse_wheel(self, e):
        r = e.GetWheelRotation()
        self.scroll = max(
            min(self.scroll + r, 0),
            -self.max_scroll + self.height - self.shift
        )
        self.Refresh()

    def _on_size(self, event):
        self.height = self.GetClientSize()[1]
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

        Commit.cache = cache = {}
        self.graph = graph = {}

        i = -1 # empty repo
        for i, head in enumerate(repo.heads):
            c = Commit(head.commit)
            c._i = i
            c._j = i # 0
            queue.append(c)
            graph[(c._i, c._j)] = c

        self.g_width = i + 1

        self.lines = lines = []

        # J = list(count(1) for _ in range(width)
        J = count(self.g_width)

        while queue:
            c = queue.pop(0)

            parents = c.parents

            if parents:
                for p in c.parents:
                    if not hasattr(p, "_i"):
                        pi, pj = c._i, next(J) # next(J[c._i])
                        p._i = pi
                        p._j = pj
                        graph[(pi, pj)] = p
                        skip = False
                    else:
                        skip = True

                    lines.append([p._i, p._j, c._i, c._j, c])

                    if not skip:
                        queue.append(p)
            else: # root
                lines.append([c._i, c._j, c._i, c._j, c])

        # adapt coordinates
        scale, shift = self.scale, self.shift
        max_scroll = 0
        for l in lines:
            for t in range(4):
                l[t] = (l[t] << scale) + shift

            if max_scroll < l[1]:
                max_scroll = l[1]

        self.max_scroll = max_scroll

        self.current = cache[repo.head.commit]

    def _on_paint(self, _e):
        scroll = self.scroll
        text_offset_x = self.text_offset_x

        dc = AutoBufferedPaintDC(self)
        dc.Clear()

        text_shift = -(1 << (self.scale - 1))

        hl, cur = self._hl, self.current

        br = dc.GetBackground()
        prev_c = br.GetColour()
        revert_color = False

        for x1, y1, x2, y2, c in self.lines:
            while True:
                if c is cur:
                    br.SetColour((0, 255, 0, 255))
                elif c is hl:
                    br.SetColour((255, 0, 0, 255))
                else:
                    break
                dc.SetBrush(br)
                revert_color = True
                break

            dc.DrawLine(x1, y1 + scroll, x2, y2 + scroll)
            dc.DrawCircle(x2, y2 + scroll, 4)
            # XXX: do something with overlapping
            dc.DrawText(c.label, x1 + text_offset_x, y2 + scroll + text_shift)

            if revert_color:
                br.SetColour(prev_c)
                dc.SetBrush(br)
                revert_color = False

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
        master.Bind(EVT_BUTTON, self._on_select_save_dir, selectSaveDir)
        openSave = Button(master, label = "Open")
        saveDirSizer.Add(openSave, 0, EXPAND)
        master.Bind(EVT_BUTTON, self._on_open_save_dir, openSave)

        backupDirSizer = BoxSizer(HORIZONTAL)
        self.backupDir = TextCtrl(master)
        if backupDirVal:
            self.backupDir.SetValue(backupDirVal)
        backupDirSizer.Add(StaticText(master, label = "Backup directory"), 0,
            EXPAND
        )
        backupDirSizer.Add(self.backupDir, 1, EXPAND)
        manage = Button(master, label = "Manage")
        master.Bind(EVT_BUTTON, self._on_manage, manage)
        backupDirSizer.Add(manage, 0, EXPAND)
        selectBackupDir = Button(master, -1, "Select")
        master.Bind(EVT_BUTTON, self._on_select_backup_dir, selectBackupDir)
        backupDirSizer.Add(selectBackupDir, 0, EXPAND)
        openBackup = Button(master, label = "Open")
        backupDirSizer.Add(openBackup, 0, EXPAND)
        master.Bind(EVT_BUTTON, self._on_open_backup_dir, openBackup)

        filterOutSizer = BoxSizer(HORIZONTAL)
        filterOutSizer.Add(StaticText(master, label = "Filter Out"), 0, EXPAND)
        self.filterOut = TextCtrl(master)
        filterOutSizer.Add(self.filterOut, 1, EXPAND)

        self.cbMonitor = CheckBox(master, label = "Monitor")
        master.Bind(EVT_CHECKBOX, self._on_monitor, self.cbMonitor)

        self.sizer = sizer = BoxSizer(VERTICAL)
        sizer.Add(saveDirSizer, 0, EXPAND)
        sizer.Add(backupDirSizer, 0, EXPAND)
        sizer.Add(filterOutSizer, 0, EXPAND)
        sizer.Add(self.cbMonitor, 0, EXPAND)

        self.settingsWidgets = [
            selectSaveDir,
            self.saveDir,
            self.backupDir,
            manage,
            selectBackupDir,
            self.filterOut
        ]

    def _on_manage(self, _):
        backupDir = self.backupDir.GetValue()
        if not isdir(backupDir):
            return
        BackupManager(self.master, backupDir).ShowModal()

    def _open_dir(self, path):
        if exists(path):
            open_directory_in_explorer(path)

    def _on_open_save_dir(self, _):
        self._open_dir(self.saveDir.GetValue())

    def _on_open_backup_dir(self, _):
        self._open_dir(self.backupDir.GetValue())

    def _on_select_save_dir(self, _):
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

    def _on_select_backup_dir(self, _):
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

    def _enable_settings(self):
        for w in self.settingsWidgets:
            w.Enable(True)

    def _disable_settings(self):
        for w in self.settingsWidgets:
            w.Enable(False)

    def _on_monitor(self, _):
        root = self.saveDir.GetValue()
        backup = self.backupDir.GetValue()
        root2threads = self.master.root2threads

        # See: http://timgolden.me.uk/python/win32_how_do_i/watch_directory_for_changes.html
        if self.cbMonitor.IsChecked():
            self._disable_settings()

            if not root:
                dlg = MessageDialog(self.master, "Pleas select save directory",
                    "Error"
                )
                dlg.ShowModal()
                dlg.Destroy()
                self.cbMonitor.SetValue(False)
                self._enable_settings()
                return
            if not exists(root):
                dlg = MessageDialog(self.master,
                    "No such directory '%s'" % root,
                    "Error"
                )
                dlg.ShowModal()
                dlg.Destroy()
                self.cbMonitor.SetValue(False)
                self._enable_settings()
                return
            if not backup:
                dlg = MessageDialog(self.master,
                    "Pleas select backup directory",
                    "Error"
                )
                dlg.ShowModal()
                dlg.Destroy()
                self.cbMonitor.SetValue(False)
                self._enable_settings()
                return
            if root in root2threads:
                return # already monitored

            if not exists(backup):
                dlg = MessageDialog(self.master,
                    "Directory '%s' does not exist. Create?" % backup,
                    "Create backup directory",
                    YES_NO
                )
                res = dlg.ShowModal()
                dlg.Destroy()
                if not res:
                    self.cbMonitor.SetValue(False)
                    self._enable_settings()
                    return

                makedirs(backup)

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
                            self._enable_settings()
                            return

            mt = MonitorThread(root, lambda : root2threads.pop(root))
            bt = BackUpThread(root, backup, mt.changes, filterOutRe)
            root2threads[root] = (mt, bt)
            mt.start()
            bt.start()
        else:
            self._enable_settings()

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

        fileMenu = Menu()
        addItem = fileMenu.Append(ID_NEW, "&Add",
            "Add save data backup settings"
        )
        self.Bind(EVT_MENU, self._on_add, addItem)
        menuBar.Append(fileMenu, "&File")

        aboutMenu = Menu()
        aboutItem = aboutMenu.Append(ID_ABOUT,
            "&About", "Information about this program"
        )
        self.Bind(EVT_MENU, self._on_about, aboutItem)
        menuBar.Append(aboutMenu, "&About")

        self.SetMenuBar(menuBar)

        self.root2threads = {}
        self.settings = []

        self.mainSizer = mainSizer = BoxSizer(VERTICAL)

        mainSizer.SetSizeHints(self)
        self.SetSizer(mainSizer)

        self.Bind(EVT_CLOSE, self._on_close, self)

    def _on_add(self, _):
        self._add_settings(SaveSettings(self))

    def add_settings(self, saveDirVal, backupDirVal, filterOutVal = None):
        settings = SaveSettings(self,
            saveDirVal = saveDirVal,
            backupDirVal = backupDirVal
        )
        if filterOutVal is not None:
            settings.filterOut.SetValue(filterOutVal)
        self._add_settings(settings)

    def _add_settings(self, settings):
        self.settings.append(settings)
        self.mainSizer.Add(settings.sizer, 0, EXPAND)
        self.mainSizer.SetSizeHints(self)

    def _on_close(self, e):
        for threads in list(self.root2threads.values()):
            for t in threads:
                t.exit_request = True

        self.saveData = [s.saveData for s in self.settings]
        e.Skip()

    def _on_about(self, _):
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
