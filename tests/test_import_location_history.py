"""Location-separated, revision-aware imports (Phase 7).

The first six tests are the approved specification of 15 November 2026
(written before the code); the others cover the Owner's review decisions,
repairs and the files beside the workbook.
"""
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fsr_import as imp
import fsr_storage as storage
from factories import report


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
    # one new report: listed under Added, and renumbered because Manila's
    # report already has the number
    assert summary["added"] == ["FSR-MPR-202611-0002"]
    assert summary["renumbered"] == [
        ("FSR-MPR-202611-0001", "FSR-MPR-202611-0002")]


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


def test_same_revision_with_different_content_is_rejected(tmp_path):
    """A revision number cannot silently refer to two different snapshots."""
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(source_report()))

    inconsistent = source_report(so="DIFFERENT CONTENT, SAME REVISION")
    summary = imp.import_master_data(book, master(inconsistent))

    assert summary["invalid_revisions"] == ["FSR-MPR-202611-0001"]
    assert storage.read_report(book, "FSR-MPR-202611-0001")[
        "general_information"]["so_number"] == "SO-ORIGINAL"


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



# ---------- the Owner's decisions ----------

def revision(number, **changes):
    value = source_report(saved=f"{15 + number}-Nov-2026 09:00")
    value["revision"] = number
    value.update(changes)
    return value


def with_so(value, so):
    value["general_information"] = dict(value["general_information"],
                                        so_number=so)
    return value


def owner_edits(book, control, **changes):
    """The Owner changes the report on this PC (a normal save)."""
    value = storage.read_report(book, control)
    value.update(changes)
    storage.write_report_to_excel(book, value, True)


def test_review_shows_who_changed_what_and_accepting_keeps_both(tmp_path):
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(source_report()))
    control = "FSR-MPR-202611-0001"
    owner_edits(book, control, other_important_remarks=["Owner remark"])
    imp.import_master_data(book, master(revision(
        2, findings_and_remarks=["User detail"])))

    (waiting,) = imp.pending_reviews(book)
    assert waiting["control"] == control and waiting["revision"] == 2
    assert waiting["location_id"] == "location-manila"
    comparison = imp.review_comparison(book, waiting["key"])
    assert comparison.user_only == ["findings_and_remarks[0]"]
    assert comparison.owner_only == ["other_important_remarks[0]"]
    assert comparison.conflicts == []

    summary = imp.accept_revision(book, waiting["key"])
    assert summary["accepted"] == [control]
    saved = storage.read_report(book, control)
    assert saved["findings_and_remarks"] == ["User detail"]
    assert saved["other_important_remarks"] == ["Owner remark"]
    assert imp.pending_reviews(book) == []
    assert imp.load_import_history(book)[-1]["result"] == "accepted"

    again = imp.import_master_data(book, master(revision(
        2, findings_and_remarks=["User detail"])))
    assert again["unchanged"] == [control]
    assert again["pending_review"] == []


def test_accepting_a_conflict_takes_the_users_value(tmp_path):
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(source_report()))
    control = "FSR-MPR-202611-0001"
    storage.write_report_to_excel(
        book, with_so(storage.read_report(book, control), "SO-OWNER"), True)
    imp.import_master_data(book, master(with_so(revision(2), "SO-USER")))

    (waiting,) = imp.pending_reviews(book)
    comparison = imp.review_comparison(book, waiting["key"])
    assert comparison.conflicts == ["general_information.so_number"]
    (field,) = comparison.fields
    assert (field["base"], field["user"], field["owner"]) == (
        "SO-ORIGINAL", "SO-USER", "SO-OWNER")
    imp.accept_revision(book, waiting["key"])
    assert storage.read_report(book, control)[
        "general_information"]["so_number"] == "SO-USER"


def test_keeping_the_owner_version_counts_the_revision_as_received(tmp_path):
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(source_report()))
    control = "FSR-MPR-202611-0001"
    second = revision(2, findings_and_remarks=["Rejected detail"])
    imp.import_master_data(book, master(second))
    (waiting,) = imp.pending_reviews(book)

    imp.keep_owner_version(book, waiting["key"])
    assert storage.read_report(book, control)[
        "findings_and_remarks"] == ["Invented test detail"]
    assert imp.pending_reviews(book) == []
    assert imp.import_master_data(book, master(second))["unchanged"] == [
        control]

    third = revision(3, findings_and_remarks=["Rejected detail"],
                     other_important_remarks=["Third remark"])
    assert imp.import_master_data(book, master(third))["pending_review"] == [
        control]
    (waiting,) = imp.pending_reviews(book)
    # compared with revision 2 (received), so only the new change is the
    # user's; the Owner's copy still differs from revision 2 there
    comparison = imp.review_comparison(book, waiting["key"])
    assert comparison.user_only == ["other_important_remarks[0]"]
    assert comparison.owner_only == ["findings_and_remarks[0]"]
    results = [e["result"] for e in imp.load_import_history(book)]
    assert results == ["added", "pending_review", "kept_owner", "unchanged",
                       "pending_review"]


