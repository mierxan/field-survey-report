"""Handing a report or a draft over to the next inspector (fsr_handover).

Two site PCs (A hands over, B finishes) and the Owner, each with its own
invented workbook in a temporary folder.
"""
import json
from datetime import date
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fsr_drafts                                   # noqa: E402
import fsr_handover as ho                           # noqa: E402
import fsr_import as imp                            # noqa: E402
import fsr_master_export                            # noqa: E402
import fsr_storage as storage                       # noqa: E402
import fsr_store                                    # noqa: E402
from factories import report                        # noqa: E402

A = {"inspector": "Inspector Alpha", "initials": "ALP", "device_id": "pc-a"}
B = {"inspector": "Inspector Bravo", "initials": "BRV", "device_id": "pc-b"}
OWNER = {"inspector": "The Owner", "initials": "MPR", "device_id": "owner"}
NUMBER = "FSR-ALP-202611-0001"


def invented(control=NUMBER, so="SO-HANDOVER", remark="First remark"):
    value = report(control, "Receiving", date(2026, 11, 16), "North Yard",
                   [{"qty": 3, "unit": "Crate", "desc": "Invented valve",
                     "ref": f"RCV-{control}-1-01"}], so=so)
    value["other_important_remarks"] = [remark]
    return value


def pc(tmp_path, name, *reports):
    book = tmp_path / name / "Field_Survey_Reports.xlsx"
    book.parent.mkdir()
    for value in reports:
        fsr_store.ExcelStore(book).write_report(value, False)
    return book


def edit(book, control, **general):
    value = storage.read_report(book, control)
    value["general_information"].update(general)
    fsr_store.ExcelStore(book).write_report(value, True)


def export(book, device):
    return fsr_master_export.build_export(book, device, "Inspector")


def drafts(tmp_path, owner):
    return fsr_drafts.Store(tmp_path / "Drafts", "a" * 32, owner * 32)


def snapshot(so="SO-DRAFT"):
    return {"simple": {"SO_number_entry": so}, "date": "16-Nov-2026",
            "condition": "", "goods": {}, "others": False, "others_text": "",
            "item_form": "Default", "item_cache": {}, "other_item_forms": {},
            "items": [{"rows": [{"cells": {"Quantity": "1,"}, "hidden": {},
                                 "po_link": {}, "manual": []}]}],
            "declared": [["", "", ""]], "remarks": ["half a remark"],
            "findings": [""], "incidents": [], "schedule_entries": {},
            "transport_entries": {}, "document_entries": {},
            "withdrawal": {"po": "", "owned": False, "activity": "",
                           "editing": None}}


def draft_value(store, book, editing=False, control=""):
    value = {"version": 1, "id": "c" * 32, "scope": store.scope,
             "owner": store.owner, "revision": 3,
             "changed": fsr_drafts.now_text(), "workbook": str(book),
             "editing": editing, "control": control, "baseline": {},
             "source": "excel", "form": snapshot()}
    store.write(value)
    (found,), _ = store.list()
    return found


# ---------- completed reports ----------

def test_a_handed_over_report_keeps_its_number_and_is_locked_at_the_sender(
        tmp_path):
    a = pc(tmp_path, "a", invented())
    b = pc(tmp_path, "b")
    file = tmp_path / "handover.json"
    payload = ho.hand_over_report(a, NUMBER, file, A, to="Inspector Bravo")
    assert payload["report"]["revision"] == 1
    assert ho.handed_over(a, NUMBER)["to"] == "Inspector Bravo"

    received = ho.receive(b, ho.read_file(file))
    assert received["result"] == "added"
    assert received["control"] == NUMBER and not received["renumbered"]
    assert storage.read_report(b, NUMBER)["general_information"][
        "so_number"] == "SO-HANDOVER"
    assert ho.handed_over(b, NUMBER) is None          # B works on it
    # the Receiving Ref still names the report's own number
    assert storage.read_report(b, NUMBER)["item_lists"][0]["rows"][0][
        "Receiving Ref"] == f"RCV-{NUMBER}-1-01"

    again = ho.receive(b, ho.read_file(file))
    assert again["result"] == "unchanged"
    assert len(storage.list_saved_reports(b)) == 1


