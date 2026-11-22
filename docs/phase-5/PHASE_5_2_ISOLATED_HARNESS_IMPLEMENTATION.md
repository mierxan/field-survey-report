# Phase 5.2 — Isolated MySQL Test Harness Implementation

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Mode:** Test-only implementation + offline verification. **No MySQL connection, no SQL executed, no database/account created or modified, no production config touched, real-MySQL tests NOT run.**

The harness now targets a dedicated, disposable database **`fsr_phase5_isolated_test`** and is **fail-closed**: it refuses to run unless explicitly configured, and it can never reach `field_survey` (production) or `field_survey_test` (existing).

---

## 1. Architecture changes

`tests/real_mysql.py` was rewritten from "hardcoded `field_survey_test`, default config fallback" to a fail-closed design:

| Before | After |
|---|---|
| `TEST_DATABASE = "field_survey_test"` (fixed) | `ISOLATED_DATABASE = "fsr_phase5_isolated_test"` + `ALLOWED_DATABASES` allow-list |
| Config = `FSR_TEST_DB_CONFIG` **or** `data/json/private/db_config.json` | Config = `FSR_TEST_DB_CONFIG` **only** (no fallback to `db_config.json`) |
| Name not validated against an allow-list | `FSR_TEST_DB_NAME` **mandatory** and must equal the isolated name |
| `_checked()` compared to `field_survey_test` | `_checked()` compares to the isolated name **and** the allow-list |
| Cleanup = 5 report tables (`control_no`) | Cleanup = 5 report tables **+ `master_list`** (`item_name`), all `FSR-ZZT-2099%` |
| No production-user/credential guard | Rejects the production config path, the `fsr_app` user, and protected DB names |

`fsr_test_db_script.py` gained `build_for()`, `build_isolated()`, and a `--isolated` CLI flag to generate the dedicated schema, while `build()` is unchanged (so the existing `field_survey_test` schema and `tests/test_test_copy.py` are unaffected).

## 2. Modified files

| File | Change |
|---|---|
| `tests/real_mysql.py` | Rewritten as the fail-closed isolated harness |
| `fsr_test_db_script.py` | Added `build_for`/`build_isolated` + `--isolated` CLI (default `build()` unchanged) |
| `tests/test_real_mysql.py` | DB-identity assertion now uses `ISOLATED_DATABASE` |
| `tests/test_db_mysql_real.py` | `NAME_PREFIX` unified to `real_mysql.PREFIX` (`FSR-ZZT-2099`) |
| `tests/test_phase5_harness.py` | **New** — 17 offline tests |
| `data/schema/fsr_phase5_isolated_test_schema.sql` | **New** — generated isolated schema (not executed) |
| `docs/phase-5/PHASE_5_2_ISOLATED_HARNESS_IMPLEMENTATION.md` | **New** — this document |

No production/application source was modified.

## 3. Configuration requirements

Two environment variables are **mandatory**; there is no fallback:

| Variable | Required value | Behaviour if missing/wrong |
|---|---|---|
| `FSR_TEST_DB_NAME` | exactly `fsr_phase5_isolated_test` | `NotAvailable` → tests **skip** with a clear reason |
| `FSR_TEST_DB_CONFIG` | path to a **dedicated** test config file | `NotAvailable` → tests **skip** |

- `FSR_TEST_DB_CONFIG` pointing at the production `data/json/private/db_config.json` is **refused**.
- The config file must contain `"database": "fsr_phase5_isolated_test"` and a non-`fsr_app` user with a password (inline or via Credential Manager).
- The config must be separate from production configuration.

## 4. Database allow-list

Only **`fsr_phase5_isolated_test`** is permitted (`ALLOWED_DATABASES`). Explicitly rejected:

- `field_survey` (production)
- `field_survey_test` (existing)
- any other name (unknown)

`FSR_TEST_DB_NAME` is an env var but is validated against the fixed allow-list, so **arbitrary names cannot be introduced** through the environment.

## 5. Connection safeguards

Every connection path (`connect()`, `run()`, `load_report()`, `control_numbers()`, `remove_test_rows()`) goes through `connect()` → `_checked()`:

1. Uses the dedicated test configuration (`RealTestDB._config`, forced to the isolated DB).
2. `settings()` verifies the configured name is exactly `fsr_phase5_isolated_test` (and the config names that DB).
3. `_checked()` executes `SELECT DATABASE()` after connecting.
4. Compares the actual database to `fsr_phase5_isolated_test` (and the allow-list).
5. **Closes the connection immediately** if verification fails.
6. Refuses all operations after a failed identity check (raises `AssertionError`).

## 6. Cleanup protections

- **Unified prefix:** every test-generated row uses `FSR-ZZT-2099` (`PREFIX`). `master_list` test names now use the same prefix (`tests/test_db_mysql_real.py` `NAME_PREFIX = real_mysql.PREFIX`).
- `CLEAN_TABLES = (incident_reports, remarks, item_lines, declared_goods, reports, master_list)`.
  - Report tables: `DELETE … WHERE control_no LIKE 'FSR-ZZT-2099%'`.
  - `master_list`: `DELETE … WHERE item_name LIKE 'FSR-ZZT-2099%'`.
