"""The User (site) edition on the reports database (Phase 5): its workbook
moves in at the first start exactly like the Owner edition's, a save goes
into the database and the export, and Export Master Data still writes the
file the owner imports - also an owner still on the previous version."""
import json
import sys
import time
from datetime import date

import pytest

import fsr_import
import fsr_sqlite_store as sq
import fsr_storage
import fsr_store
from factories import report

pytestmark = pytest.mark.gui


def pump(g, until, limit=60):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        g["window"].update()
        if until():
            g["window"].update()
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    import db_mysql
    home = tmp_path_factory.mktemp("fsr_user_sqlite_home")
    book = home / "excel" / "Field_Survey_Reports.xlsx"
    book.parent.mkdir(parents=True)
    site = fsr_store.ExcelStore(book)               # saved before the update
    for number in (1, 2):
        site.write_report(report(f"FSR-STE-202611-{number:04d}", "Receiving",
                                 date(2026, 11, number + 3),
                                 so=f"SO-SITE-{number}"), False)
    saved_enabled = db_mysql.is_enabled
    saved_initials = dict(fsr_storage._control_initials)
    sys.modules.pop("fsr_edition", None)
    try:
        g, answers = h.start_app(home, {"FSR_EDITION": "user",
                                        "FSR_NO_SQLITE": "0"})
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    live = g["save_report"].__globals__
    assert pump(g, lambda: sq.is_active(book)
                and not live["db_move_state"]["running"])
    g["home"] = home
    yield g, answers
    h.stop_app(g, answers)
    import os
    os.environ.pop("FSR_EDITION", None)
    sys.modules.pop("fsr_edition", None)
    db_mysql.is_enabled = saved_enabled
    fsr_storage._control_initials.update(saved_initials)


def live(g):
    return g["save_report"].__globals__


def test_the_site_workbook_moved_in_like_the_owners(app):
    g, answers = app
    assert g["IS_OWNER_EDITION"] is False
    said = [m for kind, title, m in answers.calls
            if title == "Reports Database"]
    assert said and "2 report(s) were moved into the database" in said[0]
    store = live(g)["data_store"]()
    assert store.kind == "sqlite"
    assert [r[0] for r in store.list_reports()] == ["FSR-STE-202611-0002",
                                                    "FSR-STE-202611-0001"]
    assert g["db_mysql"].is_enabled() is False      # still no MySQL here


def test_a_site_save_and_the_file_for_the_owner(app, tmp_path):
    g, answers = app
    g["app_shell"].show("inspection")
    g["new_report"](confirm=False)
    g["choose_condition"]("Good Order")
    g["set_entry"](g["SO_number_entry"], "SO-SITE-NEW")
    g["schedule_entries"]["activity"].set("Receiving")
    g["location_combobox"].set("Site Warehouse")
    section = g["item_frames"][0]
    cols = g["ITEM_FORM_HEADERS"]
    for header, value in {"Description of Goods": "Site valve",
                          "Quantity": "2", "UOM": "PCS",
                          "Packaging": "Box"}.items():
        g["set_entry"](section.rows[0][cols.index(header)], value)
    control = g["control_entry"].get()
    assert g["save_report"]() is True
    store = live(g)["data_store"]()
    assert store.read_report(control)["general_information"][
        "so_number"] == "SO-SITE-NEW"
    book = live(g)["excel_state"]["path"]
    assert control in [r[0] for r in fsr_storage.list_saved_reports(book)]

    target = tmp_path / "FSR_Master_Data_site.json"
    dialog = g["filedialog"]
    original = dialog.asksaveasfilename
    dialog.asksaveasfilename = lambda **_: str(target)
    try:
        g["export_master_button"].invoke()
        assert pump(g, target.exists)
    finally:
        dialog.asksaveasfilename = original
    data = json.loads(target.read_text(encoding="utf-8"))
    assert sorted(r["control_no"] for r in data["reports"]) == sorted(
        ["FSR-STE-202611-0001", "FSR-STE-202611-0002", control])

    # the owner, still on the previous version (the workbook), takes it in
    owner = tmp_path / "owner" / "data.xlsx"
    owner.parent.mkdir()
    summary = fsr_import.import_master_data(
        owner, fsr_import.read_master_file(target))
    assert len(summary["added"]) == 3
    assert fsr_store.open_store(owner).kind == "excel"
    assert fsr_storage.read_report(owner, control)["general_information"][
        "so_number"] == "SO-SITE-NEW"
