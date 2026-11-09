# Field inventory and field-to-database mapping

This is the source-checked inventory for the proposal in
[`field_survey_schema_v2_proposed.sql`](../../data/schema/field_survey_schema_v2_proposed.sql).
The prior CSV copy was incomplete; this document replaces it rather than
presenting a partial inventory as complete.

The inventory was checked against `fsr_storage.py`, `field_survey_report.py`,
`app_auth.py`, `fsr_import.py`, `fsr_legacy_import.py`, `warehouse/`,
`warehouse_ui/`, the Excel storage headers, and the four existing form
templates. This schema task did not modify application or template files.

## Inspection report fields

| Screen / section | Application field or Excel heading | Proposed database mapping | Output / behavior |
|---|---|---|---|
| Report identity | Control # / `control_no` | `reports.control_no`; shared allocator `report_number_counters` | Unique per workspace. New IDs follow `FSR-YYYYMM-####`, monthly restart; imported and older IDs remain unrestricted text. |
| General Information | SO Number / `so_number` | `reports.so_number` | Required; printed and searchable; intentionally not unique. |
| General Information | Inspection Date / `inspection_date` | `reports.inspection_date` | Required date; used by printed forms, periods and aging. |
| General Information | Consignee | `reports.consignee`; optional `report_master_selections` entry `consignee` | Saved text snapshot plus optional link to `consignee_list`. |
| General Information | Supplier | `reports.supplier`; optional master selection `supplier` | Saved text snapshot plus optional link to `supplier_list`. |
| General Information | Brokerage | `reports.brokerage`; optional master selection `brokerage` | Saved text snapshot plus optional link to `broker_list`. |
| General Information | Hauler | `reports.hauler`; optional master selection `hauler` | Saved text snapshot plus optional link to `hauler_list`. |
| General Information | Location | `reports.location`; optional master selection `location` | Saved text snapshot plus optional link to `location_list`; used as warehouse. |
| General Information | Destination | `reports.destination`; optional master selection `destination` | Saved text snapshot plus optional link to `destination_list`. |
| General Information | Country of Origin | `reports.country_of_origin`; optional master selection `country_of_origin` | Saved text snapshot plus optional link to `country_of_origin_list`. |
| Inspection Schedule | Activity | `reports.activity` | Receiving / Withdrawal are offered; the field is typeable and is not constrained to those values. |
| Inspection Schedule | Commenced Date | `reports.commenced_date` | Optional date; defaults from Inspection Date in the UI. |
| Inspection Schedule | Commenced Time | `reports.commenced_time` | Optional `HHMMH`; accepts `2400H`. |
| Inspection Schedule | Completion Date | `reports.completion_date` | Optional date. |
| Inspection Schedule | Completion Time | `reports.completion_time` | Optional `HHMMH`; accepts `2400H`. |
| Shipment / Transport | Shipment Type | `reports.shipment_type` | Suggested Local / Import; text retains other source values. |
| Shipment / Transport | Container Type | `reports.container_type` | Suggested Containerized / Non-Containerized; text retains other source values. |
| Shipment / Transport | Vessel/Carrier | `reports.vessel_carrier` | Free text. |
| Shipment / Transport | Vehicle Type | `reports.vehicle_type` | Free text. |
| Shipment / Transport | Vehicle Plate Number | `reports.vehicle_plate_number` | Free text. |
| Documents Used | Invoice Number | `reports.invoice_number` | Printed and searchable/exportable. |
| Documents Used | PO Number | `reports.po_number` | Printed, searchable, and usable as an item-line field. |
| Documents Used | JO Number | `reports.jo_number` | Printed/exported. |
| Documents Used | Gatepass Number | `reports.gatepass_number` | Printed and searchable. |
| Documents Used | BL/AWB Number | `reports.bl_awb_number` | Printed and searchable. |
| Documents Used | DR Number | `reports.dr_number` | Printed and searchable. |
| Documents Used | Other Documents | `reports.other_documents` | Free text. |
| Inspection | Good Order / Bad Order | `reports.cargo_condition` | Required; Bad Order enables incident cards and drives warehouse case reporting. |
| Types of Goods | New, Used, Food Stuff, Vehicle, Pharma / Chemical | `reports.goods_new`, `goods_used`, `goods_food_stuffs`, `goods_vehicle`, `goods_pharma_chemicals` | Independent booleans; used in printed report and analytics. |
| Types of Goods | Others checkbox and its text | `reports.goods_others`, `reports.goods_others_text` | Text is valid only when Others is selected. |
| Item Lists | Selected form | `reports.item_form` | Default, Containerized, or Loading; warehouse reporting uses only the selected form. |
| Form rendering | Signed-in user's full name / imported inspector | `reports.prepared_by_name` | Schema supports a nullable print-name snapshot because the PDF generators require it. Today the Windows generator uses the local signed-in name or import-ledger inspector at render time; it does not save this value in the Excel report. |
| Report audit display | Last Saved | `reports.last_saved` | Printed/exported when applicable; database-managed update timestamp. |

