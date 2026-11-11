"""The skip report: skipped tests are counted out loud, and a run that could
not open the program's window fails when the build asks for that."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent

PASSING = "def test_ok():\n    assert True\n"
GUI_SKIP = '''
import pytest

@pytest.fixture(scope="module")
def app():
    pytest.skip("GUI cannot start here: no display")

def test_one(app):
    pass

def test_two(app):
    pass

def test_ok():
    pass
'''
OTHER_SKIP = '''
import pytest

def test_other():
    pytest.skip("needs Linux")

def test_ok():
    pass
'''


def run(tmp_path, source, *options):
    file = tmp_path / "test_sample.py"
    file.write_text(source, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-m", "pytest", str(file), "-q", "-p", "skip_report",
         "-p", "no:cacheprovider", "--rootdir", str(tmp_path), *options],
        capture_output=True, text=True, cwd=str(tmp_path),
        env={**__import__("os").environ, "PYTHONPATH": str(TESTS)})
    return done.returncode, done.stdout + done.stderr


def test_run_without_skips_says_so(tmp_path):
    code, text = run(tmp_path, PASSING, "--fail-on-gui-skip")
    assert code == 0
    assert "SKIPPED: 0 - every selected test ran." in text


def test_gui_skip_is_listed_and_counted(tmp_path):
    code, text = run(tmp_path, GUI_SKIP)
    assert code == 0                       # without the option: only loud
    assert "SKIPPED TESTS - THESE DID NOT RUN" in text
    assert "2 test(s): GUI cannot start here: no display" in text
    assert "test_sample.py::test_one" in text
    assert "SKIPPED: 2 test(s) did not run." in text
    assert "it is not a pass" in text


def test_gui_skip_fails_the_run_when_the_build_asks(tmp_path):
    code, text = run(tmp_path, GUI_SKIP, "--fail-on-gui-skip")
    assert code == 1
    assert "FAILED: 2 test(s) could not open the program's window" in text
    assert "the screens were NOT tested" in text


def test_other_skips_are_reported_but_do_not_fail(tmp_path):
    code, text = run(tmp_path, OTHER_SKIP, "--fail-on-gui-skip")
    assert code == 0
    assert "1 test(s): needs Linux" in text
    assert "SKIPPED: 1 test(s) did not run." in text
    assert "FAILED:" not in text


def test_a_failing_test_still_fails(tmp_path):
    code, text = run(tmp_path, "def test_bad():\n    assert False\n",
                     "--fail-on-gui-skip")
    assert code == 1


def test_both_scripts_use_the_option():
    for name in ("RUN_TESTS.bat", "build_installer.bat"):
        script = (ROOT / name).read_text(encoding="utf-8")
        assert "--fail-on-gui-skip" in script, name
    assert 'pytest_plugins = ["skip_report"]' in (
        TESTS / "conftest.py").read_text(encoding="utf-8")
