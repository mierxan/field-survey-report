# Performance: starting figures for Phase 3

Measured on the owner's PC before any performance work, so Phase 3 has
something to compare with.

## One save, on a copy of the real workbook (11 November 2026)

10 reports, workbook 16 KB.

| What | Time |
|---|---|
| Workbook write alone (as before Phase 2) | 107 ms |
| One save with the save record, first version | 261 ms |
| **One save with the save record, exact match (Phase 2 as it stands)** | **202 ms** |

Median of nine saves each (range 190 to 210 ms for the last line). The
first version read the workbook twice more per save; the exact match
(section 4.1 of [DATA_SAFETY.md](DATA_SAFETY.md)) removed both reads. The
remaining 95 ms over the plain workbook write is the record file, which is
written once per step (about five times per save), plus the incident and
item-form files. **202 ms is the starting figure for Phase 3.**

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

695 tests: 578 without the program window in about 4 min, 117 with it in
2 to 3 min.
