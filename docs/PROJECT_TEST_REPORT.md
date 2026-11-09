# Field Survey Report Project Test Report

**Run date:** 1 November 2026  
**Environment:** Windows (`win32`), Python 3.14.4, pytest 9.2.0  
**Overall result:** **PASS; human-operated UI acceptance remains not tested**

## 1. Project and environment

The application is a Tkinter/ttkbootstrap desktop program. Inspection reports
are stored in Excel; JSON stores local accounts, settings, sidecar data, and
other application data. MySQL is an optional mirror. Warehouse summaries and
exports are derived from saved reports.

The repository already had extensive staged/unstaged-equivalent working-tree
changes and untracked files before this test run. Those changes were preserved.
The application tests, UI checks, PDF fixtures, 500/1,000-report benchmarks,
package build, installation, and startup used temporary folders. No production
workbook was opened for writing. The schema was subsequently created in
MySQL Workbench by the user, and adapter integration tests used a unique
temporary report identifier that was deleted along with its dependent rows
after verification. Existing Demo/report workbooks, templates, and private
settings/account/configuration files were not changed. No credential
contents were included in this report.

## 2. Scope and methods

Automated tests use pytest temporary directories. The GUI harness starts the
real application with a test identity, automatically answers message boxes,
and returns from Tk's event loop so it can exercise the real widgets and
application callbacks. It does not simulate a person's mouse or keyboard.
Follow-up checks also captured the real Tk window and report form for visual
review and exercised the saved-report search dialog by driving its controls.

The MySQL unit tests use fake connections. The user created the schema in
Workbench using an administrator connection and configured the app login.
The follow-up integration used the configured `fsr_app` login against the
local `field_survey` database. A uniquely generated QA report and dependent
rows were removed after the checks. No credentials are recorded here.

## 3. Automated test suite

**Current full suite:**  
**Command:** `.venv\Scripts\python.exe -m pytest -q`  
**Result:** **241 passed, 0 failed, 0 skipped** in **213.58 seconds**.

| Test module | Passed |
|---|---:|
| `test_analytics.py` | 12 |
| `test_auth.py` | 9 |
| `test_db_mysql.py` | 3 |
| `test_exports.py` | 23 |
| `test_gui.py` | 24 |
| `test_import.py` | 16 |
| `test_inventory.py` | 39 |
| `test_legacy_import.py` | 28 |
| `test_periods_and_parsing.py` | 36 |
| `test_sample_data.py` | 30 |
| `test_storage_regression.py` | 14 |
| `test_store.py` | 7 |
| **Total** | **241** |

The full suite was rerun after the PDF fix. The test tree currently collects
241 tests; all 241 passed in this run.

Earlier, the affected export module independently passed all 23 tests.

## 4. Application startup and navigation

**PASS — automated GUI startup and navigation.** All 24 GUI tests passed.
They start the application in an isolated `FSR_HOME`, verify the window and
navigation, visit the application modules, and exercise screens and callbacks
without reported startup errors.

**PASS — documented Python entry point from another working directory.** Ran
`main.py` with the current directory outside the repository and `FSR_HOME`
pointing to a temporary directory. The window started, no error message was
shown, and application data directories were created under the temporary
home.

**PASS — visual Tk review.** Captured the actual 1440 × 820 application window
on a 1920 × 1080 desktop. The report form, navigation, required-condition
prompt, and saved-report search results were visible without clipped controls
or overlapping form elements. Automated validation produced the expected
"Cargo Condition" and "Missing SO Number" warnings.

The app's status bar showed "Server inactive" in this isolated no-MySQL
profile; this was an optional-storage status, not a startup error.
Human-operated mouse/keyboard acceptance remains **NOT TESTED**.

## 5. Report workflows

**PASS — create, save, reopen, edit, and save in place.** The GUI test created
a fictional Receiving report, read it back from its isolated workbook,
checked generated Control Number and Receiving Ref values, reopened it,
edited it, and confirmed one saved record remained.

**PASS — Bad Order and incident data.** The GUI test saved a Bad Order report
with an incident line and verified the stored JSON and generated report-form
workbook. Sample-data and storage tests also exercise Good Order and Bad Order
records.

