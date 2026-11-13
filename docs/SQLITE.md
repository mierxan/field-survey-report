# The reports database (Phase 5)

From this version on, the reports of a PC are kept in **one SQLite
database file** beside the Excel file:

```
Field_Survey_Reports.xlsx        the Excel file - now an EXPORT, kept up to date
Field_Survey_Reports.sqlite3     the reports (new)
Withdrawal_Reports.xlsx          the PO-linked Withdrawal reports - also an export
PO_Master.xlsx / Withdrawn_Item.xlsx   as before
```

A save writes one report in one transaction instead of rewriting the
whole workbook: it now takes about 1 to 1.5 seconds whatever the number of
reports (measured at 300, 2,000 and 6,000 reports), against 4 to 39 seconds
with the workbook on the same PC (see
[PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md), Phase 5).
Nothing new is installed: SQLite is part of Python.

What is NOT in the database (unchanged, as files beside it): the incident
texts, the other Item List forms, the import record, the MySQL ownership
ledger, the save record, PO_Master and Withdrawn_Item, the printed forms.
MySQL is unchanged: same tables, same overwrite guard, no schema change.

## 1. What the database holds

Exactly what the two workbooks hold: every row of the Reports, Declared
Goods, Item List and Remarks sheets and of the four sheets of the
Withdrawal workbook, each row as its cells hold it (numbers as numbers,
dates as dates) and in the order of the sheet. The rows are made and read
by the same program code as the workbook's, so every screen shows the same.
A Control # is unique across both kinds of report (enforced by the
database).

## 2. The move, at the first start

At the first start of this version (Owner and User edition alike), with a
progress window "Moving the reports into the database (this is done once)":