def test_a_number_already_used_by_another_report_gets_the_next_free_one(
        tmp_path):
    a = pc(tmp_path, "a", invented())
    b = pc(tmp_path, "b", invented(so="SO-B-OWN"))     # B's own, same number
    file = tmp_path / "handover.json"
    ho.hand_over_report(a, NUMBER, file, A)
    received = ho.receive(b, ho.read_file(file))
    assert received["renumbered"]
    assert received["control"] == "FSR-ALP-202611-0002"
    moved = storage.read_report(b, "FSR-ALP-202611-0002")
    assert moved["general_information"]["so_number"] == "SO-HANDOVER"
    assert moved["item_lists"][0]["rows"][0]["Receiving Ref"] == \
        "RCV-FSR-ALP-202611-0002-1-01"
    assert storage.read_report(b, NUMBER)["general_information"][
        "so_number"] == "SO-B-OWN"


def test_handing_back_unlocks_the_senders_copy(tmp_path):
    a = pc(tmp_path, "a", invented())
    b = pc(tmp_path, "b")
    ho.hand_over_report(a, NUMBER, tmp_path / "1.json", A)
    ho.receive(b, ho.read_file(tmp_path / "1.json"))
    edit(b, NUMBER, so_number="SO-FINISHED-BY-B")
    back = ho.hand_over_report(b, NUMBER, tmp_path / "2.json", B)
    assert back["report"]["revision"] == 3      # 1 sent, 2 received, edited
    assert ho.handed_over(b, NUMBER) is not None

    result = ho.receive(a, ho.read_file(tmp_path / "2.json"))
    assert result["result"] == "updated" and result["control"] == NUMBER
    assert ho.handed_over(a, NUMBER) is None
    assert storage.read_report(a, NUMBER)["general_information"][
        "so_number"] == "SO-FINISHED-BY-B"
    # A receiving its own first file again changes nothing
    assert ho.receive(a, ho.read_file(tmp_path / "1.json"))["result"] == \
        "unchanged"


def test_a_working_copy_here_is_only_replaced_when_asked(tmp_path):
    a = pc(tmp_path, "a", invented())
    b = pc(tmp_path, "b")
    ho.hand_over_report(a, NUMBER, tmp_path / "1.json", A)
    ho.receive(b, ho.read_file(tmp_path / "1.json"))
    ho.cancel(a, NUMBER)                        # A takes it back meanwhile
    edit(a, NUMBER, so_number="SO-A-AFTER-CANCEL")
    edit(b, NUMBER, so_number="SO-B-FINISHED")
    ho.hand_over_report(b, NUMBER, tmp_path / "2.json", B)

    with pytest.raises(ho.HandoverConflict) as raised:
        ho.receive(a, ho.read_file(tmp_path / "2.json"))
    assert any(change["path"] == ("general_information", "so_number")
               for change in raised.value.changes)
    assert storage.read_report(a, NUMBER)["general_information"][
        "so_number"] == "SO-A-AFTER-CANCEL"
    ho.receive(a, ho.read_file(tmp_path / "2.json"), replace=True)
    assert storage.read_report(a, NUMBER)["general_information"][
        "so_number"] == "SO-B-FINISHED"


def test_cancel_lets_the_sender_save_again(tmp_path):
    a = pc(tmp_path, "a", invented())
    ho.hand_over_report(a, NUMBER, tmp_path / "1.json", A)
    ho.cancel(a, NUMBER)
    assert ho.handed_over(a, NUMBER) is None
    with pytest.raises(ho.HandoverError):
        ho.cancel(a, NUMBER)


# ---------- the files ----------

