# Phase 5.1 — Historical MySQL Test Execution and Data Integrity Audit

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Mode:** Offline, read-only (source + existing logs/artifacts + Git history). **No MySQL connection, no SQL executed, no DB/account/config change, no source change.**

> Scope: determine what the earlier real-MySQL integration tests did and whether existing data in `field_survey_test` could have been affected. Conclusions are limited to offline evidence; no live database query was performed.

---

## 1. Historical test-run identification

| Run | Log | Command | Result | Time |
|---|---|---|---|---|
| **Specified run** | `test_run_temp/coverage_full.log` | `pytest -q -rs --cov --cov-report=term --cov-report=json:… --cov-report=html:…` (no `-m` filter) | **1,461 passed, 0 failed, 0 skipped** ("SKIPPED: 0") | **1,280.74 s (0:21:20)** |
| Corroborating run | `test_run_temp/full_after.log` | `pytest -rs -q --fail-on-gui-skip --junitxml=…` | **1,461 passed, 0 failed, 0 skipped** | 1,197.59 s (0:19:57) |
| Split (logic) | `test_run_temp/not_gui.log` / `.xml` | `pytest -m "not gui"` | 1,143 passed | 779 s |
| Split (GUI) | `test_run_temp/gui.log` / `.xml` | `pytest -m "gui"` | 318 passed | 462 s |

The **21 m 20 s** run is the Phase 4.1 full-coverage run (`coverage_full.log`). It produced a terminal summary and JSON/HTML coverage but **no per-test JUnit XML**. The 19 m 57 s run (`full_after.log`) is the **same suite** (1,461 collected, no `-m` filter) and **did** emit `test_run_temp/full_after.xml`, which provides per-test status (used in §2).

Both runs report **0 skipped** and **1,461 = total collected**, so no test was excluded or conditionally skipped without appearing in the summary.

## 2. Evidence that the real-MySQL tests executed

- **Per-test (JUnit, 19 m 57 s run):** `full_after.xml` contains **33** real-MySQL testcases, **all `passed`**, **0 skipped / 0 failed / 0 errors**. XML totals: `tests=1461, failures=0, errors=0, skipped=0`.
- **Skip-count (both runs):** `SKIPPED: 0 - every selected test ran.` The real-MySQL tests call `pytest.skip(...)` when `field_survey_test` is unavailable (`real_mysql.open_database()` → `NotAvailable`). Zero skips ⇒ the DB **was** reachable and the tests **ran**.
- **Runtime identity assertion passed:** `test_it_is_the_test_database_and_nothing_else` asserts `SELECT DATABASE() == "field_survey_test"` and passed ⇒ the connections were to `field_survey_test`.
- **Login-scope assertion passed:** `test_the_test_login_cannot_read_the_real_database` expects `SELECT … FROM field_survey.reports` to fail (errno 1142/1044/1146) and passed ⇒ the `fsr_test` login is **denied** access to production `field_survey`.

Execution is therefore established by per-test evidence and runtime assertions, **not** inferred from the total count alone.

## 3. Complete list of the 33 real-MySQL tests (from `full_after.xml`)

All 33 **passed**. Classification key: **S**=SELECT/read, **I**=INSERT, **U**=UPDATE, **D**=DELETE, **T**=TRANSACTION (commit/rollback), **L**=lock (`SELECT … FOR UPDATE` / `GET_LOCK`).

### `tests/test_db_mysql_real.py` (11)
| # | Test | Ops | Writes target |
|---|---|---|---|
| 1 | test_a_full_report_reads_back_as_written | I,S,T | FSR-ZZT-209910-… |
| 2 | test_writing_again_replaces_the_lines_not_adds_to_them | I,D,T,S | FSR-ZZT-209910-… (replace) |
| 3 | test_a_rollback_leaves_nothing_behind | I,T(rollback),S | FSR-ZZT-209910-… |
| 4 | test_lists_search_and_numbers | I,T,S | FSR-ZZT-209910-… |
| 5 | test_weekly_summary_has_one_row_per_item_line | I,T,S | FSR-ZZT-209910-… |
| 6 | test_the_lock_of_one_report_keeps_out_a_second_connection | L,S | none (GET_LOCK only) |
| 7 | test_report_exists_holds_the_row_inside_the_transaction | I,T,S | FSR-ZZT-209910-… |
| 8 | test_master_lists_add_names_and_never_duplicate | I(master_list),S | `ZZT-TEST-%` names |
| 9 | test_the_connection_check_and_the_tables | S | none |
| 10 | test_a_server_that_is_not_there_is_reported_as_away | connect-fail (no data) | none |
| 11 | test_the_shipment_fields_are_kept_and_old_lines_carry_none | I,T,S | FSR-ZZT-209910-… |

