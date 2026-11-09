"""Owner edition (Excel + MySQL) and User edition (this PC only)."""
import json
import sys

import fsr_edition as e


def write(folder, value):
    target = folder / "data" / "json" / e.FILE_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"edition": value}), encoding="utf-8")


def test_source_run_is_owner_unless_asked(tmp_path):
    assert e.read_edition(tmp_path, environ={}) == e.OWNER
    assert e.read_edition(tmp_path, environ={"FSR_EDITION": "user"}) == e.USER
    assert e.read_edition(tmp_path, environ={"FSR_EDITION": "nonsense"}) == e.OWNER


def test_bundled_file_decides(tmp_path):
    write(tmp_path, "user")
    assert e.read_edition(tmp_path, environ={}) == e.USER
    write(tmp_path, "OWNER")
    assert e.read_edition(tmp_path, environ={}) == e.OWNER


def test_installed_program_trusts_only_its_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    # no file: the safer User edition, and the environment cannot switch it
    assert e.read_edition(tmp_path, environ={"FSR_EDITION": "owner"}) == e.USER
    write(tmp_path, "owner")
    assert e.read_edition(tmp_path, environ={"FSR_EDITION": "user"}) == e.OWNER
    (tmp_path / "data" / "json" / e.FILE_NAME).write_text("{broken",
                                                          encoding="utf-8")
    assert e.read_edition(tmp_path, environ={}) == e.USER
