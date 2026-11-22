# Phase 5.5 — Real-MySQL Integration Test Execution Plan

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Mode:** Preparation only. **No integration tests executed, no DB writes/cleanup, no schema/privilege/config changes, no secrets displayed.**

Target (verified in Phase 5.4): database `fsr_phase5_isolated_test`, account `fsr_phase5@localhost`. Protected: `field_survey`, `field_survey_test`.

---

## 1. Test files and counts

| File | Tests | Focus |
|---|---|---|
| `tests/test_real_mysql.py` | **16** | overwrite guard, real lock/transaction, background sender, import round-trip |
| `tests/test_real_mysql_sqlite.py` | **6** | same guard with reports in the SQLite store (migrate/round-trip) |
| `tests/test_db_mysql_real.py` | **11** | `db_mysql` CRUD, lists/search, weekly summary, master lists, connection checks |
| **Total** | **33** | |

All three use the shared fail-closed harness `tests/real_mysql.py` (module-scoped `database` fixture: cleanup before and after the module).

## 2. Write-operation inventory

All writes target **test-generated** rows only. Controls are built from `real_mysql.PREFIX` (`FSR-ZZT-2099`): `…10-` (db_mysql), `…11-` (real_mysql), `…12-` (sqlite).

### `tests/test_real_mysql.py` (controls `FSR-ZZT-209911-…`)
| Operation | Where | Scope |
|---|---|---|
| INSERT/replace via guard/journal (`mine.save`, `mine.guard.save`, `save_here`, `send_round`) | lines 133–405 | test control |
| INSERT `db.write_report(conn, db_other)` | line 188 | test control |
| UPDATE `db.run("UPDATE reports SET so_number=%s WHERE control_no=%s", …)` (`someone_else_changes`) | line 106 | test control only |
| CLEANUP `db.remove_test_rows()` | lines 31, 34 | `FSR-ZZT-2099%` |

### `tests/test_real_mysql_sqlite.py` (controls `FSR-ZZT-209912-…`)
| Operation | Where | Scope |
|---|---|---|
| INSERT/replace via guard (`mine.save`, `mine.guard.save`) | lines 110–196 | test control |
| CLEANUP `db.remove_test_rows()` | lines 30, 33 | `FSR-ZZT-2099%` |

### `tests/test_db_mysql_real.py` (controls `FSR-ZZT-209910-…`)
| Operation | Where | Scope |
|---|---|---|
| INSERT/replace `db_mysql.write_report(conn, …)` | lines 80, 104, 109, 122, 131, 151, 178, 226 | test control |
| INSERT `db_mysql.save_master_lists(names, conn)` (names `FSR-ZZT-2099…`) | lines 189, 190 | test master_list names |
| CLEANUP `db.remove_test_rows()` | lines 26, 28 | `FSR-ZZT-2099%` (incl. master_list) |
| CLEANUP `db.run("DELETE FROM master_list WHERE item_name LIKE %s", (NAME_PREFIX+"%",))` | line 29 | `FSR-ZZT-2099%` |

**No test writes to any non-`FSR-ZZT-2099` row.** The only UPDATE is bound to a test control; the only DELETEs are prefix-scoped cleanup. `test_the_test_login_cannot_read_the_real_database` issues a `SELECT` against `field_survey.reports` that is expected to be **denied** (no data read); `test_a_server_that_is_not_there…` connects to `localhost:1` expecting failure (no DB touched).

## 3. Cleanup safety assessment

- **Prefix:** every test-generated report uses `FSR-ZZT-2099`; `master_list` test names use the same prefix (`NAME_PREFIX = real_mysql.PREFIX`).
- **Scope:** `remove_test_rows()` deletes `control_no LIKE 'FSR-ZZT-2099%'` from `incident_reports, remarks, item_lines, declared_goods, reports` and `item_name LIKE 'FSR-ZZT-2099%'` from `master_list`.
- **Verified connection:** `remove_test_rows()` calls `connect()` → `_checked()` (`SELECT DATABASE()`), so cleanup refuses to run unless the connection is the isolated DB.
- **Cascades:** FK `ON DELETE CASCADE` fires only when a test parent row is deleted; non-test rows are untouched.
- **Teardown:** the module fixture runs `remove_test_rows()` after the module even if a test fails, so residual rows are removed on completion.

## 4. Database identity safeguards

- `settings()` requires `FSR_TEST_DB_NAME=fsr_phase5_isolated_test` and `FSR_TEST_DB_CONFIG=<dedicated config>`; no fallback to `db_config.json`.
- Allow-list = `{fsr_phase5_isolated_test}`; `field_survey` and `field_survey_test` are explicitly rejected.
- Every connection: `connect()` → `_checked()` → `SELECT DATABASE()`; mismatch closes the connection and raises.
- The dedicated config is separate from production; the production config path is refused.
- Verified in Phase 5.4: login as `fsr_phase5@localhost`, `DATABASE()=fsr_phase5_isolated_test`, `field_survey`/`field_survey_test` reads denied (1142).

## 5. Dependencies and execution order

- Each file is **self-contained** (own module-scoped `database` fixture); there are **no cross-file dependencies**, so the files can run in any order.
- Recommended order (core → store → db layer):
  1. `tests/test_real_mysql.py`
  2. `tests/test_real_mysql_sqlite.py`
  3. `tests/test_db_mysql_real.py`
- Running them **separately** gives the clearest per-file evidence.

## 6. Exact PowerShell commands

Set the environment once in the PowerShell session, then run each file separately:

```powershell
# One-time in the shell (the agent's process does not inherit the User-scope setx):
$env:FSR_TEST_DB_NAME   = "fsr_phase5_isolated_test"
$env:FSR_TEST_DB_CONFIG = "D:\Build Build Build\PythonProject\data\json\private\db_config.phase5.json"

# Run each file separately (from the project root):
.venv\Scripts\python.exe -m pytest tests\test_real_mysql.py        -rs -q
.venv\Scripts\python.exe -m pytest tests\test_real_mysql_sqlite.py -rs -q
.venv\Scripts\python.exe -m pytest tests\test_db_mysql_real.py     -rs -q
```

Optional: add `--junitxml=test_run_temp\phase55_<name>.xml` to any run for per-test evidence, and `-x` to stop at the first failure while debugging.

## 7. Expected outcomes

| File | Expected |
|---|---|
| `test_real_mysql.py` | 16 passed, 0 failed, 0 skipped |
| `test_real_mysql_sqlite.py` | 6 passed, 0 failed, 0 skipped |
| `test_db_mysql_real.py` | 11 passed, 0 failed, 0 skipped |
| **Total** | **33 passed, 0 failed, 0 skipped** |

- A connection failure surfaces as a **skip** with a reason starting `the isolated test database fsr_phase5_isolated_test is not available` (fail-closed), not a silent pass.
- Cleanup runs in teardown; residual `FSR-ZZT-2099%` rows should be 0 after the run (to be verified post-run).

## 8. Known risks and blockers

- Requires the env vars to be visible to the test process (pass inline as above; the agent shell predates the User-scope `setx`).
- Tests write/delete only `FSR-ZZT-2099%` rows in the isolated DB; production and existing test DBs are never contacted (harness refuses them).
- `test_a_server_that_is_not_there…` intentionally connects to `localhost:1` (expects failure) — not a protected DB.
- If a genuine assertion fails, investigate without weakening the harness or safeguards; cleanup still runs in teardown.

---

**READY FOR EXPLICIT OWNER AUTHORIZATION**

No integration tests were executed; no records were written, updated, or deleted; no schema/privilege/account/config changes were made. Awaiting separate explicit owner authorization to run the three files.