# Approved cleanup reference audit — 14 November 2026

The owner approved removal only when there are no active code, test, build,
installer or batch dependencies. Documentation-only mentions do not block
cleanup, but must be updated in this commit. Tracked removals use `git rm`;
untracked items are moved to `D:\FSR_Cleanup_2026-11-14`, never deleted.

## Search scope and method

Before removal, searched all tracked Python/batch/Inno/spec files plus
the generated `build/FieldSurveyReport.spec` (133 files in total). Excluded
a candidate's own content when looking for
its consumers. Searched exact basenames, relative paths, slash variants,
and shared output-folder names; followed path construction where a generic
basename matched. Also searched tracked Markdown/text/SQL and `.gitignore`
for documentation mentions and protection rules. Private configuration,
account files, logs, binaries and workbooks were not searched for content.

Explicit packaging/launcher inputs read: `build_installer.bat`,
`installer.iss`, the old root spec, the generated User spec under `build/`,
`BACKUP_CODE.bat`, `GO_BACK_TO_WORKBOOK.bat`, `RUN_TESTS.bat`,
`SETUP_NEW_PC.bat`, `START_DEMO.bat`, and `START_FSR.bat`.

## Per-item findings and action

| Candidate | Search and findings | Action |
|---|---|---|
| Root `FieldSurveyReport.spec` | No Python/test/batch/Inno/spec consumer. The batch uses explicit PyInstaller arguments and `--specpath build`; the generated spec contains only managed assets and edition-specific data. Documentation mentions in PHASE1_ROLLOUT and CHANGES_AND_LIMITATIONS were updated. | Removed with Git; generated spec retained. |
| `README.txt` | No Python/test/batch/Inno/spec consumer or external documentation link found, apart from the cleanup inventory. Its obsolete instructions are superseded by README.md and phase docs. | Removed with Git. |
| `test_mysql.py` | Only external source match was the `db_mysql.test_connection` docstring at line 296, not an import, call or dependency. No test/build/batch/spec consumer; pytest selects `tests/`. README.txt's mentions disappeared with that obsolete document. Removed the outdated docstring mention. | Removed with Git; runtime behavior unchanged. |
| `data/schema/fsr_schema_v2_PROPOSED.sql` | No code/test/build/batch/spec consumer. FSR_SCHEMA_PROGRESS and SCHEMA_DESIGN linked the superseded design; FILE_ORGANIZATION recorded its old location. Updated all three. Current schema, test schema, migrations and the later proposal are retained. | Removed with Git; no SQL executed or live schema changed. |
| Legacy root `demo_data/` | Followed `warehouse/sample_data.py:36`, `field_survey_report.py:4498–4515`, START_DEMO.bat, tests/conftest.py, tests/test_sample_data.py and installer/spec inputs. Actual Demo paths are `data/excel/demo_data`, `data/json/demo_data`, or isolated test homes. No consumer of the root marker, log or directory. Historical FILE_ORGANIZATION mentions updated. | Root `.fsr_test_data` removed with Git. Untracked empty log and empty Incident Reports folder moved together as `D:\FSR_Cleanup_2026-11-14\demo_data`. Managed Demo folders kept. |
| Root `field_survey_report.log` | Generic basename matches at `field_survey_report.py:4534` and a backup-tool test. Actual app log resolves under PRIVATE_JSON_DIR; test uses invented temporary files. No consumer of this old root log. | Moved to quarantine root without reading contents. |
| Root `migration_output/` | No active Python/test/batch/Inno/spec reference. Legacy converter takes a caller-selected destination; historical inventory mentions updated with current cleanup status. Empty on recheck. | Moved to quarantine with the same relative path. |
| `data/json/migration_output/` | No active consumer; only ignored output and historical inventory. Empty on recheck. | Moved to quarantine with the same relative path. |
| `data/schema/private/` | Only code match is the backup tool's forbidden-history regex, not an input consumer. The batch/installer does not package it. Empty on recheck; no private script read or moved. Historical inventory annotated. | Empty directory moved to quarantine. Protection rules retained. |
| `Installer/Archive/` | No active Python/test/batch/Inno/spec consumer. PHASE1_ROLLOUT mentioned old installers; updated it to record that the folder was empty and moved. | Empty directory moved to quarantine. The two 11 November Setup files remain in Installer. |
| Root `Incident Reports/` | Active generic output name in fsr_storage and sidecar routing; supported user-selected workbooks can use adjacent directories. | Kept. |
| Root `Report Forms/` | Active generic output name in fsr_forms and report generation; supported user-selected workbooks can use adjacent directories. | Kept. |
| `data/excel/Warehouse Reports/` | Active output built from the workbook's parent in `field_survey_report.py:4383`. | Kept. |
| `data/json/Incident Reports/` | Active managed sidecar route through fsr_paths and fsr_storage; tested by migration and sample-data tests. | Kept. |
| `demo_data/Incident Reports/` | No separate consumer of this legacy-root path; covered by the Demo audit above. | Moved inside the legacy demo folder, not deleted. |

`build/` and `dist/` from the earlier release, managed Demo data, caches,
official forms, current schemas and migrations are not cleanup targets.
Ignore/security rules for output/private paths remain useful if those paths
are created again, so they are retained.

## Documents updated in the same cleanup commit

- `CHANGELOG.md`
- `FSR_SCHEMA_PROGRESS.md`
- `docs/schema/SCHEMA_DESIGN.md`
- `docs/CHANGES_AND_LIMITATIONS.md`
- `docs/PHASE1_ROLLOUT.md`
- `docs/FILE_ORGANIZATION.md`
- `docs/HOUSEKEEPING_REVIEW.md`
- This audit document (new).

The only Python edit is removal of the obsolete manual-probe mention from a
docstring in `db_mysql.py`. There are no runtime code or test changes.

## Verification

- Complete serial `RUN_TESTS.bat`: **1114 passed, 0 skipped**, in 1113.49 s
  (18 minutes 33 seconds). No automated tests were changed or removed.
- The first attempt, which overlapped the scratch build, did not pass:
  905 passed, 140 skipped, 69 GUI setup errors. The affected MySQL-settings
  module then passed all three tests in a fresh process. The full serial
  rerun above passed without source/test changes. The first attempt's cause
  was not established; it is not counted as a successful verification.
- User-edition PyInstaller **6.22.3**, hooks **2026.9**: exit 0. Arguments
  were derived from the current batch, with only dist/work/spec/edition
  staging and cache paths redirected into
  `build/cleanup_verification_2026-11-14/`.
- Scratch generated User spec checked: MySQL driver excluded, no private
  account/configuration inputs or removed schema proposal. All four
  official templates and both public JSON inputs present in the package.
- `fsr_build_check.py` on the scratch User package: **clean**, no account
  file or private account values found. No values were displayed.
- Repeated the removed-file dependency scan against source, tests, batch,
  Inno and both the existing and new generated specs: no dependencies found.
- `git diff --check` passed. Official template/data sources are unchanged
  from the Phase 3 and Phase 4 tips. The backup branch remains at `88010e8`.

No Inno Setup installer was built, installed, distributed or overwritten.
Scratch build artifacts are retained, and no old build/dist output was
removed. The 11 November Owner and User Setup files remain in Installer.
