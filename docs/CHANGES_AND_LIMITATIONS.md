# Changes and Limitations

## What was found (inspection of the original project)

* Python 3.14, Tkinter + ttkbootstrap 2.2.6. One 6,834-line script
  (`field_survey_report.py`) builds the whole window when it runs; `main.py`
  starts it.
* Storage: one Excel workbook (sheets Reports / Declared Goods / Item List /
  Remarks, keyed by Control # `FSR-YYYY-NNNN`). Incident reports are in
  JSON files. MySQL is optional (every save is mirrored there).
* One report = one Receiving **or** Withdrawal (field *Activity*), with
  Good/Bad Order set per report and Item List lines with Description, PO,
  Packaging (formerly "UOM"), Quantity, Weights …
* **There was no cargo identifier**, so a withdrawal could not be linked to
  a receipt. Quantities were free text.
* At inspection time the configured Excel data file did not exist and the
  MySQL database held 0 reports, so there was no operational data to
  migrate.

## Approach

The existing program was enhanced incrementally, not rebuilt:

1. The pure data code (field definitions, Excel storage, incident JSON
   helpers) was **moved unchanged** into `fsr_storage.py`, so it can be
   imported and tested. The main script imports it.
2. Two new Item List columns, **Cargo ID** and **Receiving Ref**, were
   added to the form, the Excel sheet and MySQL. They come after the
   existing columns, older files are upgraded automatically, and they are
   not printed.
3. The business logic is a new package, `warehouse/`, with no widgets.
4. The presentation is a new package, `warehouse_ui/`: a navigation
   sidebar and 8 module pages. The existing form became the "Inspection
   Reports" module, unchanged.
5. Demo Mode / `FSR_HOME` isolate all files, and there is a TEST data
   generator.

## Changed files

| File | Change |
|---|---|
| `field_survey_report.py` | Storage code moved out (now imported); Demo Mode / `FSR_HOME` folders; new light theme as default (`UI_VERSION` 3, dark mode kept); navigation sidebar + module title in the top bar; Cargo ID / Receiving Ref columns in the Item Lists (Cargo ID drop-down); Receiving Refs shown after saving; MySQL notes; mouse-wheel / page keys only scroll the form when it is visible; Ctrl+N / Ctrl+O switch to the form; MySQL settings and changing the Excel file locked in Demo Mode; start-up of the warehouse modules (if they fail to load, the program still works without them); safe error handling for malformed account files |
| `app_auth.py` | Invalid, unreadable, or malformed account files now stop startup without being treated as an empty account store or overwritten; a missing file still permits first-run owner setup; new and changed passwords require 12 characters while existing passwords remain usable |
| `warehouse_ui/shell.py` | Adds the Warehouse Monitoring navigation entry and page factory |
| `warehouse_ui/warehouse_page.py` | Inventory filtering/history, issue suggestions, role-gated reconciliation actions, and audit-log reopening |
| `tests/test_auth.py`, `tests/test_gui.py` | Authentication file-safety tests and GUI tests for inventory/reconciliation actions |
| `db_mysql.py` | Link columns written / read only when the table has them; `missing_link_columns`, `upgrade_schema`, `load_all_reports`; `save_report` returns notes |
| `data/schema/field_survey_schema.sql` | `cargo_id`, `receiving_ref` and an index on `item_lines` (new installations) |
| `requirements.txt` | + matplotlib, reportlab |
| `build_installer.bat`, `FieldSurveyReport.spec` | Include `warehouse`, `warehouse_ui` and the Matplotlib Tk backend |

## New files

| File | Purpose |
|---|---|
| `fsr_storage.py` | Field definitions + Excel storage (moved), `ITEM_LINK_HEADERS`, `default_receiving_ref`, `read_all_reports` (one pass), `delete_reports_from_excel` (Demo reset only) |
| `warehouse/*.py` | periods, transactions, inventory, analytics, store, tables, exports, sample_data |
| `warehouse_ui/*.py` | shell, theme, components, pages, warehouse_page, analytics_page, settings_page, dialogs |
| `data/schema/migrations/001_add_item_warehouse_links.sql` | MySQL migration for existing databases |
| `tests/*.py`, `pytest.ini`, `requirements-dev.txt`, `RUN_TESTS.bat` | Automated tests |
| `START_DEMO.bat`, `data/excel/demo_data/`, `data/json/demo_data/` | Demo Mode and the isolated sample data set |
| `README.md`, `docs/*.md` | Documentation |

Contents not changed: the three Excel templates,
`data/json/master_list.json`, the other SQL scripts and batch files, `installer.iss`.

## Remaining limitations

1. **Reports saved before this update have no Cargo IDs.** Their
   withdrawals appear as *Unmatched* until they are linked in
   Reconciliation, or the reports are opened and the Cargo IDs filled in.
   Their receipts are separate items, identified by Receiving Ref.
2. **Transfers between warehouses are not modelled.** A withdrawal at
   warehouse B of cargo received at A is unmatched by design.
3. **No physical stock count.** "In stock" means a positive *recorded*
   balance only.
4. **No unit conversions for quantities.** Different units of one item
   make it *Reconciliation Required*. Only weights are converted (fixed
   kg/g/MT/lb rules).
5. **The reconciliation log and Bad Order case statuses are kept in the
   side JSON file** beside the Excel file, not in MySQL. PCs that share
   MySQL but each keep their own Excel file do not share these decisions.
6. **Analytics read one source at a time** (Excel by default, or MySQL).
   Excel files from several PCs are not merged.
7. **Activity and Cargo Condition are set per report**, so a report cannot
   hold both Receiving and Withdrawal lines, or Good and Bad Order lines.
8. The **Weekly Summary page of the inspection form** keeps its original
   "week of the month" (days 1–7 …) definition. The new summaries use
   calendar weeks (Monday–Sunday).
9. **Sample data dates are relative to the day of generation**; generate
   again to keep the aging scenarios exact.
10. Not verified here: a real MySQL server, the inspection-form PDF
    printing, the installer build, and visual review of the exported PDFs
    (see TESTING_REPORT.md).
11. ttkbootstrap 2.2.6 reports deprecation warnings for options the
    original code uses (`dateformat`, `inverse-…`). They work today but
    will need updating before ttkbootstrap 3.0.
