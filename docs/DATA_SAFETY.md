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

* If the PC stops in the instant between the workbook being written and
  that being noted, the program recognises its own write by the time in
  "Last Saved". A different save of the same report within two minutes of
  that instant would be mistaken for it.
* A report that was removed from the workbook after an unfinished save is
  not brought back, except when the workbook write itself had not been
  noted yet - then the save is completed. (The program has no "delete
  report" function outside Demo Mode.)
* The official report forms (First Page, Cargo Details) are not part of the
  note; use Print / PDF to make them again.
* Each save now reads the workbook two more times and writes the small note
  file: about 0.15 s more per save on today's workbook.

## 3. Control # and letter case

`fsr-abc-001` and `FSR-ABC-001` are the same Control # everywhere: Import
Master Data (a report sent again in another case is the same report; a
number already used on this PC in another case counts as taken and the
incoming report gets the next free number), the Withdrawal workbook, the
legacy CSV import, Bad Order case status, and Restore Excel from MySQL.
Nothing in existing files is renamed.
