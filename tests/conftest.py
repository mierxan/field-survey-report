import sys
from datetime import date
from pathlib import Path

import pytest

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
