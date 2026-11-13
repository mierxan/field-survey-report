"""Build identities must differ even with the same clock reading."""
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from tools.build_version import versions


def test_two_builds_at_the_same_time_have_different_release_names():
    now = datetime(2026, 11, 14, 23, 59, 59)
    first, windows = versions(now)
    second, again = versions(now)
    assert first != second
    assert re.fullmatch(r"2026\.11\.14\.235959-[0-9a-f]{32}", first)
    assert windows == again == "2026.11.14.1439"


def test_windows_version_components_fit_the_file_format():
    _, windows = versions(datetime(2026, 12, 31, 23, 59, 59))
    parts = windows.split(".")
    assert len(parts) == 4
    assert all(part.isdecimal() and 0 <= int(part) <= 65535 for part in parts)


def test_command_outputs_the_two_batch_tokens():
    root = Path(__file__).resolve().parent.parent
    done = subprocess.run(
        [sys.executable, str(root / "tools" / "build_version.py")],
        cwd=root, capture_output=True, text=True, check=True)
    release, windows = done.stdout.split()
    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d{6}-[0-9a-f]{32}", release)
    assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+", windows)
    assert not done.stderr
