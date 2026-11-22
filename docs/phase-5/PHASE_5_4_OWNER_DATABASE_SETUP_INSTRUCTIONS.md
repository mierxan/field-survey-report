# Phase 5.4 — Owner Database Setup Instructions

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **SETUP INSTRUCTIONS READY — AWAITING OWNER EXECUTION**

Offline preparation only. **No MySQL connection, no SQL executed, no database/account created or modified, no source changes, no commits.**

## Confirmed starting state (owner, MySQL Workbench on MYSQL80)
- `SELECT user, host, plugin, account_locked FROM mysql.user WHERE user='fsr_phase5';` → **0 rows** (account missing).
- `SHOW DATABASES LIKE 'fsr_phase5_isolated_test';` → **0 rows** (database missing).

Both must be created. **Protected (never drop/recreate/modify):** `field_survey` (production), `field_survey_test` (existing).

**Two roles are used below:**
- **[ADMIN]** — run as an administrator/root account in Workbench (not `fsr_app`, not `fsr_phase5`).
- **[TEST ACCOUNT]** — run in a **new Workbench connection** opened as `fsr_phase5@localhost`.

---

## 1. Owner checklist (MySQL Workbench)

- [ ] 1. As **[ADMIN]**, `SHOW DATABASES LIKE 'fsr_phase5_isolated_test';` returned **0 rows**.
- [ ] 2. As **[ADMIN]**, `SELECT user, host FROM mysql.user WHERE user='fsr_phase5';` returned **0 rows**.
- [ ] 3. As **[ADMIN]**, created the account `fsr_phase5@localhost`.
- [ ] 4. As **[ADMIN]**, created the database `fsr_phase5_isolated_test`.
- [ ] 5. As **[ADMIN]**, loaded `data/schema/fsr_phase5_isolated_test_schema.sql`.
- [ ] 6. As **[ADMIN]**, verified **7 tables + `v_item_report`** exist.
- [ ] 7. As **[ADMIN]**, verified grants (exactly two lines: `USAGE` + DML on the isolated DB).
- [ ] 8. As **[TEST ACCOUNT]**, `SELECT DATABASE()` = `fsr_phase5_isolated_test` and `USER()` = `fsr_phase5@localhost`.
- [ ] 9. As **[TEST ACCOUNT]**, `SELECT COUNT(*) FROM reports;` works.
- [ ] 10. As **[TEST ACCOUNT]**, `SELECT … FROM field_survey.reports` and `… FROM field_survey_test.reports` both **fail** (error 1142).
- [ ] 11. The password in `data/json/private/db_config.phase5.json` matches the account password.

---

## 2. Execution order (overview)

| Step | Role | Action | Expected |
|---|---|---|---|
| 1 | ADMIN | Confirm DB + account absent | 0 rows each |
| 2 | ADMIN | Create account | Query OK |
| 3 | ADMIN | Create database | Query OK |
| 4 | ADMIN | Load schema (tables/view/seed/grant) | Query OK |
| 5 | ADMIN | Verify tables + view | 7 BASE TABLE + 1 VIEW |
| 6 | ADMIN | Verify grants | 2 lines |
| 7 | TEST ACCOUNT | Verify identity | isolated DB + user |
| 8 | TEST ACCOUNT | Read own data | works |
| 9 | TEST ACCOUNT | Confirm protected DBs denied | error 1142 |

---

## 3. Administrator commands — run as root/admin

