"""Which edition of the program this is: the Owner app or a User (site) app.

  owner  Excel + MySQL (Workbench). Imports the Master Data files that the
         sites and the phones send, so every report ends up in one database.
  user   Excel and JSON files on this PC only, never MySQL. Exports one
         Master Data file to send to the owner.

The installer bundles data/json/edition.json ({"edition": "user"} or
{"edition": "owner"}); build_installer.bat writes it. Run from source, the
program is the Owner edition unless FSR_EDITION=user is set (for testing).
"""
import json
import os
import sys
from pathlib import Path

OWNER = "owner"
USER = "user"
EDITIONS = (OWNER, USER)
FILE_NAME = "edition.json"


def _bundle_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def read_edition(bundle_dir=None, environ=None):
    """'owner' or 'user'. An installed program trusts only its bundled file;
    a missing or unreadable file there means the safer User edition."""
    environ = os.environ if environ is None else environ
    frozen = getattr(sys, "frozen", False)
    path = Path(bundle_dir or _bundle_dir()) / "data" / "json" / FILE_NAME
    if not frozen:
        wanted = str(environ.get("FSR_EDITION", "")).strip().lower()
        if wanted in EDITIONS:
            return wanted
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("edition")
    except (OSError, ValueError, AttributeError):
        return USER if frozen else OWNER
    value = str(value or "").strip().lower()
    if value in EDITIONS:
        return value
    return USER if frozen else OWNER


EDITION = read_edition()
IS_OWNER_EDITION = EDITION == OWNER
LABEL = "Owner" if IS_OWNER_EDITION else "User"
