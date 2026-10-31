"""The Windows program against a real running API. Needs these, else it is skipped:

  FSR_TEST_API_URL     http://127.0.0.1:8765 (a backend on a TEST database)
  FSR_TEST_OWNER       initials of an owner account
  FSR_TEST_INSPECTOR   initials of an inspector account
  FSR_TEST_PASSWORD    the password of both

Nothing here touches the real data: the program runs in a temporary folder.
"""
import json
import os
import time
import uuid
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook

import app_auth
import fsr_api
import fsr_storage

URL = os.environ.get("FSR_TEST_API_URL")
OWNER = os.environ.get("FSR_TEST_OWNER")
INSPECTOR = os.environ.get("FSR_TEST_INSPECTOR")
PASSWORD = os.environ.get("FSR_TEST_PASSWORD")
pytestmark = pytest.mark.skipif(not URL, reason="FSR_TEST_API_URL is not set")


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "api_config.json"
    path.write_text(json.dumps({"enabled": True, "base_url": URL}))
    monkeypatch.setattr(fsr_api, "CONFIG_FILE", path)
    fsr_api._report_meta.clear()
    fsr_api._pending_uuid.clear()
    fsr_api._master_snapshot.clear()
    return path


def sign_in(initials):
    return fsr_api.ApiUserStore(app_auth.AuthError).sign_in(initials, PASSWORD)


def form_data(so="SO-API", label="FSR-209901-0001"):
    return {
        "control_no": label, "cargo_condition": "Good Order", "item_form": "Default",
        "goods_types": {"new": True},
        "general_information": {"so_number": so, "inspection_date": "25-Oct-2026", "consignee": "EDC",
                                "supplier": "ABB"},
        "inspection_schedule": {"activity": "Receiving"},
        "transport_details": {}, "documents_used": {},
        "declared_goods": [{"description": "Valve", "quantity": "2", "packaging": "Box"}],
        "other_important_remarks": [], "findings_and_remarks": [],
        "item_lists": [{"name": "Item List 1", "rows": [
            {"Description of Goods": "Valve", "Quantity": "12", "UOM": "PCS",
             "Receiving Ref": f"RCV-{label}-1-01"}]}],
        "other_item_forms": {}, "incident_reports": [],
    }


def test_https_is_required_for_remote_addresses(config):
    config.write_text(json.dumps({"base_url": "http://example.com"}))
    with pytest.raises(fsr_api.ApiError, match="https"):
        fsr_api.base_url()


def test_sign_in_and_wrong_password(config):
    assert sign_in(OWNER)["role"] == "owner"
    assert sign_in(INSPECTOR)["role"] == "user"
    with pytest.raises(app_auth.AuthError, match="Incorrect"):
        fsr_api.ApiUserStore(app_auth.AuthError).sign_in(INSPECTOR, "wrong-password")
    assert fsr_api.test_connection()[0] is True


def test_master_list_add_read_deactivate_between_users(config):
    name = f"Supplier {uuid.uuid4().hex[:8]}"
    sign_in(OWNER)
    lists = fsr_api.refresh_master_lists({"supplier_list": []})
    lists["supplier_list"].append(name)
    fsr_api.save_master_lists(lists)

    sign_in(INSPECTOR)
    theirs = fsr_api.refresh_master_lists({"supplier_list": []})
    assert name in theirs["supplier_list"]
    # an inspector may not deactivate: the server refuses
    theirs["supplier_list"].remove(name)
    with pytest.raises(fsr_api.ApiError) as refused:
        fsr_api.save_master_lists(theirs)
    assert refused.value.status == 403

    sign_in(OWNER)
    lists = fsr_api.refresh_master_lists({"supplier_list": []})
    lists["supplier_list"].remove(name)
    fsr_api.save_master_lists(lists)
    assert name not in fsr_api.refresh_master_lists({"supplier_list": []})["supplier_list"]


def test_refresh_changes_lists_in_place(config):
    sign_in(OWNER)
    combo_list = ["stale"]
    data = {"hauler_list": combo_list}
    fsr_api.refresh_master_lists(data)
    assert data["hauler_list"] is combo_list and "stale" not in combo_list


