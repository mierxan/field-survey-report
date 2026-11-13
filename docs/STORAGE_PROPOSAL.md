# Proposal: SQLite as the store of record, Excel as an export

**Status: proposal only. Nothing here is built.** Written in Phase 3
(13 November 2026) for a decision by the owner, and revisited the same day
for the expected volume of **about 2,000 reports a year** (section 9).
Figures: [PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md).

## 1. Why the question comes up

The Excel workbook is the store of record today: every save opens the whole
workbook, changes one report and writes the whole workbook back. openpyxl
has no way to change one row of a file in place. So the time of every save
grows with the number of reports in the file, whatever is saved:

| Reports in the workbook | One save before Phase 3 | After Phase 3 (lists in the background) |
|---|---|---|
| 300 | 3.4 s | 2.0 s |
| 1,000 | 10.8 s | 4.2 s |
| 2,000 | - | 8.1 s |
| 3,000 | 31.5 s | 12.1 s |
| 4,000 | - | 15.7 s |
| 6,000 | - | 23.4 s |

(Edit of a saved report, MySQL off, invented reports with five item lines
each, this PC. A new report takes about 30% longer. With MySQL on the
window waits the same - MySQL follows in the background.)

Phase 3 removes the waste around the workbook write: the extra reads, the
save-record writes, the waiting for MySQL. What it cannot remove is the
workbook write itself. That one load and one save of the whole file is
what is left, and it keeps growing with the file.

## 2. The proposal

A SQLite database file (`Field_Survey_Reports.fsrdb`) beside the workbook
becomes the store of record. SQLite is one file on the PC, built into
Python, with no server and nothing extra to install.

* **Save** changes only the rows of one report, inside one transaction, and
  is safe against a power cut. It takes milliseconds, whether there are 30
  or 30,000 reports.
* **Excel stays.** The workbook is written from the database in exactly
  today's layout: on request ("Export to Excel"), and automatically a short
  while after the last save, in the background. Anyone who opens the
  workbook in Excel still finds every report.
* Incident texts, other Item List forms, the import record and the MySQL
  ledger move into the same database. They are then saved in the same
  transaction as the report, so the Phase 2 save record is no longer needed
  for them.
* PO_Master and Withdrawn_Item stay Excel files, made from the database.

## 3. What it gains

