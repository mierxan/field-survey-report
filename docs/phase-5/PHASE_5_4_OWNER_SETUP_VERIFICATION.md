# Phase 5.4 — Owner Setup Verification

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **FAIL — login rejected (MySQL 1045)**

Offline/DB verification only. **No integration tests run, no database/account/privilege changes, no secrets displayed.**

## 1. What was attempted

The agent connected using the isolated configuration through the fail-closed harness (`real_mysql.open_database()`), with:
- `FSR_TEST_DB_NAME = fsr_phase5_isolated_test`
- `FSR_TEST_DB_CONFIG = D:\Build Build Build\PythonProject\data\json\private\db_config.phase5.json`

## 2. Verification results

| # | Check | Result |
|---|---|---|
| 1 | Database identity (`SELECT DATABASE()`) | ⏸ **BLOCKED** — no connection |
| 2 | Account identity + host (`USER()`, `CURRENT_USER()`) | ❌ **FAIL** — login rejected |
| 3 | Seven tables + `v_item_report` | ⏸ **BLOCKED** — no connection |
| 4 | DML-only privileges | ⏸ **BLOCKED** — no connection |
| 5 | Successful test-account login | ❌ **FAIL** — MySQL error 1045 |
| 6 | Production (`field_survey`) access denied | ⏸ **BLOCKED** — no connection |
| 7 | Existing (`field_survey_test`) access denied | ⏸ **BLOCKED** — no connection |

## 3. Exact failure

- **Error:** MySQL **1045 (Access denied)** for user `fsr_phase5` at `localhost`.
- **Config side:** verified valid — `host=localhost`, `port=3306`, `user=fsr_phase5`, `database=fsr_phase5_isolated_test`, password present (non-empty; never displayed). The harness read the config successfully; the failure is at MySQL authentication.
- **Interpretation:** MySQL rejected the login. The account either does not exist for this host, is locked, or the password in the config does not match the account password.

## 4. Owner action required (MySQL Workbench, as root/admin)

1. Confirm the account exists and note its host and lock state:
   ```sql
   SELECT user, host, plugin, account_locked
     FROM mysql.user
    WHERE user = 'fsr_phase5';
   ```
2. Confirm the password in `data/json/private/db_config.phase5.json` matches the account. To reset it and align the config:
   ```sql
   ALTER USER 'fsr_phase5'@'localhost' IDENTIFIED BY '<same-password-as-config>';
   FLUSH PRIVILEGES;
   ```
3. Ensure the account host matches how the app connects. The config uses `host = localhost`; if the account is `'fsr_phase5'@'%'` only, either create `'fsr_phase5'@'localhost'` or align the config host accordingly.
4. Ensure `account_locked = 'N'` (unlock if needed: `ALTER USER 'fsr_phase5'@'localhost' ACCOUNT UNLOCK;`).
5. Re-run the setup verification (the agent will retry the connection and, if it succeeds, verify database identity, 7 tables + view, DML-only grants, and that `field_survey` / `field_survey_test` reads are denied).

## 5. Not performed

- No integration tests were run.
- No schema/privilege verification was possible (no successful connection).
- No database, account, privilege, or configuration was modified.
- No production or existing test database was accessed (connection failed before any query).
- No credentials were displayed or logged.

---

**STOP — setup verification FAILED at login (MySQL 1045). Awaiting owner correction of the `fsr_phase5` account/password/host, then re-verification.**

**Status: FAIL — OWNER ACTION REQUIRED**