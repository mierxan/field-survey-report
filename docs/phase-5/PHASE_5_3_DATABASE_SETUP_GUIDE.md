# Phase 5.3 — Database Setup Guide (Owner-Controlled)

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Mode:** Offline preparation. **No MySQL connection, no SQL executed, no database/account created or modified, no real-MySQL tests run.**

The owner performs all database/account creation in MySQL Workbench. This guide provides the exact, non-destructive steps and SQL. The agent only prepared this guide and verified the schema offline.

- **Approved database:** `fsr_phase5_isolated_test`
- **Approved account:** `fsr_phase5@localhost`
- **Protected (never touch):** `field_survey` (production), `field_survey_test` (existing)

---

## 1. Schema verification results

File: `data/schema/fsr_phase5_isolated_test_schema.sql` (12,042 bytes). Offline checks:

| Check | Result |
|---|---|
| File exists | PASS |
| Targets only `fsr_phase5_isolated_test` | PASS (`CREATE DATABASE … fsr_phase5_isolated_test`, `USE fsr_phase5_isolated_test;`) |
| Production DB references in executable SQL | PASS (none; `field_survey` appears only in comments) |
| `DROP DATABASE` / `DROP TABLE` / `TRUNCATE` / `DELETE FROM` | PASS (none) |
| `ALL PRIVILEGES` / `GRANT OPTION` / `*.*` | PASS (none) |
| Tables created | PASS — 7: `reports`, `declared_goods`, `item_lines`, `remarks`, `incident_reports`, `incident_lines`, `master_list` |
| View created | PASS — `v_item_report` |
| Account referenced by the grant | PASS — `'fsr_phase5'@'localhost'` |
| Grant scope | PASS — `GRANT SELECT, INSERT, UPDATE, DELETE ON fsr_phase5_isolated_test.* …` (DML only) |
| Creates a login / embeds a password | PASS (none — the login is created separately by the owner) |
| `master_list` seed data | PASS (`INSERT IGNORE INTO master_list …`) |

---

## 2. Exact owner setup instructions (MySQL Workbench)

Run these steps **as an administrator/root** account in MySQL Workbench (not `fsr_app`, not `fsr_phase5`).

**Step 0 — Confirm the database does NOT already exist (mandatory):**
```sql
SHOW DATABASES LIKE 'fsr_phase5_isolated_test';
```
- If this returns **no rows**, continue.
- If it returns **any row**, **STOP**. Do not reuse, drop, or overwrite the existing database. Report back to the agent.

**Step 1 — Create the restricted test account** (choose a strong password; do not reuse the production `fsr_app` password):
```sql
CREATE USER 'fsr_phase5'@'localhost' IDENTIFIED BY '<CHOOSE-A-STRONG-PASSWORD>';
```
- If the account already exists, use `ALTER USER 'fsr_phase5'@'localhost' IDENTIFIED BY '<password>';` instead.

**Step 2 — Create the dedicated database explicitly** (this **fails** if it already exists, reinforcing Step 0):
```sql
CREATE DATABASE fsr_phase5_isolated_test
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

**Step 3 — Load the generated schema:**
- Workbench: **File ▸ Open SQL Script…** ▸ `data/schema/fsr_phase5_isolated_test_schema.sql` ▸ **lightning bolt** (Execute).
- The script creates the 7 tables + `v_item_report`, seeds `master_list`, and grants DML on the isolated DB to `fsr_phase5`. Its `CREATE DATABASE IF NOT EXISTS` is now a harmless no-op (the DB already exists and is empty).
- Alternatively, run the schema with the MySQL client:
  ```
  mysql -u root -p < data/schema/fsr_phase5_isolated_test_schema.sql
  ```

**Step 4 — Verify** (see §7).

> The schema contains **no** `CREATE USER`, `IDENTIFIED`, or `PASSWORD` — it never creates or changes the login.

---

## 3. SQL statements for owner-controlled execution

```sql
-- Step 0: must return NO rows before continuing
SHOW DATABASES LIKE 'fsr_phase5_isolated_test';

-- Step 1: create the restricted account (choose your own password)
CREATE USER 'fsr_phase5'@'localhost' IDENTIFIED BY '<CHOOSE-A-STRONG-PASSWORD>';

-- Step 2: create the dedicated database (fails if it already exists)
CREATE DATABASE fsr_phase5_isolated_test
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Step 3: run data/schema/fsr_phase5_isolated_test_schema.sql in full.
-- (It performs the USE, table/view creation, seed, and the grant below.)