def test_older_revisions_and_resent_waiting_ones_change_nothing(tmp_path):
    book = tmp_path / "owner.xlsx"
    control = "FSR-MPR-202611-0001"
    imp.import_master_data(book, master(revision(2)))

    older = imp.import_master_data(book, master(source_report()))
    assert older["older_revisions"] == [control]

    third = with_so(revision(3), "SO-THIRD")
    assert imp.import_master_data(book, master(third))[
        "pending_review"] == [control]
    assert imp.import_master_data(book, master(third))["unchanged"] == [
        control]
    imp.import_master_data(book, master(with_so(revision(4), "SO-FOURTH")))
    (waiting,) = imp.pending_reviews(book)     # the newer one replaced it
    assert waiting["revision"] == 4
    assert imp.import_master_data(book, master(third))[
        "older_revisions"] == [control]
    assert storage.read_report(book, control)[
        "general_information"]["so_number"] == "SO-ORIGINAL"


def test_a_report_sent_twice_in_one_file_counts_in_its_newest_revision(
        tmp_path):
    book = tmp_path / "owner.xlsx"
    summary = imp.import_master_data(book, master(
        with_so(revision(3), "SO-NEWEST"), with_so(revision(2), "SO-OLDER")))
    assert summary["added"] == ["FSR-MPR-202611-0001"]
    assert storage.read_report(book, "FSR-MPR-202611-0001")[
        "general_information"]["so_number"] == "SO-NEWEST"
    assert len(imp.load_import_history(book)) == 1


def test_a_revision_of_a_report_deleted_here_is_not_brought_back(tmp_path):
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(source_report()))
    storage.delete_reports_from_excel(book, ["FSR-MPR-202611-0001"])
    summary = imp.import_master_data(book, master(revision(2)))
    assert summary["deleted_here"] == ["FSR-MPR-202611-0001"]
    assert storage.read_all_reports(book) == []
    assert imp.pending_reviews(book) == []


def test_reports_without_a_report_id_keep_the_device_matching(tmp_path):
    """Files from phones that do not send identities yet: as before."""
    book = tmp_path / "owner.xlsx"
    legacy = source_report()
    del legacy["report_id"], legacy["revision"]
    imp.import_master_data(book, master(legacy))
    edited = with_so(dict(legacy, last_saved="16-Nov-2026 09:00"),
                     "SO-LEGACY-EDIT")
    summary = imp.import_master_data(book, master(edited))
    assert summary["updated"] == ["FSR-MPR-202611-0001"]
    assert summary["pending_review"] == []
    events = imp.load_import_history(book)
    assert [e["result"] for e in events] == ["added", "updated"]
    assert all(e["report_id"] == "" for e in events)


def test_renumbering_on_this_pc_is_followed_by_the_review(tmp_path):
    import fsr_renumber
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(source_report()))
    imp.import_master_data(book, master(with_so(revision(2), "SO-AFTER")))
    fsr_renumber.renumber_report(book, "FSR-MPR-202611-0001",
                                 "FSR-MPR-202611-0009")

    (waiting,) = imp.pending_reviews(book)
    assert waiting["control"] == "FSR-MPR-202611-0009"
    imp.accept_revision(book, waiting["key"])
    assert storage.read_report(book, "FSR-MPR-202611-0009")[
        "general_information"]["so_number"] == "SO-AFTER"


def test_repair_after_a_cut_off_import_is_safe_twice(tmp_path):
    book = tmp_path / "owner.xlsx"
    data = source_report()
    key = imp.identity_key("location-manila", "report-a")
    entry = {"control": "FSR-MPR-202611-0001", "fingerprint": "f",
             "revision": 1, "report_id": "report-a"}
    info = {"base": {"revision": 1, "fingerprint": "f", "report": None},
            "event": {"id": "event-1", "result": "added"}}
    for _ in range(2):
        imp.repair_import_record(book, key, entry, info, data)
    assert [e["id"] for e in imp.load_import_history(book)] == ["event-1"]
    assert imp.load_review(book)["bases"][key]["revision"] == 1
    assert imp.load_ledger(book)[key]["control"] == "FSR-MPR-202611-0001"


