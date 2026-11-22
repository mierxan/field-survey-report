# Phase 5.6 — Schema Completeness Fix Report

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **PASS**

Offline code/schema fix + offline tests. **No MySQL database was accessed or modified; no integration tests were run; nothing committed or pushed.**

---

## 1. Confirmed root cause

`db_mysql.py` expects two optional shipment columns on `item_lines`:

- `db_mysql.py:48-52` — `LINK_COLUMNS` includes `("Packing List No.", "packing_list_no")` and `("Origin Line", "origin_line")`.
- `db_mysql.py:53-59` — `LINK_COLUMN_SQL` defines both as `VARCHAR(120) NULL`.
- `db_mysql.py:393-429` — `upgrade_schema()` adds any missing `LINK_COLUMNS` (checks `missing_link_columns()` first, so it is **idempotent**).

The repo's base schema `data/schema/field_survey_schema.sql` contained the earlier link columns (`cargo_id`, `receiving_ref`, `uom`, `currency`, `unit_no`) but **not** the two newer ones (`packing_list_no`, `origin_line`), which were only ever added by `upgrade_schema()`. The generated isolated schema inherited the gap, so Phase 5.5's `test_the_connection_check_and_the_tables` and `test_the_shipment_fields_are_kept_and_old_lines_carry_none` failed.

## 2. Files changed

| File | Change |
|---|---|
| `data/schema/field_survey_schema.sql` | Added `packing_list_no` and `origin_line` to `item_lines` (canonical base schema). |
| `data/schema/field_survey_test_schema.sql` | Regenerated via `python fsr_test_db_script.py` to stay in sync with the base (required by `tests/test_test_copy.py`). |
| `data/schema/fsr_phase5_isolated_test_schema.sql` | Regenerated via `python fsr_test_db_script.py --isolated`; now contains both columns. |
| `tests/test_schema_completeness.py` | **New** — 8 focused offline tests. |

No other files were changed. Existing columns were not removed or renamed.

## 3. Exact schema correction

In `data/schema/field_survey_schema.sql` (`item_lines`), after `unit_no`:
```sql
    packing_list_no VARCHAR(120) NULL,      -- Packing List No. (shipment import)
    origin_line     VARCHAR(120) NULL,      -- Origin Line (shipment import)
```
Types and nullability match `db_mysql.LINK_COLUMN_SQL` (`VARCHAR(120) NULL`).

## 4. Migration compatibility assessment

- **Idempotent:** `upgrade_schema()` calls `missing_link_columns()` first and only issues `ALTER TABLE item_lines ADD COLUMN` for columns not present. Re-running it adds nothing (verified by `test_upgrade_is_idempotent`).
- **Missing both:** `upgrade_schema()` adds both (verified by `test_upgrade_adds_both_when_missing`; also covered by the existing `test_db_mysql.py::test_upgrade_adds_only_missing_columns`).
- **Missing one:** adds only the missing one (verified by `test_upgrade_adds_only_the_missing_one`).
- **Both present:** no `ALTER` issued (`test_missing_link_columns_empty_when_present`; `test_upgrade_is_idempotent`).
- **Types/nullability:** `VARCHAR(120) NULL`, matching the application's expectation.
- **Dependents:** the columns are optional (`NULL`); `write_report` already tolerates their absence (it emits an "Excel only" note when missing), `fsr_shipment`/`fsr_import`/export handle them, and no view/index/query requires them to be non-null. Adding them is backward-compatible.
- **No destructive SQL:** the schema change only adds nullable columns; `upgrade_schema` only adds columns (and, only when needed, widens `control_no`), never drops data.

## 5. Tests executed and results (offline)

```
pytest tests/test_schema_completeness.py tests/test_db_mysql.py tests/test_test_copy.py \
       tests/test_phase5_harness.py tests/test_shipment.py tests/test_shipment_migration.py -q
→ 93 passed, 0 failed, 0 skipped (9.13 s)
```
- `tests/test_schema_completeness.py` (new) → **8 passed** (re-run after lint fix).
- `ruff check` (new + related tests) → **All checks passed!**

New tests cover: base/test/isolated schema define both columns; upgrade adds both when missing; upgrade adds only the missing one; upgrade is idempotent (no duplicate-column ALTERs); `missing_link_columns()` empty when present and reports both when absent.

## 6. No MySQL access or modification

- All tests use **fake connections** (no MySQL server). No real-MySQL tests were run.
- No connection was made to `field_survey`, `field_survey_test`, or `fsr_phase5_isolated_test`.
- No database, account, privilege, or data was modified. The database correction is **not** applied yet.

## 7. Remaining risks

- **The isolated database `fsr_phase5_isolated_test` still lacks the two columns** until the corrected schema is applied to it (reload the schema or run **Settings ▸ Upgrade MySQL tables** / `upgrade_schema()`). This is intentionally deferred to a separate, owner-authorized step.
- The base-schema change should be validated on a fresh database when applied (offline tests only here).
- `data/schema/field_survey_test_schema.sql` was regenerated (tracked file changed) to keep it consistent with the base; the protected `field_survey_test` **database** was not touched.

## 8. Recommended next step

1. Owner applies the corrected schema to the isolated DB (reload `fsr_phase5_isolated_test_schema.sql` into `fsr_phase5_isolated_test`, or run the app's **Upgrade MySQL tables** against it) — separate, authorized step.
2. Re-run Phase 5.5 (`test_real_mysql.py`, `test_real_mysql_sqlite.py`, `test_db_mysql_real.py`) against the isolated DB.
3. Commit the schema + test changes when the owner is ready (not done here).

---

**STOP — code/schema fix complete and verified offline (PASS). No database was accessed or modified. Database application and Phase 5.5 retesting are separate, owner-authorized steps.**

**Status: PASS**