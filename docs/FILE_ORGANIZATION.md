# Field Survey Report file organization

This is the historical file-move inventory. Approved cleanup on
14 November 2026 removed the superseded SQL proposal from the working tree
(retained in Git history), removed the legacy root Demo marker, and moved
the root Demo folder's untracked log/empty directory to
`D:\FSR_Cleanup_2026-11-14\demo_data`. The empty root `migration_output`,
`data/json/migration_output`, and `data/schema/private` directories were
also moved there, with their relative paths preserved. Current managed
Demo folders under `data/excel` and `data/json` remain in use and unchanged.

## Plan and safeguards

The project was scanned for `.sql`, `.json`, and Excel workbooks before any
files were moved. JSON was inspected for top-level structure only; passwords,
credentials, and account values were not displayed. Workbook sheet names were
read in read-only mode. No running Field Survey Report application was found.

The dedicated `data/` tree separates database scripts, JSON, and Excel files.
Local credentials and account files are kept in git-ignored private
subfolders and are not bundled as public project data. Existing per-user data
outside the project (for example a workbook selected through the file picker)
continues to stay with its owner; only managed project data uses the new
folders.

## Moved-file inventory: application files

| Original path | Final path | Purpose | Application consumers |
|---|---|---|---|
| `field_survey_schema.sql` | `data/schema/field_survey_schema.sql` | Current optional-MySQL creation schema. | Manual MySQL setup documentation and installer payload; not executed by application startup. |
| `add_shipment_columns.sql` | `data/schema/add_shipment_columns.sql` | Older database alteration script. | Manual database maintenance only. |
| `update_declared_goods.sql` | `data/schema/update_declared_goods.sql` | Older database alteration script. | Manual database maintenance only. |
| `migrations/001_add_item_warehouse_links.sql` | `data/schema/migrations/001_add_item_warehouse_links.sql` | Optional MySQL migration for warehouse link fields. | Settings instructions, installer payload, and manual upgrade. |
| `migrations/002_add_item_uom_currency.sql` | `data/schema/migrations/002_add_item_uom_currency.sql` | Optional MySQL migration for item UOM/currency fields. | Manual database upgrade. |
| `migrations/003_add_item_list_form.sql` | `data/schema/migrations/003_add_item_list_form.sql` | Optional MySQL migration for item form/list fields. | Manual database upgrade. |
| `docs/schema/field_survey_schema_v2_proposed.sql` | `data/schema/field_survey_schema_v2_proposed.sql` | Proposal-only normalized schema; not applied. | Design documentation only. |
| Earlier superseded SQL draft | Removed in the approved 14 November 2026 cleanup; retained in Git history | Superseded proposal; never applied by cleanup. | No active consumers. |
| `allow_network_access.sql` | `data/schema/private/allow_network_access.sql` | Local database administration script; ignored and not packaged. | Manual/local use only. |
| `set_password.sql` | `data/schema/private/set_password.sql` | Local database credential administration script; ignored and not packaged. | Manual/local use only. |
| `First_Page.xlsx` | `data/excel/First_Page.xlsx` | Unchanged first-page report template. | `field_survey_report.py` report form generator. |
| `Cargo_Details.xlsx` | `data/excel/Cargo_Details.xlsx` | Unchanged Default item-list template. | `field_survey_report.py` cargo form generator. |
| `Containerized_Loading_Form.xlsx` | `data/excel/Containerized_Loading_Form.xlsx` | Unchanged Containerized and Loading templates. | `field_survey_report.py` cargo form generator. |
| `Incident_Report.xlsx` | `data/excel/Incident_Report.xlsx` | Unchanged incident report template. | `field_survey_report.py` incident form generator. |
| `demo_data/Field_Survey_Reports_DEMO.xlsx` | `data/excel/demo_data/Field_Survey_Reports_DEMO.xlsx` | Fictional demo report workbook (Reports, Declared Goods, Item List, Remarks sheets). | Demo Mode and `warehouse/sample_data.py`. |
| `Report Forms/FSR-2026-0001_Report.xlsx` | `data/excel/Report Forms/FSR-2026-0001_Report.xlsx` | Existing generated report-form workbook; retained unchanged. | Existing generated output; normal new output follows the selected workbook's parent. |

No separate production report workbook named `Field_Survey_Reports.xlsx` was
present in the project scan. The configured production workbook is selected
or created at runtime.

## Moved-file inventory: JSON files