def test_create_edit_conflict_and_permissions(config):
    sign_in(INSPECTOR)
    data = form_data()
    saved = fsr_api.save_document(data, editing=False)
    control = saved["control_no"]
    assert control.startswith(f"FSR-{date.today():%Y%m}-") and saved["version"] == 1
    assert saved["item_lists"][0]["rows"][0]["Receiving Ref"] == f"RCV-{control}-1-01"

    edited = {**saved, "findings_and_remarks": ["Edited by inspector"]}
    assert fsr_api.save_document(edited, editing=True)["version"] == 2

    # the owner edits meanwhile; the inspector's stale copy must not overwrite
    sign_in(OWNER)
    owners = fsr_api.load_report(control)
    assert owners["findings_and_remarks"] == ["Edited by inspector"]
    fsr_api.save_document({**owners, "findings_and_remarks": ["Edited by owner"]}, editing=True)
    fsr_api._report_meta[control]["version"] = 1
    with pytest.raises(fsr_api.VersionConflict) as conflict:
        fsr_api.save_document({**owners, "findings_and_remarks": ["stale"]}, editing=True)
    assert conflict.value.server_report["findings_and_remarks"] == ["Edited by owner"]
    fsr_api.accept_server_version(control, conflict.value.server_report["version"])
    final = fsr_api.save_document({**owners, "findings_and_remarks": ["kept"]}, editing=True)
    assert final["findings_and_remarks"] == ["kept"] and final["version"] == 4


def test_inspector_cannot_edit_another_users_report(config):
    sign_in(OWNER)
    saved = fsr_api.save_document(form_data(label="FSR-209901-0002"), editing=False)
    sign_in(INSPECTOR)
    report = fsr_api.load_report(saved["control_no"])
    assert report["can_edit"] is False
    with pytest.raises(fsr_api.ApiError) as refused:
        fsr_api.save_document(report, editing=True)
    assert refused.value.status == 403


def test_retried_save_of_a_new_report_is_one_report(config, monkeypatch):
    sign_in(INSPECTOR)
    data = form_data(so=f"SO-RETRY-{uuid.uuid4().hex[:6]}", label="FSR-209901-0003")
    first = fsr_api.save_document(data, editing=False)
    # the answer was lost: same form, same uuid
    fsr_api._pending_uuid[data["control_no"]] = first["uuid"]
    second = fsr_api.save_document(data, editing=False)
    assert second["control_no"] == first["control_no"]
    assert [r[0] for r in fsr_api.list_reports() if r[1] == data["general_information"]["so_number"]] == \
        [first["control_no"]]


def test_reads_used_by_the_program(config):
    sign_in(OWNER)
    so = f"SO-READ-{uuid.uuid4().hex[:6]}"
    saved = fsr_api.save_document(form_data(so=so, label="FSR-209901-0004"), editing=False)
    row = next(r for r in fsr_api.list_reports() if r[0] == saved["control_no"])
    assert row[1:4] == (so, "25-Oct-2026", "EDC")
    assert fsr_api.search_index()[saved["control_no"]]["so"] == [so]
    summary = fsr_api.weekly_summary(date(2026, 10, 25), date(2026, 10, 25))
    line = next(r for r in summary if r[0] == so)
    assert len(line) == 28 and (line[20], line[21]) == ("12", "PCS")
    assert any(r["control_no"] == saved["control_no"] for r in fsr_api.load_all_reports())


def test_expired_access_token_is_renewed(config):
    sign_in(OWNER)
    fsr_api._tokens["access"] = "expired"
    assert fsr_api.list_reports() is not None
    assert fsr_api._tokens["access"] != "expired"


def test_offline_gives_a_clear_error(config):
    sign_in(OWNER)
    config.write_text(json.dumps({"base_url": "http://127.0.0.1:9"}))
    with pytest.raises(fsr_api.ApiError) as offline:
        fsr_api.list_reports()
    assert offline.value.offline and "cannot be reached" in str(offline.value)
    assert fsr_api.test_connection()[0] is False


# ---------- the real program ----------

@pytest.fixture
def program(tmp_path, monkeypatch):
    import gui_harness as h
    (tmp_path / "api_config.json").write_text(json.dumps({"enabled": True, "base_url": URL}))
    (tmp_path / "master_list.json").write_text(json.dumps({key: [] for key in fsr_api.LIST_SLUGS}))
    fsr_api.CONFIG_FILE = tmp_path / "api_config.json"
    sign_in(OWNER)
    try:
        g, answers = h.start_app(tmp_path)
    except Exception as error:
        pytest.skip(f"GUI cannot start here: {error}")
    assert g["API_MODE"] is True
    yield g, answers
    h.stop_app(g, answers)


