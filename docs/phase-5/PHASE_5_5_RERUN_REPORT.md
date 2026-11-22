# Phase 5.5 — Real-MySQL Integration Test RERUN Report

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **PASS** (33 passed, 0 failed, 0 skipped)

Rerun of the three real-MySQL integration test files against `fsr_phase5_isolated_test` (account `fsr_phase5@localhost`), after the Phase 5.6/5.7/5.8 schema-completeness fix was applied. This supersedes the earlier Phase 5.5 FAIL (which was caused by the missing `packing_list_no` / `origin_line` columns).

---

## 1. Environment

- `FSR_TEST_DB_NAME = fsr_phase5_isolated_test`
- `FSR_TEST_DB_CONFIG = D:\Build Build Build\PythonProject\data\json\private\db_config.phase5.json`
- Identity verified in Phase 5.8C: `DATABASE()=fsr_phase5_isolated_test`, `USER()=fsr_phase5@localhost`; `item_lines` has 20 columns incl. `packing_list_no` and `origin_line` (`VARCHAR(120) NULL`).

## 2. Commands executed (each file separately)

```powershell
.venv\Scripts\python.exe -m pytest tests\test_real_mysql.py        -rs -q --junitxml=test_run_temp\phase55b_real_mysql.xml
.venv\Scripts\python.exe -m pytest tests\test_real_mysql_sqlite.py -rs -q --junitxml=test_run_temp\phase55b_real_mysql_sqlite.xml
.venv\Scripts\python.exe -m pytest tests\test_db_mysql_real.py     -rs -q --junitxml=test_run_temp\phase55b_db_mysql_real.xml
```

## 3. Results per file

| File | Passed | Failed | Skipped | Duration |
|---|---:|---:|---:|---:|
| `tests/test_real_mysql.py` | 16 | 0 | 0 | 157.85 s |
| `tests/test_real_mysql_sqlite.py` | 6 | 0 | 0 | 61.92 s |
| `tests/test_db_mysql_real.py` | 11 | 0 | 0 | 43.69 s |
| **Total** | **33** | **0** | **0** | **~263 s (4:23)** |

No unexpected skips (`SKIPPED: 0` on every file). The two previously failing tests (`test_the_connection_check_and_the_tables`, `test_the_shipment_fields_are_kept_and_old_lines_carry_none`) now pass.

## 4. Cleanup verification

Post-run, using the dedicated account on the isolated database, residual `FSR-ZZT-2099%` rows:

| Table | Residual |
|---|---:|
| reports | 0 |
| declared_goods | 0 |
| item_lines | 0 |
| remarks | 0 |
| incident_reports | 0 |
| master_list | 0 |

**Cleanup completed; zero residual test-prefix records.**

## 5. Protected databases

- No protected database (`field_survey`, `field_survey_test`) was accessed or modified. The harness only connects to `fsr_phase5_isolated_test`; `test_the_test_login_cannot_read_the_real_database` confirmed `field_survey` reads are denied.
- No DDL/DML/privilege changes were made by the tests beyond the isolated test rows (all cleaned up).

## 6. Overall status: **PASS**

All completion criteria met: 33 passed, 0 failed, 0 skipped, 0 residual test-prefix rows, no protected-DB modification. Phase 5.5 integration testing is validated.

---

**STOP — Phase 5.5 rerun PASS. Awaiting owner direction for the next phase (e.g., coverage baseline, installer validation, or release assessment).**