| Original path | Final path | Purpose | Application consumers |
|---|---|---|---|
| `master_list.json` | `data/json/master_list.json` | Seven editable master-list categories; tracked application data. | `field_survey_report.py`, Settings page. |
| `db_config.example.json` | `data/json/db_config.example.json` | Safe example of optional MySQL configuration (no live account values). | `db_mysql.py` setup guidance. |
| `db_config.json` | `data/json/private/db_config.json` | Local optional-MySQL credentials; ignored by Git. | `db_mysql.py`; Windows application configuration. |
| `auth_seed.json` | `data/json/private/auth_seed.json` | Owner account seed (names and password hash only); ignored by git, bundled into the Owner installer only. Rewritten by `python app_auth.py make-seed`. | `app_auth.py`; Owner installer build input. |
| `users.json` | `data/json/private/users.json` | Local account records and password hashes; ignored by Git. | `app_auth.py` via `field_survey_report.py`. |
| `settings.json` | `data/json/private/settings.json` | Per-PC settings and paths; ignored by Git. | `field_survey_report.py`. |
| `installer_defaults/db_config.json` | `data/json/private/installer_defaults/db_config.json` | Private installer configuration input; ignored and not included in public example data. | Installer build scripts/specification. |
| `demo_data/master_list.json` | `data/json/demo_data/master_list.json` | Fictional demo master lists. | Demo Mode settings. |
| `demo_data/settings.json` | `data/json/demo_data/settings.json` | Demo-specific UI settings. | Demo Mode. |
| `Incident Reports/FSR-2026-0004.json` | `data/json/Incident Reports/FSR-2026-0004.json` | Existing incident sidecar, including its envelope metadata. | `fsr_storage.py` incident load/save helpers. |
| `demo_data/Incident Reports/TEST-REC-0025.json` | `data/json/demo_data/Incident Reports/TEST-REC-0025.json` | Demo incident record. | `fsr_storage.py` in Demo Mode. |
| `demo_data/Incident Reports/TEST-REC-0026.json` | `data/json/demo_data/Incident Reports/TEST-REC-0026.json` | Demo incident record. | `fsr_storage.py` in Demo Mode. |
| `demo_data/Incident Reports/TEST-REC-0027.json` | `data/json/demo_data/Incident Reports/TEST-REC-0027.json` | Demo incident record. | `fsr_storage.py` in Demo Mode. |
| `demo_data/Incident Reports/TEST-REC-0032.json` | `data/json/demo_data/Incident Reports/TEST-REC-0032.json` | Demo incident record. | `fsr_storage.py` in Demo Mode. |
| `demo_data/Incident Reports/TEST-REC-0039.json` | `data/json/demo_data/Incident Reports/TEST-REC-0039.json` | Demo incident record. | `fsr_storage.py` in Demo Mode. |
| `demo_data/Incident Reports/TEST-REC-0046.json` | `data/json/demo_data/Incident Reports/TEST-REC-0046.json` | Demo incident record. | `fsr_storage.py` in Demo Mode. |
| `demo_data/Incident Reports/TEST-WDR-0021.json` | `data/json/demo_data/Incident Reports/TEST-WDR-0021.json` | Demo incident record. | `fsr_storage.py` in Demo Mode. |
| `migration_output/legacy_master_data.json` | `data/json/migration_output/legacy_master_data.json` | Existing legacy import/export output; retained as local data. | No runtime reader found; `fsr_legacy_import.py` creates outputs in the user-selected destination. |
| `migration_output/summary.json` | `data/json/migration_output/summary.json` | Existing legacy conversion summary; retained as local data. | No runtime reader found; `fsr_legacy_import.py` creates outputs in the user-selected destination. |

## Files intentionally not moved

* `dist/` and `build/` contain generated packaging artifacts, including
  bundled copies of some templates and third-party dependency JSON assets.
  They are build outputs, not authoritative project data. The bundled
  `Cargo_Details.xlsx` and `First_Page.xlsx` copies were byte-identical to the
  source templates at scan time; generated outputs remain untouched.
* SQL scripts and JSON resources inside compiled distributions, installer
  archives, and third-party libraries are not project source inputs and stay
  inside their respective build/dependency artifacts.
* Any workbook or sidecar selected from outside the managed `data/` folders
  remains in that external location. Generated sidecars follow the workbook
  unless it is in the managed Excel tree, in which case they use the matching
  path under `data/json/`.
* Python source, documentation other than the two proposal SQL files,
  dependency manifests, logs, installer archives, and unrelated binaries
  remain in place.

