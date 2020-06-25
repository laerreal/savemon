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
    time,
    sleep
)
from re import (
    compile
)
import sys
from subprocess import (
    Popen
)
from datetime import (
    datetime
)


try:
    from wx import (
        ITEM_CHECK,
        ID_FILE,
        ID_ANY,
        PostEvent,
        EVT_SCROLL,
        EVT_ENTER_WINDOW,
        ScrollBar,
        SB_VERTICAL,
        Control,
        EVT_LEFT_UP,
        EVT_LEFT_DOWN,
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
        ID_CANCEL,
        ID_YES,
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
    from wx.lib.newevent import (
        NewEvent
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

class lazy(tuple):

    def __new__(type, getter):
        ret = tuple.__new__(type, (getter,))
        return ret

    def __get__(self, obj, type = None):
        getter = self[0]
        val = getter(obj)
        obj.__dict__[getter.__name__] = val
        return val


class NullStream(object):

    write = lambda *_: None
    flush = lambda *_: None

nullStream = NullStream()

logLock = Lock()
globalLogStream = nullStream


def cloneStream(stream):

    class StreamClone(object):

        def write(self, *a, **kw):
            with logLock:
                globalLogStream.write(*a, **kw)
                stream.write(*a, **kw)

        def flush(self):
            globalLogStream.flush()
            stream.flush()

    return StreamClone()

sys.stderr = cloneStream(sys.stderr)
sys.stdout = cloneStream(sys.stdout)


class Settings(object):

    def __init__(self):
        self.path = expanduser(join("~", "savemon.settings.py"))
        self.saves = []
        self.hidden = set()
        self.logging = False
        self.logFile = expanduser(join("~", "savemon.log"))

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
                "hidden",
                "logging",
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
        print("Start monitoring of '%s'" % root)
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
                print(changed,
                    ACTIONS.get(action, "[unknown 0x%X]" % action)
                )

        print("Stop monitoring of '%s'" % root)
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

    def commit(self, attempts = 5, period = 5):
        try:
            self._do_commit()
        except:
            print("Checking for index.lock")
            lock = join(self.backupDir, ".git", "index.lock")
            # XXX: If lock file exists then another Git process can operate.
            # And removing of the lock is likely a very bad idea.
            # However, if it still exists after some time then it likely
            # has been forgotten (there is known bug).
            # Also, user should not work with the repo while monitoring is
            # active.
            if exists(lock):
                while attempts > 0:
                    print("Waiting for %d sec. (%d)" % (period, attempts))
                    sleep(period)
                    if not exists(lock):
                        break
                    attempts -= 1
                else:
                    print("Removing " + lock)
                    remove(lock)

                self._do_commit()
            else:
                # some other error
                raise

    def _do_commit(self):
        repo, doCommit = self.repo, self.doCommit
        if doCommit:
            print("Committing changes")
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
            print("Committing finished")

    def check(self, relN):
        fullN = join(self.saveDir, relN)
        fullBackN = join(self.backupDir, relN)

        if isfile(fullN):
            if exists(fullBackN):
                with open(fullN, "rb") as f0:
                    with open(fullBackN, "rb") as f1:
                        doChanged = f0.read() != f1.read()
                if doChanged:
                    print("Replacing %s with %s" % (fullBackN, fullN))
                    copyfile(fullN, fullBackN)
                    self.doCommit.append(("add", relN))
            else:
                fullBackNDir = dirname(fullBackN)
                if not exists(fullBackNDir):
                    print("Creating directories '%s'" % fullBackNDir)
                    makedirs(fullBackNDir)
                print("Copying '%s' to '%s'" % (fullN, fullBackN))
                copyfile(fullN, fullBackN)
                self.doCommit.append(("add", relN))
        else:
            if isfile(fullBackN):
                print("Removing '%s'" % fullBackN)
                self.doCommit.append(("remove", relN))

    def run(self):
        backupDir = self.backupDir
        saveDir = self.saveDir
        filterOut = self.filterOut

        try:
            self.repo = Repo(backupDir)
        except InvalidGitRepositoryError:
            print("Initializing Git repository in '%s'" % backupDir)
            self.repo = Repo.init(backupDir)

        print("Backing up current content of '%s'" % saveDir)
        stack = [""]
        while stack:
            cur = stack.pop()
            curSave = join(saveDir, cur)
            curBackup = join(backupDir, cur)
            toCheck = set(listdir(curSave))
            if isdir(curBackup):
                toCheck.update(listdir(curBackup))
            for n in toCheck:
                relN = join(cur, n)

                if filterOut and filterOut.match(relN):
                    print("Ignoring '%s' (Filter Out)" % relN)
                    continue

                fullN = join(saveDir, relN)

                if isdir(fullN):
                    # Note, directories are created by `check` if needed
                    stack.append(relN)
                else:
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

                    print("Checking\n    %s" % "\n    ".join(
                        c[1] for c in toCheck)
                    )
                    for c in toCheck:
                        cur = c[1]
                        fullN = join(self.saveDir, cur)
                        if isdir(fullN):
                            fullBackN = join(self.backupDir, cur)
                            if not exists(fullBackN):
                                print("Creating directory '%s'" % fullBackN)
                                mkdir(fullBackN)
                        else:
                            self.check(cur)

                    changes.clear()
                    self.commit()
                continue

            if filterOut and filterOut.match(change[1]):
                print("Ignoring '%s' (Filter Out)" % change[1])
                continue
            else:
                changes.add(change)
            lastChange = time()

        print("Stop backing up of '%s'" % saveDir)


class GitGraph(object):

    def __init__(self):
        self.cache = {}
        self.roots = None

    def __getitem__(self, gitpython_commit):
        return self.cache[gitpython_commit]

    def __setitem__(self, gitpython_commit, commit):
        self.cache[gitpython_commit] = commit

    def get(self, *a, **kw):
        return self.cache.get(*a, **kw)

    def iter_commits(self):
        visited = set()
        stack = list(self.roots)
        while stack:
            c = stack.pop(0)
            if c in visited:
                continue
            visited.add(c)
            yield c
            stack.extend(c.children)

class Commit(object):

    graph = GitGraph()

    def __new__(type, backed, *a, **kw):
        ret = type.graph.get(backed, None)
        if ret is None:
            ret = super().__new__(type)
            ret.backed = backed
            ret.children = []
            type.graph[backed] = ret
        return ret

    @lazy
    def parents(self):
        ps = []
        for p in self.backed.parents:
            pc = Commit(p)
            ps.append(pc)
            pc.children.append(self)
        return tuple(ps)

    @lazy
    def committed_time_str(self):
        return commit_time_str(self.backed)

    @lazy
    def label(self):
        return self.committed_time_str + " | " + self.backed.message


def commit_time_str(commit):
    return commit.committed_datetime.strftime("%Y.%m.%d %H:%M:%S %z")


def build_commit_graph(*heads):
    stack = list(heads)
    roots = []
    visited = set()
    while stack:
        c = stack.pop()
        if c in visited:
            continue
        visited.add(c)
        ps = c.parents
        if not ps:
            roots.append(c)
            continue
        for p in ps:
            p.children.append(c)
            stack.append(p)

    Commit.graph.roots = tuple(roots)

backup_re = compile("backup_([0-9]+)")


class Strip(object):

    def __init__(self, c):
        self.commits = [c]
        start_j = c._j
        self.start_j = start_j
        self.end_j = start_j

    def bind(self, c):
        self.commits.append(c)
        self.end_j = max(c._j, self.end_j)


CommitSelectedEvent, EVT_COMMIT_SELECTED = NewEvent()

class GitSelector(Control):

    def __init__(self, parent, repo_dir, **kw):
        super(GitSelector, self).__init__(parent, **kw)

        self._scrollbar = None
        self.height = 300

        self.repo_dir = repo_dir

        self.scale, self.xshift, self.yshift = 4, 8, -8
        self.half_step = 1 << (self.scale - 1)
        self.text_offset_x = 8

        self.read_repo()

        self.Bind(EVT_MOTION, self._on_mouse_motion)
        self._hl = None

        self.Bind(EVT_LEFT_DOWN, self._on_lmb_down)
        self.Bind(EVT_LEFT_UP, self._on_lmb_up)
        self._lmb = None

        self.Bind(EVT_SIZE, self._on_size)

        self.SetBackgroundStyle(BG_STYLE_CUSTOM)
        self.Bind(EVT_PAINT, self._on_paint)

        self._scroll = 0
        self.scroll = self.current._y - self.half_step
        self.Bind(EVT_MOUSEWHEEL, self._on_mouse_wheel)

        self.Bind(EVT_ENTER_WINDOW, self._on_enter_window)

    def read_repo(self):
        try:
            repo = Repo(self.repo_dir)
        except:
            print("Cannot refresh backup")
            print(format_exc())
            return

        self.repo = repo

        heads = []

        Commit.graph = graph = GitGraph()

        for head in repo.heads:
            c = Commit(head.commit)
            if c in heads:
                continue
            heads.append(c)

        build_commit_graph(*heads)

        # layout commits
        stripes = []
        for j, c in enumerate(graph.iter_commits()):
            c._j = j
            parents = c.parents

            for p in parents:
                try:
                    s = p._s
                except AttributeError:
                    # p's strip is already stolen by another child
                    continue
                else:
                    del p._s
                    s.bind(c)
                    c._s = s
                    break
            else:
                # No free strip or c is root
                c._s = s = Strip(c)
                stripes.append(s)

        for i, s in enumerate(stripes):
            for c in s.commits:
                c._i = i

        # self.g_width = i + 1

        # assign coordinates
        self.index = index = {}
        max_j = len(graph.cache)
        scale, xshift, yshift = self.scale, self.xshift, self.yshift
        self.lines = lines = []
        for c in graph.iter_commits():
            c._x = (c._i << scale) + xshift
            # graph grows to the top
            inv_j = max_j - c._j
            index[inv_j] = c
            c._y = (inv_j << scale) + yshift
            for p in c.parents:
                lines.append([p._x, p._y, c._x, c._y])

        self.max_y = (max_j << scale) + yshift

        self.current = graph[repo.active_branch.commit]

    @property
    def max_scroll(self):
        return self.max_y - self.height + self.half_step

    @property
    def scroll(self):
        return self._scroll

    @scroll.setter
    def scroll(self, v):
        scroll = min(max(v, 0), self.max_scroll)
        if scroll == self._scroll:
            return
        self._scroll = scroll
        if self._scrollbar:
            self._scrollbar.SetThumbPosition(scroll)
        self.Refresh()

    def _on_mouse_wheel(self, e):
        self.scroll -= e.GetWheelRotation()

    @property
    def scrollbar(self):
        return self._scrollbar

    @scrollbar.setter
    def scrollbar(self, sb):
        prev = self._scrollbar
        if sb is prev:
            return
        if prev is not None:
            prev.Unbind(EVT_SCROLL, handler = self._on_scroll)
        self._scrollbar = sb
        if sb is None:
            return
        h = self.height
        sb.SetScrollbar(self._scroll, h, self.max_scroll + h, h)
        sb.Bind(EVT_SCROLL, self._on_scroll)

    def _on_scroll(self, e):
        self.scroll = e.GetPosition()

    def _on_size(self, event):
        event.Skip()
        h = self.GetClientSize()[1]
        self.height = h

        # update scrolling
        if self._scrollbar:
            self._scrollbar.SetScrollbar(self._scroll, h, self.max_scroll + h,
                h
            )
        self.scroll = self._scroll

        self.Refresh()

    def _on_mouse_motion(self, e):
        if self._lmb is None:
            x, y = e.GetPosition()
            self._highlight(x, y)

    def _highlight(self, x, y):
        mid = self.half_step
        # i = (x + mid - self.xshift) >> self.scale
        # i = min(i, self.g_width - 1)
        j = (y + mid + self.scroll - self.yshift) >> self.scale
        try:
            c = self.index[j] # (i, j)]
        except KeyError:
            self.highlighted = None
        else:
            self.highlighted = c

    @property
    def highlighted(self):
        return self._hl

    @highlighted.setter
    def highlighted(self, v):
        if v is self._hl:
            return
        self._hl = v
        self.Refresh()

    def _on_lmb_down(self, e):
        self._lmb = e.GetPosition()
        e.Skip()

    def _on_lmb_up(self, e):
        lmb = self._lmb
        if lmb is None:
            return
        self._lmb = None

        hl = self._hl

        if hl is self.current:
            return

        x0, y0 = lmb

        x, y = e.GetPosition()
        self._highlight(x, y)

        if hl is None:
            return

        if max(abs(x0 - x), abs(y0 - y)) > self.half_step:
            return

        PostEvent(self, CommitSelectedEvent(commit = hl))

    def _on_paint(self, _e):
        scroll = -self.scroll
        text_offset_x = self.text_offset_x

        dc = AutoBufferedPaintDC(self)
        dc.Clear()

        text_shift = -self.half_step

        hl, cur = self._hl, self.current

        for x1, y1, x2, y2 in self.lines:
            dc.DrawLine(x1, y1 + scroll, x2, y2 + scroll)

        br = dc.GetBackground()
        prev_c = br.GetColour()
        revert_color = False

        for c in Commit.graph.iter_commits():
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

            x = c._x
            y = c._y

            dc.DrawCircle(x, y + scroll, 4)
            dc.DrawText(c.label, x + text_offset_x, y + scroll + text_shift)

            if revert_color:
                br.SetColour(prev_c)
                dc.SetBrush(br)
                revert_color = False

    def _on_enter_window(self, _):
        self.SetFocus()


class BackupSelector(Dialog):

    def __init__(self, parent, backupDir):
        super(Dialog, self).__init__(parent,
            style = DEFAULT_DIALOG_STYLE | RESIZE_BORDER
        )
        self.SetMinSize((300, 300))

        sizer = BoxSizer(HORIZONTAL)

        selector = GitSelector(self, backupDir, size = (700, 500))
        sizer.Add(selector, 1, EXPAND)

        scrollbar = ScrollBar(self, style = SB_VERTICAL)
        selector.scrollbar = scrollbar
        sizer.Add(scrollbar, 0, EXPAND)

        sizer.SetSizeHints(self)
        self.SetSizer(sizer)

        selector.Bind(EVT_COMMIT_SELECTED, self._on_commit_selected)

    def _on_commit_selected(self, e):
        c = e.commit

        dlg = MessageDialog(self,
            "Do you want to switch to that version?\n\n" +
            "SHA1: %s\n\n%s\n\n" % (c.backed.hexsha, c.label) +
            "Files in both save and backup directories will be overwritten!",
            "Confirmation is required",
            YES_NO
        )
        switch = dlg.ShowModal() == ID_YES
        dlg.Destroy()
        if not switch:
            return

        self.target = c.backed
        self.EndModal(ID_OK)


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
        hide = Button(master, label = "Hide")
        saveDirSizer.Add(hide, 0, EXPAND)
        master.Bind(EVT_BUTTON, self._on_hide, hide)

        backupDirSizer = BoxSizer(HORIZONTAL)
        self.backupDir = TextCtrl(master)
        if backupDirVal:
            self.backupDir.SetValue(backupDirVal)
        backupDirSizer.Add(StaticText(master, label = "Backup directory"), 0,
            EXPAND
        )
        backupDirSizer.Add(self.backupDir, 1, EXPAND)
        switch = Button(master, label = "Switch")
        master.Bind(EVT_BUTTON, self._on_switch, switch)
        backupDirSizer.Add(switch, 0, EXPAND)
        override = Button(master, label = "Overwrite")
        master.Bind(EVT_BUTTON, self._on_overwrite, override)
        backupDirSizer.Add(override, 0, EXPAND)
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
            switch,
            selectBackupDir,
            self.filterOut
        ]

    def _on_overwrite(self, _):
        backupDir = self.backupDir.GetValue()
        savePath = self.saveDir.GetValue()
        if not (isdir(backupDir) and bool(savePath)):
            with MessageDialog(self.master, "Set paths up!", "Error") as dlg:
                dlg.ShowModal()
            return

        repo = Repo(backupDir)
        if repo.is_dirty():
            raise RuntimeError("Backup repository is dirty")

        c = repo.active_branch.commit
        label = commit_time_str(c) + " | " + c.message

        dlg = MessageDialog(self.master,
            "Do you want to overwrite save data with current version?\n\n" +
            "SHA1: %s\n\n%s\n\n" % (c.hexsha, label) +
            "Files in save directory will be overwritten!",
            "Confirmation is required",
            YES_NO
        )
        switch = dlg.ShowModal() == ID_YES
        dlg.Destroy()
        if not switch:
            return

        self._switch_to(c)

    def _on_switch(self, _):
        backupDir = self.backupDir.GetValue()
        if not isdir(backupDir):
            return
        with BackupSelector(self.master, backupDir) as dlg:
            res = dlg.ShowModal()
            if res != ID_OK:
                return
            target = dlg.target

        try:
            self._switch_to(target)
        except BaseException as e:
            with MessageDialog(self.master, str(e), "Error") as dlg:
                dlg.ShowModal()

    def _switch_to(self, target):
        repo = Repo(self.backupDir.GetValue())

        if repo.is_dirty():
            raise RuntimeError("Backup repository is dirty")

        active = repo.active_branch
        cur = active.commit

        if cur.hexsha != target.hexsha:
            # select name for backup branch
            backups = []
            need_head = True
            for h in repo.heads:
                mi = backup_re.match(h.name)
                if mi:
                    backups.append(int(mi.group(1), base = 10))
                    if h.commit.hexsha == cur.hexsha:
                        need_head = False

            if backups:
                n = max(backups) + 1
            else:
                n = 0

            # TODO: do not set branch if commits are reachable (other
            # branch exists)

            # setup backup branch and checkout new version
            if need_head:
                back_head = repo.create_head("backup_%u" % n, cur)

            try:
                active.commit = target
                try:
                    active.checkout(True)
                except:
                    active.commit = cur
                    raise
            except:
                if need_head:
                    repo.delete_head(back_head)
                raise

        save_path = self.saveDir.GetValue()

        # remove files of current
        stack = [cur.tree]
        while stack:
            node = stack.pop()
            for b in node.blobs:
                b_path = join(save_path, b.path)
                if exists(b_path):
                    remove(b_path)
            stack.extend(node.trees)

        # copy files from target
        stack = [target.tree]
        while stack:
            node = stack.pop()
            for b in node.blobs:
                b_path = join(save_path, b.path)
                makedirs(dirname(b_path), exist_ok = True)
                with open(b_path, "wb+") as f:
                    b.stream_data(f)
            stack.extend(node.trees)

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

    def _on_hide(self, __):
        self.master._hide_save_settings(self)

    @property
    def saveData(self):
        return (
            self.saveDir.GetValue(),
            self.backupDir.GetValue(),
            self.filterOut.GetValue(),
        )


SHOW_TITLE_LIMIT = 100

class SaveMonitor(Frame):

    def __init__(self,
        logging = False,
        logFile = None,
    ):
        super(SaveMonitor, self).__init__(None,
            title = "Game Save Monitor"
        )

        menuBar = MenuBar()

        fileMenu = Menu()
        addItem = fileMenu.Append(ID_NEW, "&Add",
            "Add save data backup settings"
        )
        menuBar.Append(fileMenu, "&File")

        self.showMenu = Menu()
        menuBar.Append(self.showMenu, "&Show")

        debugMenu = Menu()
        menuBar.Append(debugMenu, "&Debug")

        self._logging = None
        self.loggingItem = debugMenu.Append(ID_FILE,
            "&Logging",
            "Save program output to file",
            ITEM_CHECK
        )
        self.Bind(EVT_MENU, self._on_log, self.loggingItem)

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

        self._logFile = logFile
        if logFile is None:
            stream = NullStream()
        else:
            try:
                stream = open(logFile, "a+")
            except:
                print_exc()
                print("Cannot log to %s" % logFile)
                stream = NullStream()

        self._logStream = stream

        self.logging = logging

    @property
    def logFile(self):
        return self._logFile

    @property
    def logging(self):
        return self._logging

    @logging.setter
    def logging(self, logging):
        if self._logging is logging:
            return
        self._logging = logging
        self.loggingItem.Check(logging)

        global globalLogStream
        if logging:
            globalLogStream = self._logStream
        else:
            globalLogStream = nullStream

    def _on_log(self, __):
        self.logging = self.loggingItem.IsChecked()

    def _on_add(self, _):
        self._add_settings(SaveSettings(self))

    def _hide_save_settings(self, save_settings):
        self.mainSizer.Hide(save_settings.sizer)
        self.mainSizer.SetSizeHints(self)
        self._add_show_item(save_settings)

    def _add_show_item(self, save_settings):
        save_dir = save_settings.saveDir.GetValue()

        if not save_dir:
            save_dir = "[not configured]"

        if len(save_dir) > SHOW_TITLE_LIMIT:
            save_short = (
                save_dir[:SHOW_TITLE_LIMIT//2 - 3]
              + "..."
              + save_dir[SHOW_TITLE_LIMIT//2:]
            )
        else:
            save_short = save_dir

        showItem = self.showMenu.Append(ID_ANY, save_short, save_dir)
        self.Bind(EVT_MENU,
            lambda __: self._on_show_save_settings(showItem, save_settings),
            showItem
        )

    def _on_show_save_settings(self, item, save_settings):
        self.showMenu.Remove(item.GetId())
        self._show_save_settings(save_settings)

    def _show_save_settings(self, save_settings):
        self.mainSizer.Show(save_settings.sizer)
        self.mainSizer.SetSizeHints(self)

    def add_settings(self, saveDirVal, backupDirVal,
        filterOutVal = None,
        hidden = False
    ):
        settings = SaveSettings(self,
            saveDirVal = saveDirVal,
            backupDirVal = backupDirVal
        )
        if filterOutVal is not None:
            settings.filterOut.SetValue(filterOutVal)
        self._add_settings(settings, hidden)

    def _add_settings(self, settings, hidden):
        self.settings.append(settings)
        self.mainSizer.Add(settings.sizer, 0, EXPAND)
        if hidden:
            self.mainSizer.Hide(settings.sizer)
            self._add_show_item(settings)
        self.mainSizer.SetSizeHints(self)

    def _on_close(self, e):
        for threads in list(self.root2threads.values()):
            for t in threads:
                t.exit_request = True

        self.saveData = [s.saveData for s in self.settings]
        self.hidden = set(
            i for i, s in enumerate(self.settings)
                if not self.mainSizer.IsShown(s.sizer)
        )
        e.Skip()

        global globalLogStream
        globalLogStream = nullStream
        self._logStream.close()

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
        mon = SaveMonitor(
            logging = s.logging,
            logFile = s.logFile,
        )
        for i, save in enumerate(s.saves):
            mon.add_settings(*save,
                hidden = i in s.hidden,
            )

        mon.Show(True)

        app.MainLoop()

        s.saves[:] = mon.saveData
        s.hidden = mon.hidden
        s.logging = mon.logging
        s.logFile = mon.logFile


if __name__ == "__main__":
    main()