def test_damaged_or_foreign_files_are_refused_before_anything_changes(
        tmp_path):
    a = pc(tmp_path, "a", invented())
    b = pc(tmp_path, "b")
    file = tmp_path / "handover.json"
    ho.hand_over_report(a, NUMBER, file, A)
    envelope = json.loads(file.read_text(encoding="utf-8"))
    envelope["payload"] = envelope["payload"].replace("SO-HANDOVER", "SO-X")
    file.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ho.HandoverError, match="damaged"):
        ho.read_file(file)

    master = tmp_path / "master.json"
    fsr_master_export.write_export(a, master, "pc-a")
    with pytest.raises(ho.HandoverError, match="Master Data"):
        ho.read_file(master)
    assert storage.list_saved_reports(b) == []


def test_a_damaged_phone_draft_is_refused(tmp_path):
    b = pc(tmp_path, "b")
    payload = {"handover_id": "x" * 32, "kind": "draft", "app": "android",
               "created_at": "", "from": A, "to": "", "note": "",
               "report": None, "draft": {"app": "android", "report": {}}}
    file = tmp_path / "phone.json"
    file.write_text(json.dumps(ho._envelope(payload)), encoding="utf-8")
    store = drafts(tmp_path, "b")
    with pytest.raises(ho.HandoverError, match="damaged"):
        ho.receive(b, ho.read_file(file), draft_store=store,
                   to_form=lambda data: snapshot())
    assert store.list()[0] == []


def test_a_report_made_on_a_phone_is_received(tmp_path):
    """A completed report from the Android app: the Master Data shape."""
    b = pc(tmp_path, "b")
    phone = dict(invented(control="FSR-PHN-202611-0007"), report_id="phone-1",
                 revision=4, location_id="handover:phone-9",
                 location_name="Handed over by PHN",
                 handover_origin={"device": "phone-9",
                                  "control": "FSR-PHN-202611-0007"})
    payload = {"handover_id": "y" * 32, "kind": "report", "app": "android",
               "created_at": "", "from": {"inspector": "Phone",
                                          "device_id": "phone-9"},
               "to": "", "note": "", "report": phone, "draft": None}
    file = tmp_path / "phone.json"
    file.write_text(json.dumps(ho._envelope(payload)), encoding="utf-8")
    assert ho.receive(b, ho.read_file(file))["control"] == \
        "FSR-PHN-202611-0007"
    exported = export(b, "pc-b")["reports"][0]
    assert exported["report_id"] == "phone-1"
    assert exported["revision"] == 5


def test_withdrawal_reports_linked_to_a_po_are_not_handed_over(
        tmp_path, monkeypatch):
    a = pc(tmp_path, "a", invented())
    monkeypatch.setattr(fsr_store.ExcelStore, "withdrawal_numbers",
                        lambda self: [NUMBER])
    with pytest.raises(ho.HandoverError, match="Withdrawal"):
        ho.hand_over_report(a, NUMBER, tmp_path / "1.json", A)
    assert ho.status(a, NUMBER) is None


# ---------- at the Owner ----------

def test_both_inspectors_master_data_give_the_owner_one_report(tmp_path):
    a = pc(tmp_path, "a", invented())
    b = pc(tmp_path, "b")
    owner = pc(tmp_path, "owner")
    ho.hand_over_report(a, NUMBER, tmp_path / "1.json", A)
    ho.receive(b, ho.read_file(tmp_path / "1.json"))
    edit(b, NUMBER, so_number="SO-FINISHED-BY-B")

    first = imp.import_master_data(owner, export(a, "pc-a"))
    assert first["added"] == [NUMBER]
    second = imp.import_master_data(owner, export(b, "pc-b"))
    assert second["added"] == [] and second["pending_review"] == [NUMBER]
    (waiting,) = imp.pending_reviews(owner)
    imp.accept_revision(owner, waiting["key"])
    assert [r[0] for r in storage.list_saved_reports(owner)] == [NUMBER]
    assert storage.read_report(owner, NUMBER)["general_information"][
        "so_number"] == "SO-FINISHED-BY-B"
    # A's locked copy, sent again, is older
    assert imp.import_master_data(owner, export(a, "pc-a"))[
        "older_revisions"] == [NUMBER]


