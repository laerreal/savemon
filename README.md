# Save Monitor

![Main window screenshot](/docs/main_window.png)

The utility is designed to watch a directory with save data of a game and
automatically back the data up.

## Updates

_Screenshot is outdated._

* Buttons to open both save & backup directories in the file explorer.
* Support multiple backup settings (`File` -> `Add`).

## Description

Save data files are backed-up with a delay after changes have been detected.
I.e. it may happen many times during game runtime.

Backed-up data is under [Git](https://git-scm.com/about) Version Control
System.
So, the last version of backed files is always available in backup
directory.
Also, there are [many](https://git-scm.com/downloads/guis) free/open source
tools to access previous file versions
(ex. [TortoiseGit](https://tortoisegit.org/download) for Windows)

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