1. **Backup.** Both workbooks, PO_Master, Withdrawn_Item and the JSON files
   are copied, unchanged, to `Backups\before_sqlite_<date>_<time>\` beside
   the Excel file.
2. **Copy.** Every row of every sheet goes into a new database.
3. **Compare.** Every report is read from the workbook and from the
   database and compared **field by field**; so are the saved-reports
   list, the search indexes, the Last Saved times and the Control #s. The
   export is written to a temporary folder and compared with the workbook
   **row by row, cell by cell**.
4. Only when everything is equal is the database taken into use. The user
   sees "*N report(s) were moved into the database ...; the Excel file is
   now kept up to date as an export. Everything as it was is in ...*".

**If anything differs**, the program keeps using the workbook exactly as
before, puts the database aside (`.sqlite3.not_used_<time>`) and says so:
"*The reports stay in the Excel file, as before; nothing was changed*",
followed by the first differences (report, field, both values). It does not
try again until the workbook has changed.

It also stays on the workbook, and says why, when the workbook holds
something the export would not keep: a sheet the program did not make,
cells to the right of the program's columns, a formula typed into a cell
(the export keeps values only), a row of the Reports sheet without a
Control #, or two reports with the same Control #. A workbook that is open
in Excel, or that is saved in Excel while the move runs, is tried again at
the next start.

A new PC (no workbook yet) starts with an empty database.

## 3. Every way people use the workbook - and what happens now

| Use | What happens |
|---|---|
| **Opening the Excel file in Excel** (to look, filter, print) | Works as before. The file is the export, in today's layout (same sheets, columns, number formats, tables). It is brought up to date in the background after every save, import, restore or renumbering: within a few seconds (about 13 s at 6,000 reports). |
| **Typing into the Excel file and saving it** (by mistake or on purpose) | The program never overwrites a file that was changed outside it (it notes size, time and SHA-256 of every export). At the next save or start it decides, and says what it did: **(a)** the database has not changed since that export → the file is the newer one and is taken as it is (the database is built again from it, with the full backup and comparison; the old database is kept as `.sqlite3.replaced_<time>`); **(b)** the database has newer reports too → the database stays, the changed file is kept as `Field_Survey_Reports (changed outside <time>).xlsx`, reports that are only in that file are added (nothing is overwritten), reports that differ are listed for a person to check. Nothing is lost either way. |
| **The Excel file is open in Excel while saving** | The save is NOT stopped any more: it goes into the database. The export waits; a notice says once "*The Excel file is open in another program, so it could not be brought up to date yet ...*", and it is tried again every 30 seconds and at each save. |
| **Sending the Excel file to someone** (e-mail, USB) | Works as before: the export holds every report. Close the program first (closing waits until the export is up to date) or wait a few seconds after the last save. |
| **Change Excel File...** | The chosen workbook is moved into its own database the same way (backup, comparison, progress window), the first time it is chosen. A workbook that cannot be moved is used as before. |
| **Restore Excel from MySQL** | Adds the reports from MySQL to the database (nothing is overwritten); the export follows. |
| **Import Master Data / Export Master Data** | Unchanged file format. Works in both directions between this version and the previous one (tested). The copy made before an import is now a copy of the database (`..._before_import_<time>.sqlite3`). |
| **Daily backup** | Before the first save of a day, a copy of the database (`Backups\Field_Survey_Reports_backup_<date>.sqlite3`, made with SQLite's own backup), newest 14 kept, as before. |
| **PO_Master / Withdrawn_Item** | Rebuilt from the database in the background, as before. |
| **MySQL overwrite guard** | Unchanged. Its ledger's note of "the data as the program last left it" is now about the database file, not the export (writing the export does not make the ledger look out of date). A ledger that was current before the move stays current; one that was not stays distrusted. |
| **Weekly Summary, dashboards, Open Saved Report, search** | Read from the database (faster), same results. |
| **Demo Mode** | The demo workbook moves into its own database the same way; the demo reset still deletes only TEST-... reports in a test folder. |

## 4. The way back

* **Going back to the previous version** (uninstall this one, install the
  previous one): the previous version opens `Field_Survey_Reports.xlsx` - the
  export - as its workbook and has every report, including those saved
  since the move. Close this version normally first, so its export is up to
  date (the closing window "*Bringing the Excel file up to date...*" waits
  for it).
* **Coming back to this version later:** it finds the export changed by the
  previous version and the database unchanged since its last export, so it
  takes the Excel file as it is (case (a) above): nothing saved in the
  previous version is lost.
* **Stopping the database by hand** (for support, with the program
  closed): `python fsr_sqlite_migrate.py <workbook> --use-excel-again`
  brings the export up to date and puts the database aside
  (`.sqlite3.retired_<time>`); the workbook is then used as before (this
  version moves it in again at its next start).

## 5. Restoring a backup

Close the program. Copy `Backups\Field_Survey_Reports_backup_<date>.sqlite3`
over `Field_Survey_Reports.sqlite3`. At the next start the export is
written from the restored database, and the MySQL ledger notices the change
(every report counts as not owned, as after restoring a workbook).

The copy taken before the move (`Backups\before_sqlite_...`) holds the
workbooks as they were; to go back to it completely, close the program,
move `Field_Survey_Reports.sqlite3` away and copy the workbooks back.

## 6. The code

| File | |
|---|---|
| `fsr_sqlite_store.py` | `SqliteStore`: every method of `ExcelStore`, same results; one transaction per write |
| `fsr_sqlite_migrate.py` | the move (backup, copy, comparison), an export changed outside, the way back |
| `fsr_sqlite_export.py` | the Excel export in today's layout, and the note of what was written |
| `fsr_store.open_store()` | picks the store: the database once the workbook has moved |
| `tests/test_store_contract.py` | the store contract, run on both stores (unchanged, one line added) |
| `tests/test_sqlite_twin.py` | the same steps on a workbook and a database: every read and every exported row equal |
| `tests/test_sqlite_migrate.py`, `tests/test_sqlite_gui.py` | the move, the cases above, the program on the database |
| `tools/measure_migration.py` | times the move on invented workbooks or a copy of a real one |

`FSR_NO_SQLITE=1` keeps the reports in the workbook (the GUI tests of the
workbook's own behaviour use it).