### Repeating report sections

| Section / input | Application fields | Proposed mapping | Cardinality / limit handling |
|---|---|---|---|
| Declared Goods | Description, Quantity, Packaging, row order | `declared_goods.description`, `.quantity`, `.packaging`, `.line_no` | One-to-many. The current form displays five rows and the First Page template prints five; the database deliberately has no five-row constraint, so additional values are not truncated. |
| Other Important Remarks | Ordered free-text lines | `report_remarks` with section `Other Important Remarks` | One-to-many. The form has 12 entry rows and the form template exposes 12 positions (five initially visible plus continuation positions); no database row cap. |
| Findings and Remarks | Ordered free-text lines | `report_remarks` with section `Findings and Remarks` | One-to-many; no database row cap. |
| Item List identity | Item form, list number, list name | `item_lists.item_form`, `.list_no`, `.list_name` | One-to-many; empty lists can be retained; all three forms can be represented for one report. |
| Item line | Unit / Container / Truck No. | `item_lines.unit_no` | Text is retained; label is form-specific (Unit No., Container No., or Truck Plate No.). |
| Item line | Description of Goods | `item_lines.description` | Free text; never used as a unique cargo key. |
| Item line | PO Number | `item_lines.po_number` | Free text; distinct from the report's PO Number. |
| Item line | Packaging | `item_lines.packaging` | Free text. Older workbook `UOM` heading is normalized by the application to Packaging. |
| Item line | Quantity | `item_lines.quantity` | Text, not a decimal: accepted values may contain formatting or units. |
| Item line | UOM | `item_lines.uom` | Separate free-text value; retain unknown units. |
| Item line | Dimensions | `item_lines.dimensions` | Free text. |
| Item line | Weights | `item_lines.weights` | Free text, including unit text; warehouse parsing is derived behavior. |
| Item line | Currency | `item_lines.currency` | Suggested JPY, USD, PHP, SEK, EUR; text preserves other entered values. |
| Item line | Unit Price / Total Price | `item_lines.unit_price`, `.total_price` | Text to preserve non-numeric entries and formatting. |
| Item line | Findings | `item_lines.findings` | Free text. |
| Item line | Cargo ID | `item_lines.cargo_id` | Stored in the workbook/database but intentionally hidden in the current report form; not printed. Do not infer it from description. |
| Item line | Receiving Ref | `item_lines.receiving_ref` | Receiving rows get the generated `RCV-<Control #>-<list>-<line>` value when saved; a withdrawal may identify a batch. Stored, not printed. |
| Item line | Row order | `item_lines.line_no` | Unique within an item list. Current form supports 30 lines per list; database has no 30-line constraint. |

The default item form has the legacy columns. Containerized and Loading forms
use a form-specific unit-number heading and omit some Default-form columns.
All source fields have columns in `item_lines`; omitted controls on a particular
form are nullable, and no data from another form is collapsed into the
selected form. The selected-form view enforces the warehouse rule by joining
only `item_lists.item_form = reports.item_form`.