```sql
-- [ADMIN] 1. Confirm BOTH are absent (each must return 0 rows). If either returns a row, STOP.
SHOW DATABASES LIKE 'fsr_phase5_isolated_test';
SELECT user, host FROM mysql.user WHERE user = 'fsr_phase5';

-- [ADMIN] 2. Create the restricted account.
--          Type your own strong password in Workbench; do NOT reuse the fsr_app password.
CREATE USER 'fsr_phase5'@'localhost' IDENTIFIED BY '<CHOOSE-A-STRONG-PASSWORD>';

-- [ADMIN] 3. Create the dedicated database (this FAILS if it already exists).
CREATE DATABASE fsr_phase5_isolated_test
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- [ADMIN] 4. Load the schema.
--   Workbench: File > Open SQL Script... > data/schema/fsr_phase5_isolated_test_schema.sql > Execute (lightning bolt).
--   The schema creates the 7 tables + v_item_report, seeds master_list, and runs:
--     GRANT SELECT, INSERT, UPDATE, DELETE ON fsr_phase5_isolated_test.* TO 'fsr_phase5'@'localhost';
--     FLUSH PRIVILEGES;
--   (Its CREATE DATABASE IF NOT EXISTS is now a harmless no-op, because step 3 created the DB.)

-- [ADMIN] 5. Verify tables + view: expect 7 'BASE TABLE' rows + 1 'VIEW' row.
SELECT table_name, table_type
  FROM information_schema.tables
 WHERE table_schema = 'fsr_phase5_isolated_test'
 ORDER BY table_name;

-- [ADMIN] 6. Verify grants: expect exactly two lines —
--   GRANT USAGE ON *.* TO `fsr_phase5`@`localhost`
--   GRANT SELECT, INSERT, UPDATE, DELETE ON `fsr_phase5_isolated_test`.* TO `fsr_phase5`@`localhost`
SHOW GRANTS FOR 'fsr_phase5'@'localhost';
```

> If you prefer to grant manually instead of relying on the schema's grant, run (as ADMIN):
> ```sql
> GRANT SELECT, INSERT, UPDATE, DELETE ON fsr_phase5_isolated_test.* TO 'fsr_phase5'@'localhost';
> FLUSH PRIVILEGES;
> ```
> This is idempotent — running it after the schema is harmless.

---

## 4. Test-account verification — new connection as `fsr_phase5@localhost`

Open a **new** MySQL Workbench connection using user `fsr_phase5` and the password you set, then run:

```sql
-- [TEST ACCOUNT] 7. Identity: expect fsr_phase5_isolated_test / fsr_phase5@localhost / fsr_phase5@localhost
SELECT DATABASE(), USER(), CURRENT_USER();

-- [TEST ACCOUNT] 8. Own data is readable: expect a count (0), no error
SELECT COUNT(*) AS reports FROM reports;

-- [TEST ACCOUNT] 9. Protected DBs must be DENIED (expect ERROR 1142 for both)
SELECT COUNT(*) FROM field_survey.reports;       -- must fail
SELECT COUNT(*) FROM field_survey_test.reports;  -- must fail
```

If step 9 does **not** fail (i.e., the account can read a protected DB), **STOP** and report — the grants are too broad.

---

## 5. Safeguards (mandatory)

- **Preserve** `field_survey` and `field_survey_test`; never `DROP`, `TRUNCATE`, or recreate them.
- The isolated database must be **new** (Step 1 confirms absence). If it exists, **STOP** — do not reuse/drop/overwrite.
- **No** global privileges (`ON *.*`), **no** `ALL PRIVILEGES`, **no** `GRANT OPTION`.
- **No** DDL rights for `fsr_phase5`; DML only (SELECT, INSERT, UPDATE, DELETE) on `fsr_phase5_isolated_test.*`.
- **Do not embed the password** in any `.sql` file, report, or chat. Type it in Workbench and in `data/json/private/db_config.phase5.json` only.
- Do not change the production `fsr_app` account or `db_config.json`.

---

## 6. Done criteria

Setup is complete when: the account exists, the database exists with 7 tables + `v_item_report`, `SHOW GRANTS` shows only `USAGE` + DML on the isolated DB, the `fsr_phase5` connection resolves to `fsr_phase5_isolated_test`, and protected-DB reads fail with error 1142. The password in `data/json/private/db_config.phase5.json` matches the account.

Once complete, the owner re-authorizes Phase 5.4 and the agent runs:
```
pytest tests/test_real_mysql.py tests/test_real_mysql_sqlite.py tests/test_db_mysql_real.py -q
```
with `FSR_TEST_DB_NAME=fsr_phase5_isolated_test` and `FSR_TEST_DB_CONFIG=<absolute path to db_config.phase5.json>`.

---

**STOP — instructions ready. No MySQL connection, no SQL executed, nothing created or changed. Awaiting owner execution and re-authorization.**

**SETUP INSTRUCTIONS READY — AWAITING OWNER EXECUTION**