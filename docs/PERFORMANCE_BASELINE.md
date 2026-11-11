# Performance: starting figures for Phase 3

Measured on the owner's PC before any performance work, so Phase 3 has
something to compare with.

## One save, on a copy of the real workbook (11 November 2026)

10 reports, workbook 16 KB.

| What | Time |
|---|---|
| Workbook write alone (as before Phase 2) | 108 ms |
| **One save with the save record (Phase 2)** | **261 ms** |

The difference is two extra reads of the workbook (the report's Last Saved
time before and after the write) and the small record file. Proposal 4.1 in
[DATA_SAFETY.md](DATA_SAFETY.md) would remove the two reads.

## Growth with the number of reports (audit, synthetic workbook)

300 reports with five item lines each, workbook write alone:

| Reports in the workbook | Time for one save |
|---|---|
| 1 | 0.08 s |
| 50 | 0.20 s |
| 100 | 0.23 s |
| 200 | 0.38 s |
| 300 | 0.50 s |

Reading all 300 reports: 0.38 s. Listing them: 0.22 s. Every save rewrites
the whole workbook, so the time grows with the file; an import saves once
per report and re-reads the workbook after each one.

## Test suite

687 tests: 570 without the program window in about 4 min, 117 with it in
2 to 3 min.
