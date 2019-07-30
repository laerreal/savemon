# Save Monitor

![Main window screenshot](/docs/main_window.png)

The utility is designed to watch a directory with save data of a game and
automatically back the data up.
The files are backed-up with a delay after changes have been detected.
I.e. it may happen many times during game runtime.

Backed-up data is under [Git](https://git-scm.com/about) Version Control
System.
So, the last version of backed files is always available in backup
directory.
Also, there are [many](https://git-scm.com/downloads/guis) free/open source
tools to access previous file versions
(ex. [TortoiseGit](https://tortoisegit.org/download) for Windows)

It's Windows-only (for now).