def test_the_finished_copy_first_then_the_old_one_is_ignored(tmp_path):
    a = pc(tmp_path, "a", invented())
    b = pc(tmp_path, "b")
    owner = pc(tmp_path, "owner")
    ho.hand_over_report(a, NUMBER, tmp_path / "1.json", A)
    ho.receive(b, ho.read_file(tmp_path / "1.json"))
    edit(b, NUMBER, so_number="SO-FINISHED-BY-B")
    assert imp.import_master_data(owner, export(b, "pc-b"))["added"] == [
        NUMBER]
    assert imp.import_master_data(owner, export(a, "pc-a"))[
        "older_revisions"] == [NUMBER]
    assert storage.read_report(owner, NUMBER)["general_information"][
        "so_number"] == "SO-FINISHED-BY-B"


def test_a_report_the_owner_had_before_the_hand_over_is_not_doubled(
        tmp_path):
    """A sent it the old way (no identity) before handing it over."""
    a = pc(tmp_path, "a", invented())
    b = pc(tmp_path, "b")
    owner = pc(tmp_path, "owner")
    assert imp.import_master_data(owner, export(a, "pc-a"))["added"] == [
        NUMBER]
    ho.hand_over_report(a, NUMBER, tmp_path / "1.json", A)
    ho.receive(b, ho.read_file(tmp_path / "1.json"))
    edit(b, NUMBER, so_number="SO-FINISHED-BY-B")
    summary = imp.import_master_data(owner, export(b, "pc-b"))
    assert summary["added"] == [] and summary["pending_review"] == [NUMBER]
    assert len(storage.list_saved_reports(owner)) == 1


def test_the_owner_hands_over_its_own_report_and_gets_it_back(tmp_path):
    owner_number = "FSR-MPR-202611-0001"
    owner = pc(tmp_path, "owner", invented(control=owner_number))
    b = pc(tmp_path, "b")
    ho.hand_over_report(owner, owner_number, tmp_path / "1.json", OWNER,
                        owner_edition=True)
    assert ho.handed_over(owner, owner_number)
    ho.receive(b, ho.read_file(tmp_path / "1.json"))
    edit(b, owner_number, so_number="SO-FINISHED-BY-B")

    summary = imp.import_master_data(owner, export(b, "pc-b"))
    assert summary["added"] == [] and summary["pending_review"] == [
        owner_number]
    (waiting,) = imp.pending_reviews(owner)
    comparison = imp.review_comparison(owner, waiting["key"])
    assert comparison.user_only == ["general_information.so_number"]
    imp.accept_revision(owner, waiting["key"])
    assert ho.handed_over(owner, owner_number) is None      # back here
    assert len(storage.list_saved_reports(owner)) == 1


def test_a_report_the_owner_receives_directly_is_known_to_its_import(
        tmp_path):
    a = pc(tmp_path, "a", invented())
    owner = pc(tmp_path, "owner")
    ho.hand_over_report(a, NUMBER, tmp_path / "1.json", A)
    ho.receive(owner, ho.read_file(tmp_path / "1.json"), owner_edition=True)
    summary = imp.import_master_data(owner, export(a, "pc-a"))
    assert summary["added"] == []
    assert summary["unchanged"] + summary["older_revisions"] == [NUMBER]
    results = [e["result"] for e in imp.load_import_history(owner)]
    assert results[0] == "received_handover"


def test_renumbering_moves_the_hand_over_record(tmp_path):
    a = pc(tmp_path, "a", invented())
    ho.hand_over_report(a, NUMBER, tmp_path / "1.json", A)
    fsr_store.ExcelStore(a).renumber(NUMBER, "FSR-ALP-202611-0009")
    assert ho.handed_over(a, "FSR-ALP-202611-0009") is not None


# ---------- drafts ----------