| | 3,000 reports | 30,000 reports |
|---|---|---|
| One save, today's design after Phase 3 | 17 s (measured) | about 10 times that: minutes per save (estimate) |
| One save, SQLite | under 0.1 s | under 0.1 s |
| Open one report | under 0.1 s (index on Control #) | under 0.1 s |
| Saved reports list, search | under 0.5 s | about 1 s |
| Import 200 reports | about 1 s, one transaction | about 1 s |
| Memory | small | small. openpyxl would hold the whole workbook (tens of MB of file, GBs in memory) - estimate |
| A save cut off by a power cut | SQLite rolls it back by itself | the same |

The 30,000 column is an estimate: I did not build a 30,000-report
workbook. With today's design, at that size every save would take minutes
and may run out of memory on a site PC.

The automatic export would still write the whole workbook. But it runs in
the background after the saves, does not hold anyone up, and does not
decide whether a save succeeded.

## 4. Risks

1. **The workbook is no longer the original.** Today, a change made by hand
   in Excel is read by the program. After the change it would be
   overwritten by the next export.
   *Mitigation:* the export is marked read-only and has a first sheet
   saying "made by the program". A workbook that differs from the last
   export is detected and kept aside as a copy, never overwritten silently.
2. **A new file to look after.** The backups must copy the database
   (SQLite's own backup function, which is safe while the program runs),
   and the Backups folder gets `.fsrdb` copies.
3. **OneDrive or network folders.** A SQLite file that a sync tool copies
   while it is open can be damaged. The database must stay in a local
   folder (Documents\Field Survey Report, as today), not in a synced one.
4. **Size of the change.** Every read and write in fsr_storage,
   fsr_withdrawal, the dashboards and the import moves to the database.
   Errors there touch every report. This needs the same care as Phase 2:
   power-cut tests at every step, and comparing every report before and
   after the migration.
5. **Two formats during the switch.** For one version, the program must
   still open a workbook that has no database (migration, section 5).
6. **Site PCs.** The User edition changes the same way. Site PCs exchange
   data by Master Data files, so the files they send and receive do not
   change.

## 5. Migration

At the first start of the new version, for each workbook:

1. Copy the workbook, the Withdrawal workbook and the JSON files
   unchanged to `Backups\before_sqlite_<date>\`.
2. Read every report once and write all of them into a new database in one
   transaction.
3. Read every report back from the database and compare it with the
   workbook, report by report and field by field (the "equal in value" rule
   of the MySQL guard). One difference: the database is set aside, the
   program carries on with the workbook, and the user is told.
4. Write the export. It must be the same as the original workbook, report
   for report.

Rolling back is easy, because the export has today's layout: the previous
version of the program opens it as it opens any workbook.

Site PCs migrate the same way at their first start, with nothing for the
user to do. Master Data files from not-yet-updated PCs are imported as
today.

## 6. How it fits with MySQL

* The MySQL tables already mirror the report structure (reports,
  item_lines, declared_goods, remarks, incident_reports), so the SQLite
  tables would be nearly the same. Reading and writing MySQL is then a
  table-to-table copy.
* The overwrite guard stays as it is: check and write in one MySQL
  transaction, nothing overwritten that this copy does not own. Its ledger
  moves into the database. Then "is the ledger still current?" is answered
  by a counter in the same transaction as each save, not by comparing file
  times. That removes the kind of fault found on 12 November altogether.
* The background sender stays, and reads the reports to send from the
  database.

### Several PCs writing to one MySQL database

How the guard works now with several copies:

* Every copy owns the reports it wrote. Control #s carry the inspector's
  initials (`FSR-MPR-...`), so two people rarely produce the same number.
* A report changed by another copy is never overwritten; it becomes a
  conflict for a person to decide.
* That is correct, but it is built for **separate** work: each PC enters
  its own reports, and MySQL collects them. If two PCs regularly **edit
  the same** reports, every edit made after the other PC's becomes a
  conflict.

For true shared editing, two further steps would be needed. Neither is
proposed for now:

1. **A version column** in `reports` (`version INT`, plus `written_by_copy`
   as in [TWO_COPIES_ONE_DATABASE.md](TWO_COPIES_ONE_DATABASE.md)). Each
   write says "update if the version is still N". A conflict is then a
   plain fact in MySQL, not a comparison with a local ledger. This is a
   MySQL schema change and needs your approval.
2. **Bringing other PCs' reports in:** each PC's SQLite would also take the
   reports other copies wrote, so every PC sees all reports. That is a sync
   design with its own rules, a phase of its own.

With SQLite, both are easier than with the workbook. Without SQLite they
are not practical: the workbook would have to be rewritten for every
report another PC sends.

## 7. How much work

Roughly as much as Phases 1 and 2 together:

| Part | Size |
|---|---|
| Database layer: tables, read, write, transaction (replacing the workbook part of fsr_storage and fsr_withdrawal) | large |
| Export to Excel in today's layout, in the background, with the read-only marker and change detection | medium |
| Migration with the copy, the comparison and the way back | medium |
| Dashboards, search, saved reports list, PO_Master / Withdrawn_Item from the database | medium |
| MySQL ledger and sender reading from the database | small |
| Tests: every existing test on the new store, power-cut tests, migration of real-shaped data, the 30,000 figure measured | large |

The installers change too. SQLite is part of Python, so nothing new is
installed on the PCs.

## 8. Recommendation (first version, before the volume was known)

*Replaced by section 9.* Not now; plan it as its own phase when it is
needed.

* Today there are 10 reports. After Phase 3 a save takes about 2 s at 300
  reports and 6 s at 1,000, and MySQL no longer adds to it
  ([PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md)).
* Rebuilding PO_Master / Withdrawn_Item in the background would halve the
  wait again before any storage change is needed (PERFORMANCE_BASELINE.md,
  "What limits a save").
* The point to start is when a save at the real number of reports takes
  long enough to bother the inspectors: in the measurements, somewhere past
  1,000 reports. Or when several PCs must share and edit the same reports.
  Whichever comes first.
* Until then, one workbook per year (Change Excel File... at the start of a
  year) keeps every file small, if the yearly number of reports stays in
  the hundreds. The price: the dashboards, the search and the saved reports
  list see only the workbook in use (MySQL still holds all years). Decide
  that before it matters.

When the switch is made, keep the export in today's layout. That one rule
keeps both the way back and the people who read the workbook in Excel.

## 9. At about 2,000 reports a year

### What a save costs

Measured (section 1): every 1,000 reports in the workbook add about
4 seconds to every save - the workbook write itself.

| Reports in the one workbook | When, at 2,000 a year | Save (edit / new report) | Open a report |
|---|---|---|---|
| 2,000 | end of year 1 | 8 s / 11 s | 3 s |
| 4,000 | end of year 2 | 16 s / 21 s | 6 s |
| 6,000 | end of year 3 | 23 s / 31 s | 9 s |

At 2,000 a year (about 8 reports per working day) that is about one and a
half minutes of waiting a day at the end of year 1 and about four by
year 3 - more when reports are edited and saved again - and every wait is
long enough to break the flow of work.

### Three options

| | 1. Keep one workbook | 2. A new workbook each year | 3. SQLite, Excel as an export |
|---|---|---|---|
| Save, year 1 / 3 | 8 / 23 s (end of the year) | at most 8 s, starting at about 0 every January | under 0.1 s, every year |
| Open a report | 3 to 9 s | up to 3 s | under 0.1 s |
| Old years searchable and printable | yes (one file) | **not today**: the program sees one workbook at a time. Needs a search across the year workbooks and opening/printing from a closed year (medium work) | yes (one database) |
| PO_Master: stock received in one year, withdrawn in the next | works | **breaks**: a withdrawal finds only Receiving reports of its own workbook, so stock carried over from last year disappears from PO_Master and from PO-linked withdrawals. Needs the receipts of earlier years to be carried over, or read across years (medium to large work, easy to get wrong) | works |
| The Excel file people open | the real file | the real file of the year | an export, read-only, in today's layout |
| Work | none | medium to large (the two bold points) | large (section 7) |
| Risk | none new; it only gets slower | splitting stock across files - the most error-prone part of the data | the migration (section 5), done once, with a full comparison and a way back |

### Recommendation

**Option 3, SQLite with Excel as an export - decided within the first
three months of real use, built before the workbook reaches about 1,000
reports (about six months at 2,000 a year).**

* Option 1 is fine for the first months and then gets steadily worse;
  by the end of year 2 it is no longer acceptable for daily work.
* Option 2 looks cheap, but making old years searchable and keeping the
  PO stock right across years is about half the work of option 3, and it
  only slows the problem down: each year starts fast and ends at 8 to 11
  seconds again.
* Option 3 removes the cause. It is the larger piece of work, but it is
  done once, and it also makes the questions of several PCs sharing data
  (section 6) easier later.
* **When to decide:** the counter starts when the program goes into daily
  use (today there are 10 reports). Decide by the time the workbook holds
  about 500 reports; then there is time to build, test and migrate it as a
  phase of its own while saves are still 3 to 4 seconds.
* Until then nothing else is needed: Phase 3 keeps a save around 2 to
  4 seconds up to 1,000 reports.

Nothing of this is built. It needs your decision first.

## 10. The storage interface (Phase 4)

Written before any code is moved onto it, for the owner's review.

### Where report data is read and written today

| Module | Reads / writes | Through |
|---|---|---|
| field_survey_report.py (the window) | list, read, write reports (main and Withdrawal workbook), Control #s, incident and item-form files, the save record (13 places), the MySQL ledger (2), renumbering, the backup, the import, the inspector of an imported report | about 20 functions of fsr_storage, fsr_withdrawal, fsr_save_journal, fsr_mysql_guard, fsr_renumber, fsr_backup, fsr_import - never a workbook directly. The one workbook it opens itself is the Weekly Summary **export** (a new file, not report data). |
| fsr_withdrawal_ui.py (PO-linked Withdrawal panel) | the Receiving lines of a PO, the quantity still in stock | fsr_withdrawal.find_po, remaining_quantity |
| fsr_save_journal.py (save record) | every write of a save, the record file | Stores (workbook, incidents, item forms, import record, PO lists, MySQL), Journal |
| fsr_import.py | one read, one batch write, side files, the import record | fsr_storage |
| fsr_renumber.py | the workbooks, JSON files, PO lists | openpyxl directly (it rewrites cells in place) |
| fsr_mysql_guard.py | the MySQL ledger file | its own JSON file |
| warehouse/store.py (dashboards) | all reports of both workbooks | fsr_storage.read_all_reports, fsr_withdrawal.read_all_reports |
| fsr_master_export.py | all reports, the Reports sheet | fsr_storage, and openpyxl for one sheet |
| warehouse/sample_data.py (Demo Mode) | writes and deletes the sample reports | fsr_storage |
| fsr_backup.py | copies the workbook | file copy |

### The interface: `fsr_store.ExcelStore(excel_path, required_root=None)`

One object per data folder. Today's implementation only hands each call
on to the function listed above; nothing is done differently.

| Group | Methods |
|---|---|
| Reports | `list_reports`, `read_report`, `read_all_reports`, `search_index`, `write_report(data, editing, saved_at)`, `write_reports(items)` (one write, all or none), `delete_reports` (Demo Mode only) |
| PO-linked Withdrawal reports | `owns_withdrawal`, `withdrawal_numbers`, `list_withdrawal_reports`, `read_withdrawal_report`, `read_all_withdrawal_reports`, `withdrawal_search_index`, `write_withdrawal_report` |
| PO lines | `find_po`, `remaining_quantity` |
| Control #s | `next_control_number`, `control_numbers`, `next_free_number`, `renumber(old, new)` |
| Beside a report | `save_incidents`, `load_incidents`, `delete_incidents`, `save_item_forms`, `load_item_forms` |
| Derived lists | `rebuild_item_lists` (PO_Master, Withdrawn_Item) |
| Records | `save_record()` (the save record), `save_steps()` (the writes of one save), `mysql_guard(db)` (the ownership ledger), `imported_inspector`, `import_master_data`, `backup_before_save` |

MySQL stays outside: it is the shared copy, written only through the
guard.

### What a SQLite implementation must provide (checklist)

- [ ] Every method above, with the same arguments and the same results
      (the same report dictionaries, the same Control # rules - unique
      across both kinds of report, case-insensitive).
- [ ] `write_report` / `write_reports` in one transaction each: all or
      nothing, as the workbook replace is today.
- [ ] The "Last Saved" time a save chose in advance is stored exactly (to
      the millisecond): the save record recognises a save by it.
- [ ] Incident texts, other Item List forms, the import record, the MySQL
      ledger and the save record as tables in the same database - then a
      save of a report and its side data is one transaction, and the save
      record is only needed for MySQL and the exports.
- [ ] The MySQL ledger's "is it current?" answered by a change counter in
      the database instead of file times.
- [ ] PO_Master and Withdrawn_Item still written as Excel files (people
      open them), from the database, in the background.
- [ ] An Excel export of all reports in today's workbook layout (the way
      back and the file people read), written in the background.
- [ ] `renumber` as one transaction.
- [ ] Backups: SQLite's backup function into the Backups folder.
- [ ] The migration of section 5: copy, read every report once, write,
      compare every report field by field, keep the original.
- [ ] Every existing test run against both implementations (the tests
      take the store as a parameter).

### What the SQLite phase will then involve

With the interface in place, the SQLite phase is one new class
(`SqliteStore`) plus the migration and the export - the window, the save
record and the import do not change. Rough size: about half of section
7's estimate, because the "dashboards, search, saved list" row and most of
the "database layer" row become calls that already exist.