def fill(g, so):
    g["new_report"](confirm=False)
    g["choose_condition"]("Good Order")
    g["set_entry"](g["SO_number_entry"], so)
    g["schedule_entries"]["activity"].set("Receiving")
    section = g["item_frames"][0]
    cols = g["ITEM_FORM_HEADERS"]
    for header, value in {"Description of Goods": "Program Pump", "Quantity": "10", "UOM": "PCS"}.items():
        g["set_entry"](section.rows[0][cols.index(header)], value)


def test_program_saves_to_server_then_excel_backup(program):
    g, answers = program
    assert g["master_data"]["supplier_list"] is not None
    so = f"SO-GUI-{uuid.uuid4().hex[:6]}"
    fill(g, so)
    assert g["save_report"]() is True, answers.calls
    control = g["control_entry"].get()
    on_server = fsr_api.load_report(control)
    assert on_server["general_information"]["so_number"] == so
    assert on_server["prepared_by"]

    workbook = Path(g["excel_state"]["path"])
    in_excel = fsr_storage.read_report(workbook, control)
    assert in_excel["general_information"]["so_number"] == so
    row = in_excel["item_lists"][0]["rows"][0]
    assert row["Receiving Ref"] == f"RCV-{control}-1-01"
    assert g["item_frames"][0].rows[0].hidden["Receiving Ref"] == row["Receiving Ref"]
    form = workbook.parent / "Report Forms" / f"{control}_Report.xlsx"
    assert form.exists() and "First Page" in load_workbook(form).sheetnames

    # open from the server, edit, save: same number, one report, new version
    g["new_report"](confirm=False)
    g["load_report_into_form"](control, "excel")     # the program goes to the server anyway
    assert g["SO_number_entry"].get() == so
    g["set_entry"](g["SO_number_entry"], so + "-E")
    assert g["save_report"]() is True, answers.calls
    assert fsr_api.load_report(control)["version"] == 2
    assert fsr_storage.read_report(workbook, control)["general_information"]["so_number"] == so + "-E"
    assert not [c for c in answers.calls if c[0] == "showerror"], answers.calls


def test_program_keeps_form_when_server_refuses_or_is_down(program, monkeypatch):
    g, answers = program
    fill(g, "SO-DOWN")
    workbook = Path(g["excel_state"]["path"])
    monkeypatch.setattr(fsr_api, "base_url", lambda: "http://127.0.0.1:9")
    assert g["save_report"]() is False
    assert any(c[1] == "Not Saved" for c in answers.calls)
    assert g["SO_number_entry"].get() == "SO-DOWN"              # still on the form
    assert not workbook.exists() or "SO-DOWN" not in str(fsr_storage.list_saved_reports(workbook))
    monkeypatch.undo()
    assert g["save_report"]() is True                           # retry works


def test_program_conflict_does_not_overwrite(program):
    g, answers = program
    so = f"SO-CONFLICT-{uuid.uuid4().hex[:6]}"
    fill(g, so)
    assert g["save_report"]() is True
    control = g["control_entry"].get()
    other = fsr_api.load_report(control)
    fsr_api.save_document({**other, "findings_and_remarks": ["From another PC"]}, editing=True)
    fsr_api._report_meta[control]["version"] = 1       # this form still holds version 1
    g["set_entry"](g["SO_number_entry"], so + "-STALE")
    answers.yes = True                                 # load the server copy
    assert g["save_report"]() is False
    assert any(c[1] == "Report Changed By Someone Else" for c in answers.calls)
    assert fsr_api.load_report(control)["findings_and_remarks"] == ["From another PC"]
    assert g["SO_number_entry"].get() == so


def test_all_modules_open_on_server_data(program):
    g, answers = program
    shell = g["app_shell"]
    end = time.time() + 30
    while shell.service.snapshot is None and time.time() < end:
        shell.service.request(lambda *_: None)
        for _ in range(10):
            g["window"].update()
            time.sleep(0.02)
    assert shell.service.snapshot is not None, shell.service.error
    for key in ("dashboard", "receiving", "withdrawal", "bad_order", "analytics", "settings", "inspection"):
        shell.show(key)
        for _ in range(20):
            g["window"].update()
            time.sleep(0.02)
    assert not [c for c in answers.calls if c[0] == "showerror"], answers.calls