def test_a_draft_of_a_new_report_moves_to_the_next_inspector(tmp_path):
    a = pc(tmp_path, "a")
    b = pc(tmp_path, "b")
    mine, theirs = drafts(tmp_path, "a"), drafts(tmp_path, "b")
    value = draft_value(mine, a)
    file = tmp_path / "draft.json"
    payload = ho.hand_over_draft(a, value, mine, file, A, to="Bravo")
    assert payload["report"] is None
    (kept,), _ = mine.list()
    assert kept["handed_over"]["to"] == "Bravo"
    with pytest.raises(ho.HandoverError, match="already"):
        ho.hand_over_draft(a, kept, mine, file, A)

    result = ho.receive(b, ho.read_file(file), draft_store=theirs,
                        owner_label="BRV")
    assert result["result"] == "draft"
    (received,), _ = theirs.list()
    assert received["form"]["remarks"] == ["half a remark"]
    assert received["editing"] is False and received["control"] == ""
    assert received["workbook"] == str(b)
    assert storage.list_saved_reports(b) == []      # no number taken
    # the same file again: still one draft
    assert ho.receive(b, ho.read_file(file), draft_store=theirs)[
        "result"] == "unchanged"
    assert len(theirs.list()[0]) == 1


def test_a_draft_of_a_saved_report_brings_the_report_along(tmp_path):
    a = pc(tmp_path, "a", invented())
    b = pc(tmp_path, "b", invented(so="SO-B-OWN"))     # number taken at B
    mine, theirs = drafts(tmp_path, "a"), drafts(tmp_path, "b")
    value = draft_value(mine, a, editing=True, control=NUMBER)
    value["form"]["items"][0]["rows"][0]["hidden"] = {
        "Receiving Ref": f"RCV-{NUMBER}-1-01"}
    mine.write({k: v for k, v in value.items() if k not in ("orphan",
                                                            "old")})
    (value,), _ = mine.list()
    ho.hand_over_draft(a, value, mine, tmp_path / "d.json", A)
    assert ho.handed_over(a, NUMBER) is not None

    result = ho.receive(b, ho.read_file(tmp_path / "d.json"),
                        draft_store=theirs, owner_label="BRV")
    assert result["control"] == "FSR-ALP-202611-0002"
    (received,), _ = theirs.list()
    assert received["editing"] and received["control"] == \
        "FSR-ALP-202611-0002"
    assert received["form"]["items"][0]["rows"][0]["hidden"][
        "Receiving Ref"] == "RCV-FSR-ALP-202611-0002-1-01"
    assert received["baseline"]["data"]["general_information"][
        "so_number"] == "SO-HANDOVER"


def test_withdrawal_drafts_linked_to_a_po_are_not_handed_over(tmp_path):
    a = pc(tmp_path, "a")
    mine = drafts(tmp_path, "a")
    value = draft_value(mine, a)
    value["form"]["withdrawal"]["owned"] = True
    with pytest.raises(ho.HandoverError, match="Withdrawal"):
        ho.hand_over_draft(a, value, mine, tmp_path / "d.json", A)
    assert not (tmp_path / "d.json").exists()


# ---------- files made by the Android app (tests/data, written by its
# HandoverCodecTest) ----------

DATA = ROOT / "tests" / "data"


def test_a_completed_report_from_the_phone_app_is_received(tmp_path):
    b = pc(tmp_path, "b")
    owner = pc(tmp_path, "owner")
    payload = ho.read_file(DATA / "handover_from_android_report.json")
    assert payload["app"] == "android" and payload["to"] == "Next Inspector"
    result = ho.receive(b, payload)
    assert result["result"] == "added"
    assert result["control"] == "FSR-PHN-202611-0004"
    saved = storage.read_report(b, "FSR-PHN-202611-0004")
    assert saved["general_information"]["so_number"] == "SO-PHONE"
    assert saved["other_important_remarks"] == ["Phone remark"]
    # the phone's revision 2, received here: revision 3 in this PC's files
    exported = export(b, "pc-b")["reports"][0]
    assert exported["report_id"] == "uid-1" and exported["revision"] == 3
    assert exported["handover_origin"] == {"device": "phone-1",
                                           "control": "FSR-PHN-202611-0004"}
    assert imp.import_master_data(owner, export(b, "pc-b"))["added"] == [
        "FSR-PHN-202611-0004"]


PHONE = "FSR-PHN-202611-0004"


