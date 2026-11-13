# Proposal: SQLite as the store of record, Excel as an export

**Status: proposal only. Nothing here is built.** Written in Phase 3
(13 November 2026) for a decision by the owner. Figures:
[PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md).

## 1. Why the question comes up

The Excel workbook is the store of record today: every save opens the whole
workbook, changes one report and writes the whole workbook back. openpyxl
has no way to change one row of a file in place. So the time of every save
grows with the number of reports in the file, whatever is saved:

| Reports in the workbook | One save before Phase 3 | After Phase 3 |
|---|---|---|
| 300 | 3.4 s | 2.2 s |
| 1,000 | 10.8 s | 6.1 s |
| 3,000 | 31.5 s | 17.3 s |

(Edit of a saved report, MySQL off, invented reports with five item lines
each, this PC. With MySQL on, before: 7.8 / 14.6 / 35.4 s; after: the same
as off, MySQL follows in the background.)

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

## 8. Recommendation

**Not now. Plan it as its own phase when it is needed. Measure once a year.**

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
