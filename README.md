# Save Monitor

![Main window screenshot](/docs/main_window.png)

The utility is designed to watch a directory with save data of a game and
automatically back the data up.

## Recent updates

### 2021.12.31 (devel)

* Remove files and directories in backup if they have been removed from
  save directory while the tool was not launched.

### 2021.04.10 (devel)

* Horizontal scrolling for version selector.
* Optimize version graph drawing.
* Drag version graph while right mouse button is held.

### 2020.09.19 (devel)

* Ask user when save directory content differs from backup directory content
  (draft feature).

### 2020.09.19

* error messages instead of some faults

## Description

Save data files are backed-up with a delay after changes have been detected.
I.e. it may happen many times during game runtime.

Backed-up data is under [Git](https://git-scm.com/about) Version Control
System.
So, the last version of backed files is always available in backup
directory.

Use "Switch" button to revert to a previous version of the save data.
Current version will also be accessible for switch back.
Files in the save directory are automatically replaced.

![Switch window screenshot](/docs/switch_window.png)

Also, there are [many](https://git-scm.com/downloads/guis) free/open source
tools to access previous file versions
(ex. [TortoiseGit](https://tortoisegit.org/download) for Windows).
**Warning**: never use another tools while save directory is _being monitored._
It may result in failures with unpredictable consequences.

It's Windows-only (for now).

The utility's settings are stored in user directory in file
`savemon.settings.py`.
E.g.: `C:\Users\Vasya\savemon.settings.py`.

## How to (Windows)

1. Install Python. At least version 
[3.7](https://www.python.org/downloads/windows/)
is recommended.

2. Launch `cmd.exe` (`Win` + `R` shortcut) install dependencies of the
utility:
```
C:\Python37\python.exe -m pip install wxPython pywin32 gitpython
```

3. Install [Git](https://git-scm.com/download/win) because it seems to
be required by `pywin32` and, likely, by you to access old versions of
backed up files.

4. Launch `savemon.py`.
Python normally integrates to file explorer during installation to
allow launching scripts on double click.

## History

### 2019.08.08

* Buttons to open both save & backup directories in the file explorer.
* Support multiple backup settings (`File` -> `Add`).

### 2019.08.10

* fixup failure when a directory is created at runtime

### 2019.08.31

* switching between backup versions

### 2020.02.08

* overwriting files in save directory with current backup version,
  useful after game installation
* correctly handle non-existing files and directories in save directory
* workaround internal Git error with `index.lock` file

### 2020.06.12

* hide/show backup settings

### 2020.06.22

* fixup failure when a game creates nesting directories in save directory
  during monitoring
* debug logging (turned off by default)

### 2020.06.25

* fixup the failure on absence a folder inside backup folder at monitoring
  startup

### 2020.08.09

* fixup "File" -> "Add"
