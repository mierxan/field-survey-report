"""A skipped test must not look like a passed one.

Loaded by conftest.py. At the end of every run it prints how many tests
were SKIPPED and why. With --fail-on-gui-skip (used by RUN_TESTS.bat and
build_installer.bat) the run FAILS when a test skipped because the program's
window could not be opened: those tests exist to prove the screens work, so
"could not look" is not a result a build may rest on.
"""
import pytest

GUI_REASON = "GUI cannot start"


def pytest_addoption(parser):
    parser.addoption(
        "--fail-on-gui-skip", action="store_true", default=False,
        help="fail the run when a test is skipped because the GUI could "
             "not be started")


def pytest_configure(config):
    config._fsr_skips = []


def pytest_runtest_logreport(report):
    if not report.skipped:
        return
    reason = report.longrepr
    if isinstance(reason, tuple) and len(reason) == 3:
        reason = reason[2]
    reason = str(reason)
    if reason.startswith("Skipped: "):
        reason = reason[len("Skipped: "):]
    _skips_of(report).append((report.nodeid, reason))


def _skips_of(report):
    # the config is not on the report; the list is shared through pytest
    return _STATE["skips"]


_STATE = {"skips": []}


def pytest_sessionstart(session):
    _STATE["skips"] = session.config._fsr_skips


def gui_skips(skips):
    return [item for item in skips if GUI_REASON in item[1]]


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    skips = config._fsr_skips
    if not skips:
        terminalreporter.write_line("SKIPPED: 0 - every selected test ran.")
        return
    terminalreporter.section("SKIPPED TESTS - THESE DID NOT RUN", sep="!")
    by_reason = {}
    for nodeid, reason in skips:
        by_reason.setdefault(reason, []).append(nodeid)
    for reason, nodes in by_reason.items():
        terminalreporter.write_line(f"{len(nodes)} test(s): {reason}")
        for nodeid in nodes:
            terminalreporter.write_line(f"    {nodeid}")
    terminalreporter.write_line(
        f"SKIPPED: {len(skips)} test(s) did not run. A skipped test proves "
        "nothing - it is not a pass.")
    blocked = gui_skips(skips)
    if blocked and config.getoption("--fail-on-gui-skip"):
        terminalreporter.write_line(
            f"FAILED: {len(blocked)} test(s) could not open the program's "
            "window, so the screens were NOT tested. Run the tests again; "
            "if it keeps happening, close other programs and check the "
            "display.", red=True, bold=True)


def pytest_sessionfinish(session, exitstatus):
    if session.config.getoption("--fail-on-gui-skip") and gui_skips(
            session.config._fsr_skips):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
