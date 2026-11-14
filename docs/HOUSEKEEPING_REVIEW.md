# Housekeeping review — 14 November 2026

This was the proposal reviewed by the owner. Cleanup was subsequently
approved with dependency checks and quarantine instead of deletion for
untracked items. The per-item decisions and current outcome are recorded
in [CLEANUP_REFERENCE_AUDIT.md](CLEANUP_REFERENCE_AUDIT.md); the tables below
preserve the original proposal, rather than instructions to delete more.
Paths are relative to the project folder. Logs and account/configuration
contents were not displayed, and no SQL script or old executable was run.

## Candidates for removal

| Path | Finding | Proposed action after approval |
|---|---|---|
| `FieldSurveyReport.spec` | Old, unused root spec, dated 2 November. It includes the owner seed and lacks the current edition separation. The supported build generates its own spec under `build/`. | Remove; never use it to build a release. |
| `README.txt` | Older, overlapping setup instructions, dated 1 November. It describes obsolete account/password storage and workbook-first behavior. `README.md` and the phase docs are the current references. | Remove the outdated short README. |
| `test_mysql.py` | Root manual connection probe, not part of the configured `tests/` suite. Importing/running it calls the default connection check immediately. | Remove; use the application's MySQL Settings test and the guarded integration suite instead. |
| `field_survey_report.log` | Root runtime log, 56,372 bytes, last modified 31 October. Contents not inspected. | Remove if no longer needed for troubleshooting. |
| `demo_data/` | Legacy root demo folder. Contains a marker, an empty log, and an empty `Incident Reports/` folder. File-organization docs identify this path as unused; the managed demo data is under `data/`. | Remove the legacy folder as a unit. |
| `data/schema/fsr_schema_v2_PROPOSED.sql` | Explicitly superseded proposal, still linked from `docs/schema/SCHEMA_DESIGN.md` and the historical file inventory. | Remove only with approval; update current design links in the same cleanup. Keep historical inventory understandable. |

## Empty folders found

- `Incident Reports/`
- `Report Forms/`
- `migration_output/`
- `data/excel/Warehouse Reports/`
- `data/json/Incident Reports/`
- `data/json/migration_output/`
- `data/schema/private/`
- `demo_data/Incident Reports/` (included in the legacy demo candidate above)
- `Installer/Archive/`

These were empty when scanned, not proof that every path is obsolete.
Several are runtime/output locations and may be created again. Recheck
contents immediately before any approved removal. Keep the private schema
directory if it is useful for local-only administration scripts.

## Generated artifacts — retain pending a separate decision

- `build/`, including `build/FieldSurveyReport.spec`, work executables and
  PyInstaller warning files: generated packaging artifacts from the
  11 November build, not source inputs. The supported build recreates them.
- `dist/Owner/` and `dist/User/`: generated programs and bundled resources,
  not duplicate authoritative templates or documentation.
- Python, pytest and Ruff caches are disposable generated files, but are
  not included in the proposed source-file cleanup.

The two `Installer/FieldSurveyReport_*_Setup_2026.11.11.exe` files are
explicitly retained. No 9 November installer or populated installer archive
was present in this scan.

## SQL files that are not interchangeable duplicates

- `data/schema/field_survey_schema_v2_proposed.sql` and
  `data/schema/fsr_schema_v2_PROPOSED.sql` have different contents. The
  former is the later proposal; the latter is superseded. Neither is a
  migration to apply during housekeeping.
- `data/schema/field_survey_schema.sql` is the current production setup
  script; `field_survey_test_schema.sql` is its intentionally separate,
  restricted test-database counterpart. Keep both.
- `add_shipment_columns.sql`, `update_declared_goods.sql`, and the four
  scripts under `data/schema/migrations/` are manual upgrade history, not
  duplicate schema definitions. Keep pending a separate schema review.

No MySQL schema, official form template, workbook layout, real report data,
installed application, or backup branch is changed by this review.
