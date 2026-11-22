"""A PC that starts with no reports: the Dashboard shows the "No saved
inspection reports yet" notice; once reports are there, the notice is gone
and leaves no blank band above the page (Tk keeps an emptied frame at its
last size, so the notice's holder must be taken out of the layout)."""
import time
from pathlib import Path

import pytest

from conftest import ANCHOR
from warehouse import sample_data as sd

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_empty_home")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


def wait_until(g, condition, timeout=30):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        g["window"].update()
        time.sleep(0.05)
    return condition()


def test_the_no_reports_notice_leaves_no_gap(app):
    g, answers = app
    shell = g["app_shell"]
    shell.show("dashboard")
    page = shell.pages["dashboard"]
    holder = page.state_holder
    assert wait_until(g, lambda: holder.winfo_children())
    assert holder.grid_info()                   # the notice is shown
    assert not page.main.grid_info()

    path = Path(g["excel_state"]["path"])
    sd.generate(path.parent, anchor=ANCHOR, workbook_name=path.name)
    page.reload()
    assert wait_until(g, lambda: page.snapshot is not None
                      and page.snapshot.reports and page.built)
    g["window"].update()
    assert not holder.winfo_children()
    assert not holder.grid_info()               # out of the layout: no gap
    assert page.main.grid_info()
    assert not [c for c in answers.calls if c[0] == "showerror"]
