"""A hand-over file opened from Windows (fsr_incoming). Invented files only."""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import fsr_incoming as incoming

ROOT = Path(__file__).resolve().parents[1]


def test_the_opened_file_is_found_among_the_arguments(tmp_path):
    new = tmp_path / "FSR_Handover_X.fsrhandover"
    old = tmp_path / "FSR_Handover_X.json"
    other = tmp_path / "notes.txt"
    for path in (new, old, other):
        path.write_text("{}", encoding="utf-8")
    assert incoming.handover_argument([str(new)]) == new
    assert incoming.handover_argument([str(old)]) == old
    assert incoming.handover_argument(
        ["--report", str(other), str(new)]) == new
    assert incoming.handover_argument([str(other)]) is None
    assert incoming.handover_argument(
        [str(tmp_path / "gone.fsrhandover")]) is None
    assert incoming.handover_argument(["-q", "tests/test_x.py"]) is None
    assert incoming.handover_argument([]) is None


def test_a_file_waits_until_it_is_answered(tmp_path):
    source = tmp_path / "mail" / "FSR Handover (1).fsrhandover"
    source.parent.mkdir()
    source.write_text('{"format": "x"}', encoding="utf-8")
    folder = tmp_path / "incoming"

    first = incoming.queue(folder, source)
    second = incoming.queue(folder, source)
    assert first.read_text(encoding="utf-8") == '{"format": "x"}'
    assert first.suffix == ".fsrhandover" and " " not in first.name
    assert incoming.waiting_files(folder) == [first, second]

    assert incoming.take(folder) == first
    incoming.done(first)
    assert incoming.take(folder) == second
    incoming.done(second)
    incoming.done(second)                   # already gone: no error
    assert incoming.take(folder) is None
    assert source.exists()                  # the inspector's file stays


def test_a_half_copied_file_is_not_taken(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "1_2_x.fsrhandover.waiting").write_text("{", encoding="utf-8")
    assert incoming.take(folder) is None
    assert incoming.waiting_files(tmp_path / "missing") == []


def test_a_very_large_file_is_refused(tmp_path, monkeypatch):
    source = tmp_path / "big.fsrhandover"
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(incoming, "MAX_BYTES", 1)
    with pytest.raises(OSError, match="too large"):
        incoming.queue(tmp_path / "incoming", source)


def test_each_data_folder_has_its_own_program(tmp_path):
    real = incoming.lock_name(tmp_path / "real")
    assert real == incoming.lock_name(tmp_path / "real")
    assert real != incoming.lock_name(tmp_path / "demo")
    assert real.startswith("Local\\FieldSurveyReport-")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex")
def test_a_second_start_sees_the_open_program(tmp_path):
    folder = tmp_path / "incoming"
    assert incoming.already_running(folder) is False      # this test: open
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        import fsr_incoming
        print(fsr_incoming.already_running({str(folder)!r}),
              fsr_incoming.already_running({str(tmp_path / "other")!r}))
    """)
    shown = subprocess.run([sys.executable, "-c", script], check=True,
                           capture_output=True, text=True).stdout.split()
    assert shown == ["True", "False"]