-- The grant the schema performs (shown for reference; DML only, isolated DB only):
GRANT SELECT, INSERT, UPDATE, DELETE ON fsr_phase5_isolated_test.* TO 'fsr_phase5'@'localhost';
FLUSH PRIVILEGES;
```

---

## 4. Required permissions

| Permission | Scope |
|---|---|
| SELECT, INSERT, UPDATE, DELETE | `fsr_phase5_isolated_test.*` only |

- **No** global privileges (`ON *.*`).
- **No** DDL grants (CREATE/DROP/ALTER) for `fsr_phase5`.
- **No** `GRANT OPTION`.
- **No** access to `field_survey` or `field_survey_test`.

---

## 5. Configuration instructions

Create the dedicated test config (this path is git-ignored; it is separate from the production `db_config.json`):

`data/json/private/db_config.phase5.json`
```json
{
  "enabled": true,
  "host": "localhost",
  "port": 3306,
  "user": "fsr_phase5",
  "password": "<owner enters locally>",
  "database": "fsr_phase5_isolated_test"
}
```
- The password is entered **locally by the owner**; do not send it through chat.
- The production config `data/json/private/db_config.json` must remain untouched.

---

## 6. Environment-variable instructions

The harness requires both variables (fail-closed; no fallback). Set them in the shell that will run the tests:

**PowerShell (current session):**
```powershell
$env:FSR_TEST_DB_NAME   = "fsr_phase5_isolated_test"
$env:FSR_TEST_DB_CONFIG = "D:\Build Build Build\PythonProject\data\json\private\db_config.phase5.json"
```

**Persist for new shells (optional):**
```powershell
setx FSR_TEST_DB_NAME   "fsr_phase5_isolated_test"
setx FSR_TEST_DB_CONFIG "D:\Build Build Build\PythonProject\data\json\private\db_config.phase5.json"
```
- `FSR_TEST_DB_CONFIG` must be an **absolute path** to the dedicated config.
- Missing either variable → the real-MySQL tests **skip** with a clear reason (no fallback to `db_config.json`).

---

## 7. Verification queries

Run as root/admin after loading the schema:

```sql
-- (a) Tables + view: expect 8 rows (7 tables + v_item_report)
SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'fsr_phase5_isolated_test'
 ORDER BY table_name;

-- (b) Grants for the test account: expect exactly two lines —
--     GRANT USAGE ON *.* TO `fsr_phase5`@`localhost`
--     GRANT SELECT, INSERT, UPDATE, DELETE ON `fsr_phase5_isolated_test`.* TO `fsr_phase5`@`localhost`
SHOW GRANTS FOR 'fsr_phase5'@'localhost';

-- (c) master_list seed: expect 7 list_name groups
SELECT list_name, COUNT(*) AS items FROM master_list GROUP BY list_name;
```

Optional (run **as `fsr_phase5`**) to confirm production is inaccessible — this **must fail**:
```sql
SELECT COUNT(*) FROM field_survey.reports;   -- expect ERROR 1142 (SELECT command denied)
```

---

## 8. Rollback precautions (no deletion of existing databases)

- **Never** drop or modify `field_survey` or `field_survey_test`.
- If the isolated setup must be removed, drop **only** the newly created objects, and only after confirming they are the ones you created and hold no data you need:
  ```sql
  -- OPTIONAL — only if you created these and want to remove them:
  -- DROP DATABASE fsr_phase5_isolated_test;
  -- DROP USER 'fsr_phase5'@'localhost';
  ```
  Ensure no application/test connection is open before dropping.
- Prefer leaving the isolated database in place (it is harmless when unused) rather than dropping anything.
- Dropping the account is only safe if nothing else depends on `fsr_phase5`.

---

## 9. Explicit owner authorization requirements for Phase 5.4

Phase 5.4 (running the real-MySQL integration tests) will proceed **only** after the owner:

1. Confirms the Step 0 check returned **no** existing `fsr_phase5_isolated_test` (or, if it existed, that the owner intentionally chose to proceed with it).
2. Confirms the account `fsr_phase5@localhost` was created and the grants are restricted to `fsr_phase5_isolated_test.*`.
3. Confirms the schema loaded and §7(a) shows 7 tables + `v_item_report`.
4. Confirms `data/json/private/db_config.phase5.json` exists and both environment variables are set.
5. **Explicitly authorizes** the agent to run the real-MySQL tests.

When authorized, the agent will run (with the env vars set):
```
pytest tests/test_real_mysql.py tests/test_real_mysql_sqlite.py tests/test_db_mysql_real.py -q
```
These tests write and delete only `FSR-ZZT-2099%` rows in the isolated database; production `field_survey` and `field_survey_test` are never contacted (the harness refuses any other database).

---

**STOP — setup guide delivered. The agent did not connect to MySQL, execute SQL, or create/modify any database or account. Awaiting the owner's completed setup and explicit authorization for Phase 5.4.**