def from_phone(book, store, name="handover_from_android_draft.json",
               **more):
    """Receive a phone draft; the window's form is stood in for: the data
    it is given is kept in `seen`."""
    seen = []

    def to_form(data):
        seen.append(data)
        return snapshot(data["general_information"]["so_number"])
    result = ho.receive(book, ho.read_file(DATA / name), draft_store=store,
                        to_form=to_form, **more)
    return result, seen


def finish(book, data, control, received, **more):
    """The finishing inspector saves the restored draft as `control`."""
    value = json.loads(json.dumps(data))
    value["control_no"] = control
    fsr_store.ExcelStore(book).write_report(value, False)
    return ho.adopt(book, control, received, **more)


def test_the_phone_apps_draft_is_converted_as_the_app_itself_does():
    """Every field of a phone draft, against the app's own export of it
    (both files written by the app's HandoverCodecTest)."""
    payload = ho.read_file(DATA / "handover_from_android_rich_draft.json")
    expected = json.loads((DATA / "android_rich_draft_windows_shape.json")
                          .read_text(encoding="utf-8"))
    assert ho.phone_report_data(payload["draft"]["report"]) == expected
    assert ho.describe(payload).startswith(
        "unfinished report FSR-PHN-202611-0007 (a draft from the phone app)")


def test_a_draft_from_the_phone_app_becomes_a_draft_that_keeps_its_number(
        tmp_path):
    b = pc(tmp_path, "b")
    owner = pc(tmp_path, "owner")
    store = drafts(tmp_path, "b")
    result, seen = from_phone(b, store)
    assert result["result"] == "draft" and result["control"] is None
    value = result["draft"]
    assert value["editing"] is False and value["control"] == ""
    assert value["received"]["control"] == PHONE
    assert value["received"]["identity"]["report_id"] == "uid-1"
    assert value["received"]["from"]["inspector"] == "Phone Inspector"
    data = seen[0]
    assert data["general_information"]["so_number"] == "SO-PHONE"
    assert data["other_important_remarks"] == ["Phone remark"]
    # Receiving Refs made from the phone's number are given again on save
    assert data["item_lists"][0]["rows"][0]["Receiving Ref"] == ""
    # the same file again: still one draft
    again, _ = from_phone(b, store)
    assert again["draft"] is None and len(store.list()[0]) == 1
    assert ho.kept_number(b, value["received"]) == PHONE

    entry = finish(b, data, PHONE, value["received"])
    assert entry["revision"] == 3 and entry["state"] == ho.ACTIVE
    saved = storage.read_report(b, PHONE)
    assert saved["item_lists"][0]["rows"][0]["Receiving Ref"] == \
        f"RCV-{PHONE}-1-01"
    # one report everywhere: Master Data carries the phone's report id
    exported = export(b, "pc-b")["reports"][0]
    assert exported["control_no"] == PHONE
    assert exported["report_id"] == "uid-1" and exported["revision"] == 3
    assert exported["handover_origin"] == {"device": "phone-1",
                                           "control": PHONE}
    assert imp.import_master_data(owner, export(b, "pc-b"))["added"] == [
        PHONE]
    # and handed back to the phone, the phone finds its own report
    back = ho.hand_over_report(b, PHONE, tmp_path / "back.json", B,
                               to="Phone Inspector")
    assert back["report"]["report_id"] == "uid-1"
    assert back["report"]["revision"] == 3


def test_a_phone_drafts_number_used_here_gets_the_next_free_one(tmp_path):
    b = pc(tmp_path, "b", invented(PHONE, so="SO-ALREADY-HERE"))
    result, seen = from_phone(b, drafts(tmp_path, "b"))
    received = result["draft"]["received"]
    expected = fsr_store.ExcelStore(b).next_free_number(PHONE)
    assert expected != PHONE and expected.startswith("FSR-PHN-")
    assert ho.kept_number(b, received) == expected
    finish(b, seen[0], expected, received)
    assert storage.read_report(b, PHONE)["general_information"][
        "so_number"] == "SO-ALREADY-HERE"
    assert export(b, "pc-b")["reports"][1]["report_id"] == "uid-1"