### `tests/test_real_mysql.py` (16)
| # | Test | Ops | Writes target |
|---|---|---|---|
| 12 | test_it_is_the_test_database_and_nothing_else | S | none |
| 13 | test_the_test_login_cannot_read_the_real_database | S (denied) | none |
| 14 | test_what_is_written_reads_back_equal_in_value | I,T,S | FSR-ZZT-209911-… |
| 15 | test_save_then_save_again | I,U,T,S | FSR-ZZT-209911-… |
| 16 | test_save_three_times_with_time_between | I,U,T | FSR-ZZT-209911-… |
| 17 | test_save_offline_then_catch_up_then_save_again | I,U,T | FSR-ZZT-209911-… |
| 18 | test_replace_then_save_again | I,U,T | FSR-ZZT-209911-… |
| 19 | test_changed_in_mysql_by_someone_else_then_save | I,U,S | FSR-ZZT-209911-… (UPDATE scoped to test control) |
| 20 | test_report_of_another_copy_is_not_overwritten | I,S | FSR-ZZT-209911-… |
| 21 | test_workbook_changed_outside_the_program_asks_again | I,S (conflict, no write) | FSR-ZZT-209911-… |
| 22 | test_a_report_being_saved_by_another_copy_is_not_written | I,L,S | FSR-ZZT-209911-… |
| 23 | test_a_conflict_leaves_no_half_written_report | I,U,S | FSR-ZZT-209911-… |
| 24 | test_round_sends_several_reports_over_one_connection | I,S | FSR-ZZT-209911-…(+ -2/-3) |
| 25 | test_power_cut_after_commit_resends_without_a_conflict | I,U,T | FSR-ZZT-209911-… |
| 26 | test_power_cut_before_commit_leaves_mysql_unchanged | I,U,T(rollback) | FSR-ZZT-209911-… |
| 27 | test_imported_reports_reach_the_real_database_in_one_round | I,S | FSR-ZZT-209911-…-I1..I5 |

### `tests/test_real_mysql_sqlite.py` (6)
| # | Test | Ops | Writes target |
|---|---|---|---|
| 28 | test_sent_from_the_workbook_moved_in_then_edited | I,U,S | FSR-ZZT-209912-… |
| 29 | test_save_then_save_again_on_the_database | I,U | FSR-ZZT-209912-… |
| 30 | test_offline_then_catch_up_on_the_database | I,U | FSR-ZZT-209912-… |
| 31 | test_another_copys_report_is_not_overwritten | I,S | FSR-ZZT-209912-… |
| 32 | test_a_restored_database_asks_again | I,S | FSR-ZZT-209912-… |
| 33 | test_the_export_does_not_make_the_ledger_look_stale | I,U,S | FSR-ZZT-209912-… |

**DDL:** none of the 33 tests executes `CREATE`/`ALTER`/`DROP` (schema is pre-loaded).

