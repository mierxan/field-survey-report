# Field Survey Report schema proposal progress

## Current status

The schema proposal is being finalized as a clean, proposal-only design for a
new empty MySQL database. There is no historical report data in the proposed
schema and nothing is imported. The Excel-first Windows application,
optional existing MySQL mirror, local `users.json` accounts, and form
templates remain unchanged.

## Deliverables

| Deliverable | Location | Status |
|---|---|---|
| Source-checked field inventory and field-to-database mapping | [`docs/schema/field_inventory_and_mapping.md`](docs/schema/field_inventory_and_mapping.md) | Complete |
| Normalized schema, creation SQL, keys, constraints, indexes, seed choices, and views | [`data/schema/field_survey_schema_v2_proposed.sql`](data/schema/field_survey_schema_v2_proposed.sql) | Proposal; not applied |
| ER diagram and design decisions | [`docs/schema/SCHEMA_DESIGN.md`](docs/schema/SCHEMA_DESIGN.md) | Complete |
| Compatibility assessment | [`docs/schema/SCHEMA_DESIGN.md`](docs/schema/SCHEMA_DESIGN.md) | Complete |
| Testing plan and actual results | [`docs/schema/SCHEMA_DESIGN.md`](docs/schema/SCHEMA_DESIGN.md) and this file | Structural and application checks complete |

The earlier partial `field_inventory.csv` was removed and replaced with the
source-checked Markdown inventory; do not use that partial copy.
[`data/schema/fsr_schema_v2_PROPOSED.sql`](data/schema/fsr_schema_v2_PROPOSED.sql)
is an earlier draft marked superseded and must not be applied.

## Architecture and safety decisions

* Excel remains primary for current reports; current MySQL stays optional.
* This SQL creates a separate `field_survey_v2` database and is not connected
  to the current application's database adapter.
* No historical reports, master list contents, accounts, settings, or import
  records are loaded.
* No live database, source-code storage flow, or Excel/PDF template was
  modified.
* Accounts and credentials stay local; soft deletion and row versions are
  omitted. The future shared-backend control-number counter is not used by the
  current Excel workflow.
* The five-row Declared Goods and 12-row remarks UI limitations are
  documented; the schema does not truncate these repeated sections.
* The mapping covers all 14 warehouse export types and includes all three
  item forms, sidecar envelope metadata, import history, master list
  categories, authentication/account controls (local-only), and
  analytics/settings controls.

## Verification log

* Inventory cross-check: performed against application source, storage
  definitions, auth/import code, warehouse modules, and form templates.
* Warehouse report count: 14 verified in `warehouse/exports.py`.
* Static DDL checks: passed for 22 tables, two views, and every declared
  foreign key's local/parent columns and referenced candidate key; account
  table absence, workspace-scoped sidecar identity, and import envelope
  metadata were checked.
* Source-to-schema cross-check: passed for the 31 Excel report headings, 14
  item-line fields, three item forms, all seven master-list categories,
  exact report-field/list-category mappings, seeded choices, and all 14
  warehouse export types.
* Repository tests: `python -m pytest -q` — 238 passed in 301 seconds; one
  dependency deprecation warning (`anyio` imports pytest's deprecated
  `CallSpec2` alias).
* `git diff --check`: passed. MySQL command-line tooling was unavailable, so
  no SQL-engine parse was run; the proposal was not applied and no live
  database was contacted.
* SQL was not applied and no live database was contacted.

## Remaining review gate

Before any integration or DDL deployment, review the proposal and test it on a
disposable MySQL 8.0.16+ instance. Separately implement and test an adapter
against the existing Excel and report-generator data shapes. No such
integration or migration is authorized by this proposal task.
