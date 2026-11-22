# Phase 5 — Database Identity and Test Isolation Review

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Mode:** Offline, read-only investigation + offline verification
**Status:** Review complete — **no database contacted, no SQL executed, no DB/account/config created or modified.**

> Scope reminder: `MYSQL80` (production), `FSR test`, `field_survey`, and `field_survey_test` are all treated as protected. This review changes nothing in any database and does not modify production configuration.

---

## 1. Confirmed meaning of `MYSQL80`

`MYSQL80` is the **Windows MySQL 8.0 service name** (the server/service), **not** a database or schema.

Evidence (code only references it as a service in user-facing messages):
- `db_mysql.py:249-250` — "Make sure the MySQL80 service is running (Windows: Services > MySQL80 > Start)…"
- `field_survey_report.py:1100, 2912, 4762` — "Is the MySQL80 service running?"
- `docs/TWO_COPIES_ONE_DATABASE.md:178` — "A stopped MySQL80 service…"
- Confirmed on this host: `Get-Service` → `MySQL80` **Running**; TCP `127.0.0.1:3306` open.

No code uses `MYSQL80` as a schema name. It is the server instance that hosts the schemas.

## 2. Confirmed meaning of `FSR test`

`FSR test` (with a space) is **not a schema name** and does not exist as one anywhere in the code (there is no `` `FSR test` `` identifier).

- `fsr_test` is the MySQL **login/account name** used by the test schema and docs:
  - `fsr_test_db_script.py:20` — `TEST_LOGIN = "fsr_test"`
  - `field_survey_test_schema.sql:227` — `GRANT … ON field_survey_test.* TO 'fsr_test'@'localhost';`
  - `docs/TWO_COPIES_ONE_DATABASE.md:228-248`
- `FSR test` is almost certainly the owner's **MySQL Workbench connection label** (a saved connection), not a schema. A Workbench connection label points at a host plus a default schema; its target cannot be determined from the code.

**Conclusion:** `FSR test` = Workbench connection label (owner-side). The schema the test harness uses is `field_survey_test`. The owner should confirm in Workbench which schema the `FSR test` connection actually opens. Do not assume it equals `field_survey_test`.

## 3. Existing database-name references

| Name | Kind | Where |
|---|---|---|
| `field_survey` | **Production schema** | `db_mysql.py:189` (`PRODUCTION_DATABASE`), `data/json/db_config.example.json`, `data/json/private/installer_defaults/db_config.json` (disabled), `data/schema/field_survey_schema.sql`, `data/schema/migrations/*` (`USE field_survey`), `add_shipment_columns.sql`, `update_declared_goods.sql` |
| `field_survey_test` | **Test schema (current)** | `tests/real_mysql.py:25` (`TEST_DATABASE`), `fsr_test_db_script.py:19`, `data/schema/field_survey_test_schema.sql`, `docs/TWO_COPIES_ONE_DATABASE.md` |
| `field_survey_v2` | Proposal only (not applied) | `data/schema/field_survey_schema_v2_proposed.sql` |
| `fsr_test` | **Login/account** (not a schema) | `fsr_test_db_script.py`, `field_survey_test_schema.sql`, docs |
| `MYSQL80` | **Service name** (not a schema) | `db_mysql.py`, `field_survey_report.py`, docs |

**Live configuration (read-only, password masked):**
- `data/json/private/db_config.json` → `enabled=true`, `host=localhost`, `port=3306`, `user=fsr_test`, **`database=field_survey_test`**, `password_store=credential-manager` (password held in Windows Credential Manager, not in the file). This is the source-run **test copy** config.
- `data/json/private/installer_defaults/db_config.json` → `enabled=false`, `user=fsr_app`, `database=field_survey` (installed-edition template; disabled).
- `data/json/db_config.example.json` → template with `user=fsr_app`, `database=field_survey` (example only).

## 4. Current real-MySQL harness behavior

Files: `tests/real_mysql.py`, `tests/test_real_mysql.py`, `tests/test_real_mysql_sqlite.py`, `tests/test_db_mysql_real.py` (33 tests total).

