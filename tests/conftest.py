import os
import sys
from datetime import date
from pathlib import Path

import pytest

# Secrets (the set-up record of users.json, the MySQL password) stay in
# memory: the tests never touch the Windows Credential Manager.
os.environ["FSR_SECRET_STORE"] = "memory"

# The reports databases of the tests go to a temporary folder - never to
# this PC's Local AppData (fsr_db_location).
if not os.environ.get("FSR_DATABASE_DIR"):
    import atexit
    import shutil
    import tempfile
    os.environ["FSR_DATABASE_DIR"] = tempfile.mkdtemp(
        prefix="fsr_test_databases_")
    atexit.register(shutil.rmtree, os.environ["FSR_DATABASE_DIR"], True)

# Counts skipped tests out loud; --fail-on-gui-skip (tests/skip_report.py).
pytest_plugins = ["skip_report"]

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Fixed "today" for the sample data, so every expected value is stable.
ANCHOR = date(2026, 10, 29)


@pytest.fixture(scope="session")
def sample(tmp_path_factory):
    """The full TEST data set written with the real storage code into an
    isolated temporary demo folder, loaded back as a snapshot."""
    from warehouse import sample_data, store
    folder = tmp_path_factory.mktemp("demo_data")
    path, spec = sample_data.generate(folder, anchor=ANCHOR)
    snapshot = store.load_snapshot(path, as_of=ANCHOR)
    return {"folder": folder, "path": path, "spec": spec,
            "snapshot": snapshot}