**Indirect writes via application functions:** `db_mysql.write_report` (INSERT + replace/DELETE of that control's children), `fsr_mysql_guard.Guard.save` / `fsr_save_journal.run` / `send_waiting` / `fsr_import.import_master_data` (all call `write_report`), `db_mysql.save_master_lists` (INSERT IGNORE). All are parameterized by the test control/name.

## 4. Database-target evidence

| Question | Evidence | Verdict |
|---|---|---|
| Tests used `field_survey_test`? | Live config `data/json/private/db_config.json` → `database=field_survey_test`; `test_it_is_the_test_database_and_nothing_else` (SELECT DATABASE() = field_survey_test) **passed**; `_checked()` guards every connection | **Confirmed** |
| `SELECT DATABASE()` verified? | `real_mysql._checked()` runs it on every `connect()` and refuses on mismatch (code + offline verify 14/14) | **Confirmed** |
| Every connection through the identity guard? | `RealTestDB.connect()` → `_checked(db_mysql.connect(...))`; `run()`/`load_report()`/etc. use `connect()` | **Confirmed** |
| Any test could connect to `field_survey`? | `settings()` requires exact `field_survey_test`; `_checked()` refuses otherwise; `test_the_test_login_cannot_read_the_real_database` proves the login is denied `field_survey` | **Confirmed No** |
| Production credentials used? | Config user = `fsr_test` (not `fsr_app`); access-denied test passed | **Confirmed No** |
| Env vars affected DB? | `FSR_TEST_DB_CONFIG` unset historically (default config used); `FSR_TEST_DB_NAME` does not exist in this code (name hardcoded) | **Confirmed** |

**Confirmed vs assumption:** confirmed that connections were to `field_survey_test` with the `fsr_test` login and that production `field_survey` was not accessible. **Assumption (unverifiable offline):** that no *other* process wrote to `field_survey_test` during the run.

## 5. SQL write-operation analysis

All write paths, with their predicates:

| Operation | Statement (parameterized) | Scope |
|---|---|---|
| Report insert/replace | `db_mysql.write_report` → `DELETE`/`INSERT` for a single `control_no` | Test control `FSR-ZZT-2099…` only |
| "Someone else" edit | `UPDATE reports SET so_number=%s WHERE control_no=%s` | Test control only |
| Master-list add | `INSERT IGNORE INTO master_list (list_name,item_name)` | `ZZT-TEST-%` names only |
| Cleanup (reports) | `DELETE FROM {incident_reports,remarks,item_lines,declared_goods,reports} WHERE control_no LIKE 'FSR-ZZT-2099%'` | Test prefix only |
| Cleanup (master_list) | `DELETE FROM master_list WHERE item_name LIKE 'ZZT-TEST-%'` | Test prefix only |

**Every INSERT/UPDATE/DELETE is bound to a test-generated control (`FSR-ZZT-2099…`) or test name (`ZZT-TEST-…`).** No statement targets an existing record by a non-test predicate. `INSERT IGNORE` on master_list cannot overwrite an existing different name.

**Foreign-key cascades:** `reports → declared_goods/item_lines/remarks/incident_reports` and `incident_reports → incident_lines` are `ON DELETE CASCADE`. Cascades fire only when a **test** report/incident row is deleted, so they cannot reach non-test rows. `incident_lines` has no `control_no`; it is removed only via its parent `incident_reports` (test) cascade.

## 6. Cleanup analysis

- Every real-MySQL module fixture calls `remove_test_rows()` **before and after** the module (`test_db_mysql_real.py:26-30`, `test_real_mysql.py:31-34`, `test_real_mysql_sqlite.py:30-33`).
- `remove_test_rows()` deletes only `control_no LIKE 'FSR-ZZT-2099%'` from the 5 report tables (children first), on the identity-checked connection.
- `test_db_mysql_real.py` additionally deletes `master_list WHERE item_name LIKE 'ZZT-TEST-%'` in teardown (lines 29-30).
- All 33 tests **passed** ⇒ module fixtures completed ⇒ teardown **ran**.
- **No failed tests** ⇒ no failure-aborted residual path.
- Offline verification (`test_run_temp/verify_harness.py`): cleanup issues exactly 5 deletes, each `LIKE %s` with param `FSR-ZZT-2099%`, on the 5 report tables only — **PASS**.

## 7. Existing-data protection assessment

**Verdict: CONFIRMED SAFE (by code inspection) — with an offline-evidence limitation.**

- All writes are scoped to `FSR-ZZT-2099…` (reports/children) and `ZZT-TEST-…` (master_list). No operation modifies existing, non-test records.
- Production `field_survey` was not reachable by the test login (proven by a passing test), and no production credentials were used.
- **Limitation:** I did not (and must not) query the live DB. I therefore **cannot prove** the exact row counts before/after, nor prove that **zero** residual test rows remain. The reported approximate counts (declared_goods 10, incident_lines 0, incident_reports 0, item_lines 7, master_list 54, remarks 8, reports 4) are InnoDB `information_schema.TABLE_ROWS` **estimates**, not exact, and cannot be reconciled offline.

**Per the owner's instruction, I do not claim existing data was preserved beyond what the code proves: no test path writes outside the test prefixes.**

## 8. Unresolved risks

1. **Residual test rows (unproven zero):** cleanup is code-scoped and teardown ran, but exact zero cannot be confirmed without a live `SELECT … WHERE control_no LIKE 'FSR-ZZT-2099%'` / `item_name LIKE 'ZZT-TEST-%'`. **INSUFFICIENT HISTORICAL EVIDENCE.**
2. **Composition of reported counts:** whether the ~4 `reports` / 7 `item_lines` / 10 `declared_goods` / 8 `remarks` / 54 `master_list` are pre-existing (e.g., manual use of the test copy) or residual test rows cannot be determined offline. **INSUFFICIENT HISTORICAL EVIDENCE.**
3. **master_list uses a different prefix** (`ZZT-TEST-`) and a **separate** teardown DELETE, not the `FSR-ZZT-2099%` cleanup. If that module's teardown had not run, `ZZT-TEST-` rows could remain. It did run (tests passed), so this is a **POTENTIAL (low) RISK** only if the process had been interrupted.
4. **`FSR test` connection label** still unconfirmed (owner-side); not used by the harness.
5. **Live config points at `field_survey_test`:** future runs will target it unless changed; the owner wishes to preserve it. (Operational, not a data-integrity defect.)
6. **No SQL/DB logs exist** for the historical run; the audit is based on source + test outcome artifacts, not a statement log.

## 9. Recommendations for the isolated Phase 5 database (`fsr_phase5_isolated_test`)

The future harness should:
1. Require explicit `FSR_TEST_DB_NAME` (no default).
2. Require explicit `FSR_TEST_DB_CONFIG` (no fallback to the app's `db_config.json`).
3. Have **no silent fallback** to `field_survey_test`.
4. **Reject `field_survey`** (production).
5. **Reject `field_survey_test`** (preserve).
6. **Reject any unapproved DB name** (allow-list of exactly `fsr_phase5_isolated_test`).
7. Verify `SELECT DATABASE()` on **every** connection.
8. Use a **dedicated restricted account** (DML only on the isolated DB).
9. Restrict cleanup to generated test records — and **unify the prefix** so master_list uses the same `FSR-ZZT-2099%` scheme (or explicitly document/clean `ZZT-TEST-%`), so one guard covers all tables.
10. Never use production credentials.

These are **not implemented** in this phase.

---

## Verdicts

| Area | Verdict |
|---|---|
| Real-MySQL tests executed | **CONFIRMED** (33/33 passed, 0 skipped; JUnit + runtime assertions) |
| Database target = `field_survey_test` | **CONFIRMED** |
| Production `field_survey` accessed / production creds used | **CONFIRMED NO** |
| Modification of existing (non-test) records | **CONFIRMED SAFE** (by code inspection; no non-test write path) |
| Zero residual test rows | **INSUFFICIENT HISTORICAL EVIDENCE** (no live query) |
| Exact before/after row counts | **INSUFFICIENT HISTORICAL EVIDENCE** (estimates only) |
| master_list cleanup (separate `ZZT-TEST-` prefix) | **POTENTIAL (low) RISK** if teardown interrupted; ran in this run |
| Any confirmed data modification of existing data | **None found** |

## Files modified

- **Created:** `docs/phase-5/PHASE_5_1_HISTORICAL_MYSQL_DATA_INTEGRITY_AUDIT.md` (this report).
- **No other repository files were modified.** Scratch analysis scripts are under the git-ignored `test_run_temp/`.

**STOP — historical audit complete. No database was contacted; no SQL executed; nothing created/modified in any database. Awaiting owner review before Phase 5.2.**