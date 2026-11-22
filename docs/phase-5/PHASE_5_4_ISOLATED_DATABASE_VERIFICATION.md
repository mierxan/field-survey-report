# Phase 5.4 — Isolated Database Verification

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **PASS**
**MySQL:** 8.0.46 at `localhost:3306`

Verification only. **No integration tests executed, no database/account/privilege/object changes, no credentials displayed or logged.**

---

## A. Configuration verification (offline)

File: `data/json/private/db_config.phase5.json` (password read but never printed).

| Check | Result |
|---|---|
| File exists | PASS |
| Parses as JSON | PASS |
| host = `localhost` | PASS |
| port = `3306` | PASS |
| database = `fsr_phase5_isolated_test` | PASS |
| user = `fsr_phase5` | PASS |
| password present (non-empty) | PASS (not displayed) |
| Not the production config (`db_config.json`) | PASS |

## B. Harness verification (`tests/real_mysql.py`, by inspection + offline tests)

| Property | Result | Evidence |
|---|---|---|
| Missing env vars → fail-closed | PASS | `settings()` raises `NotAvailable` if `FSR_TEST_DB_NAME` or `FSR_TEST_DB_CONFIG` is missing; tests skip |
| Only `fsr_phase5_isolated_test` allowed | PASS | `ALLOWED_DATABASES = frozenset({ISOLATED_DATABASE})`; `ISOLATED_DATABASE = "fsr_phase5_isolated_test"` |
| Rejects `field_survey` / `field_survey_test` | PASS | `PROTECTED_DATABASES = {"field_survey", "field_survey_test"}` + allow-list check |
| Rejects unknown DB names | PASS | allow-list check in `settings()` |
| Every connection verifies `SELECT DATABASE()` | PASS | `_checked()` runs `SELECT DATABASE()` (line 131); `connect()` calls it (line 207) |
| No fallback to another config | PASS | no default to `db_config.json`; `FSR_TEST_DB_CONFIG` mandatory; production path explicitly refused |
| Cleanup restricted to `FSR-ZZT-2099` | PASS | `PREFIX = "FSR-ZZT-2099"`; `CLEAN_TABLES` (5 report tables + `master_list`) deleted by prefix |

Offline unit tests `tests/test_phase5_harness.py` already verify these properties (all pass).

## C. Dedicated account authentication (read-only identity)

Connected via the harness and ran `SELECT DATABASE(), USER(), CURRENT_USER()`:

| Check | Result |
|---|---|
| `DATABASE()` | `fsr_phase5_isolated_test` ✅ |
| `USER()` | `fsr_phase5@localhost` ✅ |
| `CURRENT_USER()` | `fsr_phase5@localhost` ✅ |

Login succeeded; credentials were not printed.

## D. Database object verification

| Check | Result |
|---|---|
| Base tables (exactly 7) | ✅ `declared_goods`, `incident_lines`, `incident_reports`, `item_lines`, `master_list`, `remarks`, `reports` |
| Views (exactly 1) | ✅ `v_item_report` |
| `v_item_report` present | ✅ |
| `reports` present | ✅ |

## E. Privilege isolation (read-only)

| Check | Result |
|---|---|
| `SELECT COUNT(*) FROM fsr_phase5_isolated_test.reports` | ✅ works (count = 0) |
| `SELECT COUNT(*) FROM field_survey.reports` | ✅ **denied** — MySQL error **1142** |
| `SELECT COUNT(*) FROM field_survey_test.reports` | ✅ **denied** — MySQL error **1142** |

The dedicated account can read only the isolated database; both protected databases are inaccessible.

## F. Production / existing-test protection

- **No protected database was accessed or modified.** The only reads attempted against `field_survey` and `field_survey_test` were denied (1142) — no rows were read.
- No `DROP`/`TRUNCATE`/`DELETE`/`ALTER`/recreate was performed on any database.
- No account, privilege, or configuration was changed.

## G. Tests deliberately NOT executed

- `tests/test_real_mysql.py`
- `tests/test_real_mysql_sqlite.py`
- `tests/test_db_mysql_real.py`
- `fsr_test_db_script.py`
- Any other real-MySQL integration test; no cleanup was run.

## H. Failures / blockers

- **None.** All checks passed.

---

## Overall status: **PASS**

All completion criteria are met:
1. Dedicated account authentication succeeds ✅
2. Correct database identity confirmed ✅
3. Seven tables + one view verified ✅
4. Isolated-database SELECT succeeds ✅
5. Both protected-database access attempts denied (1142) ✅
6. No protected database modified ✅
7. No integration tests executed ✅

No passwords, secrets, or sensitive connection details are included in this report.

**STOP — verification complete. Integration testing requires separate explicit owner authorization.**