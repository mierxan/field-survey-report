# Data safety: daily backup and interrupted saves

What Phase 2 (November 2026) added, where the files are, and what to do
when something goes wrong. Code: `fsr_backup.py`, `fsr_save_journal.py`,
`fsr_import.py`.

## 1. Daily backup of the workbook

Before the **first save of each day** the workbook is copied, exactly as it
is before that save, to a folder named `Backups` beside it:

    Documents\Field Survey Report\excel\Backups\
        Field_Survey_Reports_backup_20261112.xlsx
        Field_Survey_Reports_backup_20261111.xlsx
        ...

* The Withdrawal workbook (`Withdrawal_Reports.xlsx`) gets its own backups
  in the same folder the first time it is saved each day.
* The newest **14** backups of each workbook are kept; older ones are
  removed at the next save. To change the number, close the program and add
  `"backup_keep": 30` (any whole number; `0` turns the backup off) to
  `settings.json` in `%APPDATA%\FieldSurveyReport`.
* Only files in that `Backups` folder whose name is exactly
  `<workbook name>_backup_<8 digits>.xlsx` are ever removed. A copy you
  rename, or any other file you put there, is never touched.
* If the backup cannot be made (disk full, folder not writable) the report
  is still saved and a note says: "Today's backup copy of the Excel file
  could NOT be made". It is also written to the log.
* A day on which nothing is saved has no backup; "14" means the last 14
  days on which something was saved.
* Import Master Data keeps making its own copy before an import
  (`..._before_import_<time>.xlsx` beside the workbook), as before.

### Restore a backup

1. Close the program.
2. In `Documents\Field Survey Report\excel`, rename the current
   `Field_Survey_Reports.xlsx` (for example add `_bad` to the name) - do not
   delete it yet.
3. Copy the backup you want out of `Backups` into that folder and rename the
   copy to `Field_Survey_Reports.xlsx`.
4. Start the program and check the reports.

The backup holds the reports themselves. Incident texts and the lines of
the other Item List forms are separate JSON files and are not part of it;
PO_Master and Withdrawn_Item are rebuilt at the next save. On the owner's
PC, use "Sync to MySQL" afterwards if MySQL should match the restored
workbook (it updates and adds; it never deletes from MySQL).

`python fsr_backup.py "<path to the workbook>"` lists the backups with
their dates and sizes.

### Proposed, not built: "Restore from backup..."

A menu item (Owner / Administrator only) that
1. lists the backups with date, size and number of reports,
2. shows which reports the current workbook has that the backup does not
   (they would be lost),
3. asks for confirmation, copies the current workbook to
   `Backups\<name>_before_restore_<time>.xlsx`, then swaps the backup in,
4. rebuilds PO_Master / Withdrawn_Item and offers "Sync to MySQL".

## 2. A save that stops halfway

