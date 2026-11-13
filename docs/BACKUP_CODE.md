# Backing up and restoring the program's code

The code lives only on this PC (the copy on GitHub was deleted). Back it up
with **BACKUP_CODE.bat** in the project folder.

## Making a backup

1. Double-click `BACKUP_CODE.bat` (or run `BACKUP_CODE.bat D:\CodeBackups`).
2. The first time, pick the folder for the backups - best on another drive
   or a USB stick. The folder is remembered for the next time.
3. If some changes are not committed yet, it lists them and asks: they are
   **not** in a backup, only committed work is.
4. It ends with "Done and checked: ...\FSR_code_2026-11-14_101500.bundle".

What it does:

* **One file per backup**, named with the date and time
  (`FSR_code_YYYY-MM-DD_HHMMSS.bundle`): every branch and every tag, with the
  whole history.
* **Checked before it counts.** The file is written as `....bundle.partial`.
  It gets its real name only after three checks: `git bundle verify` passes,
  every branch and tag is in it at the same commit as in the project, and a
  trial copy made from it passes `git fsck`. If a check fails, the partial
  file is removed and the message says "THE BACKUP WAS NOT MADE".
* **The newest 10 are kept.** Older files named `FSR_code_<date>_<time>.bundle`
  in that folder are removed; nothing else in the folder is touched.
* **No data in it.** A bundle holds only what is committed. Reports,
  accounts, settings, MySQL settings, passwords, databases and the `.venv`
  are never committed (`.gitignore`), and the backup stops if any such file
  appears in any commit of any branch.

The program's DATA (reports, accounts, settings) is backed up separately -
see [DATA_SAFETY.md](DATA_SAFETY.md).

## Restoring from a backup

You need **Git for Windows** (git-scm.com) on the PC.

### A. The whole project, into a new folder (new PC, or a lost folder)

1. Open **Git Bash** (Start menu).
2. Make the project folder from the backup (use your file names):

       git clone "/d/CodeBackups/FSR_code_2026-11-14_101500.bundle" "/d/Build Build Build/PythonProject"

   The branch that was open at the time of the backup is checked out.
3. Make every branch of the backup a local branch again:

       cd "/d/Build Build Build/PythonProject"
       for b in $(git branch -r | grep -v HEAD | sed 's#  origin/##'); do git branch --track "$b" "origin/$b" 2>/dev/null; done
       git remote remove origin
       git branch

   The last command lists the branches (main, improvements/phase-1-security,
   ... improvements/phase-5-sqlite).
4. Double-click `SETUP_NEW_PC.bat` in that folder: it makes the `.venv` and
   installs the Python packages.
5. Run `RUN_TESTS.bat` once: every test should pass.

### B. One branch only, into the existing project

    cd "/d/Build Build Build/PythonProject"
    git fetch "/d/CodeBackups/FSR_code_2026-11-14_101500.bundle" improvements/phase-5-sqlite:restored-phase-5

The branch comes back as `restored-phase-5`, next to the one you have; look
at it before you use it.

### Checking a backup without restoring it

    git bundle verify "/d/CodeBackups/FSR_code_2026-11-14_101500.bundle"
    git bundle list-heads "/d/CodeBackups/FSR_code_2026-11-14_101500.bundle"

The first says "... is okay"; the second lists every branch with its commit.
