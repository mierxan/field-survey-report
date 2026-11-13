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

and, when the save on this PC is done, notes what is still open. When all
are done the note is removed. A note that is still there - power cut, a
file open in Excel, MySQL not reachable - is finished automatically:

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
| Report saved (owner's PC) | Green notice "Report … saved on this PC … Sending it to MySQL...", then, a moment later, "Report … is now in MySQL". Beside the MySQL circles: "Sending 1 to MySQL..." while it is on its way. The window does not wait (Phase 3). |
| PO_Master / Withdrawn_Item (Receiving and PO-linked reports) | Rebuilt in the background a moment after the save (Phase 3). When done, the status bar says "PO_Master and Withdrawn_Item are up to date (HH:MM)". |
| PO_Master or Withdrawn_Item open in Excel | One box "PO_Master - Not Updated: … open in another program (Excel?). Close it; both lists are updated at the next save or the next start." Not repeated after every save; the lists are rebuilt as soon as they can be. |
| Report saved, MySQL not reachable | No message box. An orange notice: "MySQL was not reached - N report(s) saved on this PC wait; they are sent at the next save or start". Beside the circles: "N waiting for MySQL". The status shows "Server inactive". |
| MySQL refused the login, a table is missing, ... | "MySQL - Not Updated": the reports are saved on this PC but not in MySQL, with the reason. |
| An import was cut off before the Excel file was written | "Unfinished Save": "The import of N report(s) ... was cut off before the Excel file was changed. NOTHING was imported; import the file again." |
| An import was cut off after the Excel file was written | "Unfinished Save": "The import of N report(s) ... had not finished. The Excel file already held all of them; it was completed now: ... Everything was imported." |
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
* The note is written twice per save (three times for a new report), not
  once per step: every step can be repeated, so a save cut off between two
  steps simply has those steps done again at the next start. (Phase 3; it
  was about seven writes.)
* MySQL is sent in the background (Phase 3). The step is ticked off only
  after MySQL has committed. A program closed, or a PC losing power, while
  a report is on its way leaves the step open; at the next start the report
  is sent again, and the overwrite guard finds MySQL either without it
  (written then) or equal to it (nothing written, it counts as this copy's
  own). Closing the program while a report is on its way shows a small
  window, "Sending N report(s) to MySQL...", which closes by itself when the
  send is done (at most 8 seconds) and has a button "Close now; it will be
  sent at the next start". The program keeps responding meanwhile.
* PO_Master and Withdrawn_Item are rebuilt in the background (Phase 3):
  once for every save waiting for it, and only those saves whose report
  was in the workbook when the rebuild read it are ticked off. Each list
  file is replaced as a whole, so a rebuild cut off midway (program
  closed, power cut) leaves the previous lists and its saves open; the
  next start rebuilds them. Closing the program does not wait for it.
* An import is written into the workbook in ONE write for the whole file
  (Phase 3). The file is replaced as a whole, so it holds either every
  report of the import or none, and the note says which.

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