def test_a_torn_history_line_does_not_hide_later_events(tmp_path):
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(source_report()))
    path = imp.history_path(book)
    path.write_text(path.read_text(encoding="utf-8") + '{"cut off',
                    encoding="utf-8")
    imp.import_master_data(book, master(source_report()))
    assert [e["result"] for e in imp.load_import_history(book)] == [
        "added", "unchanged"]


def test_merge_keeps_an_owner_list_the_user_did_not_touch():
    base = source_report()
    owner = source_report()
    rows = owner["item_lists"][0]["rows"]
    rows.append(dict(rows[0], **{"Description of Goods": "Owner row"}))
    user = with_so(revision(2), "SO-USER")
    merged = imp.merged_revision(base, user, owner)
    assert merged["general_information"]["so_number"] == "SO-USER"
    assert [row["Description of Goods"]
            for row in merged["item_lists"][0]["rows"]] == [
        "Invented pump", "Owner row"]


def test_without_a_base_every_difference_is_for_the_owner_to_decide():
    owner = source_report(so="SO-OWNER")
    user = with_so(revision(2), "SO-USER")
    comparison = imp.compare_revisions(None, user, owner)
    assert not comparison.has_base
    assert comparison.conflicts == ["general_information.so_number"]
    assert comparison.user_only == [] and comparison.owner_only == []


def test_review_works_with_the_reports_database(tmp_path):
    import fsr_sqlite_migrate as migrate
    import fsr_store
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(source_report()))
    assert migrate.migrate(book).status == "migrated"
    store = fsr_store.open_store(book)
    assert store.kind == "sqlite"

    store.import_master_data(master(with_so(revision(2), "SO-IN-DATABASE")))
    (waiting,) = imp.pending_reviews(book)
    assert imp.review_comparison(book, waiting["key"]).user_only == [
        "general_information.so_number"]
    imp.accept_revision(book, waiting["key"])
    assert fsr_store.open_store(book).read_report("FSR-MPR-202611-0001")[
        "general_information"]["so_number"] == "SO-IN-DATABASE"


# ---------- phones that start sending identities ----------

def legacy_copy(value):
    value = dict(value)
    value.pop("report_id", None)
    value.pop("revision", None)
    return value


def test_first_file_with_identities_does_not_duplicate_imported_reports(
        tmp_path):
    """Reports imported before the app sent report ids are recognised by
    phone + Control # once more, and from then on by their identity."""
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(legacy_copy(source_report())))

    summary = imp.import_master_data(book, master(source_report()))
    assert summary["unchanged"] == ["FSR-MPR-202611-0001"]
    assert summary["added"] == [] and summary["renumbered"] == []
    assert len(storage.read_all_reports(book)) == 1
    key = imp.identity_key("location-manila", "report-a")
    assert list(imp.load_ledger(book)) == [key]

    # from now on the identity is followed, from any phone
    later = imp.import_master_data(book, master(
        with_so(revision(2), "SO-LATER"), device="replacement-phone"))
    assert later["pending_review"] == ["FSR-MPR-202611-0001"]
    (waiting,) = imp.pending_reviews(book)
    assert waiting["has_base"]
    assert imp.review_comparison(book, waiting["key"]).user_only == [
        "general_information.so_number"]


def test_a_report_changed_while_the_app_was_updated_waits_for_review(
        tmp_path):
    book = tmp_path / "owner.xlsx"
    imp.import_master_data(book, master(legacy_copy(source_report())))
    changed = with_so(revision(2), "SO-CHANGED")

    summary = imp.import_master_data(book, master(changed))
    assert summary["pending_review"] == ["FSR-MPR-202611-0001"]
    assert len(storage.read_all_reports(book)) == 1
    (waiting,) = imp.pending_reviews(book)
    assert not waiting["has_base"]
    comparison = imp.review_comparison(book, waiting["key"])
    assert comparison.conflicts == ["general_information.so_number"]
    imp.accept_revision(book, waiting["key"])
    assert storage.read_report(book, "FSR-MPR-202611-0001")[
        "general_information"]["so_number"] == "SO-CHANGED"
    assert imp.import_master_data(book, master(changed))["unchanged"] == [
        "FSR-MPR-202611-0001"]
