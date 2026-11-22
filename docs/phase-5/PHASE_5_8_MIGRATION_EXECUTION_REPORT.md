# Phase 5.8 — Migration Execution Report

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **BLOCKED**

Migration **not applied** — the dedicated account lacks the `ALTER` privilege required. **No schema was changed; no protected database was touched; no source code was modified; nothing committed or pushed.**

---

## 1. Pre-migration verification

Connected via the fail-closed harness (`real_mysql.open_database()`), which verifies `SELECT DATABASE()`:

| Check | Result |
|---|---|
| `DATABASE()` | `fsr_phase5_isolated_test` ✅ |
| `USER()` / `CURRENT_USER()` | `fsr_phase5@localhost` / `fsr_phase5@localhost` ✅ |
| `item_lines` columns (before) | 18: `id, control_no, item_list, line_no, description, po_number, packaging, quantity, dimensions, weights, unit_price, total_price, findings, cargo_id, receiving_ref, uom, currency, unit_no` |
| `packing_list_no` present | **No** |
| `origin_line` present | **No** |

Both required columns were missing, so the migration correctly intended to add both.

## 2. Migration executed

File: `data/schema/fsr_phase5_phase5_7_item_lines_migration.sql` (idempotent; fully qualified to `fsr_phase5_isolated_test`; no destructive statements).

The file was read and its statements executed. Execution stopped on the first `ALTER TABLE … ADD COLUMN packing_list_no` with:

- **MySQL error 1142 (42000): `ALTER command denied to user 'fsr_phase5'@'localhost' for table 'item_lines'`**

## 3. Post-migration verification

| Check | Result |
|---|---|
| `item_lines` column count (after) | **18** (unchanged) |
| `packing_list_no` / `origin_line` present | **No / No** (unchanged) |
| Partial change | **None** — the `ALTER` was denied, so no column was added |
| Tables | unchanged (7 base tables + `v_item_report`) |

**No partial application occurred.** The database is exactly as it was before the attempt.

## 4. Root cause

The dedicated account is **DML-only** by design (least privilege):

```
GRANT USAGE ON *.* TO `fsr_phase5`@`localhost`
GRANT SELECT, INSERT, UPDATE, DELETE ON `fsr_phase5_isolated_test`.* TO `fsr_phase5`@`localhost`
```

`ALTER TABLE` requires DDL (`ALTER`) privilege, which this account does **not** have. The migration file itself is valid and idempotent (verified: MySQL accepts the adjacent-string form; the `information_schema` guard works) — the only blocker is privilege.

## 5. Phase 5.5 rerun

**Not performed** — the migration did not apply, so rerunning the integration tests would reproduce the same 2 failures. Per instructions, tests were not run and the database/source were not altered to force a result.

## 6. Protected databases

- **No connection to or modification of `field_survey` or `field_survey_test`.** The harness only connects to `fsr_phase5_isolated_test`.
- No records were written/updated/deleted; no other table was touched.

## 7. Safety

- I did **not** use root or any alternative credentials (forbidden).
- I did **not** grant/alter privileges or accounts.
- I did **not** modify source code, schema, or user records.
- Nothing was committed or pushed.

## 8. Overall status: **BLOCKED**

The migration requires `ALTER` on `fsr_phase5_isolated_test.item_lines`, which the restricted `fsr_phase5` account does not have. Applying it requires an administrator/root account or a temporary privilege grant — both outside this task's authorization.

### Owner action required (to unblock)
Apply `data/schema/fsr_phase5_phase5_7_item_lines_migration.sql` using one of:
- **MySQL Workbench as root/admin** (recommended): open the file and execute; then verify the two columns are `VARCHAR(120) NULL`. No other statement is included.
- **Temporarily grant `ALTER`** to `fsr_phase5` (e.g., `GRANT ALTER ON fsr_phase5_isolated_test.* TO 'fsr_phase5'@'localhost';`), have the agent apply the migration, then revoke `ALTER` to restore DML-only — owner decision.
- Or run the app's **Settings ▸ Upgrade MySQL tables** as an admin (it issues the same `ALTER TABLE … ADD COLUMN`).

After the columns exist, re-authorize Phase 5.5; the agent will re-run the three test files (expected 33 passed) and verify zero residual `FSR-ZZT-2099` rows.

---

**STOP — migration blocked (ALTER denied for the restricted account). No database/schema/source changes; no protected DB touched. Awaiting owner action to apply the migration with sufficient privilege.**