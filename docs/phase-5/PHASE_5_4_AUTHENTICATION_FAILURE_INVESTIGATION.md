# Phase 5.4 — Authentication Failure Investigation

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **ACCOUNT MISSING — OWNER SETUP REQUIRED**

**Scope:** Offline analysis of the Phase 5.4 authentication failure. **No MySQL connection, no SQL executed, no database/account creation, no privilege/password changes, no source changes, no commits.**

---

## 1. Confirmed finding

The owner ran the following in MySQL Workbench against the `MYSQL80` server:

```sql
SELECT user, host, plugin, account_locked
FROM mysql.user
WHERE user = 'fsr_phase5';
```

Result: **0 row(s) returned.**

**Conclusion:** the expected account **`fsr_phase5` does not exist** on the inspected MySQL server. This is a confirmed, owner-supplied finding.

## 2. Consistency with MySQL error 1045

The Phase 5.4 harness attempt failed with **MySQL error 1045 (Access denied)** for `fsr_phase5`. This is **consistent** with the account being absent:

- MySQL returns **1045** for *both* a wrong password *and* a non-existent user, deliberately not disclosing which, to avoid leaking account existence.
- The dedicated configuration was verified correct (`user=fsr_phase5`, `database=fsr_phase5_isolated_test`, password present, `host=localhost`, `port=3306`).
- Therefore the failure is explained by the missing account, not by the configuration.

## 3. Database existence — NOT assumed

This investigation does **not** assume `fsr_phase5_isolated_test` exists. The owner must verify database existence **separately** (the earlier 0-row result was for the *account*, not the database):

```sql
SHOW DATABASES LIKE 'fsr_phase5_isolated_test';
```

- If this returns **no rows**, the database does not exist and must be created (step 3 below).
- If it returns a row, the owner must confirm it is the intended new/empty isolated database (do not reuse/drop/overwrite an unknown database).

## 4. Required owner setup (from the Phase 5.3 setup guide)

Run as an administrator/root account in MySQL Workbench. **Do not** run any statement that drops or overwrites `field_survey` or `field_survey_test`.

**Step A — Verify the database does NOT already exist:**
```sql
SHOW DATABASES LIKE 'fsr_phase5_isolated_test';
```

**Step B — Create the restricted account** (choose a strong password; do not reuse the production `fsr_app` password):
```sql
CREATE USER 'fsr_phase5'@'localhost' IDENTIFIED BY '<CHOOSE-A-STRONG-PASSWORD>';
```

**Step C — Create the database (only if Step A returned no rows):**
```sql
CREATE DATABASE fsr_phase5_isolated_test
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

**Step D — Grant only the required DML, scoped to the isolated database:**
```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON fsr_phase5_isolated_test.* TO 'fsr_phase5'@'localhost';
FLUSH PRIVILEGES;
```
*(The generated schema `data/schema/fsr_phase5_isolated_test_schema.sql` also performs this grant and creates the 7 tables + `v_item_report`; create the account first, then run the schema, or run Steps B–D then the schema.)*

**Step E — Verify:**
```sql
SHOW GRANTS FOR 'fsr_phase5'@'localhost';
-- expected (two lines):
--   GRANT USAGE ON *.* TO `fsr_phase5`@`localhost`
--   GRANT SELECT, INSERT, UPDATE, DELETE ON `fsr_phase5_isolated_test`.* TO `fsr_phase5`@`localhost`
```

**Permissions:** SELECT, INSERT, UPDATE, DELETE on `fsr_phase5_isolated_test.*` only. **No** global privileges, **no** DDL for `fsr_phase5`, **no** `GRANT OPTION`, **no** access to `field_survey` or `field_survey_test`.

**Password/config alignment:** ensure the password in `data/json/private/db_config.phase5.json` exactly matches the password set in Step B. If the account already exists with a different password, use `ALTER USER 'fsr_phase5'@'localhost' IDENTIFIED BY '<password>';` and update the config to match.

## 5. Configuration status (from prior investigation)

The dedicated configuration is already correct and does not need changing (only the account is missing):

| Field | Value |
|---|---|
| host | `localhost` |
| port | `3306` |
| user | `fsr_phase5` |
| database | `fsr_phase5_isolated_test` |
| password | present (non-empty; never displayed) |

## 6. Safety

No MySQL connection was made in this investigation, no SQL was executed, no database or account was created or modified, no password/privilege change was made, no source code was changed, and nothing was committed or pushed. The `field_survey` and `field_survey_test` databases were not accessed.

---

**STOP — account `fsr_phase5` is missing (confirmed). Owner must create the account (and verify the isolated database exists) using the steps above, then re-authorize Phase 5.4.**

**Status: ACCOUNT MISSING — OWNER SETUP REQUIRED**