## Incident report JSON

| Source JSON / control | Proposed mapping | Notes |
|---|---|---|
| Top-level Control # | `report_incident_sets.source_control_no` | Composite FK requires the sidecar workspace, report ID, and source Control # to identify the same report. |
| Top-level SO Number | `report_incident_sets.so_number_snapshot` | Preserved independently of the current report value. |
| Top-level saved timestamp | `report_incident_sets.saved_at` | Parsed timestamp when available. |
| Unmodeled envelope keys | `report_incident_sets.source_metadata` | JSON preservation slot for forward compatibility. |
| Incident card order / title | `incident_reports.card_no`; title is derived using current title convention | One or more cards per report; title need not be separately stored. |
| Vessel, Voyage, Client, S.O. No., Port, Date, Operation | `incident_reports.vessel`, `.voyage`, `.client`, `.so_number`, `.port`, `.incident_date_text` / `.incident_date`, `.operation` | Raw date text is retained alongside optional parsed date. |
| Incident lines | `incident_lines.line_no`, `.line_text` | Current app keeps at most 15 nonblank lines per card. The database enforces the current line range. |

## Alternate item-form JSON

The sidecar envelope's Control # and saved timestamp map to
`report_item_form_sets.source_control_no` and `.saved_at`. The list/form/row
data maps to the same `item_lists` and `item_lines` entities as the workbook
form. `source_metadata` retains envelope metadata not otherwise modeled.
The composite foreign key requires the sidecar's workspace, report, and
control number to identify the same report. This preserves Containerized and
Loading lists that are not the currently selected form.

## Warehouse history and supporting data

| Source / control | Proposed mapping | Required fields / behavior |
|---|---|---|
| `*.warehouse.json` version and unknown envelope data | `workspace_sidecar_metadata` | One record per workspace and document type; preserves version/metadata. |
| Reconciliation event ID, subject, action, target, note, user, timestamp | `reconciliation_log` | Append-only history; target JSON is retained in addition to indexed warehouse, Cargo ID, and Receiving Ref values. Supports `propose`, `confirm`, `reject`, `exclude`, `accept`, `reopen`, and `note`. |
| Bad Order case status history | `case_status_log` | Append-only Open / Under Review / Resolved entries with note, user-name snapshot, timestamp; each entry references a report in the same workspace. No entry means “Not recorded.” |
| Aging thresholds | `app_settings` key `aging_thresholds` | Workspace JSON setting; proposed default `[7, 30, 60, 90]`. |
| Phone import ledger and master-data JSON envelope | `import_ledger` | Workspace, source format/version/unknown envelope metadata, device ID, phone control, local control, imported report link, inspector, phone/PC saved markers, imported timestamp. Unique device + phone control supports idempotency. |
| Legacy CSV import archive | `legacy_import_records` | Workspace, source file/line, status/reason, optional report link, invoice total, original rows and issue data. No records are loaded by this proposal. |

## Master data, options, user accounts, and transient controls

