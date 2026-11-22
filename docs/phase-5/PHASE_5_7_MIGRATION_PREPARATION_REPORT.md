# Phase 5.7 — Migration Preparation Report

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **PASS**

Preparation only. **No MySQL connection was made and no SQL was executed. No database, account, privilege, or record was modified. Nothing was committed or pushed.**

---

## 1. Objective & confirmed state

Correct the two missing columns in `fsr_phase5_isolated_test.item_lines`:
- `packing_list_no VARCHAR(120) NULL`
- `origin_line VARCHAR(120) NULL`

Phase 5.6 fixed the canonical SQL schemas (`field_survey_schema.sql`, regenerated `field_survey_test_schema.sql` and `fsr_phase5_isolated_test_schema.sql`) and passed 93 offline tests. The **live isolated database has not yet been upgraded** — per the Phase 5.6 report it still lacks both columns. (Current live state was not re-queried, per the no-connection restriction.)

## 2. Exact migration SQL

Artifact: `data/schema/fsr_phase5_phase5_7_item_lines_migration.sql`

The script is **idempotent** (MySQL 8.0 has no `ADD COLUMN IF NOT EXISTS`, so it checks `information_schema.columns` and only alters when a column is missing). Executable statements are **fully qualified** to `fsr_phase5_isolated_test`:

```sql
SELECT DATABASE() AS current_database;   -- expect fsr_phase5_isolated_test

SET @col := 'packing_list_no';
SET @ddl := (SELECT IF(
    (SELECT COUNT(*) FROM information_schema.columns
      WHERE table_schema='fsr_phase5_isolated_test'
        AND table_name='item_lines' AND column_name=@col) = 0,
    'ALTER TABLE `fsr_phase5_isolated_test`.`item_lines` ADD COLUMN `packing_list_no` VARCHAR(120) NULL',
    'SELECT ''packing_list_no already exists'' AS note'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col := 'origin_line';
SET @ddl := (SELECT IF(
    (SELECT COUNT(*) FROM information_schema.columns
      WHERE table_schema='fsr_phase5_isolated_test'
        AND table_name='item_lines' AND column_name=@col) = 0,
    'ALTER TABLE `fsr_phase5_isolated_test`.`item_lines` ADD COLUMN `origin_line` VARCHAR(120) NULL',
    'SELECT ''origin_line already exists'' AS note'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- verify: both columns, VARCHAR(120), NULLable
SELECT column_name, column_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema='fsr_phase5_isolated_test' AND table_name='item_lines'
   AND column_name IN ('packing_list_no','origin_line') ORDER BY column_name;
```

The file also documents the plain (non-idempotent) `ALTER` alternative and warns that it errors on duplicate columns, so the owner must run the existence check first if using it.

## 3. Expected schema (current → final)

- **Current** `item_lines`: 18 columns — `id, control_no, item_list, line_no, description, po_number, packaging, quantity, dimensions, weights, unit_price, total_price, findings, cargo_id, receiving_ref, uom, currency, unit_no`.
- **Final** `item_lines`: 20 columns — the above plus `packing_list_no VARCHAR(120) NULL` and `origin_line VARCHAR(120) NULL`.

No existing column is removed, renamed, or altered; no other table is touched.

## 4. Idempotency assessment

- Each column is added only when `information_schema.columns` shows it missing → **safe to run repeatedly**; a second run issues no `ALTER` (it selects a "already exists" note).
- Missing both → adds both. Missing one → adds only that one. Both present → no change.
- Matches `db_mysql.upgrade_schema()` semantics (same `LINK_COLUMN_SQL` types `VARCHAR(120) NULL`), and `upgrade_schema()` remains idempotent for any other database.
- No destructive statements; no table/database recreation.

## 5. Read-only verification commands

```sql
-- target database
SELECT DATABASE();                              -- fsr_phase5_isolated_test

-- both columns, type, nullability
SELECT column_name, column_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema='fsr_phase5_isolated_test' AND table_name='item_lines'
   AND column_name IN ('packing_list_no','origin_line');

-- full item_lines column list (confirm no unrelated column changed)
SELECT column_name, column_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema='fsr_phase5_isolated_test' AND table_name='item_lines'
 ORDER BY ordinal_position;

-- confirm no other table added/removed
SELECT table_name FROM information_schema.tables
 WHERE table_schema='fsr_phase5_isolated_test' ORDER BY table_name;
```

## 6. Database protection safeguards

- Every executable statement is **fully qualified** to `fsr_phase5_isolated_test.item_lines`; none can affect `field_survey` or `field_survey_test`.
- Only `item_lines` is altered; no other table is touched.
- No `DROP`, `TRUNCATE`, `DELETE`, table recreation, or database recreation.
- Offline scan of the migration file confirmed: **0** destructive statements and **0** protected-DB references in executable SQL; **5** references to the isolated target.

## 7. Confirmation

- **No MySQL connection was made.**
- **No SQL was executed.**
- **No database, account, privilege, or record was modified.**
- No protected database (`field_survey`, `field_survey_test`) was referenced by any executable statement.
- Nothing was committed or pushed.

---

**Overall status: PASS** — migration prepared and verified offline.

**Do not apply yet.** Awaiting explicit owner authorization to execute `data/schema/fsr_phase5_phase5_7_item_lines_migration.sql` against `fsr_phase5_isolated_test` (read-only verification first, then the migration, then re-run Phase 5.5).