**PASS — data-layer retrieval, indexing, and filters.** Storage, analytics,
inventory, and GUI tests passed, including report listing/search-index
behavior, warehouse calculations, and period/filter scenarios.

**PASS — focused UI-harness workflow.** Created and saved fictional Good
Order and Bad Order records, checked the Bad Order incident entry, filtered
the saved-report dialog by description and SO Number, reopened the result,
edited it, saved again, and read the updated record back from the isolated
workbook. Both classification values persisted.

These were real application widgets and callbacks, not a human-operated
acceptance test. Search by Cargo ID was not treated as a supported search
field; the dialog's supported description and SO Number searches were
verified. GUI deletion, every optional form field, and manual keyboard/mouse
flows remain **NOT TESTED**.

## 6. Excel and JSON storage

**PASS — isolated Excel storage.** Tests save and read reports, update reports
without duplicates, preserve older workbook compatibility, reject foreign
workbooks, and validate report listing/search behavior. The GUI test generated
and opened the report-form workbook and confirmed its expected worksheets.
All writes used test workbooks.

**PASS — tested JSON paths.** Tests cover account-file validation and
protection against overwriting malformed account data, JSON-backed incident
records, and an unreadable warehouse sidecar error. The report workflow
verified that incident data round-trips.

The complete matrix of missing, empty, malformed, and structurally invalid
files for every JSON configuration type was **NOT TESTED**. No real account,
settings, or database configuration was changed.

## 7. MySQL and schema

**PASS — fake-connection adapter tests (3 tests).** They verify compatibility
with older item tables, optional warehouse-link columns, and the adapter's
schema-upgrade statement generation.

**PASS — Workbench schema setup (user-confirmed).** The user reported that the
legacy schema script ran successfully in Workbench and configured the
least-privilege app account.

**PASS — live adapter integration.** Using the configured app account:
connection/table check, insert, retrieval, search indexing, update, and
duplicate-control-number upsert were verified. A deliberately malformed
child row raised after the report header had been updated; the adapter rolled
back the transaction and the previously committed report remained unchanged.
A unique temporary report and its cascading child rows were then deleted and
verified absent. No existing report was modified.

The initial QA attempt had been blocked by MySQL error 1044 when the app
account lacked schema-creation privilege. This was resolved by creating the
schema through the user's Workbench admin connection; no database DDL was
executed by the app account during the CRUD checks.

**Static compatibility assessment:** [`field_survey_schema.sql`](../data/schema/field_survey_schema.sql)
is the legacy schema intended for the current `db_mysql.py` adapter. Its
reports, declared-goods, item-lines, remarks, incident, and master-list
structures and keys align with the adapter's table/column expectations by
static inspection. The user confirmed the legacy schema script ran
successfully in Workbench.

[`field_survey_schema_v2_proposed.sql`](../data/schema/field_survey_schema_v2_proposed.sql)
is explicitly a separate proposal for a new `field_survey_v2` database. It is
**not a drop-in compatible schema** for the current adapter; a separate
adapter/migration would be required. The v2 proposal was not applied; the
legacy schema is the one the user installed.

## 8. PDF and Excel report generation

**PASS — warehouse exports generated and opened by tests.** The export tests
produce Excel and PDF files for every configured warehouse report type.
`openpyxl` reads the generated workbooks; `pypdf` opens the PDFs and verifies
report titles and extracted page-footer text. Additional assertions compare
exported report values with summaries and inventory data.

**PASS — visual inspection of a representative rendered PDF.** Opened a
three-page weekly Receiving summary PDF in the browser PDF viewer. It included
three cargo items and a long remark with escaped characters. After the fix,
wide tables were split into readable horizontal parts, long text appeared in
a full-width details section, and page headers/footers were present. The
review covered page breaks, table readability, cargo details, text placement,
page-edge clearance, and clipping; no overlap or clipped content was observed.
Large multi-page reports were opened by `pypdf`; visual review was limited to
the representative report, and margins were not measured against a print
specification.

Inspection-form PDF/printing remains **NOT TESTED**; Excel/LibreOffice
automation was unavailable.

## 9. Error handling and edge cases

**PASS — tested automated cases.** The suite covers invalid dates and parsing,
older workbook structures, malformed account-file protection, unreadable
sidecar errors, imports with invalid/duplicate records and special
characters, missing quantities/units, unmatched withdrawals, duplicate
references, inconsistent units, and empty datasets.

