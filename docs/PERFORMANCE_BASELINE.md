# Performance: figures before and after Phase 3

Measured on the owner's PC. Invented workbooks of 300, 1,000 and 3,000
reports (five item lines each, two thirds Receiving), and a copy of the real
workbook (16 KB; the copy was deleted afterwards). Tool:
`tools/measure_performance.py`, which drives the real program, as the GUI
tests do, on copies.

* **Before** = the Phase 2 branch at `d36a924`; **after** = the Phase 3
  branch at `b7a163b`. Each was measured from its own git worktree, so
  later edits could not creep in.
* Time = median of 3 runs: the time until the program hands the window
  back. "Until done" also counts what still runs in the background
  afterwards (MySQL, the dashboards reading the workbook again, an import).
* MySQL on = against the test database `field_survey_test` on this PC.
  Opening one connection takes about **2 seconds** here.

## The starting figure

**202 ms**: one save on a copy of the real workbook (10 reports), storage
part only, measured on 11 November (below, unchanged). The figures that
follow are for the whole Save of the program: the form, the report forms,
PO_Master and Withdrawn_Item. So they are larger.

## Save, open (MySQL off)

Before and after were measured one after the other, on a quiet PC, on the
same workbooks.

| Reports | Open a report | Save, edit: before → after | Save, new report: before → after |
|---|---|---|---|
| real copy (16 KB) | 0.17 s → 0.16 s | 0.44 s → **0.35 s** | 0.48 s → **0.40 s** |
| 300 | 0.53 s → 0.51 s | 3.4 s → **2.2 s** | 4.0 s → **2.6 s** |
| 1,000 | 1.5 s → 1.5 s | 10.8 s → **6.1 s** | 11.7 s → **8.0 s** |
| 3,000 | 4.1 s → 4.1 s | 31.5 s → **17.3 s** | 35.2 s → **21.1 s** |

Workbook loads and writes per save:

| | Before | After |
|---|---|---|
| Main workbook loaded | 6 (edit), 7 (new) | 2 (edit), 3 (new) in the save, plus 1 by the dashboards afterwards, in the background |
| Main workbook written | 1 | 1 |
| PO_Master loaded / written, Withdrawn_Item written | 1 / 1, 1 | 1 / 1, 1 |
| Save record written | about 7 | 2 (edit), 3 (new report) |

## Save with MySQL on

| Reports | Before: save (edit / new) | After: save (edit / new) | After: until in MySQL |
|---|---|---|---|
| 300 | 7.8 s / 10.3 s | **2.2 s / 2.7 s** | 5.2 s / 5.4 s |
| 1,000 | 14.6 s / 18.1 s | **6.1 s / 7.8 s** | 10.4 s / 11.9 s |
| 3,000 | 35.4 s / 41.4 s | **17.2 s / 21.0 s** | 22.9 s / 26.9 s |

