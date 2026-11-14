"""Executable specification for location-separated, revision-aware imports.

These strict expected failures describe the approved Phase 7 behaviour before
production code exists.  When an implementation makes one pass, pytest treats
the XPASS as a failure until its marker is deliberately removed.
"""
from datetime import date
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fsr_import as imp
import fsr_storage as storage
from factories import report


PENDING = pytest.mark.xfail(
    strict=True,
    reason="Phase 7 location and revision import history is not implemented",
)


def source_report(
        control="FSR-MPR-202611-0001", *, report_id="report-a",
        so="SO-ORIGINAL", saved="15-Nov-2026 08:00"):
    value = report(
        control, "Receiving", date(2026, 11, 15), "Manila Warehouse",
        [{"qty": 2, "unit": "Crate", "desc": "Invented pump",
          "ref": f"RCV-{control}-1-01"}], so=so,
    )
    value.update({
        "report_id": report_id,
        "revision": 1,
        "last_saved": saved,
        "declared_goods": [],
        "other_important_remarks": ["Invented test remark"],
        "findings_and_remarks": ["Invented test detail"],
    })
    return value


def master(*reports, device="phone-a", location_id="location-manila"):
    return {
        "format": imp.FORMAT,
        "version": 1,
        "device_id": device,
        "location_id": location_id,
        "location_name": "Manila Warehouse",
        "inspector": "Test Inspector",
        "reports": list(reports),
        "master_lists": {},
    }


@PENDING
def test_same_report_follows_owner_number_after_phone_replacement(tmp_path):
    """The permanent report identity, not device ID, follows a renumber."""
    book = tmp_path / "owner.xlsx"
    storage.write_report_to_excel(
        book, source_report(so="OWNER'S EXISTING REPORT"), False)

    first = imp.import_master_data(book, master(source_report()))
    source_control, owner_control = first["renumbered"][0]
    assert source_control == "FSR-MPR-202611-0001"

    changed = source_report(
        so="SO-EDITED-ON-REPLACEMENT-PHONE",
        saved="16-Nov-2026 09:00",
    )
    changed["revision"] = 2
    second = imp.import_master_data(
        book, master(changed, device="replacement-phone"))

    assert second["pending_review"] == [owner_control]
    assert second["added"] == [] and second["renumbered"] == []
    assert len(storage.read_all_reports(book)) == 2


@PENDING
def test_same_device_and_control_from_two_locations_are_separate(tmp_path):
    """Location identity prevents one site's report being mistaken for another."""
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(
        book,
        master(source_report(report_id="manila-report"),
               location_id="location-manila"),
    )
    second = source_report(report_id="cebu-report", so="SO-CEBU")
    summary = imp.import_master_data(
        book,
        master(second, location_id="location-cebu"),
    )

    assert len(storage.read_all_reports(book)) == 2
    assert len(summary["added"] + summary["renumbered"]) == 1


@PENDING
def test_completed_edit_waits_for_owner_review_without_overwriting(tmp_path):
    """A later source revision is queued, never applied automatically."""
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(source_report()))

    changed = source_report(so="SO-CHANGED-BY-USER",
                            saved="16-Nov-2026 09:00")
    changed["revision"] = 2
    summary = imp.import_master_data(book, master(changed))

    assert summary["pending_review"] == ["FSR-MPR-202611-0001"]
    assert summary["updated"] == []
    assert storage.read_report(book, "FSR-MPR-202611-0001")[
        "general_information"]["so_number"] == "SO-ORIGINAL"


@PENDING
def test_import_history_is_append_only_and_keeps_every_decision(tmp_path):
    """Repeated imports add events instead of replacing the last ledger row."""
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(source_report()))
    imp.import_master_data(book, master(source_report()))

    events = imp.load_import_history(book)
    assert [event["result"] for event in events] == ["added", "unchanged"]
    assert all(event["location_id"] == "location-manila"
               for event in events)
    assert all(event["report_id"] == "report-a" for event in events)


@PENDING
def test_same_revision_with_different_content_is_rejected(tmp_path):
    """A revision number cannot silently refer to two different snapshots."""
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(source_report()))

    inconsistent = source_report(so="DIFFERENT CONTENT, SAME REVISION")
    summary = imp.import_master_data(book, master(inconsistent))

    assert summary["invalid_revisions"] == ["FSR-MPR-202611-0001"]
    assert storage.read_report(book, "FSR-MPR-202611-0001")[
        "general_information"]["so_number"] == "SO-ORIGINAL"


@PENDING
def test_three_way_review_identifies_user_owner_and_conflicting_fields():
    base = source_report()
    user = source_report(so="SO-USER", saved="16-Nov-2026 09:00")
    user["revision"] = 2
    user["findings_and_remarks"] = ["User changed details"]
    owner = source_report(so="SO-OWNER", saved="16-Nov-2026 08:30")
    owner["other_important_remarks"] = ["Owner changed remark"]

    comparison = imp.compare_revisions(base, user, owner)

    assert comparison.user_only == ["findings_and_remarks[0]"]
    assert comparison.owner_only == ["other_important_remarks[0]"]
    assert comparison.conflicts == ["general_information.so_number"]