**NOT TESTED — exhaustive fault injection.** Read-only workbook saves,
permission failures, process interruption during every save path, all malformed
JSON shapes, and live database connection failures were not comprehensively
injected. No failing assertion or confirmed application defect was found in
the executed tests.

## 10. Performance and larger datasets

**PASS — isolated 500- and 1,000-report benchmarks.** Both datasets contained
Good Order and Bad Order records and were created only in temporary
directories. Results on this machine:

| Dataset | Snapshot load | Search/filter | One report update save | Build monthly summary | PDF + Excel export | PDF pages |
|---|---:|---:|---:|---:|---:|---:|
| 500 reports | 0.615 s | 0.000696 s (416 matches) | 0.473 s | 0.019 s | 2.646 s | 55 |
| 1,000 reports | 0.844 s | 0.002037 s (916 matches) | 0.787 s | 0.024 s | 8.906 s | 121 |

Both datasets contained Good Order and Bad Order records and used isolated
fictional Excel workbooks. Generating the initial 84 reports took 15.836 s;
adding reports 85–500 took 162.458 s; adding reports 501–1,000 took
343.566 s. The measured report export was a monthly Receiving summary.

These are single-run local measurements, not performance guarantees. Startup
time and memory use were not measured. The large summary PDF page counts
reflect the broad report table layout and warrant consideration when users
export large monthly datasets.

## 11. Installation and portability

**PASS — isolated package and installer test.** PyInstaller produced a
1,978-file package (120,520,119 bytes) in a temporary stage. Inno Setup 6
compiled a 41,861,983-byte installer. The installer was installed silently
into a temporary directory, required templates/schema/resources were checked,
and the installed executable launched to its Sign In window using an isolated
user profile. The app created data under that profile; the temporary
installation was then uninstalled.

The repository's `build_installer.bat` was not run because it deletes the
existing `build` and `dist` directories. Equivalent PyInstaller and Inno
commands were run with redirected outputs in the isolated temporary stage.
Fresh dependency installation and clean-machine/VM testing remain
**NOT TESTED**.

## 12. Defects, fixes, and regression testing

**FAIL (reproduced before fix; resolved):** a long remark in a wide warehouse summary table caused
ReportLab `LayoutError` because a single table row grew beyond the page frame.
Visual inspection also showed the 29-column report compressed into an
unreadable single table.

**Fix:** long cell values now remain complete in a full-width Long Text
Details section, and wide tables are split into horizontal parts with key
identifiers repeated. Small groups of rows are kept together to avoid broken
continuations. Added
`test_long_multi_item_remarks_export_to_pdf` as a regression test.

**Verification:** the new test failed before the change and passed afterward;
all 23 tests in `tests/test_exports.py` pass after the change. The full suite
was not rerun after this focused fix. The v2 schema's lack of drop-in
compatibility is intentional, not an application defect.

## 13. Tests not performed and remaining risks

| Check | Status | Reason |
|---|---|---|
| Live MySQL CRUD/rollback tests | **PASS** | Adapter CRUD, upsert, search, and rollback verified; unique temporary record cleaned up. |
| MySQL DDL execution and deployed-schema comparison | **PASS (user-confirmed setup)** | User reported the compatible schema script ran in Workbench; no independent server-side DDL inspection was performed. |
| Human-operated keyboard/mouse acceptance | **NOT TESTED** | GUI actions were automated through the real Tk application. |
| Inspection-form PDF/printing | **NOT TESTED** | Excel/LibreOffice conversion workflow was not run. |
| Fresh-machine dependency install / VM deployment | **NOT TESTED** | Installer was tested on this machine in a temporary install/profile. |
| 500/1,000-report memory benchmark | **NOT TESTED** | Load/save/search/export timings were measured; memory was not. |
| Exhaustive permission/read-only/interrupted-save tests | **NOT TESTED** | Not all filesystem failure modes were injected. |

## 14. Running the application and tests

From the repository root on Windows:

```bat
.venv\Scripts\python.exe main.py
.venv\Scripts\python.exe -m pytest -v
```

Use `START_DEMO.bat` only when intentionally working with the existing Demo
profile. The Demo launcher and its persistent sample workbook were not used
for this test run.