- Cleanup **refuses to run without a verified connection**: `remove_test_rows()` calls `connect()` (which runs `_checked()`), so it raises before deleting anything if the DB is unavailable or is not the isolated DB.
- Cleanup **never targets existing records**: every DELETE is bound to the `FSR-ZZT-2099%` prefix.
- FK cascades (`reports → children`, `incident_reports → incident_lines`) fire only when a **test** parent row is deleted.

## 7. Schema-generation changes

- `fsr_test_db_script.py`:
  - `build_for(schema_text, database, login)` — generalized builder.
  - `build(schema_text)` — unchanged behaviour (field_survey_test).
  - `build_isolated()` — builds the `fsr_phase5_isolated_test` schema (login `fsr_phase5`).
  - CLI: `python fsr_test_db_script.py --isolated` writes `data/schema/fsr_phase5_isolated_test_schema.sql`.
- **Generated:** `data/schema/fsr_phase5_isolated_test_schema.sql` (12,042 bytes, 7 tables + `v_item_report`, `USE`/`GRANT` on `fsr_phase5_isolated_test`, login `fsr_phase5`).
- **Currency:** the base `field_survey_schema.sql` already contains every migration column (`cargo_id`, `receiving_ref`, `uom`, `currency`, `item_form`, `unit_no`, `shipment_type`, `container_type`), so the generated schema is current. The migration files only upgrade *old* databases.
- The original `field_survey_schema.sql` and `field_survey_test_schema.sql` are **preserved unchanged** (verified by `test_existing_test_schema_is_unchanged`).
- The generated schema was **not executed**.

## 8. Offline test results

| Check | Result |
|---|---|
| `tests/test_phase5_harness.py` (new) + `tests/test_test_copy.py` + `tests/test_db_mysql.py` | **54 passed, 0 failed** |
| `tests/test_sqlite_migrate.py` + `tests/test_sqlite_twin.py` (SQLite) | **35 passed, 0 failed** |
| `ruff check` (changed files) | **All checks passed!** |
| `--collect-only` on the 3 real-MySQL files | **33 collected, 0 errors** (no import breakage) |
| Real-MySQL tests | **Not run** (per restrictions) |

New offline tests (`tests/test_phase5_harness.py`) cover: missing `FSR_TEST_DB_NAME`, missing `FSR_TEST_DB_CONFIG`, production/existing/unknown DB rejection, correct isolated acceptance, config DB mismatch, production-config-path rejection, `fsr_app` rejection, missing password, no production-config fallback, `_checked` reject+close on wrong DB, `_checked` accept, cleanup prefix/master_list enforcement, cleanup refusal without a connection, and schema-generation invariants.

## 9. Remaining limitations

- **No real-MySQL execution** was performed (by design); the harness is verified offline only. It will run against `fsr_phase5_isolated_test` once the owner creates it and sets the two env vars.
- The generated schema uses `CREATE DATABASE IF NOT EXISTS`; per the owner's rule, the owner must ** positively confirm the isolated DB is new and empty** before running it.
- Password handling: if the config uses `"password_store": "credential-manager"`, the owner must store the test password in Windows Credential Manager under the derived name; otherwise put it inline in the (git-ignored) test config.
- The three real-MySQL test files now **skip** unless `FSR_TEST_DB_NAME` + `FSR_TEST_DB_CONFIG` are set — intended fail-closed behaviour.

## 10. Instructions for owner-controlled database setup (Phase 5.3)

1. **Create the login** (MySQL Workbench, as root): account `` 'fsr_phase5'@'localhost' `` with a password of your own.
2. **Create and verify the isolated DB is new/empty**, then load the schema:
   - `CREATE DATABASE fsr_phase5_isolated_test;` (verify it did not exist / is empty), then run `data/schema/fsr_phase5_isolated_test_schema.sql` (it also grants DML on that DB to `fsr_phase5`).
3. **Create a dedicated test config** (git-ignored), e.g. `data/json/private/db_config.phase5.json`:
   ```json
   {
     "enabled": true,
     "host": "localhost",
     "port": 3306,
     "user": "fsr_phase5",
     "password": "<your test password>",
     "database": "fsr_phase5_isolated_test"
   }
   ```
4. **Run the tests with both variables set** (no production config involved):
   ```
   FSR_TEST_DB_NAME=fsr_phase5_isolated_test
   FSR_TEST_DB_CONFIG=data/json/private/db_config.phase5.json
   pytest tests/test_real_mysql.py tests/test_real_mysql_sqlite.py tests/test_db_mysql_real.py -q
   ```
5. The harness will verify `SELECT DATABASE()` on every connection and refuse anything that is not `fsr_phase5_isolated_test`.

**STOP — implementation and offline verification complete. No database was contacted; no SQL executed; nothing created or modified in any database. Awaiting owner approval before Phase 5.3 database setup.**