# Withdrawal-to-Receiving shipment files

An origin inspector shares the Item List of a Withdrawal report with the
destinations it goes to. Each destination gets **one file holding only its
Packing Lists**, and brings it into a new Receiving draft, so the item list
is not typed again. The Windows Owner and User editions and the Android app
read and write the same file. Everything works offline: the file travels by
e-mail, chat or USB stick.

Status:
- **Phase 1 (done):** sharing, on a PC (Storage > Share Shipment...) and in
  the phone test app (Share with Destination on a completed Withdrawal).
- **Phase 2 (done):** receiving, on a PC (Storage > Receive Shipment..., or
  double-click the file) and in the phone test app (Master Data > Receive
  Shipment, or tap the file): a new Receiving draft. Two hidden line fields,
  **Packing List No.** and **Origin Line**, keep the Packing List number and
  the origin line, whatever the destination writes in Findings.
- **Findings in one click (18 November 2026):** above the Item Lists, **All
  Good Order and Complete** and **With Issues...** (see below), on PC and
  phone. Unit Price, Total Price and Currency now travel with the lines
  (the owner's decision, reversing Phase 1 decision 5 for these three).
- **Not yet:** printing `<Packing List> · <Findings>` (Phase 3), items added
  at the destination (Phase 4), the released phone version (Phase 5).

## Receiving (Phase 2)

**This site's destination (once).** A PC is set to the destination it
receives for (Receive Shipment shows it, with **Change...**); a phone in
**Settings > This phone's destination**. Both choose from the Destination
master list. A file made for another destination is refused with a clear
message; nothing is made. This prevents mistakes; it is **not security**
(the apps share no user directory, and a file can be forwarded).

**Receive Shipment** checks the file (format, version, checksum, the fields
it may hold), the destination and earlier imports, then shows the summary:
the origin Withdrawal (Control #, location, date), who sent it, the Packing
Lists with their lines and POs, and "This PC's destination: ... (matches)".
Only after **Yes** (PC) or **Make Receiving Draft** (phone):

- A **new Receiving draft** is made: on a PC in the signed-in account's
  Unfinished work (it is offered to open at once); on a phone in Draft
  Reports, with the phone's next Control #.
- **Activity = Receiving**; every other First Page field is empty (no date,
  no SO Number, no Supplier ...). The inspector fills them.
- The **Item Lists** hold the shipment's lines with all their cargo details,
  in the origin's Item List form. **Findings is empty**, for the receiving
  condition. Each line keeps its Packing List No. and Origin Line in the
  hidden fields: editing Findings does not touch them.
- The prices come along (Currency, Unit Price, Total Price). No Cargo ID
  and not the origin's Receiving Ref: when the draft is saved, its lines get
  Receiving Refs of the new report.
- The draft has no Cargo Condition yet: on a PC the form stays covered
  ("Select the Cargo Condition to start") until the inspector clicks Good
  Order or Bad Order - nothing is marked automatically.

## Findings in one click

Above the Item Lists (PC: the **Findings:** row under Create New Item List;
phone: the **Findings** card at the top of the Item Lists tab):

- **All Good Order and Complete** writes `Good Order and Complete` in the
  Findings of every item line. If some lines already say something else,
  it asks first: replace them too, or fill only the lines without Findings
  (or cancel).
- **With Issues...** lists every line (Item List and line number, Packing
  List, description, PO, quantity). Tick each line with an issue and type
  its findings; **Apply** writes those, and `Good Order and Complete` on
  every line not ticked. A ticked line without findings is refused. Opened
  again, it shows the lines with other findings ticked.

Only the Findings change (the report is saved as usual); the Packing List
No. of each line is never touched. Blank spare lines are left blank. Works
on any report's Item Lists, not only on drafts made from a shipment.
- If anything fails, no draft is made (the PC removes a draft whose import
  record could not be written).

**Duplicates.** A shipment is refused as **imported before** when any of its
origin lines is already in a draft made from an earlier import (that still
exists) or in a saved report of this workbook / phone. This covers the same
file twice and a second file the origin made for the same lines. A draft
deleted by mistake can be imported again. The PC keeps a record of every
import in `<workbook>_shipments.json` beside the workbook's other side files
(transfer id, origin, destination, Packing Lists, origin lines, draft).

The origin Withdrawal report is never touched by receiving either.

## The two hidden line fields (schema change, Phase 2)

`Packing List No.` and `Origin Line` belong to a line; they are saved but
never printed in the Item List columns. **A line carries them only when they
have a value**, so every report made before - or without a shipment - is
stored, exported, handed over and compared exactly as before.

| Where | Change | Existing records |
|---|---|---|
| Main workbook, Item List sheet | two columns added at the **end** when a report is saved (as UOM and Currency were) | old rows read as blank; nothing moves |
| Withdrawal_Reports.xlsx | **no change** (its own columns follow the line fields by position) | untouched |
| Reports database (SQLite) | none: rows are stored as lists; longer rows from now on | old, shorter rows read as blank |
| MySQL `item_lines` | `packing_list_no`, `origin_line` (VARCHAR(120) NULL), added by Upgrade MySQL tables | until then saving works without them; the values stay on the PC |
| Android database | version 2 -> 3: two TEXT columns, default `''` (`MIGRATION_2_3`) | every report, line and hand-over kept |
| Master Data / hand-over files | the two keys, only on lines that have them | older files read as blank |
| Owner's import | fingerprints and change lists ignore empty new fields | no report looks changed |

**The way back** (tests/test_shipment_migration.py runs the previous
version's own code, from the last commit):
- The previous version still reads a **reports database** this version
  wrote to: every report; it simply does not know the two fields.
- The previous version **refuses a workbook** this version saved
  ("different layout") - the accepted caveat. Keep the previous installers;
  the daily backups (made before the first save of a day) and the Excel
  export allow a restore.

**Evidence** (18 November 2026):
- your real reports database read by the previous and this version: all 64
  reports and 3 PO-linked Withdrawals (386 lines) identical, all 67 Owner
  fingerprints identical, the database file unchanged (read only);
- the phone test app upgraded in place on the emulator from database 2 to
  3 with invented reports: reports, lines and hand-over records kept
  exactly, the new columns blank.

## Sharing (Windows, Phase 1)

Side panel, **Storage > Share Shipment...** (the window is called Share with
Destination):

1. **Choose the Withdrawal report.** Every saved Withdrawal report is
   listed: the normal ones and the PO-linked ones. The report open on the
   form is chosen for you. Unsaved changes are not shared, and you are
   asked first whether to save them.
2. **Give each Packing List its destination.** Select one or more Packing
   Lists, choose the destination (the Destination master list) and click
   **Assign**. When the report's own Destination is one known destination,
   every Packing List starts there. A Packing List without a destination is
   not shared.
3. **Create Shipment Files...** asks for a folder and writes one file per
   destination:
   `FSR_Shipment_<Control #>_to_<Destination>_<yyyy-mm-dd>.fsrshipment`.
   An existing file of the same name is never overwritten: the new one gets
   `_2`, `_3` and so on.

The Withdrawal report is **only read**: nothing in the workbook, the reports
database, PO_Master, Withdrawn_Item or MySQL changes. Each file is read back
and checked after it is written. If one file cannot be written, the files
of that click are removed again, so you never get only some of them.

## Packing List numbers

The origin keeps typing the Packing List number in each line's **Findings**
(the Withdrawal form is unchanged). Sharing reads it from there:

- **A Findings cell that holds a packing list number** (letters, digits, a
  dash, digits: `BAC111126-009`, `MTA11126-001`) is used **as the whole
  cell, exactly as written**. So `BAC111126-001 & 002` is one entry. It is
  never split or guessed.
- **Any other Findings** (for example `Good condition`, or empty) puts the
  line in the group **(no Packing List)**. That group can be shared like
  any other.
- **A line that already has its own Packing List No.** field uses that.

## The file

The same envelope as the hand-over file:

```json
{"format": "fsr-shipment", "version": 1,
 "payload": "<the JSON below, as text>",
 "checksum": "<SHA-256 of the payload text, UTF-8>"}
```

The payload:

| Field | Meaning |
|---|---|
| `transfer_id` | A random id of this file (32 hex characters). The destination uses it to refuse a second import. |
| `kind` | Always `withdrawal_share`. |
| `app` | `windows` or `android`: the app that wrote it. |
| `created_at` | When it was written (ISO 8601, with the time zone). |
| `from` | `inspector`, `initials` and `device_id` of the sender. |
| `origin` | The origin reference: `control_no`, `activity` (`Withdrawal`), `location`, `inspection_date` (dd-MMM-yyyy, as on the report) and `item_form` (`Default`, `Containerized` or `Loading`). |
| `destination` | The ONE destination this file is for, spelled as in the Destination master list. |
| `packing_lists` | `[{"number", "po_numbers", "line_count"}]`, in the order the lists first appear. `""` is the group without a Packing List. |
| `item_lists` | `[{"name", "rows"}]`. The origin's Item Lists that have shared lines, renumbered from `Item List 1`. |

Each row has exactly these fields, all text:

| Field | From the origin line |
|---|---|
| `Description of Goods`, `PO Number`, `Packaging`, `Quantity`, `UOM`, `Dimensions` | As saved. |
| `Weights` | The number with its unit, e.g. `1,250 KG` (the phone joins its weight and weight unit). |
| `Container / Truck No.` | As saved (Containerized / Loading forms). |
| `Currency`, `Unit Price`, `Total Price` | As saved (since 18 November 2026). |
| `Packing List No.` | See above; `""` when none. |
| `Origin Line` | `<origin Control #>/<Item List no.>/<line no.>`, counting the saved (filled) lines from 1. |

**Never in the file:** Findings (other than as the Packing List No.), Cargo
ID, Receiving Ref, SO Number, Supplier,
Consignee, and every other First Page field. A reader **refuses** a line
with any other field, even when the checksum is right.

A reader also refuses:
- another `format` (a hand-over file is named as such) or `version`
- a wrong checksum
- a missing transfer id, origin Control # or destination
- an empty Item List
- a list of Packing Lists that does not match the lines

## Tests

- **Windows** (`tests/test_shipment.py`, `tests/test_shipment_gui.py`):
  - Packing List reading, one and several destinations
  - nothing private in the file, the origin unchanged (also PO-linked)
  - all or nothing when a write fails
  - wrong choices
  - damaged, foreign or tampered files
- **Shared samples:**
  - `tests/data/shipment_from_windows.fsrshipment` is written by this
    program. A copy is in the Android project's `app/src/test/resources`,
    and the Windows test checks the copy is the same.
  - `tests/data/shipment_from_android.fsrshipment` is written by the
    Android `ShipmentCodecTest` and read by the Windows tests. Its lines
    are the same as the Windows file's for the same report.
- **Android** (`ShipmentCodecTest`): the same rules, and reading the Windows
  file.
- **Receiving, Windows** (`tests/test_shipment_import_gui.py`): a shipment
  into a draft, opened, verified and saved (Packing Lists kept, workbook
  columns at the end, fresh Receiving Refs); duplicates (same file, second
  file, discarded draft); another destination; no destination set; a
  damaged file; a shipment file chosen as a hand-over.
- **Schema, Windows** (`tests/test_shipment_migration.py`): against the
  previous version's own code - its workbooks and databases read the same;
  the way back for the database; the refused workbook; the Withdrawal
  workbook unchanged; fingerprints.
- **Android**: `ShipmentCodecTest` (the draft made from the Windows file;
  Master Data carries the fields only when set), `ShipmentFlowTest` (device:
  import once, refused again, another destination refused),
  `ShipmentMigrationTest` (device: database 2 -> 3 keeps every report, line
  and hand-over).
