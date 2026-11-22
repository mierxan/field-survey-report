# Phase 6.1 — Full Regression and Coverage Report

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **PASS** (1460 passed, 0 failed, 0 errors, 33 skipped; Ruff clean)

Full offline regression + fresh coverage baseline after the Phase 5 changes. **No MySQL connection, no DDL/DML, no source/schema changes, nothing staged/committed/pushed.**

---

## 1. Git branch and working-tree status

- Branch: `improvements/excel-dashboard`
- Working tree (unchanged by this phase): 6 modified files (schema fix + Phase 5.2 harness/tests) + untracked new files (`data/schema/fsr_phase5_isolated_test_schema.sql`, `data/schema/fsr_phase5_phase5_7_item_lines_migration.sql`, `tests/test_phase5_harness.py`, `tests/test_schema_completeness.py`, `docs/phase-5/`). No reset/stash/clean performed.

## 2. Test environment

- Windows, Python 3.14.4, project `.venv`.
- **Phase 5 MySQL env vars explicitly removed** from the test process: `FSR_TEST_DB_NAME` and `FSR_TEST_DB_CONFIG` were deleted from the environment before the run (verified empty), so the fail-closed harness cannot connect to MySQL and the real-MySQL tests skip.

## 3. Exact test commands

```powershell
Remove-Item Env:FSR_TEST_DB_NAME,Env:FSR_TEST_DB_CONFIG -ErrorAction SilentlyContinue
$env:PYTHONUNBUFFERED = "1"
.venv\Scripts\python.exe -m pytest -rs -q --cov --cov-report=term `
    --cov-report=json:test_run_temp/coverage_phase6.json `
    --junitxml=test_run_temp/phase6_full.xml
.venv\Scripts\python.exe -m ruff check .
```

## 4. Full test results

| Metric | Value |
|---|---|
| Tests collected | 1493 |
| Passed | **1460** |
| Failed | **0** |
| Errors | **0** |
| Skipped | **33** |
| Duration | 974.71 s (16:14) |

(The suite grew from 1461 to 1493 with the Phase 5.2 `test_phase5_harness.py` (+24) and Phase 5.6 `test_schema_completeness.py` (+8) tests.)

## 5. Skipped-test explanations

All **33 skips** are the three real-MySQL files (`test_real_mysql.py` 16, `test_real_mysql_sqlite.py` 6, `test_db_mysql_real.py` 11), each with reason:

> `the isolated test database fsr_phase5_isolated_test is not available: FSR_TEST_DB_NAME is not set`

This is the **intended fail-closed behaviour** — the env vars were deliberately disabled so no database connection could occur. The 318 GUI tests were **not** skipped; they ran and passed (part of the 1460).

## 6. Coverage statistics (new baseline)

- **Overall: 86.5%** — 18,141 covered / 20,966 statements / 2,825 missing.

Module-level (key modules):

| Module | Stmts | Miss | Cov% |
|---|---:|---:|---:|
| `field_survey_report.py` | 3522 | 787 | 77.7% |
| `app_auth.py` | 1140 | 86 | 92.5% |
| `db_mysql.py` | 516 | 187 | 63.8% |
| `fsr_storage.py` | 769 | 48 | 93.8% |
| `fsr_import.py` | 764 | 54 | 92.9% |
| `fsr_sqlite_store.py` | 483 | 29 | 94.0% |
| `fsr_mysql_guard.py` | 404 | 32 | 92.1% |
| `fsr_deletions.py` | 160 | 20 | 87.5% |
| `fsr_open_dialog.py` | 219 | 44 | 79.9% |
| `fsr_test_db_script.py` | 42 | 9 | 78.6% |

## 7. Historical coverage comparison

| | Statements | Covered | Missing | Pct |
|---|---:|---:|---:|---:|
| Baseline (Phase 4.1) | 20,948 | 18,260 | 2,688 | 87.2% |
| New (Phase 6.1) | 20,966 | 18,141 | 2,825 | 86.5% |
| **Delta** | +18 | −119 | +137 | **−0.6 pts** |

**Explanation (not a regression):**
- **`db_mysql.py` 88.6% → 63.8%** (missing 59 → 187; +128 newly-uncovered lines at 248, 289–298, 498, 691–1013). These are the **real-server connection/transaction/write paths**, exercised only by the real-MySQL tests — which were intentionally skipped here. This single file accounts for the coverage drop.
- **`fsr_test_db_script.py` 24 → 42 stmts** (78.6%): new `build_for`/`build_isolated`/`main` code from Phase 5.2; partially exercised by tests (some new statements uncovered).
- `fsr_mysql_guard.py` −1.2 pt: minor (a few real-DB-dependent branches).

The −0.6 pt overall change is a **measurement difference from skipping the real-MySQL tests**, not a loss of tested application logic. (With the real-MySQL tests enabled, `db_mysql.py` returns to ~88%.)

## 8. Ruff results

`ruff check .` → **All checks passed!** (no fixes/reformats applied).

## 9. Regression findings

No regressions in tested functionality. All 1460 non-skipped tests pass, including:
- **MySQL schema-generation compatibility:** `test_test_copy.py` (on-disk test schema matches generator) and `test_schema_completeness.py` (base/test/isolated schemas contain `packing_list_no`/`origin_line`; upgrade idempotent) pass.
- **SQLite operations:** `test_sqlite_migrate.py`, `test_sqlite_twin.py`, `test_sqlite_export.py`, `test_sqlite_gui.py` pass.
- **Report creation/editing, import/export, shipment:** `test_shipment.py`, `test_shipment_migration.py`, import/export tests pass.
- **PDF/print, dashboard, warehouse, auth/storage:** GUI and non-GUI suites pass (318 GUI included).

**Not covered in this run (by design):** real-MySQL integration (33 skipped). That was validated separately in Phase 5.5 (33 passed, 0 residual).

## 10. Confirmation — no MySQL connection

- `FSR_TEST_DB_NAME`/`FSR_TEST_DB_CONFIG` were removed from the process before the run.
- The only tests that connect to MySQL are the three real-MySQL files; they **skipped** at `settings()` (fail-closed) before any connection.
- **No MySQL connection was made.** No DDL/DML executed; no database/account/privilege touched.

## 11. Confirmation — no source/schema changes

- This phase only ran tests and produced the report. **No application source, schema, test, or config file was modified.** No staging/commit/push.

---

**Overall status: PASS.** Full offline regression green (1460 passed, 0 failed, 33 expected skips), Ruff clean, coverage 86.5% (explained vs 87.2% baseline by the intentionally skipped real-MySQL tests). No MySQL access, no source/schema changes.

**STOP — report complete.**