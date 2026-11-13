"""Where the reports database of a workbook lives (Phase 5).

The database is NOT next to the workbook: a SQLite database must never be in
a folder that OneDrive (or Dropbox, Google Drive, iCloud, Box) synchronises,
nor on a network drive - both can damage a database that is in use. It lives
in this Windows user's Local AppData, which none of them synchronises and
roaming profiles do not copy:

    %LOCALAPPDATA%\\FieldSurveyReport\\Databases\\<workbook name>-<code>.sqlite3

The Excel file (the export), PO_Master, Withdrawn_Item, the JSON files and
all backups stay in Documents beside the workbook, where people expect them.

One database per workbook. Which workbook a database belongs to is recorded
three times: in the database itself (meta: database_id, workbook), in
databases.json in that folder, and in the workbook - the export carries the
database's id in its document properties. So a workbook that is moved or
renamed (or chosen again with Change Excel File in its new place) finds its
database by that id; a COPY of a workbook whose original is still in its
place gets its own database.

FSR_DATABASE_DIR (the automated tests) and FSR_HOME (a sandbox: then
<FSR_HOME>\\LocalAppData\\FieldSurveyReport\\Databases) choose another folder,
so a test never touches the real one.
"""
import ctypes
import hashlib
import json
import logging
import os
import re
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

log = logging.getLogger("fsr")

APP_FOLDER = "FieldSurveyReport"
DB_FOLDER = "Databases"
INDEX_NAME = "databases.json"
DB_SUFFIX = ".sqlite3"
CUSTOM_PROPERTY = "FSR database id"

_DC = "{http://purl.org/dc/elements/1.1/}"
_CUSTOM = ("{http://schemas.openxmlformats.org/officeDocument/2006/"
           "custom-properties}")
_VT = ("{http://schemas.openxmlformats.org/officeDocument/2006/"
       "docPropsVTypes}")


# ---------- the folder ------------------------------------------------------

def database_dir(environ=None):
    environ = os.environ if environ is None else environ
    chosen = str(environ.get("FSR_DATABASE_DIR", "")).strip()
    if chosen:
        return Path(chosen)
    home = str(environ.get("FSR_HOME", "")).strip()
    if home:
        return Path(home) / "LocalAppData" / APP_FOLDER / DB_FOLDER
    local = (environ.get("LOCALAPPDATA")
             or str(Path.home() / "AppData" / "Local"))
    return Path(local) / APP_FOLDER / DB_FOLDER


def _key(path):
    """A workbook path as it is compared: full, resolved, any case."""
    try:
        path = Path(path).resolve()
    except OSError:
        path = Path(os.path.abspath(path))
    return os.path.normcase(str(path))


def code_of(excel_path):
    return hashlib.sha256(_key(excel_path).encode("utf-8")).hexdigest()[:8]


def default_db_path(excel_path):
    excel_path = Path(excel_path)
    return database_dir() / f"{excel_path.stem}-{code_of(excel_path)}" \
                            f"{DB_SUFFIX}"


def legacy_db_path(excel_path):
    """Where the database was before (next to the workbook)."""
    excel_path = Path(excel_path)
    return excel_path.with_name(excel_path.stem + DB_SUFFIX)


# ---------- the index (databases.json) --------------------------------------

def _index_path():
    return database_dir() / INDEX_NAME


def load_index():
    try:
        data = json.loads(_index_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning("%s cannot be read; the databases are found by their "
                    "own records", _index_path())
        return {}
    entries = data.get("databases") if isinstance(data, dict) else None
    return entries if isinstance(entries, dict) else {}


def _save_index(entries):
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps({"version": 1, "databases": entries},
                               indent=2), encoding="utf-8")
    os.replace(temp, path)


def register(db_path, excel_path, database_id):
    entries = load_index()
    entries[Path(db_path).name] = {
        "workbook": str(Path(excel_path).resolve()),
        "id": database_id,
        "registered": datetime.now().isoformat(timespec="seconds")}
    _save_index(entries)


def forget(db_path):
    entries = load_index()
    if entries.pop(Path(db_path).name, None) is not None:
        _save_index(entries)


def find_db(excel_path):
    """The database of this workbook, or None. Quick: the index, then the
    usual name. (A moved workbook is found by its id at start - relink.)"""
    key = _key(excel_path)
    folder = database_dir()
    for name, entry in load_index().items():
        if isinstance(entry, dict) and \
                os.path.normcase(str(entry.get("workbook", ""))) == key:
            path = folder / name
            if path.is_file():
                return path
    path = default_db_path(excel_path)
    return path if path.is_file() else None


def entry_for_id(database_id):
    """(database file, recorded workbook) of the database with this id."""
    if not database_id:
        return None
    folder = database_dir()
    for name, entry in load_index().items():
        if isinstance(entry, dict) and entry.get("id") == database_id and \
                (folder / name).is_file():
            return folder / name, Path(entry.get("workbook", ""))
    return None