def test_a_phone_draft_handed_on_from_a_pc_keeps_its_number(tmp_path):
    b = pc(tmp_path, "b")
    c = pc(tmp_path, "c")
    store_b = drafts(tmp_path, "b")
    from_phone(b, store_b)
    (value,), _ = store_b.list()
    payload = ho.hand_over_draft(b, value, store_b, tmp_path / "on.json", B,
                                 to="Inspector Charlie")
    assert payload["draft"]["kept"]["control"] == PHONE
    store_c = drafts(tmp_path, "c")
    result = ho.receive(c, ho.read_file(tmp_path / "on.json"),
                        draft_store=store_c)
    received = result["draft"]["received"]
    assert received["control"] == PHONE
    assert received["identity"]["report_id"] == "uid-1"
    assert ho.kept_number(c, received) == PHONE


def test_the_owner_who_finishes_a_phone_draft_knows_it_at_import(tmp_path):
    owner = pc(tmp_path, "owner")
    result, seen = from_phone(owner, drafts(tmp_path, "e"),
                              owner_edition=True)
    finish(owner, seen[0], PHONE, result["draft"]["received"],
           owner_edition=True)
    key = imp.report_identity({}, {"report_id": "uid-1",
                                   "location_id": "handover:phone-1"})
    assert imp.load_ledger(owner)[key]["control"] == PHONE


def test_a_phone_draft_of_a_report_this_pc_has_is_refused(tmp_path):
    b = pc(tmp_path, "b")
    ho.receive(b, ho.read_file(DATA / "handover_from_android_report.json"))
    store = drafts(tmp_path, "b")
    with pytest.raises(ho.HandoverError, match="already has this report"):
        from_phone(b, store)
    assert store.list()[0] == []


def test_a_phone_draft_needs_the_window(tmp_path):
    b = pc(tmp_path, "b")
    with pytest.raises(ho.HandoverError, match="window"):
        ho.receive(b, ho.read_file(DATA / "handover_from_android_draft.json"),
                   draft_store=drafts(tmp_path, "b"))


def test_a_copy_renumbered_at_the_receiver_is_unchanged_for_the_owner(
        tmp_path):
    """B already had the number, so B keeps it as -0002; its Receiving Refs
    follow. Unchanged, it is still the Owner's revision."""
    a = pc(tmp_path, "a", invented())
    b = pc(tmp_path, "b", invented(so="SO-B-OWN"))
    owner = pc(tmp_path, "owner")
    ho.hand_over_report(a, NUMBER, tmp_path / "1.json", A)
    assert imp.import_master_data(owner, export(a, "pc-a"))["added"] == [
        NUMBER]
    assert ho.receive(b, ho.read_file(tmp_path / "1.json"))["renumbered"]
    summary = imp.import_master_data(owner, export(b, "pc-b"))
    assert summary["unchanged"] == [NUMBER]
    assert summary["pending_review"] == []
    assert summary["renumbered"] == [(NUMBER, "FSR-ALP-202611-0002")]


def test_a_phone_draft_without_any_item_list_is_received(tmp_path):
    """A phone draft can have no item lists at all ("Default": []), as in a
    real draft: the app's export then has none either."""
    payload = ho.read_file(DATA / "handover_from_android_draft.json")
    phone = payload["draft"]["report"]
    phone.update(itemLists={"Default": [], "Containerized": [],
                            "Loading": []}, otherRemarks=[],
                 additionalDetails=[], cargoCondition="")
    data = ho.phone_report_data(phone)
    assert data["item_lists"] == [] and data["other_item_forms"] == {}
    assert data["other_important_remarks"] == []
    file = tmp_path / "empty.json"
    file.write_text(json.dumps(ho._envelope(payload)), encoding="utf-8")
    b = pc(tmp_path, "b")
    seen = []
    result = ho.receive(b, ho.read_file(file),
                        draft_store=drafts(tmp_path, "b"),
                        to_form=lambda value: seen.append(value) or snapshot())
    assert result["draft"]["received"]["control"] == PHONE
    assert seen[0]["item_lists"] == []