- `TEST_DATABASE = "field_survey_test"` — **hardcoded** (`tests/real_mysql.py:25`).
- `CONFIG_FILE` = `FSR_TEST_DB_CONFIG` env var, else `data/json/private/db_config.json` — read **once at import** (`real_mysql.py:31-33`).
- `settings()` requires `config["database"] == "field_survey_test"` **exactly**, a `user`, and a password (config field or Credential Manager); otherwise raises `NotAvailable` → tests **skip** (never fall back).
- `_checked()` runs `SELECT DATABASE()` on every connection and **refuses (closes + AssertionError)** if it is not `field_survey_test`.
- `RealTestDB.__init__` forces `database = "field_survey_test"`.
- `remove_test_rows()` deletes only `WHERE control_no LIKE 'FSR-ZZT-2099%'` on the 5 report tables.

**Deficiency (exact):** the target database name is **hardcoded** to `field_survey_test`. There is no supported way to point the harness at a different dedicated database (e.g., `fsr_phase5_isolated_test`) without editing code. Everything else the owner requires (exact-name match, `SELECT DATABASE()` verification, refusal, scoped cleanup) is already implemented and verified below.

**Important operational fact:** because the live config points at `field_survey_test` and prior full runs reported **0 skips** (1,461 = total collected, including these 33 tests), the real-MySQL tests **already executed against `field_survey_test`** during earlier runs. Cleanup only removes `FSR-ZZT-2099%` rows, so any other data in `field_survey_test` was not touched — but the owner's wish to preserve it means future Phase 5 runs should target a dedicated DB.

## 5. Schema safety assessment — `data/schema/field_survey_test_schema.sql`

- Creates/uses **only** `field_survey_test`: `CREATE DATABASE IF NOT EXISTS field_survey_test` (line 20) + `USE field_survey_test;` (line 22). All tables/views are **unqualified** → confined to the current DB.
- **No destructive statements:** no `DROP DATABASE/TABLE`, no `TRUNCATE`, no `DELETE FROM`. (`DELETE` appears only in `ON DELETE CASCADE` FK clauses.)
- **No cross-database access:** 0 qualified `` `field_survey`. `` references (only in comments). No routines/triggers (locking is `SELECT … FOR UPDATE`).
- **Least-privilege grant:** `GRANT SELECT, INSERT, UPDATE, DELETE ON field_survey_test.* TO 'fsr_test'@'localhost';` — no `ALL`, no DDL, no `GRANT OPTION`, scoped to the test DB.
- Idempotent: `CREATE … IF NOT EXISTS`, `INSERT IGNORE`, `CREATE OR REPLACE VIEW`, `ALTER TABLE … MODIFY`.
- **Limitation for Phase 5:** the DB name (`field_survey_test`) and login (`fsr_test`) are **hardcoded**. It cannot initialize `fsr_phase5_isolated_test` as-is. A dedicated schema must be generated from `field_survey_schema.sql` with the new name (the generator `fsr_test_db_script.py` parameterizes only the name via constants). Per the owner's rule, `CREATE DATABASE IF NOT EXISTS` must **not** be used as a substitute for verifying the new DB is new and empty.
- Currency: the test schema is generated from the base schema; `tests/test_test_copy.py` enforces that the on-disk schema matches the generator, so it cannot silently fall behind. Regenerate after any base-schema change.

## 6. Cleanup safety assessment — `tests/real_mysql.py`

Layered guarantees (verified offline, section 10):
1. `settings()` refuses unless `config["database"] == "field_survey_test"` exactly → a config naming `field_survey`, `FSR test`, `MYSQL80`, or a wrong test DB never connects.
2. `RealTestDB` forces `database = field_survey_test`.
3. `_checked()` verifies `SELECT DATABASE()` and **refuses + closes** on any mismatch.
4. `remove_test_rows()` deletes only `control_no LIKE 'FSR-ZZT-2099%'` on the verified connection.

**Conclusion:** cleanup cannot affect `field_survey` (production), cannot affect any other schema, cannot delete non-`FSR-ZZT-2099%` rows, and cannot run if the identity check fails (it skips). The only change needed for a dedicated DB is the name itself.

## 7. Proposed isolated test database name

**`fsr_phase5_isolated_test`** (as suggested). Dedicated and disposable; distinct from `field_survey` (production), `field_survey_test` (preserve), and the `FSR test` connection label.

## 8. Required test account and permissions

- A **dedicated** account, e.g. `` 'fsr_phase5'@'localhost' `` (do **not** reuse production `fsr_app`, and preferably not `fsr_test`, to keep the Phase 5 DB clearly separate).
- Least privilege, DML only, scoped to the isolated DB:
  ```sql
  GRANT SELECT, INSERT, UPDATE, DELETE ON fsr_phase5_isolated_test.* TO 'fsr_phase5'@'localhost';
  ```