* **Before**, the window waited for MySQL. An edit opened **2**
  connections (the guard's check and write, the master lists): about 4.1 s
  of the save. A new report opened **3** (also the number check): about
  6.2 s.
* **After**, the window waits for nothing from MySQL: the save takes the
  same time as with MySQL off. **One** connection is opened, in the
  background, for the report and the master lists together. The report is
  in MySQL about 3 to 6 seconds after the window was handed back.

## Import Master Data (MySQL off)

| Reports in the workbook | Import 1 / 50 / 200: before | After (until done) |
|---|---|---|
| real copy | 0.15 s / 10 s / 91 s | 1.4 s / 3.0 s / 6.2 s |
| 300 | 3.2 s / 141 s / 291 s | 7.0 s / 8.7 s / 15.3 s |
| 1,000 | 4.8 s / 186 s / 1,156 s (19 min) | 21 s / 24 s / 40 s |
| 3,000 | 14.5 s / 717 s (12 min) / not measured, see below | 60 s / 71 s / 109 s |

| | Before | After |
|---|---|---|
| Main workbook loaded / written, 50 reports | 102 / 50 | 2 / 1 (plus 1 read to rebuild PO_Master and 1 by the dashboards) |
| Main workbook loaded / written, 200 reports | 402 / 200 | the same: 2 / 1 |
| Save record written | not used | 2 |
| PO_Master / Withdrawn_Item | not updated by the import | rebuilt once |
| The window during an import | frozen | responsive, with a progress window |

* Before, an import saved once per report and read the workbook again
  after each one: the time grew with the workbook *times* the number of
  reports. Importing 200 at 3,000 was not measured to the end. A first
  attempt ran overnight while the PC slept and the counts were right (401
  loads, 200 writes), but its time cannot be used. From the 50-report
  figure it would take about an hour.
* After, the time depends little on the number of reports. Most of it is
  the one workbook write and the PO_Master rebuild.
* **One report at 3,000 now takes longer: 60 s instead of 14.5 s.** The
  import now also rebuilds PO_Master and Withdrawn_Item, which the old
  import did not do (they stayed out of date until the next Receiving
  save). The "until done" figure also includes the dashboards reading the
  workbook again afterwards. Meanwhile the window stays usable, with the
  progress shown.
* The old import failed with "File In Use" when it came straight after
  another save or import of a workbook with a few hundred reports. Fixed on
  the Phase 2 branch (the program's own background reading held the file
  open).

## After the background rebuild of PO_Master / Withdrawn_Item

Measured on 13 November 2026 (commit `11b09d6`), MySQL off, quiet PC,
invented workbooks of five item lines per report. "Lists up to date" =
until the background rebuild of PO_Master and Withdrawn_Item has finished.

| Reports (file size) | Open | Save, edit | Save, new report | Lists up to date (edit) |
|---|---|---|---|---|
| 300 (136 KB) | 0.5 s | 2.0 s | 2.4 s | 2.6 s |
| 1,000 (424 KB) | 1.5 s | 4.2 s | 5.6 s | 7.5 s |
| 2,000 (834 KB) | 2.8 s | 8.1 s | 10.7 s | 14.7 s |
| 3,000 (1.2 MB) | 4.2 s | 12.1 s | 16.0 s | 22.0 s |
| 4,000 (1.6 MB) | 5.6 s | 15.7 s | 21.3 s | 29.5 s |
| 6,000 (2.4 MB) | 8.6 s | 23.4 s | 30.7 s | 44.4 s |

At 3,000 reports an edit save went from 17.3 s to 12.1 s - less than
half, because the rest of the save (the report forms, the dashboards) runs
while the rebuild does, and Python lets only one of them compute at a
time. A save now grows by about 4 seconds per 1,000 reports in the
workbook: that is the workbook write itself.

## What limited a save at 3,000 reports (before the background rebuild)

Profiled for one save (in tenths):

* **about 4/10: the workbook write.** openpyxl loads the whole file (about
  4 s), changes one report and writes the whole file back (about 7 s).
* **about 6/10: PO_Master and Withdrawn_Item.** One read of all reports,
  then both list files rewritten, PO_Master with about 10,000 lines.
* The rest - the save record, the incident files, the report forms, the
  backup check - is well under a second.

What could still be done without changing the storage:

1. **Rebuild PO_Master / Withdrawn_Item in the background**, as MySQL now
   is - built since (see above).
2. Writing the lists in openpyxl's write-only mode was tried and was
   **slower** (10.0 s against 5.6 s for 10,000 lines), so it was not kept.
3. Nothing short of a different store removes the workbook write itself:
   openpyxl cannot change one row in place. See
   [STORAGE_PROPOSAL.md](STORAGE_PROPOSAL.md).

## Earlier figures (kept for reference)

### One save on a copy of the real workbook (11 November 2026)

10 reports, workbook 16 KB, storage part only.

| What | Time |
|---|---|
| Workbook write alone (as before Phase 2) | 107 ms |
| One save with the save record, first version | 261 ms |
| One save with the save record, exact match (Phase 2) | 202 ms |

### Growth with the number of reports (audit, synthetic workbook)

300 reports with five item lines each, workbook write alone:

| Reports in the workbook | Time for one save |
|---|---|
| 1 | 0.08 s |
| 50 | 0.20 s |
| 100 | 0.23 s |
| 200 | 0.38 s |
| 300 | 0.50 s |

## How the figures are guarded

Tests count instead of timing, so a slow PC cannot fail them:
`tests/test_phase3_counts.py` (workbook loads and writes, save-record
writes per save), `tests/test_import_batch.py` (one load and one write per
import, at 1, 50 and 200 reports), `tests/test_mysql_background*.py` and
`tests/test_real_mysql.py` (one MySQL connection per round, also against
the real test database).