Saving a report writes several places, one after another: the Excel
workbook, the incident file, the lines of the other Item List forms,
PO_Master / Withdrawn_Item, and (owner's PC) MySQL. Before the first write
the program now notes the save in

    Documents\Field Survey Report\json\Field_Survey_Reports_pending_saves.json

and ticks off each place as it is written. When all are done the note is
removed. A note that is still there - power cut, a file open in Excel,
MySQL not reachable - is finished automatically:

* at the next start of the program,
* after the next save,
* for MySQL: as soon as the status at the top right turns to "Server
  active".

**Which place is right when they disagree?** The Excel workbook. Incident
text and other-form lines exist only in their own files, so for those the
note (the report as you saved it) is used - but only while the workbook
still holds that same save. If the report was saved again in the meantime
(for example by an import), the newer version is kept and the old note is
not applied. PO_Master / Withdrawn_Item and MySQL are always rebuilt from
the workbook.

### What you see

| Situation | Message |
|---|---|
| Excel file open in Excel | "File In Use" - nothing was saved, click Save again (as before). |
| Report saved, but one of the other files could not be written | "Report Saved - Note" names the file and adds "It will also be finished automatically at the next save or the next start." |
| Report saved, MySQL not reachable | No message box. The green notice becomes orange: "Report … saved on this PC - MySQL was not reached; it will be sent at the next save or start". The status shows "Server inactive". |
| MySQL refused the login, a table is missing, ... | "Report Saved - Note: The report was saved to Excel, but NOT to MySQL" with the reason (as before). |
| An unfinished save was completed | "Unfinished Save": "<Control #>: the save of <date> had not finished. It was completed now: <what>." |
| It still cannot be written | "Unfinished Save" (warning): "<what> could still NOT be written (<reason>). It will be tried again at the next save or the next start." |
| The report was saved again since | "Unfinished Save": "The newer version was kept; the unfinished one was not applied." |
| MySQL caught up | Green notice: "MySQL caught up: N report(s) saved earlier on this PC are now in MySQL". |
| The note file itself is damaged | "Unfinished Save" (once): the file was left as it is; saving works as usual. Move the file away to get the protection back. |

### Limits

* How the program knows whether the workbook already holds a save: every
  save chooses its "Last Saved" time before it writes (to the millisecond)
  and the workbook write uses exactly that time. The workbook holding that
  time means it holds that save; an earlier time means the save was never
  written; a later time means the report was saved again since. Two saves of
  the same report seconds apart are told apart exactly.
* That rule compares times of this PC's clock. If the clock is set back
  between two saves of the same report, a newer save can look older.
* A brand-new report (never saved before) whose save stopped before the
  workbook was written is always written by the repair. If its number has
  meanwhile been given to another report, it gets the next free number.
* A report that was removed from the workbook is not brought back by an
  unfinished save. (The program has no "delete report" function outside
  Demo Mode.)
* The official report forms (First Page, Cargo Details) are not part of the
  note; use Print / PDF to make them again.
* Each save writes the small note file several times (once per step):
  about 0.1 s more per save on today's workbook.

## 3. Control # and letter case

`fsr-abc-001` and `FSR-ABC-001` are the same Control # everywhere: Import
Master Data (a report sent again in another case is the same report; a
number already used on this PC in another case counts as taken and the
incoming report gets the next free number), the Withdrawal workbook, the
legacy CSV import, Bad Order case status, and Restore Excel from MySQL.
Nothing in existing files is renamed.

## 4. Proposed, not built

### 4.1 An exact match between a save and the workbook - BUILT

Built on 11 November 2026 (see "Limits" in section 2): the save's chosen
"Last Saved" time is its mark in the workbook. Nothing was added to the
workbook; the save record gained one field, `stamp_planned`. Records
written before that keep the earlier two-minute rule.

### 4.2 A second backup location

The `Backups` folder is on the same disk as the workbook, so it protects
against a bad save or a mistake, not against a lost or broken disk.

Proposal: an optional second folder (a USB drive, a network share, a
synced folder), set in Master Lists and Settings:

* After the daily backup is made, the same file is copied to
  `<second folder>\<PC name>\`, so several PCs can share one folder.
* It keeps its own number of backups (suggested 60), with the same rule:
  only files with the backup's own name pattern are ever removed there.
* The copy runs after the save, in the background, with a time limit - a
  slow network or a sleeping drive never delays a save.
* **When the folder is not available** (USB not plugged in, no network):
  the local backup is made as usual, nothing is lost, and there is no
  message box. A line in the status area says "Second backup: not reachable
  since <date>"; after 3 days without a copy a note is shown once a day.
* When it is reachable again, every local backup that is missing there is
  copied, so the gap closes by itself.
* A "Test" button in the settings writes and removes a small file there.
* "Restore from backup" (proposed in section 1) would list the
  backups of both places.

To decide before building: backups hold business data in plain Excel
files - a USB drive or shared folder should be one only the right people
can open.

### Saving the same report again after an unfinished save

When a save could not finish (PO_Master open in Excel, say) and the SAME
report is saved again, the new save replaces the record of the old one and
does what it still owed. The note of that save says so: "Unfinished Save:
an earlier save of this report had not finished. It was completed now:
PO_Master and Withdrawn_Item." The separate "Unfinished Save" box appears
when ANOTHER report is saved, or at the next start.
