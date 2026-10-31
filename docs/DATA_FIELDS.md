# Data fields used by the warehouse monitoring

## 1. Existing inspection-report fields and their warehouse meaning

No existing field was renamed or removed, and the printed templates
(`First_Page.xlsx`, `Cargo_Details.xlsx`, `Incident_Report.xlsx`) are
unchanged.

| Warehouse meaning | Source field (Excel sheet / column) | Notes |
|---|---|---|
| Transaction ID (report) | Reports / `Control #` | `FSR-YYYY-NNNN`; sample data `TEST-REC-NNNN` / `TEST-WDR-NNNN` |
| Transaction type | Reports / `Activity` | `Receiving` / `Withdrawal` (typed values starting "receiv…" / "withdraw…" are accepted) |
| Transaction date | Reports / `Inspection Date` | Reports without a valid date are flagged and left out of aging and period figures |
| Transaction time | Reports / `Commenced Time` | Shown only |
| Warehouse | Reports / `Location` | Blank → "(Location not recorded)" |
| SO Number, Supplier, Consignee, Destination | Reports / same columns | |
| PO / DR / Gatepass / BL-AWB | Reports / Documents columns | Used for search and match suggestions |
| Cargo condition | Reports / `Cargo Condition` | Set per report (Good Order / Bad Order) |
| Cargo type | Reports / `Types of Goods` | New, Used, Food Stuff, Vehicle, Pharma/Chemical, Others |
| Incident description | `Incident Reports\<Control #>.json` | Bad Order only (existing) |
| Cargo line ID | `<Control #>/<Item List no>/<line no>` | Derived, not stored |
| Cargo description | Item List / `Description of Goods` | Never used to match |
| Quantity | Item List / `Quantity` | Must be a number ≥ 0; "12 pcs" is read as 12 PCS |
| Unit of measure | Item List / `Packaging` | This column was called "UOM" before. Normalised: pc/pcs/pieces → PCS, set(s) → SET, box(es) → BOX, crate(s) → CRATE, m/meter(s) → M … Unknown units keep their own name and are never added to other units |
| Weight | Item List / `Weights` | Read as the line's weight; converted to kg from kg, g, MT/t/ton(ne), lb(s) |
| Findings / remarks | Item List / `Findings`, Remarks sheet | Shown only |

## 2. New fields

### Item List (Excel sheet "Item List", MySQL `item_lines`, form columns)

These are added after the existing columns. Older workbooks get them on
the next save, and older reports read them as empty. They are **not
printed** on the Cargo Details form.

| Column | Excel heading | MySQL column | Rules |
|---|---|---|---|
| Cargo ID | `Cargo ID` | `cargo_id VARCHAR(100)` | Identifies an inventory item. **Receiving:** typed (or picked from known IDs for another batch of the same cargo). **Withdrawal:** picked from the items with a positive balance at the report's Location (drop-down); choosing one fills an empty Description / PO / Packaging. Two items may share a description but never a Cargo ID. |
| Receiving Ref | `Receiving Ref` | `receiving_ref VARCHAR(100)` | One received batch. **Receiving:** filled in automatically on the first save as `RCV-<Control #>-<list>-<line, 2 digits>` (e.g. `RCV-FSR-2026-0007-1-03`) and then kept. **Withdrawal:** optional, names the batch the cargo comes from. Reports saved before this update get the same reference on reading (not stored). |

### Warehouse side file (`Warehouse Data\<Excel file name>.warehouse.json`)

This file sits beside the Excel data file and is written atomically. It
never changes a report.

```json
{
  "version": 1,
  "reconciliation": [
    {"id": "REC-00001", "subject": "FSR-2026-0012/1/1", "action": "propose",
     "target": {"warehouse": "EDC-DHL Warehouse", "cargo_id": "GV-0042",
                "receiving_ref": ""},
     "note": "typo in Cargo ID", "user": "Full Name",
     "timestamp": "2026-10-29T09:41:12"}
  ],
  "case_status": [
    {"control_no": "FSR-2026-0009", "status": "Under Review",
     "note": "supplier notified", "user": "Full Name",
     "timestamp": "2026-10-29T09:45:00"}
  ],
  "settings": {"aging_thresholds": [7, 30, 60, 90]}
}
```

| Field | Values |
|---|---|
| `subject` | A cargo line ID (`<Control #>/<list>/<line>`) or an item key (`item:<warehouse>|id:<cargo id>`) |
| `action` | `propose` (needs a target), `confirm`\*, `reject`\* (only a proposal), `exclude`\* (needs a note), `accept`\* (duplicate Receiving Ref → separate batch), `reopen`\*, `note` (needs a note). \* owner accounts only |
| Resulting state | Open → Proposed → Confirmed / Rejected; Excluded; Accepted. The latest entry wins, and every entry is kept (audit trail) |
| `case_status.status` | `Open`, `Under Review`, `Resolved`. Reports without an entry are "Not recorded" and are **not** counted as unresolved |

## 3. Inventory issues (reconciliation list)

| Issue | When | Effect on the balance |
|---|---|---|
| Unmatched Withdrawal | No Cargo ID / Receiving Ref, ID not found, or found only in another warehouse | Not counted until linked (confirmed) or excluded |
| Linked Item Not Found | A confirmed link points to an item that no longer exists | Not counted |
| Missing / Invalid Quantity | Quantity empty, not a number, or negative | Item → Reconciliation Required |
| Unit of Measure Mismatch | Withdrawal unit ≠ item unit | Line not counted; item → Reconciliation Required |
| Incompatible Units Received | Batches of one item in different units | Item → Reconciliation Required |
| Withdrawal Dated Before Receiving | Withdrawal date < first receiving date | Item → Reconciliation Required |
| Duplicate Receiving Ref | Same Receiving Ref on two receiving lines | Second line not counted (unless accepted) |
| Over-Withdrawal | Withdrawn > received | Item → Over-Withdrawn; negative balance kept |
| Batch Over-Withdrawn (warning) | More taken from a named batch than it had | The rest comes from the item's other batches |
| Missing / Invalid Date (warning) | No valid Inspection Date | Left out of aging and period figures |

## 4. MySQL schema change

`migrations/001_add_item_warehouse_links.sql` (or Settings → Upgrade MySQL
Tables) adds:

```sql
ALTER TABLE item_lines ADD COLUMN cargo_id      VARCHAR(100) NULL AFTER findings;
ALTER TABLE item_lines ADD COLUMN receiving_ref VARCHAR(100) NULL AFTER cargo_id;
CREATE INDEX idx_item_cargo ON item_lines (cargo_id);
```

The reconciliation log and the case statuses are kept in the side file
only; they are not stored in MySQL.
