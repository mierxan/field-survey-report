# Testing Report

## Latest run after data-file organization

* **Command:** `.venv\Scripts\python.exe -m pytest -q`
* **Result:** **240 passed, 0 skipped** in 230.23 seconds.
* All 24 GUI tests ran, including application startup and report-form
  generation through the test harness. The harness used a test account.
* `git diff --check` and Python compilation of the modified path modules
  passed. See [FILE_ORGANIZATION.md](FILE_ORGANIZATION.md) for the move and
  hash verification.

## Previous baseline run before file organization

* **Run:** 31-Oct-2026 on Windows, Python 3.14.4.
* **Command:** `.venv\Scripts\python.exe -m pytest -q`
* **Result:** **210 passed, 0 failed, 0 skipped** (203.40 s).

| Test file | Tests | Passed |
|---|---|---|
| test_analytics.py | 12 | 12 |
| test_auth.py | 9 | 9 |
| test_db_mysql.py | 3 | 3 |
| test_exports.py | 22 | 22 |
| test_gui.py | 24 | 24 |
| test_import.py | 16 | 16 |
| test_inventory.py | 39 | 39 |
| test_periods_and_parsing.py | 36 | 36 |
| test_sample_data.py | 29 | 29 |
| test_storage_regression.py | 14 | 14 |
| test_store.py | 6 | 6 |

All tests run in temporary folders (`FSR_HOME` / pytest `tmp_path`). The
real Excel file, `settings.json`, `users.json` and MySQL server are not
used. Expected values are worked out independently in the tests, from
hand-made records or the generator's specification, not from the code
under test. Authentication tests cover malformed account-file protection,
first-run owner setup, sign-up/approval/sign-in, and password changes.
The password-policy tests also confirm that existing shorter credentials
remain valid for sign-in while new passwords require at least 12 characters.

## Results by area

| Test | Expected | Actual | Result | Notes |
|---|---|---|---|---|
| **Application startup** (test_gui) | Program starts, navigation with 8 modules, Control # assigned | As expected | Pass | Sign-in replaced by a test user |
| Every module opens (test_gui) | No error message in any module / tab / summary mode | No error | Pass | |
| Theme light ↔ dark (test_gui) | Switches without errors | As expected | Pass | |
| Demo Mode isolation (manual script, `FSR_DEMO=1`) | Data + settings in demo_data, MySQL off, real settings.json unchanged | As expected (checksum unchanged) | Pass | Run once by script, not part of pytest |
| **Existing inspection workflow** – create, save, open, edit, save again (test_gui) | Saved; reopened; updated in place (one row) | As expected | Pass | |
| Report numbering (test_gui, test_storage_regression) | Next FSR-YYYY-NNNN; a new report never overwrites | As expected | Pass | |
| Report forms from templates (test_gui) | `Report Forms\<Control #>_Report.xlsx` with First Page (+ Incident sheet for Bad Order) | As expected | Pass | PDF conversion of the forms (needs Excel/LibreOffice) not run |
| Good / Bad Order + incident report (test_gui, regression) | Condition saved; incident lines in JSON and on the form | As expected | Pass | |
| Excel storage round trip, older workbook ("UOM", no new columns), foreign workbook refused, search index (test_storage_regression) | Unchanged behaviour; old files readable and upgraded | As expected | Pass | |
| Master list file valid; date/time normalisation | As before | As expected | Pass | |
| **Receiving summaries** daily / weekly (Mon–Sun) / monthly, previous-period comparison (test_analytics) | Counts and per-unit quantities as calculated by hand | As expected | Pass | |
| **Withdrawal summaries** (test_analytics, test_sample_data) | Same | As expected | Pass | |
| Date / warehouse / condition / search filters (test_analytics) | Exactly the expected reports | As expected | Pass | |
| **Dashboard KPIs** (test_analytics, test_gui) | Match the records; KPI cards show the same values as the analytics | As expected | Pass | |
| % change with previous period = 0 | No division; "not meaningful" text | As expected | Pass | |
| Empty data set | No crash; values 0 / "-" / "Not tracked" | As expected | Pass | |
| **Bad Order monitoring** KPIs, breakdowns, unresolved only from recorded status (test_analytics, test_sample_data) | As specified | As expected | Pass | |
| **Inventory** – no withdrawal, partial, full, multiple receiving, multiple withdrawals, over-withdrawal (negative kept), unmatched, no-ID withdrawal not matched by description, missing quantity (receiving and withdrawal), warehouses separate, incompatible units (received / withdrawn), unit aliases, duplicate Receiving Ref, look-alike lines not duplicates, as-of date, weights only with units (test_inventory) | Hand-calculated balances / statuses | As expected | Pass | 39 tests |
| **Sample data scenarios A–M** on the saved TEST workbook (test_sample_data) | A 20 · B 65 · C 0 · D 75 · E 55 · G 15/30 · H −5 Over-Withdrawn · I unmatched · J Reconciliation Required · K 30 (A) / 5 (B) · L 3/14/45/75/100 days in the right buckets · M counted once | As expected | Pass | |
| Filler balances vs independent arithmetic (test_sample_data) | Every filler item equal | As expected | Pass | |
| **Inventory aging** buckets, configurable thresholds, invalid dates excluded, FIFO by batch | As specified | As expected | Pass | |
| **Reconciliation** – propose / confirm from the UI; derived ledger changes, original report unchanged, audit log and owner-only confirmation (test_store, test_gui) | As specified | As expected | Pass | GUI test verifies saved audit actions and that the source report remains unchanged |
| **Excel exports** – all 13 report types; header block; values read back = ledger / summary; quantity totals never across units (test_exports) | As specified | As expected | Pass | |
| **PDF exports** – all 13 report types; title on page 1; "Page N of N" on the last page (test_exports) | As specified | As expected | Pass | Checked by text extraction; page images were not inspected (no PDF renderer here) |
| **Sample data generation** ≥ 50 / ≥ 30, ≥ 3 months, TEST IDs, repeatable without duplicates, refuses real workbooks / program folder, reset removes TEST only (test_sample_data) | As specified | 52 Receiving / 32 Withdrawal, 4 months | Pass | |
| MySQL layer with a fake connection: link columns written only when present, note otherwise, upgrade adds only missing columns (test_db_mysql) | As specified | As expected | Pass | |

## Not run / not verified

| Item | Why | Recommendation |
|---|---|---|
| MySQL against a real server (save, load, `load_all_reports`, `upgrade_schema`) | Not run; no live or test database was contacted | Test on an isolated database copy before deployment |
| PDF / printing of the inspection forms | Needs Microsoft Excel or LibreOffice automation; unchanged code | Check Print / PDF once after the update |
| Visual review of the exported PDFs | No PDF renderer in this environment | Open a few exported PDFs |
| Installer build (PyInstaller / Inno Setup) | Not run | Run `build_installer.bat` and start the built program once |
| Colour-blind palette validator | Node.js not installed; the documented reference palette values were used | Optional |
| Hands-on use by a person (keyboard flow, file dialogs) | The GUI tests drive the program's functions, not mouse and keyboard | Click through each module once |
| Performance with very large files | The sample has 84 reports. Loading runs in a background thread and tables page at 500 rows, but thousands of reports were not measured | Measure with a copy of real data |
| MySQL load performance | No isolated MySQL server was available; the repeated per-report query pattern has not been benchmarked | Benchmark `load_all_reports` on a disposable database before optimizing |
