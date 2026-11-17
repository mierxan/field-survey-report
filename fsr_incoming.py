"""A hand-over file opened from Windows (double-click, Open with).

The installer tells Windows that a file ending in .fsrhandover opens this
program, which then starts with the file's path as its argument. The file
is put in this PC's incoming folder; the program window picks it up once
the inspector has signed in and shows the usual Receive Hand-over question.

When the program is already open (with the same data), the new start only
leaves the file in that folder and closes: the open window receives it.
Nothing is ever brought in without the inspector's Yes.

No widgets here (tests/test_incoming.py).
"""
import hashlib
import os
import shutil
import sys
import time
from pathlib import Path

SUFFIX = ".fsrhandover"         # hand-over files from now on
OLD_SUFFIX = ".json"            # the files made before
SUFFIXES = (SUFFIX, OLD_SUFFIX)
FOLDER_NAME = "Incoming hand-overs"
MAX_BYTES = 20 * 1024 * 1024    # as fsr_handover.MAX_BYTES
_WAITING = ".waiting"           # a file being copied in: not taken yet

_lock = {"handle": None}


def handover_argument(argv):
    """The hand-over file the program was started with, or None.

    Only an existing file ending in .fsrhandover (or the older .json) counts;
    other arguments (the GO_BACK_TO_WORKBOOK.bat options, test runner
    arguments) are left alone."""
    for argument in argv:
        if not argument or argument.startswith("-"):
            continue
        path = Path(argument)
        if path.suffix.lower() in SUFFIXES and path.is_file():
            return path
    return None


def lock_name(folder):
    """One name per incoming folder, so the real data and Demo Mode (or a
    test copy with data of its own) are separate programs."""
    key = os.path.normcase(os.path.abspath(str(folder)))
    return "Local\\FieldSurveyReport-" + hashlib.sha256(
        key.encode("utf-8")).hexdigest()[:24]


def already_running(folder):
    """True when this program is already open with this incoming folder.

    Holds a Windows named mutex for as long as the program runs (it goes
    when the program closes, also after a crash). Elsewhere: False."""
    if sys.platform != "win32":
        return False
    import ctypes
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    if _lock["handle"]:             # started again in the same process (tests)
        kernel.CloseHandle(ctypes.c_void_p(_lock["handle"]))
        _lock["handle"] = None
    handle = kernel.CreateMutexW(None, False, lock_name(folder))
    error = kernel.GetLastError()
    if not handle:
        return False
    _lock["handle"] = handle
    return error == 183             # ERROR_ALREADY_EXISTS


def allow_other_window_to_front():
    """Lets the open program bring its window to the front for the file
    (Windows lets only the program that was just started do that)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
    except (AttributeError, OSError):
        pass


def queue(folder, source):
    """Copies the hand-over file into the incoming folder; returns the copy.

    A copy, because the file opened from an e-mail is often a temporary
    file that goes when the e-mail program closes. Raises OSError."""
    source = Path(source)
    if source.stat().st_size > MAX_BYTES:
        raise OSError("The file is too large (more than 20 MB).")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = "".join(c if c.isalnum() or c in "._-" else "_"
                   for c in source.stem)[:80] or "handover"
    name = f"{time.time_ns()}_{os.getpid()}_{stem}{source.suffix.lower()}"
    waiting = folder / (name + _WAITING)
    shutil.copyfile(source, waiting)
    target = folder / name
    os.replace(waiting, target)
    return target


def waiting_files(folder):
    """The hand-over files waiting in the incoming folder, oldest first."""
    try:
        files = [path for path in Path(folder).iterdir()
                 if path.is_file() and path.suffix.lower() in SUFFIXES]
    except OSError:
        return []
    return sorted(files, key=lambda path: path.name)


def take(folder):
    """The oldest waiting file, or None. The caller removes it with done()
    once the inspector has answered."""
    files = waiting_files(folder)
    return files[0] if files else None


def done(path):
    """Removes a file from the incoming folder (answered or unreadable).
    The inspector's own file (in the e-mail, Downloads) is not touched."""
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        # still open somewhere: renamed, so it is not offered again
        try:
            os.replace(path, str(path) + ".done")
        except OSError:
            pass
