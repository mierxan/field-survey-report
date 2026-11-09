"""The warehouse side file: reconciliation workflow + Bad Order case status."""

import json
from datetime import date

import pytest

import fsr_storage
import fsr_paths
from factories import rec, wdr
from warehouse import store


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / "Data.xlsx"
    for data in (rec("FSR-2026-0001", date(2026, 10, 1), "C-1", 10),
                 wdr("FSR-2026-0002", date(2026, 10, 2), "C-TYPO", 4)):
        fsr_storage.write_report_to_excel(path, data, editing=True)
    return path


def test_propose_confirm_changes_ledger_and_keeps_audit(workbook):
    snap = store.load_snapshot(workbook, as_of=date(2026, 10, 29))
    issue = snap.inventory.unmatched[0]
    target = {"warehouse": "WH-1", "cargo_id": "C-1", "receiving_ref": ""}
    snap.side.add_decision(issue.subject_id, "propose", "Clerk", "user",
                           target, "typo in Cargo ID")
    store.rebuild_inventory(snap, as_of=date(2026, 10, 29))
    assert snap.inventory.item("WH-1", "C-1").remaining_qty == 10
    snap.side.add_decision(issue.subject_id, "confirm", "Owner", "owner")
    store.rebuild_inventory(snap, as_of=date(2026, 10, 29))
    assert snap.inventory.item("WH-1", "C-1").remaining_qty == 6
    assert not [u for u in snap.inventory.unmatched if u.is_open]
    log = json.loads(store.side_file_path(workbook).read_text("utf-8"))
    assert [e["action"] for e in log["reconciliation"]] == ["propose",
                                                            "confirm"]
    assert log["reconciliation"][1]["target"]["cargo_id"] == "C-1"
    # the original report is unchanged
    report = fsr_storage.read_report(workbook, "FSR-2026-0002")
    assert report["item_lists"][0]["rows"][0]["Cargo ID"] == "C-TYPO"


def test_rules_of_the_workflow(workbook):
    side = store.SideStore(workbook)
    with pytest.raises(ValueError, match="owner"):
        side.add_decision("X/1/1", "confirm", "Clerk", "user")
    with pytest.raises(ValueError, match="Propose"):
        side.add_decision("X/1/1", "confirm", "Owner", "owner")
    with pytest.raises(ValueError, match="no proposed"):
        side.add_decision("X/1/1", "reject", "Owner", "owner")
    with pytest.raises(ValueError, match="note"):
        side.add_decision("X/1/1", "exclude", "Owner", "owner")
    side.add_decision("X/1/1", "propose", "Clerk", "user",
                      {"warehouse": "W", "cargo_id": "C"})
    side.add_decision("X/1/1", "reject", "Owner", "owner", note="wrong")
    assert side.decisions()["X/1/1"].state == "Rejected"
    assert side.decisions()["X/1/1"].target is None


def test_case_status_latest_wins_and_history_kept(workbook):
    side = store.SideStore(workbook)
    assert side.case_statuses() == {}
    side.set_case_status("FSR-2026-0001", "Open", "Clerk", "damaged crate")
    side.set_case_status("FSR-2026-0001", "Resolved", "Owner", "replaced")
    assert side.case_statuses()["FSR-2026-0001"]["status"] == "Resolved"
    assert len(side.case_history("FSR-2026-0001")) == 2
    with pytest.raises(ValueError):
        side.set_case_status("FSR-2026-0001", "Lost")


def test_aging_threshold_setting(workbook):
    side = store.SideStore(workbook)
    assert side.aging_thresholds() == (7, 30, 60, 90)
    side.set_aging_thresholds([60, 15, 30])
    assert store.SideStore(workbook).aging_thresholds() == (15, 30, 60)
    with pytest.raises(ValueError):
        side.set_aging_thresholds([0, 5])


def test_unreadable_side_file_is_reported(workbook):
    path = store.side_file_path(workbook)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be read"):
        store.SideStore(workbook)


def test_missing_workbook_gives_empty_snapshot(tmp_path):
    snap = store.load_snapshot(tmp_path / "none.xlsx")
    assert snap.reports == [] and snap.inventory.items == []


def test_managed_workbook_sidecar_uses_parallel_json_tree(tmp_path, monkeypatch):
    excel_root = tmp_path / "data" / "excel"
    json_root = tmp_path / "data" / "json"
    monkeypatch.setattr(fsr_paths, "EXCEL_DIR", excel_root)
    monkeypatch.setattr(fsr_paths, "JSON_DIR", json_root)

    managed = excel_root / "demo_data" / "Reports.xlsx"
    assert store.side_file_path(managed) == (
        json_root / "demo_data" / store.SIDE_FOLDER / "Reports.warehouse.json")

    external = tmp_path / "selected" / "External.xlsx"
    assert store.side_file_path(external) == (
        external.parent / store.SIDE_FOLDER / "External.warehouse.json")
