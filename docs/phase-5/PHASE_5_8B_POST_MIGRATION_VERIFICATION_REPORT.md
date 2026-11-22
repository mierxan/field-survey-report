# Phase 5.8B — Post-Migration Verification Report

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **FAIL** (migration not present in `fsr_phase5_isolated_test`)

Read-only verification using the dedicated account/configuration only. **No DDL, no privilege changes, no repair, no source/schema changes, no protected-DB access, nothing committed.**

---

## 1. Database identity

| Check | Result |
|---|---|
| `DATABASE()` | `fsr_phase5_isolated_test` ✅ |
| `USER()` / `CURRENT_USER()` | `fsr_phase5@localhost` / `fsr_phase5@localhost` ✅ |

Identity checks passed; no stop was triggered on identity.

## 2. Migrated columns — FAIL

| Check | Expected | Actual | Result |
|---|---|---|---|
| `item_lines` column count | 20 | **18** | ❌ FAIL |
| `packing_list_no` | `VARCHAR(120)`, nullable | **missing** | ❌ FAIL |
| `origin_line` | `VARCHAR(120)`, nullable | **missing** | ❌ FAIL |

The `information_schema.columns` query for `column_name IN ('packing_list_no','origin_line')` returned **no rows**. The migration does **not** appear to have been applied to `fsr_phase5_isolated_test` (still the original 18 columns).

Per instructions, I did **not** attempt to repair or re-apply it.

## 3. Schema integrity

| Check | Result |
|---|---|
| Seven base tables present | ✅ `declared_goods, incident_lines, incident_reports, item_lines, master_list, remarks, reports` |
| `v_item_report` view present | ✅ |
| Unrelated schema changes | None evident (tables/views unchanged) |

The schema is intact, but the two target columns are absent.

## 4. Account grants

```
GRANT USAGE ON *.* TO `fsr_phase5`@`localhost`
GRANT SELECT, INSERT, UPDATE, DELETE ON `fsr_phase5_isolated_test`.* TO `fsr_phase5`@`localhost`
```
DML-only as intended (no `ALTER`). ✅ (This is also why the agent could not apply the migration itself in Phase 5.8.)

## 5. Protected databases

- No connection to or access of `field_survey` or `field_survey_test`.
- No records or schema were changed; no DDL/privilege operations performed.

## 6. Phase 5.5 readiness

**NOT safe to authorize Phase 5.5 rerun yet.** With both columns still missing, `test_the_connection_check_and_the_tables` and `test_the_shipment_fields_are_kept_and_old_lines_carry_none` would fail again (the Phase 5.5 result).

### Likely causes / owner action
The migration was likely applied to a different server/schema or has not yet been run. Please confirm it was executed:
- against **`fsr_phase5_isolated_test`** on **`localhost:3306`** (the same server the config uses), and
- with an account that has `ALTER` (root/admin), and that it completed without error.

To confirm the current state, run (as admin):
```sql
SELECT column_name, column_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema='fsr_phase5_isolated_test' AND table_name='item_lines'
   AND column_name IN ('packing_list_no','origin_line');
```
It must return two rows (`packing_list_no`, `origin_line`, `VARCHAR(120)`, `YES`). Once it does, re-request Phase 5.8B verification and then authorize Phase 5.5.

---

**STOP — verification failed: the two columns are missing from `fsr_phase5_isolated_test.item_lines` (18 columns, no target columns). No repair attempted. Awaiting corrected migration application.**

**Status: FAIL**