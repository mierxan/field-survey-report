"""A Control # is the same report whatever its letter case: import, the
Withdrawal workbook, the legacy CSV import and the Bad Order case status."""
import pytest

import fsr_import as imp
import fsr_storage as s
from test_import import fresh, master_file, phone_report
from warehouse import store

UPPER = "FSR-ABC-001"
LOWER = "fsr-abc-001"


@pytest.fixture
def book(tmp_path):
    return tmp_path / "data.xlsx"


# ---------- the helper ----------

def test_control_keyed_finds_any_letter_case():
    saved = s.ControlKeyed({UPPER: "stamp"})
    assert LOWER in saved and " Fsr-Abc-001 " in saved
    assert saved[LOWER] == saved.get(LOWER) == "stamp"
    assert saved.name(LOWER) == UPPER
    assert saved.name("FSR-XYZ-001") is None and "FSR-XYZ-001" not in saved
    saved[LOWER] = "newer"                       # same entry, spelling kept
    assert dict(saved) == {UPPER: "newer"} and list(saved) == [UPPER]
    assert saved == {UPPER: "newer"}
    assert saved.setdefault(LOWER, "x") == "newer"
    assert saved.pop(LOWER) == "newer" and LOWER not in saved
    assert saved.pop(LOWER, None) is None
    with pytest.raises(KeyError):
        saved[UPPER]
    assert s.control_key("  FsR-1 ") == "fsr-1" and s.control_key(None) == ""


# ---------- Import Master Data ----------

def test_same_number_in_other_case_is_the_same_report_not_a_second_one(book):
    """The phone sends FSR-ABC-001, later the same report as fsr-abc-001."""
    first = imp.import_master_data(
        book, fresh(master_file(phone_report(UPPER, so="PH-1"))))
    assert first["added"] == [UPPER]

    again = imp.import_master_data(
        book, fresh(master_file(phone_report(LOWER, so="PH-1"))))
    assert again["unchanged"] == [UPPER]
    assert again["added"] == [] and again["renumbered"] == []
    assert [e[0] for e in s.list_saved_reports(book)] == [UPPER]
    assert len(imp.load_ledger(book)) == 1       # one ledger entry, not two


def test_change_sent_in_other_case_updates_the_same_report(book):
    imp.import_master_data(
        book, fresh(master_file(phone_report(UPPER, so="PH-1"))))
    changed = phone_report(LOWER, so="PH-1-CHANGED",
                           saved="27-Oct-2026 09:00")

    summary = imp.import_master_data(book, fresh(master_file(changed)))

    assert summary["updated"] == [UPPER] and summary["added"] == []
    assert [e[0] for e in s.list_saved_reports(book)] == [UPPER]
    back = s.read_report(book, UPPER)
    assert back["general_information"]["so_number"] == "PH-1-CHANGED"
    # the Receiving Ref follows the workbook's spelling
    assert back["item_lists"][0]["rows"][0]["Receiving Ref"] == \
        f"RCV-{UPPER}-1-01"


def test_number_taken_on_this_pc_in_other_case_is_a_collision(book):
    """A report made on this PC is never overwritten by a phone's report
    whose number differs only by letter case: the phone's is renumbered."""
    s.write_report_to_excel(book, phone_report("FSR-ABC-202610-0001",
                                               so="ON-PC"), False)

    summary = imp.import_master_data(book, fresh(master_file(
        phone_report("fsr-abc-202610-0001", so="PHONE"))))

    (old, new), = summary["renumbered"]
    assert old == "fsr-abc-202610-0001" and summary["added"] == [new]
    assert s.control_key(new) != s.control_key(old)
    assert s.read_report(book, "FSR-ABC-202610-0001")[
        "general_information"]["so_number"] == "ON-PC"
    assert s.read_report(book, new)["general_information"][
        "so_number"] == "PHONE"
    assert len(s.list_saved_reports(book)) == 2


def test_pc_edit_is_still_protected_when_the_case_differs(book):
    imp.import_master_data(
        book, fresh(master_file(phone_report(UPPER, so="PH-1"))))
    edited = s.read_report(book, UPPER)
    edited["general_information"]["so_number"] = "EDITED-ON-PC"
    import time
    time.sleep(1.1)                              # a later Last Saved
    s.write_report_to_excel(book, edited, True)

    summary = imp.import_master_data(book, fresh(master_file(
        phone_report(LOWER, so="PH-CHANGED", saved="28-Oct-2026 09:00"))))

    assert summary["conflicts"] == [UPPER] and summary["updated"] == []
    assert s.read_report(book, UPPER)["general_information"][
        "so_number"] == "EDITED-ON-PC"


def test_report_deleted_here_does_not_come_back_in_other_case(book):
    imp.import_master_data(
        book, fresh(master_file(phone_report(UPPER, so="PH-1"))))
    s.delete_reports_from_excel(book, [LOWER])
    assert s.list_saved_reports(book) == []

    summary = imp.import_master_data(book, fresh(master_file(
        phone_report(LOWER, so="PH-1", saved="28-Oct-2026 09:00"))))

    assert summary["deleted_here"] == [UPPER] and summary["added"] == []
    assert s.list_saved_reports(book) == []


def test_number_of_the_withdrawal_workbook_in_other_case_is_taken(
        book, monkeypatch):
    monkeypatch.setattr(s, "withdrawal_control_numbers",
                        lambda path: ["FSR-ABC-202610-0007"])

    summary = imp.import_master_data(book, fresh(master_file(
        phone_report("fsr-abc-202610-0007", so="PHONE"))))

    (old, new), = summary["renumbered"]
    assert s.control_key(new) != "fsr-abc-202610-0007"
    assert [e[0] for e in s.list_saved_reports(book)] == [new]


def test_two_phones_keep_separate_entries(book):
    """Only the Control # is compared without case - not the phone."""
    imp.import_master_data(book, fresh(master_file(
        phone_report(UPPER, so="A"), device="phone-1")))
    summary = imp.import_master_data(book, fresh(master_file(
        phone_report(LOWER, so="B"), device="PHONE-1")))
    assert len(summary["renumbered"]) == 1
    assert len(imp.load_ledger(book)) == 2


# ---------- other places ----------

def test_demo_reset_counts_reports_in_any_case(book):
    s.write_report_to_excel(book, phone_report("TEST-ABC-001"), False)
    s.write_report_to_excel(book, phone_report("TEST-ABC-002"), False)
    assert s.delete_reports_from_excel(book, ["test-abc-001"]) == 1
    assert [e[0] for e in s.list_saved_reports(book)] == ["TEST-ABC-002"]


def test_case_status_is_found_in_any_case(tmp_path):
    workbook = tmp_path / "data.xlsx"          # outside the managed folders
    side = store.SideStore(workbook)
    side.set_case_status(UPPER, "Open", "Clerk", "damaged crate")
    side.set_case_status(LOWER, "Resolved", "Owner", "replaced")
    statuses = side.case_statuses()
    assert len(statuses) == 1
    assert statuses[LOWER]["status"] == statuses.get(UPPER)["status"] == \
        "Resolved"
    assert LOWER in statuses and UPPER in statuses
    assert len(side.case_history(LOWER)) == len(side.case_history(UPPER)) == 2
    assert side.case_history("FSR-XYZ-001") == []
