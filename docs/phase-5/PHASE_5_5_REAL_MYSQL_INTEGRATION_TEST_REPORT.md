# Phase 5.5 — Real-MySQL Integration Test Report

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **FAIL** (2 tests failed; 31 passed, 0 skipped)

Real-MySQL integration tests executed against the isolated database `fsr_phase5_isolated_test` (account `fsr_phase5@localhost`) only. **No source code was modified to make tests pass. No protected database was accessed or modified.**

---

## 1. Commands executed (each file run separately)

```powershell
$env:FSR_TEST_DB_NAME   = "fsr_phase5_isolated_test"
$env:FSR_TEST_DB_CONFIG = "D:\Build Build Build\PythonProject\data\json\private\db_config.phase5.json"

.venv\Scripts\python.exe -m pytest tests\test_real_mysql.py        -rs -q --junitxml=test_run_temp\phase55_real_mysql.xml
.venv\Scripts\python.exe -m pytest tests\test_real_mysql_sqlite.py -rs -q --junitxml=test_run_temp\phase55_real_mysql_sqlite.xml
.venv\Scripts\python.exe -m pytest tests\test_db_mysql_real.py     -rs -q --junitxml=test_run_temp\phase55_db_mysql_real.xml
```

## 2. Results per file

| File | Passed | Failed | Skipped | Duration |
|---|---:|---:|---:|---:|
| `tests/test_real_mysql.py` | 16 | 0 | 0 | 158.85 s |
| `tests/test_real_mysql_sqlite.py` | 6 | 0 | 0 | 63.46 s |
| `tests/test_db_mysql_real.py` | 9 | **2** | 0 | 44.12 s |
| **Total** | **31** | **2** | **0** | **~266 s (4:26)** |

No unexpected skips (`SKIPPED: 0` on every file).

## 3. Database identity verification

All connections went through the fail-closed harness (`connect()` → `_checked()` → `SELECT DATABASE()`):
- `DATABASE()` = `fsr_phase5_isolated_test` ✅
- `USER()` = `CURRENT_USER()` = `fsr_phase5@localhost` ✅
- No connection reported any other database identity.

## 4. Failures (2) — root cause

Both failures are in `tests/test_db_mysql_real.py` and share one root cause: the isolated `item_lines` table is **missing two optional shipment columns**, `packing_list_no` and `origin_line`.

| # | Test | Failure |
|---|---|---|
| 1 | `test_the_connection_check_and_the_tables` | `db_mysql.missing_link_columns(conn)` returned `['packing_list_no', 'origin_line']`; test asserts `== []`. |
| 2 | `test_the_shipment_fields_are_kept_and_old_lines_carry_none` | `db_mysql.write_report` returned a note mentioning "Packing List" (column missing); test asserts no such note. |

**Confirmed root cause:**
- `db_mysql.py:48-59` — `LINK_COLUMNS` includes `("Packing List No.", "packing_list_no")` and `("Origin Line", "origin_line")`, with `LINK_COLUMN_SQL` definitions (`VARCHAR(120) NULL`). These are added by `upgrade_schema()` (Settings ▸ Upgrade MySQL tables).
- `data/schema/field_survey_schema.sql` (the repo base schema) includes the earlier link columns (`cargo_id`, `receiving_ref`, `uom`, `currency`, `unit_no`) but **not** `packing_list_no` / `origin_line` — the base schema predates them.
- `data/schema/fsr_phase5_isolated_test_schema.sql` is generated from that base schema, so the isolated DB also lacks the two columns (verified: `item_lines` has 18 columns, none named `packing_list_no`/`origin_line`).

This is a **schema-completeness gap in the repo's base schema**, not a harness or safety failure. (The pre-existing `field_survey_test` database must have been upgraded out-of-band, which is why the same tests passed in the Phase 5.1 audit.)

## 5. Cleanup verification

Post-run, using the dedicated account on the isolated database, residual `FSR-ZZT-2099%` rows:

| Table | Residual |
|---|---:|
| reports | 0 |
| declared_goods | 0 |
| item_lines | 0 |
| remarks | 0 |
| incident_reports | 0 |
| master_list | 0 |

**Cleanup completed; zero residual test-prefix records.** Teardown ran after each module.

## 6. Production / existing-test protection

- **No protected database was modified.** The harness only ever connects to `fsr_phase5_isolated_test`.
- `test_the_test_login_cannot_read_the_real_database` (file 1) passed — it attempted `SELECT … FROM field_survey.reports` and was **denied** (no rows read).
- `field_survey_test` was never accessed.
- No `DROP`/`TRUNCATE`/`ALTER`/recreate was performed on any database.

## 7. Errors, warnings, skipped tests

- **2 failures** (section 4) — schema gap, not a regression in the harness.
- **0 skipped.**
- No other errors.

## 8. Overall status: **FAIL**

31 of 33 tests passed; 2 failed because the isolated schema (generated from the repo's base `field_survey_schema.sql`) is missing `packing_list_no` and `origin_line`. Per instructions, I stopped and did **not** modify source or schema to force a pass.

### Recommended fix (requires owner approval — NOT applied)
1. Update `data/schema/field_survey_schema.sql` `item_lines` to add:
   ```sql
   packing_list_no VARCHAR(120) NULL,
   origin_line     VARCHAR(120) NULL,
   ```
2. Regenerate the isolated schema (`python fsr_test_db_script.py --isolated`) and reload `fsr_phase5_isolated_test` (or run `upgrade_schema()` / Settings ▸ Upgrade MySQL tables against the isolated DB).
3. Re-run Phase 5.5.

Alternatively, run the app's **Settings ▸ Upgrade MySQL tables** against the isolated database to add the two columns, then re-run.

---

**STOP — Phase 5.5 FAIL (2 schema-gap failures). No source/schema changes were made; no protected DB touched; no commits/pushes. Awaiting owner decision on the schema fix before any re-run.**