| Application data/control | Database treatment |
|---|---|
| Consignees, Suppliers, Brokerages, Haulers, Locations, Destinations, Countries of Origin | Seven `master_lists` categories and workspace-scoped `master_list_items`. `report_master_fields` permits only the correct list category for each report field; `report_master_selections` uses composite FKs so a field cannot link to an item from the wrong category or workspace. The report's saved text remains a snapshot even when no master item is selected. |
| Activity, Shipment Type, Container Type, Item Form, Currency, UOM, Weight Unit, Case Status suggestions | `application_options` stores suggested choices. It does not impose a restrictive FK on free-text fields. |
| Sign-in, sign-up, account management | Remains in `users.json`; no account table, password hash, authentication foreign key, or user migration. Account properties are first/middle/last name, initials, email, salted password hash, role, status, and created timestamp. Controls include sign-in, sign-up, approve/reject/disable/delete, admin password reset, and own-password change; password confirmations and show-password toggle are transient. Current rules include valid email, unique email and initials, initials of 2-6 letters/numbers, a 12-character minimum for new/reset passwords, and approved status for sign-in. |
| Account/authorization audit identity | Warehouse event `user_name`, phone-import `inspector`, and optional report `prepared_by_name` are snapshots; no report account foreign key is created. Authorization remains enforced by the current local account workflow. |
| Period/filter controls | Transient query parameters, not stored records: Today, This Week, This Month, This Year, Previous Day/Week/Month/Year, All Records, Custom Date Range. Filter dimensions include warehouse, supplier, consignee, cargo condition, activity/transaction type, cargo type, case status, inventory status, issue state, and free-text search (SO, Control #, Cargo ID, description). |
| Analytics/export controls | Report type (all 14 types listed above), selected day, selected cargo for history, and Export Excel / Export PDF are transient. Results are derived from reports, item lines, warehouse logs, and settings. |
| Warehouse actions | Selected item/issue/suggestion/audit entry and Add Note, Propose Match, Confirm Match, Reject Proposal, Accept as Separate Batch, Exclude, Reopen, and Reopen Selected Decision are controls, not report fields. The corresponding append-only actions/targets/notes/user/time are mapped to `reconciliation_log`; owner-only actions remain authorization rules. |
| Case-status controls | Open, Under Review, Resolved, note, and the per-report status history map to `case_status_log`; no status entry means “Not recorded.” |
| Shared settings | Aging thresholds map to `app_settings` JSON. Suggested choices map to `application_options`. |
| Per-PC settings and credentials | Remain in the current local settings/configuration files: light/dark theme, Excel workbook path, selected Excel/MySQL analytics source, last-used SO number/login initials, and MySQL connection parameters/credentials are not copied into workspace settings. |
| Settings controls | Change Excel File, choose analytics data source, toggle theme, MySQL Settings, Check Tables, Upgrade MySQL Tables, choose a master-list category, Add Name, Remove Selected, and Demo Mode Generate/Refresh or Remove Sample Data. The first group remains local or operates only on the current legacy database integration; master values map to categorized master tables (removed values become inactive); Demo Mode is a separate sample-data workflow and does not become schema initialization. |
| Screen-only state | Dirty/new/saved badges, navigation selection, dialogs, validation messages, and unsaved form state are not persisted in the proposed schema. |

## Report generator coverage

The mapping covers the inputs consumed by the existing report builders:

* `First_Page.xlsx`: report identity, general information, schedule, transport,
  documents, five visible Declared Goods rows, goods checkboxes, remarks, and
  prepared-by display.
* `Cargo_Details.xlsx`: Default item lists and line fields.
* `Containerized_Loading_Form.xlsx`: Containerized and Loading form-specific
  labels/columns, including unit/container/truck number.
* `Incident_Report.xlsx`: incident header fields and up to 15 lines per card.
* The Excel data workbook sheets Reports, Declared Goods, Item List, and
  Remarks, plus the weekly/warehouse analytics exports.

Cargo ID and Receiving Ref are persistence/warehouse fields, not printed
template fields. The input values remain available to the Excel and warehouse
logic without changing any template.

## Warehouse report types verified in source

There are 14 entries in `warehouse.exports.REPORT_TYPES` (not 13):

1. Daily Receiving Summary
2. Weekly Receiving Summary
3. Monthly Receiving Summary
4. Daily Withdrawal Summary
5. Weekly Withdrawal Summary
6. Monthly Withdrawal Summary
7. Weekly Receiving Summary Report
8. Monthly Receiving Summary Report
9. Weekly Withdrawal Summary Report
10. Monthly Withdrawal Summary Report
11. Bad Order Summary
12. Remaining Warehouse Cargo Report
13. Cargo Transaction History
14. Management KPI Summary

These are derived exports, not 14 separate stored report types. Their source
fields, periods, filters, status history, and aging settings are represented
above.
