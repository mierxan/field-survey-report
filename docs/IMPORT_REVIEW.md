# Import Review and import history (Phase 7)

How the Owner edition recognises a report it has imported before, what it
does with a changed copy, and what a sending app (Android, Windows User
edition) must put in its Master Data file for this to work.

## For the Owner: what changes

- **New reports** are added as before. If the number is already used here,
  the report gets the next free number (the import message lists it).
- **A completed report the user changed later** is no longer written over
  your copy. It waits in **Import Review** (Storage panel, or Account >
  Import Review). The button shows how many are waiting, and the review
  window opens by itself after an import that left some waiting.
- In Import Review each report shows, field by field:
  - **Changed by the user**: applied when you accept.
  - **Changed on this PC**: your own edits since the last accepted
    revision; they are kept when you accept.
  - **Changed by both**: the user's value is used when you accept.
- **Accept User Changes** writes the report (a copy of the file is made
  first; MySQL follows as after an import). **Keep My Version** leaves your
  copy alone; the user's revision counts as received, and their next
  revision is compared with it. **Close** changes nothing.
- A report sent again unchanged, or an older revision, changes nothing. A
  revision number that arrives with different content than before is
  refused (ask the user to send the file again).
- Reports are kept apart by **location**. Two locations can both send
  `FSR-0001`; they stay two reports.

Files that do **not** carry the new identity fields (every phone today)
are handled exactly as before: matched by phone + Control #, and updated
directly, with the "Imported Report Changes" window listing each change.

## For the sending apps: what the file must carry

All optional, inside the existing format (`"format": "fsr-master-data"`,
`"version": 1`). An Owner program from before Phase 7 ignores them.

| Where | Field | Meaning |
|---|---|---|
| file | `location_id` | Permanent id of the location (site) the file comes from. Never changes, even if the location is renamed. A random UUID made once. |
| file | `location_name` | The location's display name (shown to the Owner; may change). |
| report | `report_id` | Permanent id of the report. A random UUID made when the report is first created. It never changes: not when the report is edited, renumbered, moved to another phone, or restored from a backup. |
| report | `revision` | Whole number. `1` when the report is first completed; `+1` each time a completed report is saved with changes. Never reused for different content. |

The identity of a report is `location_id` + `report_id`. A report that was handed
over to another inspector carries its own `location_id`, `location_name`
and `handover_origin` (the device + Control # it was handed over from);
they take the place of the file's location, so it stays one report
whichever location sends it ([HANDOVER.md](HANDOVER.md)). A phone that is
replaced or restored must keep both (they belong in the phone's backup).

**Changeover.** The first file with identities usually contains reports
already imported the old way. Each one is still found by phone + Control #
(the phone must be the same one, with the same device id), and its record
moves to the new identity, so nothing is duplicated. If the report is
unchanged since the old import, that copy becomes the accepted revision. If
it changed, it waits in Import Review with every difference listed for the
Owner to decide (there is no earlier revision to tell who changed what).
A report sent for the first time from a *different* phone at the same time
as the update cannot be matched, and comes in as a new report.

## The files beside the workbook

In the workbook's JSON folder, next to `<workbook>_imported_reports.json`:

- `<workbook>_import_history.jsonl`: one line per import decision
  (added, updated, unchanged, pending_review, older_revision,
  invalid_revision, conflict, deleted_here, accepted, kept_owner), with
  location, report id, revision, source and Owner Control #, and a content
  fingerprint. Lines are only ever added.
- `<workbook>_import_review.json`: the last accepted revision of each
  report (the "before" of the review) and the revisions waiting for review.

They hold report data, never passwords. Like the import record they are
kept out of the code backups (`tools/backup_code.py`, `.gitignore`), are
carried along when the workbook moves (`fsr_sqlite_migrate`), and the review
file follows a renumbered report (`fsr_renumber`). The history keeps the
numbers as they were when each event happened.