- No access to `field_survey`, `field_survey_test`, or any other schema; no DDL; no `GRANT OPTION`.
- Password: owner's own, **not** the production password.

## 9. Proposed test configuration

**Recommended: keep the app's `db_config.json` untouched; give the tests their own config via `FSR_TEST_DB_CONFIG`.**

1. Create (owner) the isolated DB and account, load a dedicated schema (generated for `fsr_phase5_isolated_test`), and write a **separate** config file (gitignored), e.g. `data/json/private/db_config.phase5.json`:
   ```json
   {
     "enabled": true,
     "host": "localhost",
     "port": 3306,
     "user": "fsr_phase5",
     "password": "<owner test password>",
     "database": "fsr_phase5_isolated_test"
   }
   ```
2. Set the environment before launching pytest:
   ```
   FSR_TEST_DB_CONFIG=data/json/private/db_config.phase5.json
   ```
   (`real_mysql.CONFIG_FILE` reads this at import.)

**Proposed harness change (awaiting approval — not applied):** to avoid editing code each run, make the name configurable:
- `tests/real_mysql.py`: `TEST_DATABASE = os.environ.get("FSR_TEST_DB_NAME", "field_survey_test")` and derive `SKIP_PREFIX` from it (default behavior unchanged).
- `tests/test_real_mysql.py:113`: change `assert real_mysql.TEST_DATABASE == "field_survey_test"` to compare against `os.environ.get("FSR_TEST_DB_NAME", "field_survey_test")` (preserves the guard's intent across environments).
- Generate `data/schema/fsr_phase5_isolated_test_schema.sql` (parameterize `fsr_test_db_script.py`).

All exact-match, `SELECT DATABASE()`, refusal, and cleanup safeguards remain intact under this change.

## 10. Offline verification results

No MySQL connection, no SQL, no DB/account/config changes. No tracked files modified.

| Check | Result |
|---|---|
| `tests/test_test_copy.py` + `tests/test_db_mysql.py` (fake connector) | **30 passed** |
| `tests/test_sqlite_migrate.py` + `tests/test_sqlite_twin.py` (SQLite) | **35 passed** |
| Harness enforcement script (`test_run_temp/verify_harness.py`) | **14/14 PASS** |

Harness enforcement detail (all PASS):
- `settings()` accepts `field_survey_test`; **rejects** `field_survey`, `MYSQL80`, `FSR test`, `fsr_phase5_isolated_test`, empty, missing user, missing password.
- `_checked()` **rejects** `field_survey`, `MYSQL80`, `FSR test`, `fsr_phase5_isolated_test` and **closes** the connection; accepts `field_survey_test`.
- `remove_test_rows()` issues exactly 5 deletes, each `control_no LIKE %s` with param `FSR-ZZT-2099%`, on the 5 report tables only.

Real-MySQL integration tests were **not** run (per restrictions).

## 11. Remaining risks and owner decisions

1. **Live config already targets `field_survey_test`** (`data/json/private/db_config.json`, user `fsr_test`), and earlier full runs executed the 33 real-MySQL tests against it. If `field_survey_test` must remain untouched, switch Phase 5 to the dedicated DB before further runs. (Cleanup only removed `FSR-ZZT-2099%` rows; other data was not modified.)
2. **Harness name is hardcoded** — a code change (proposed in §9) is required to use `fsr_phase5_isolated_test`; awaiting approval.
3. **`FSR test` label target unknown** — owner must confirm in Workbench which schema it opens; do not assume.
4. **Schema generation** — a dedicated `fsr_phase5_isolated_test` schema must be generated; do not reuse `field_survey_test_schema.sql` unchanged, and do not rely on `CREATE DATABASE IF NOT EXISTS` to prove the new DB is empty.
5. **Stray untracked `.coverage`** file exists in the repo root (from earlier coverage runs) and is not gitignored — owner decision whether to ignore/remove it (left untouched here).
6. **Owner decisions required before Phase 5 execution:** approve the isolated DB name, account, schema, and (optionally) the harness change in §9.

---

## Files modified

- **Created:** `docs/phase-5/DATABASE_IDENTITY_AND_ISOLATION_REVIEW.md` (this report).
- **No other repository files were modified.** (Scratch verification scripts live under the git-ignored `test_run_temp/` and are not part of the repository.)

**Awaiting owner approval before any database setup or real-MySQL integration testing.**