def new_id():
    return uuid.uuid4().hex


# ---------- the id inside a workbook ------------------------------------------

def workbook_identity(path):
    """The database id an exported workbook carries, or None (also for a
    workbook that cannot be read)."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "docProps/custom.xml" in names:
                root = ET.fromstring(archive.read("docProps/custom.xml"))
                for prop in root.iter(_CUSTOM + "property"):
                    if prop.get("name") == CUSTOM_PROPERTY:
                        for value in prop:
                            if value.text and value.text.strip():
                                return value.text.strip()
            if "docProps/core.xml" in names:
                root = ET.fromstring(archive.read("docProps/core.xml"))
                found = root.find(_DC + "identifier")
                if found is not None and found.text and \
                        re.fullmatch(r"[0-9a-f]{32}", found.text.strip()):
                    return found.text.strip()
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError):
        return None
    return None


def stamp_identity(wb, database_id):
    """Write the id into a workbook about to be saved (both places)."""
    from openpyxl.packaging.custom import StringProperty
    wb.properties.identifier = database_id
    props = wb.custom_doc_props
    for prop in list(props.props):
        if prop.name == CUSTOM_PROPERTY:
            props.props.remove(prop)
    props.append(StringProperty(name=CUSTOM_PROPERTY, value=database_id))


# ---------- synchronised folders and network drives -------------------------

# Set by the Windows cloud-files system that OneDrive, Dropbox, Google
# Drive and iCloud use. (0x40000 "recall on open" is left out: the same bit
# means "extended attributes" on ordinary folders.)
_CLOUD_ATTRIBUTES = {0x400000: "recall on data access",
                     0x80000: "pinned", 0x100000: "unpinned"}


def _attributes(path):
    if sys.platform != "win32":
        return 0
    value = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    return 0 if value == 0xFFFFFFFF else value


def _drive_type(path):
    if sys.platform != "win32":
        return 0
    root = os.path.splitdrive(os.path.abspath(path))[0]
    if not root:
        return 0
    return ctypes.windll.kernel32.GetDriveTypeW(root + "\\")


DRIVE_REMOTE = 4


def is_network(path):
    """A network share (\\\\server\\share) or a mapped network drive."""
    text = os.path.abspath(str(path))
    if text.startswith(("\\\\?\\UNC\\", "\\\\.\\UNC\\")):
        return True
    if text.startswith(("\\\\?\\", "\\\\.\\")):
        text = text[4:]                     # a long local path
    return text.startswith("\\\\") or _drive_type(text) == DRIVE_REMOTE


def _sync_roots(environ=None):
    """[(tool, folder)] of the synchronising tools found on this PC."""
    environ = os.environ if environ is None else environ
    roots = []
    for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if environ.get(name):
            roots.append(("OneDrive", environ[name]))
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\OneDrive\Accounts") as key:
                for index in range(winreg.QueryInfoKey(key)[0]):
                    account = winreg.EnumKey(key, index)
                    try:
                        with winreg.OpenKey(key, account) as sub:
                            folder = winreg.QueryValueEx(sub, "UserFolder")[0]
                            if folder:
                                roots.append(("OneDrive", folder))
                    except OSError:
                        continue
        except OSError:
            pass
    for base in (environ.get("APPDATA"), environ.get("LOCALAPPDATA")):
        if not base:
            continue
        info = Path(base) / "Dropbox" / "info.json"
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for account in data.values() if isinstance(data, dict) else ():
            if isinstance(account, dict) and account.get("path"):
                roots.append(("Dropbox", account["path"]))
    profile = environ.get("USERPROFILE")
    if profile:
        for tool, name in (("iCloud Drive", "iCloudDrive"),
                           ("Google Drive", "Google Drive"),
                           ("Box", "Box")):
            folder = Path(profile) / name
            if folder.is_dir():
                roots.append((tool, str(folder)))
    return roots


def sync_tool(path, environ=None):
    """The name of the tool that synchronises `path` ("OneDrive", ...), or
    None. Also any folder Windows marks as a cloud-synchronised one."""
    key = _key(path)
    for tool, root in _sync_roots(environ):
        root_key = _key(root)
        if key == root_key or key.startswith(root_key.rstrip("\\/") + os.sep):
            return tool
    current = Path(os.path.abspath(str(path)))
    for folder in [current, *current.parents]:
        if not folder.exists():
            continue
        flags = _attributes(folder)
        if any(flags & bit for bit in _CLOUD_ATTRIBUTES):
            return "a cloud synchronisation service"
    return None


def folder_problem(folder, environ=None):
    """Why a database must not live in `folder` (None: it may)."""
    tool = sync_tool(folder, environ)
    if tool:
        return f"{folder} is synchronised by {tool}"
    if is_network(folder):
        return f"{folder} is on a network drive"
    return None