## Final structure and move verification

The project scan found no same-name collisions among the authoritative
source files selected for these destinations. Build-directory template copies
are outputs, not competing sources. All 35 moved files were checked against
their pre-move SHA-256 hashes and retained identical bytes; no JSON, workbook,
or SQL content was edited. SQL scripts under `data/schema/private/` are
local-only and are not included in release packages.

```text
data/
  schema/                 SQL scripts, migrations, and proposal SQL
    migrations/
    private/               ignored local administration scripts
  json/                    master lists and sidecars
    demo_data/
    private/                ignored local accounts/settings/configuration
    migration_output/
  excel/                    templates, existing workbook, and Demo workbook
    demo_data/
    Report Forms/
```

### Path updates

* `fsr_paths.py` centralizes managed data paths and maps sidecars for a
  managed workbook into the parallel `data/json/` tree.
* Application startup, auth, optional MySQL configuration, Excel templates,
  warehouse sidecars, and the legacy-import ledger now use the organized
  paths. Workbooks selected outside the managed Excel folder retain adjacent
  sidecars and user-selected locations.
  The affected modules include `field_survey_report.py`, `fsr_paths.py`,
  `fsr_storage.py`, `fsr_import.py`, `warehouse/store.py`,
  `warehouse/sample_data.py`, `app_auth.py`, and `db_mysql.py`.
* PyInstaller and installer inputs now point at the `data/` paths.
* README/setup instructions, schema SQL links, and the GUI test's isolated
  workbook path were updated.
* The existing Demo Mode safety marker was copied (not moved) to
  `data/excel/demo_data/.fsr_test_data`. The copy was verified by SHA-256.
  The unused original root marker was later removed in the approved cleanup.
* Existing saved workbook locations are retained, even if they are outside
  the project. The saved setting referenced a missing workbook named
  `Field_Survey_Reports.xlsx`; it was not rewritten or redirected because
  the setting may represent an intentional external location.

### Files intentionally left in place and exceptions

* `dist/` and `build/` contain generated packaging artifacts, including
  bundled copies of templates and third-party dependency JSON assets. These
  are not authoritative project data and were left unchanged.
* At the original file move, the root `demo_data/` marker and empty runtime
  artifacts were left untouched. The application and demo generator no
  longer used that path. The later approved cleanup removed the tracked
  marker and moved the untracked remainder to the quarantine folder above.
* Compiled distributions, installer archives, and third-party libraries keep
  their internal SQL/JSON resources in place.
* Python source, documentation (apart from the two proposal SQL files),
  dependencies, logs, installer archives, and unrelated binaries remain in
  their original locations.
* The scan found no duplicate filenames among authoritative source files.
  No application reference to the old project-root template, master-list,
  SQL, or demo-data paths remains. External user-selected files remain
  intentionally independent of the managed tree.

### Validation results

* Initial post-move run: `.venv\Scripts\python.exe -m pytest -q` — **216 passed,
  24 skipped** in 105.57 seconds. This run exposed a stale `USERS_DIR`
  assignment during GUI startup; it was removed, then the GUI suite passed.
  Final suite results are below. Python compilation of changed path modules
  and `git diff --check` passed.
* Data tree: 35 moved `.sql`, `.json`, and `.xlsx` files plus the copied
  Demo safety marker are present. All 35 moved files retained their
  pre-move SHA-256 hashes. Private user/configuration JSON and private SQL
  remain git-ignored.
* The four report templates (1, 2, 2, and 1 sheets), existing generated
  report form (2 sheets), and managed Demo workbook (4 sheets) were opened
  read-only. Both master-list files and the public MySQL example parsed as
  JSON objects; managed Demo incident, warehouse, and import sidecar helpers
  resolved under `data/json/demo_data/`.
* Final full suite after the startup correction:
  `.venv\Scripts\python.exe -m pytest -q` — **240 passed, 0 skipped** in
  230.23 seconds. All 24 GUI tests ran, including application startup and
  report-form generation through the test harness.
* No automated test wrote to the old root paths. The root Demo marker and
  runtime artifacts present at that time were subsequently handled by the
  approved cleanup described above.
* The GUI test harness used its test account; no real user credentials were
  used. Interactive PDF printing and installer creation were not run.
  MySQL was not contacted and no SQL was applied.
* Tests use temporary workbooks and settings. Existing reports, JSON records,
  credentials, and workbook contents were not intentionally modified.
