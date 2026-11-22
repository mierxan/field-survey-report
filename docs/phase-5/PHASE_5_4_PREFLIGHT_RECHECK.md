# Phase 5.4 — Preflight Recheck

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Mode:** Offline preflight only. **No MySQL connection, no SQL, no tests run, no database/account/config modified, no password displayed.**

**Completion status: PREFLIGHT PASS — AWAITING EXPLICIT OWNER AUTHORIZATION**

---

## 1. Individual check results

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | `FSR_TEST_DB_NAME` present | **PASS** (User scope) | User scope = `fsr_phase5_isolated_test` (set via `setx`). Process scope empty because this agent shell predates the `setx`; a fresh shell inherits it, and the value will be passed inline for the run. |
| 2 | `FSR_TEST_DB_CONFIG` present | **PASS** (User scope) | User scope = `D:\Build Build Build\PythonProject\data\json\private\db_config.phase5.json`. |
| 3 | Config file exists at exact path | **PASS** | `Test-Path` → `True`. |
| 4 | Config parses as JSON | **PASS** | `ConvertFrom-Json` succeeded. |
| 5 | `enabled` = true | **PASS** | `True`. |
| 6 | `host` = localhost | **PASS** | `localhost`. |
| 7 | `port` = 3306 | **PASS** | `3306`. |
| 8 | `user` = fsr_phase5 | **PASS** | `fsr_phase5`. |
| 9 | `database` = fsr_phase5_isolated_test | **PASS** | `fsr_phase5_isolated_test`. |
| 10 | Password present and non-empty (not displayed) | **PASS** | Non-empty; value never shown or logged. |
| 11 | Harness rejects `field_survey` | **PASS** | `settings()` → `NotAvailable`. |
| 12 | Harness rejects `field_survey_test` | **PASS** | `settings()` → `NotAvailable`. |
| 13 | Harness rejects unknown DB names | **PASS** | `settings()` rejects `unknown_db` and empty. |
| 14 | Missing config cannot fall back | **PASS** | With `FSR_TEST_DB_NAME` valid but `FSR_TEST_DB_CONFIG` unset → `NotAvailable` (no fallback to `db_config.json`). |
| 15 | Missing name cannot fall back | **PASS** | With config set but `FSR_TEST_DB_NAME` unset → `NotAvailable`. |
| 16 | Harness accepts the valid isolated config | **PASS** | `settings()` → `database=fsr_phase5_isolated_test`, `user=fsr_phase5`. |

All locally verifiable checks **PASS**.

---

## 2. Locally verified vs owner-evidence items

**Locally verified (this preflight):**
- Environment variables are persisted at User scope with the correct values.
- The dedicated config file exists, parses, and has the required non-secret fields (`enabled`, `host`, `port`, `user`, `database`) plus a non-empty password.
- The harness is fail-closed: it rejects `field_survey`, `field_survey_test`, unknown/empty names, and never falls back to another database or the production config.

**Requires owner evidence / not independently verified offline** (would need a DB connection, which is out of preflight scope):
- The database `fsr_phase5_isolated_test` exists.
- The account `fsr_phase5@localhost` exists.
- Grants are restricted to `fsr_phase5_isolated_test.*` (DML only).
- The 7 tables + `v_item_report` view are loaded.

These are per the owner's Phase 5.3/5.4 confirmation. They are **not claimed as verified here**; they will be exercised at run time, where the harness runs `SELECT DATABASE()` on every connection and `test_it_is_the_test_database_and_nothing_else` asserts the identity.

---

## 3. Notes for the run

- The agent process does not inherit the User-scope variables (it predates the `setx`). For the authorized run, both variables will be passed explicitly:
  - `FSR_TEST_DB_NAME = fsr_phase5_isolated_test`
  - `FSR_TEST_DB_CONFIG = D:\Build Build Build\PythonProject\data\json\private\db_config.phase5.json`
- The password is read from the config file by the harness and is never printed or logged.

---

**STOP — preflight recheck complete. No MySQL connection, no SQL, no tests. Awaiting explicit owner authorization to begin Phase 5.4 integration testing.**