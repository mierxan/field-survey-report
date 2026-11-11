"""Daily backup of a workbook.

Before the first save of each day the workbook - as it is before that save -
is copied to

    <folder of the workbook>\\Backups\\<name>_backup_<YYYYMMDD>.xlsx

The newest `keep` backups of that workbook stay (default 14, the
"backup_keep" value in settings.json; 0 turns the backup off). Older ones are
removed. Only files in that Backups folder whose name has exactly this
pattern for this workbook are ever removed.

To restore: close the program, copy the backup over the workbook (keep the
workbook's own name), start the program.

  python fsr_backup.py <workbook>       lists the backups of a workbook
"""
import logging
import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger("fsr")

FOLDER_NAME = "Backups"
DEFAULT_KEEP = 14
MAX_KEEP = 3650
SETTING = "backup_keep"


class BackupError(OSError):
    """The backup copy could not be made. The workbook is untouched."""


def keep_setting(settings):
    """How many backups to keep, from the settings dictionary. Anything
    that is not a whole number from 0 to 3650 means the default."""
    value = (settings or {}).get(SETTING, DEFAULT_KEEP)
    if isinstance(value, bool) or not isinstance(value, int) \
            or not 0 <= value <= MAX_KEEP:
        return DEFAULT_KEEP
    return value


def backup_folder(workbook):
    return Path(workbook).parent / FOLDER_NAME


def backup_path(workbook, day):
    workbook = Path(workbook)
    return backup_folder(workbook) / (
        f"{workbook.stem}_backup_{day:%Y%m%d}{workbook.suffix}")


def _pattern(workbook):
    workbook = Path(workbook)
    return re.compile(
        rf"^{re.escape(workbook.stem)}_backup_(\d{{8}})"
        rf"{re.escape(workbook.suffix)}$", re.IGNORECASE)


def list_backups(workbook):
    """[(day, path)] of this workbook's backups, newest first. Anything else
    in the folder - other workbooks' backups, folders, other files, names
    with an impossible date - is not listed (and so never removed)."""
    folder = backup_folder(workbook)
    pattern = _pattern(workbook)
    found = []
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    for entry in entries:
        match = pattern.match(entry.name)
        if not match or entry.is_symlink() or not entry.is_file():
            continue
        try:
            day = datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        found.append((day, entry))
    return sorted(found, reverse=True)


def backup_before_save(workbook, keep=DEFAULT_KEEP, today=None):
    """Call before a save. Makes today's backup when there is none yet, then
    removes this workbook's backups beyond the newest `keep`.

    Returns {"created": path or None, "removed": [paths], "kept": number}.
    Raises BackupError when the copy could not be made (nothing else has
    happened then); a backup that could not be REMOVED is only logged."""
    workbook = Path(workbook)
    today = today or date.today()
    result = {"created": None, "removed": [], "kept": 0}
    if keep <= 0 or not workbook.is_file():
        return result                   # turned off / no workbook yet

    target = backup_path(workbook, today)
    if not target.exists():
        temp = target.with_name(target.name + ".saving.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(workbook, temp)
            os.replace(temp, target)
        except OSError as error:
            raise BackupError(
                f"The backup copy {target} could not be made: {error}"
            ) from error
        finally:
            try:
                temp.unlink()
            except OSError:
                pass
        result["created"] = target

    backups = list_backups(workbook)
    for _, old in backups[keep:]:
        try:
            old.unlink()
            result["removed"].append(old)
        except OSError:
            log.exception("Old backup %s could not be removed", old)
    result["kept"] = len(backups) - len(result["removed"])
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    rows = list_backups(sys.argv[1])
    print(f"{len(rows)} backup(s) in {backup_folder(sys.argv[1])}")
    for day, path in rows:
        print(f"  {day:%d-%b-%Y}  {path.stat().st_size / 1024:8.0f} KB  "
              f"{path.name}")
