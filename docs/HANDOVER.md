# Hand-over to the next inspector (Phase 8)

When an inspector moves to another location, the inspector who continues
an unfinished report can receive it from them as one file. Every user can
do this: the Owner edition, the User edition and the Android app. All three
read and write the same file.

## How to use it

**Windows (Owner and User edition):** in the side panel under **Storage**:

- **Hand Over...** lists your drafts (unfinished work of your account) and
  the saved reports. Choose one, type the **next inspector's** name (and a
  note if you want), click **Hand Over...** and save the file. Send that
  one file to the next inspector by e-mail, chat or USB stick. If the form
  has unsaved changes, you are asked first whether to save them, or to keep
  them as a draft and hand the draft over.
- **Receive Hand-over...** opens such a file. It says what the file holds
  and who sent it, and brings it in after you say yes.
  - A received **report** opens with Open saved report (Ctrl+O).
  - A received **draft** is in Account > Unfinished work; Restore it there.
    This includes a draft from the **phone app**: the PC turns it into one
    of its own drafts.

**Android:** open the report (Completed Reports), or for a draft tap the
send icon in Draft Reports, then choose **Hand Over**. Type the next
inspector's name, then **Share** or **Save File**. To receive a file, go to
**Master Data** and choose **Receive Hand-over**.

## Numbering

- A **saved report keeps the Control # it was first given**, on every PC
  and phone. The receiver sees the same number as the sender.
- Only when that exact number is already used by **another** report where
  it arrives does it get the next free number there. The running number
  continues, and the initials of the inspector who made the report are
  kept. The receiver is told the new number, and Receiving Refs follow it.
- A **draft of a new report** has no number yet (Windows). It takes the
  **finishing inspector's** next number when they first save it, like any
  new report.
- A **phone draft** already has its number (the app numbers a report at
  its first save, also as a draft) and keeps it, also on a PC: restored
  there, the form shows the phone's number, and the first save uses it. If
  another report on that PC has the number by then, it gets the next free
  one, with the same initials. Its Receiving Refs are made again from the
  number it is saved with.

## The sender's copy

The sender keeps a copy, marked **handed over**. It can be opened and
printed, but not saved:

- Windows refuses Save with a message.
- On a phone, Edit is off and the details show who has it.

A handed-over draft stays in Unfinished work marked *Handed over to ...*,
and can only be discarded.

The copy can be worked on again when:

- **It comes back.** The next inspector hands it back and the sender
  receives it.
- **The sender cancels.** Use **Cancel Hand-over** (Windows: in the Hand
  Over window; phone: in the report's details). Do this only if the next
  inspector will **not** finish it. If both change it, the Owner gets two
  different versions.

The Owner's own report that comes back through a Master Data file is
unlocked when the Owner accepts it in Import Review.

## At the Owner

A handed-over report carries a permanent **report id** and a **revision**
number, also in the Master Data files of both inspectors:

- The revision goes up by one when it is received.
- It goes up again when its content changes.

So it reaches the Owner **once**, whichever inspector sends it first:

- **The finished copy first:** added. The sender's older copy is ignored
  later ("a newer revision is already here").
- **The sender's copy first:** added. The finished copy then waits in
  **Import Review** (see [IMPORT_REVIEW.md](IMPORT_REVIEW.md)), with each
  change listed.
- **The sender had already sent it the old way** (no report id): it is still
  found, by the sender's PC or phone + Control #.
- **The Owner hands over its own report:** what comes back from the user
  waits in Import Review.
- **The Owner receives a file directly:** the report is brought in at once,
  and the copies that come later in Master Data files are recognised.

Reports that were never handed over are sent and imported exactly as
before.

## Not handed over (yet)

- **Withdrawal reports linked to a PO** (Windows): their stock belongs to
  the location's PO lists. Hand-over refuses them with a message.
- **Windows drafts to a phone.** A Windows draft is the raw form of the
  PC program; the app says it is continued on a PC. Save it as a report on
  the PC and hand the completed report over instead. (Phone drafts go to a
  PC; completed reports go both ways.)

## A phone draft on a PC

The PC turns the phone's report record into the Windows data shape exactly
as the app's own Master Data export does
(`fsr_handover.phone_report_data`; the tests compare it with a file the
app's tests write), and then into a Windows draft by filling the form as
for an opened saved report and reading it back. The form the inspector has
open is put back exactly as it was, and nothing is shown in between.

The Windows draft keeps, in `received`, the phone's Control # and the
report's identity (`report_id`, `revision`, location, origin):

- Restoring it puts that number on the form (`fsr_handover.kept_number`).
- Its first save records the identity on that PC as for a received report,
  with the next revision (`fsr_handover.adopt`; for the Owner also in the
  import record). From then on it is the phone's report: handed back to
  the phone, the phone updates its own copy, and in Master Data files the
  Owner recognises it.
- Handed on from that PC as a draft, the number and identity go along
  (`draft.kept`).
- A phone draft of a report the PC already has (from an earlier hand-over)
  is refused: the phone should hand over the completed report instead.

As on any PC save, times and prices are written in the PC's format (for
example `0830H` and `10.00`).

## The file

```json
{"format": "fsr-handover", "version": 1,
 "payload": "<the JSON below, as text>",
 "checksum": "<SHA-256 of the payload text, UTF-8>"}
```

The payload:

| Field | Meaning |
|---|---|
| `handover_id` | Random id of this hand-over (a draft received twice is kept once). |
| `kind` | `report` or `draft`. |
| `app` | `windows` or `android`: the sending app. |
| `created_at`, `from` (`inspector`, `initials`, `device_id`), `to`, `note` | Who handed it over, to whom, when. |
| `report` | A saved report in the Windows data shape (as in Master Data files) with `report_id`, `revision`, `location_id`, `location_name`, `handover_origin` (`device`, `control`). For a Windows draft of a saved report: that saved report. Otherwise `null`. |
| `draft` | Windows: `{"app": "windows", "form", "editing", "control", "source"}` (the raw form), plus `kept` (`control`, `identity`) for a phone draft handed on from a PC. Android: `{"app": "android", "report": <the phone's report>, "identity": {...}}`. `null` for a report. |

`location_id` is `handover:<device of the first sender>` and stays the
same for good. With `report_id` it is the report's identity at the Owner
(`fsr_import.report_location`).

## Kept on each device

- **Windows:** `<workbook>_handovers.json` beside the workbook's other
  side files: report id, Control #, revision, state, to whom, history. It
  is carried along when the workbook moves to the reports database,
  followed by renumbering, and kept out of code backups.
- **Android:** the `handovers` table (database version 2; existing phones
  are migrated, with their reports kept). Phone backups include it.

The Owner's import fingerprint is now taken from the report's content
without its Control #, Last Saved time and identity fields. So a copy that
differs only in its save time counts as the same; fingerprints recorded by
the first Phase 7 build are still recognised.
