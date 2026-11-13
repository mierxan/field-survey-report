# Field Survey Report – Cargo Inspection, Warehouse Monitoring and Analytics

A Windows desktop program (Python, Tkinter + ttkbootstrap) for cargo
inspection reports. It also monitors Receiving and Withdrawal transactions,
the warehouse inventory and Bad Order cargo, and produces Excel and PDF
reports.

The inspection reports stay the single source of truth. Every warehouse
figure is calculated from the saved reports, and nothing is copied or
estimated.

---

## 1. Install

Requirements: Windows 10/11 and Python 3.12 or newer (developed and tested
with Python 3.14.4).

```bat
SETUP_NEW_PC.bat                 rem creates .venv and installs requirements.txt
```

Or by hand:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -r requirements-dev.txt   rem only to run the tests
```

| Package | Used for | Tested version |
|---|---|---|
| ttkbootstrap | GUI | 2.2.6 |
| openpyxl | Excel data file and Excel reports | 3.1.5 |
| matplotlib | Charts inside the program | 3.11.2 |
| reportlab | PDF reports of the warehouse modules | 5.1.0 |
| pypdf, pywin32 | Inspection report PDF / printing (existing) | 6.21.2 / 312 |
| mysql-connector-python | Optional MySQL storage (existing) | 26.10.0 |
| pytest | Automated tests | 9.2.0 |

PDF printing of the inspection forms still needs Microsoft Excel or
LibreOffice (unchanged).

## 2. Run

| Start with | What it opens |
|---|---|
| `START_FSR.bat` (or `main.py` in PyCharm) | The program with the **real data** |
| `START_DEMO.bat` | **Demo Mode** with fictional TEST data (see §5) |
| `RUN_TESTS.bat` | All automated tests |
| `GO_BACK_TO_WORKBOOK.bat` | Stops using the reports database: the Excel file holds every report again (before going back to the previous version) - [docs/SQLITE.md](docs/SQLITE.md), section 4 |
| `BACKUP_CODE.bat` | Backs up the code: every branch in one checked git bundle, newest 10 kept - [docs/BACKUP_CODE.md](docs/BACKUP_CODE.md) (also how to restore) |

Sign-in uses local accounts (`app_auth.py`, `data/json/private/users.json`). New accounts and
password changes require at least 12 characters; existing passwords remain
valid for sign-in and are not forcibly reset.
The User edition is installed without any account: its first start shows a
one-time "Set Up This PC" screen that creates the Administrator of that PC.
The account file is signed, wrong passwords lock an account for 15 minutes
after five tries, and the MySQL password is kept in the Windows Credential
Manager - see [docs/ACCOUNT_FILE_SECURITY.md](docs/ACCOUNT_FILE_SECURITY.md)
and, for installing the update, [docs/PHASE1_ROLLOUT.md](docs/PHASE1_ROLLOUT.md).

The workbook is backed up before the first save of each day (`Backups`
folder beside it, newest 14 kept), and a save that stops halfway is finished
automatically at the next start or save - see
[docs/DATA_SAFETY.md](docs/DATA_SAFETY.md), which also explains how to
restore a backup.

Several copies of the program may share one MySQL database: a copy never
overwrites a MySQL report it does not own, and a copy run from this folder is
a TEST COPY that refuses the real database - see
[docs/TWO_COPIES_ONE_DATABASE.md](docs/TWO_COPIES_ONE_DATABASE.md), which
also has the steps for the test database.

Save does not wait for MySQL: the report is saved on this PC and sent in
the background ("N waiting for MySQL" beside the MySQL circles). An import
is written in one go, with a progress window. Measured times:
[docs/PERFORMANCE_BASELINE.md](docs/PERFORMANCE_BASELINE.md); a proposal for
larger data: [docs/STORAGE_PROPOSAL.md](docs/STORAGE_PROPOSAL.md); open
decisions for the owner: [docs/OPEN_DECISIONS.md](docs/OPEN_DECISIONS.md).

The reports are kept in a database file beside the Excel file
(`Field_Survey_Reports.sqlite3`, Phase 5); the Excel file is an export kept
up to date in the background, in the same layout as before. The move
happens once at the first start, with a backup and a full comparison - see
[docs/SQLITE.md](docs/SQLITE.md), which also lists every way the Excel file
is used, what happens to an Excel file edited by hand, and the way back.

## 3. The modules (left navigation bar)

| Module | What it does |
|---|---|
| **Dashboard** | Inspection KPIs and warehouse activity for the chosen period (with a comparison to the previous period), plus charts for Receiving vs Withdrawal, Good vs Bad Order, inventory status, and aging. |
| **Inspection Reports** | The existing form, unchanged: Good/Bad Order, the General / Documents / Item Lists / Additional Details / Incident Report pages, the Weekly Summary, Save (Ctrl+S), Open (Ctrl+O), New (Ctrl+N), Print/PDF (Ctrl+P), and MySQL sync/restore. New: the **Cargo ID** and **Receiving Ref** columns in the Item Lists. |
| **Receiving Transactions** | Daily / Weekly / Monthly summaries (KPIs, breakdowns, comparison with the previous period, lines) and a searchable, sortable, filterable table of all receiving cargo lines. Double-click opens the original report. Excel/PDF export. |
| **Withdrawal Transactions** | The same for withdrawals (consignee / destination breakdowns). Links to the cargo history. |
| **Warehouse Monitoring** | Searchable inventory and issue tables, warehouse/status filters, item transaction history, suggested reconciliation matches, and the append-only decision history. Users may propose matches and add notes; owners can confirm/reject proposals, accept duplicate receipts, exclude supported issues, and reopen recorded decisions. |
| **Bad Order Monitoring** | Bad Order KPIs, trend by day/week/month, by warehouse, Good vs Bad, and by cargo type (Types of Goods). Also the records table with a **case status** (Open / Under Review / Resolved) and exports. |
| **Analytics and Reports** | All trend charts, quantity charts (one unit of measure at a time), weight charts (kg), the management summary, and the **Report Centre** with the 13 Excel/PDF reports. |
| **Master Lists and Settings** | Data file and analytics source (Excel/MySQL), MySQL settings, a confirm-first MySQL table upgrade, the master list editor, light/dark mode, and the Demo Mode tools. |

Reporting periods: Today, This Week (Monday–Sunday), This Month, This Year,
Previous Day/Week/Month/Year, All Records, Custom Date Range.

**Period figures vs balances.** Transaction KPIs are limited to the
selected period. Inventory balances are always the *current recorded
balance* (all transactions up to today), and are labelled that way.

## 4. How the warehouse figures are calculated

* **One report = one transaction.** Its *Activity* (Receiving / Withdrawal)
  sets the type, its *Inspection Date* is the transaction date and its
  *Location* is the warehouse. Each Item List line is a cargo line.
* **Inventory item** = (warehouse, Cargo ID). A Receiving line without a
  Cargo ID is its own item, identified by its Receiving Ref.
* **Linking** a withdrawal to a receipt uses only its **Receiving Ref** or
  **Cargo ID**, in the **same warehouse**. Descriptions are never used for
  matching, and transfers between warehouses are not assumed. Anything
  else becomes an *Unmatched Withdrawal* and goes to reconciliation.
* **Remaining = Total Received − Total Withdrawn.** This is calculated only
  when every counted line has a quantity and all lines share one unit
  (units are normalised, e.g. pc/pcs/pieces → PCS). Otherwise the item is
  **Reconciliation Required** and no balance is shown. Negative balances
  are kept and shown as **Over-Withdrawn**.
* **Statuses:** In Stock (No Recorded Withdrawal), Partially Withdrawn,
  Fully Withdrawn, Over-Withdrawn, Reconciliation Required.
* **Weights** are converted to kg only from known units (kg, g, MT/t/ton,
  lb). A weight without a unit is never guessed.
* **Duplicates:** a Receiving Ref seen twice is counted once and flagged.
  Two lines with the same description, date and quantity are *not* treated
  as duplicates.
* **Aging** is calculated per receiving batch from its valid Receiving
  date. Withdrawals come off the batch they name, otherwise the oldest
  batch first (FIFO). The default buckets are 0–7, 8–30, 31–60, 61–90 and
  more than 90 days, and the thresholds can be changed.
* **Reconciliation** decisions (propose → confirm / reject, exclude, accept
  as a separate batch, reopen, note) go into an append-only audit log.
  They never change the inspection reports; the ledger applies them on
  top every time. Anyone may propose or add a note; only an **owner**
  account may confirm, reject, exclude, accept or reopen.
* "In stock" means *recorded*, not physically verified. The program has no
  stock-count function.

All fields are described in [docs/DATA_FIELDS.md](docs/DATA_FIELDS.md).

## 5. Demo Mode and sample data

`START_DEMO.bat` sets `FSR_DEMO=1`. In Demo Mode:

* the workbook and generated forms live in `data\excel\demo_data\`, while
  master lists and JSON sidecars live in `data\json\demo_data\`;
* MySQL is switched off and cannot be switched on;
* the Excel file cannot be changed to a file outside `data\excel\demo_data\`;
* the top bar and sidebar show **DEMO MODE – TEST DATA ONLY**.

Close the program and use `START_FSR.bat` to return to the real data.

The sample data (84 reports: 52 Receiving, 32 Withdrawal) covers about
3½ months and two fictional warehouses. It includes every required test
scenario (A–M). All IDs are recognisable (`TEST-REC-0001`, `TEST-WDR-0001`,
`TEST-SO-…`, Cargo IDs `TEST-…`).

```bat
.venv\Scripts\python -m warehouse.sample_data generate   rem write / refresh (no duplicates)
.venv\Scripts\python -m warehouse.sample_data status
.venv\Scripts\python -m warehouse.sample_data reset      rem remove TEST-* records only
```

The same buttons are on *Master Lists and Settings* (enabled only in Demo
Mode). The generator writes only into a folder marked as test data. It
refuses the program folder, and any workbook that holds real (non-TEST)
reports. Reset removes TEST records only.

Sample dates are relative to the day they are generated, so the aging
scenarios (3 / 14 / 45 / 75 / 100 days) hold on that day. Generate again
to refresh them.

## 6. Tests

```bat
RUN_TESTS.bat          rem or: .venv\Scripts\python -m pytest -v
```

The tests cover authentication, imports, periods, parsing, inventory
scenarios, analytics, the side file, sample data, exports, storage
regression, MySQL (with a fake connection) and the GUI. GUI tests require an
interactive Windows desktop; they skip when no display is available. Tests
use temporary data and do not touch the real Excel file, accounts, or a
MySQL server. Latest results are in
[docs/TESTING_REPORT.md](docs/TESTING_REPORT.md).

## 7. Owner and User editions, MySQL

There is no online server. Each PC and phone keeps its own data, and the
owner collects everything with Master Data files (JSON):

| Edition | Where | Storage | Master Data |
|---|---|---|---|
| **Owner** (`FieldSurveyReport_Owner_Setup_*.exe`) | the owner's PC | Excel + MySQL (Workbench) | **Import Master Data...** brings in the files of every site PC and phone |
| **User** (`FieldSurveyReport_User_Setup_*.exe`) | each site PC | Excel and JSON files on that PC only; MySQL is never used | **Export Master Data...** writes `FSR_Master_Data_<PC>_<date>.json` to send to the owner |
| **Android app** | each inspector's phone | the phone's own database | **Export Master Data** (Save File / Share), sent to the owner |

The owner's import adds each report to the owner's Excel file and MySQL
database, offers the new consignee/supplier/... names for the master lists,
and remembers what it brought in (by PC or phone and Control #), so sending
the same file again never duplicates a report. A Control # that is already
taken on the owner's PC gets the next free number with the same initials.

Run from source, the program is the Owner edition; `set FSR_EDITION=user`
starts the User edition for testing.

In the Owner edition every save still goes to the Excel file and, when set
up, to MySQL. The dashboards read Excel by default; MySQL can be chosen
under Settings.

Databases created before this update need two new columns on
`item_lines`. Either run `data/schema/migrations/001_add_item_warehouse_links.sql` in
Workbench, or use **Settings → Upgrade MySQL Tables…**, which asks for an
admin login such as `root` (not saved) when the program's own login may not
change tables. Existing rows are kept. Until then, reports still save to MySQL without the two link values,
and the program says so. New installations get the columns from
`data/schema/field_survey_schema.sql`.

## 8. Project layout

```
field_survey_report.py   main program: window, inspection form, report forms (existing)
fsr_storage.py           field definitions + Excel storage (moved unchanged out of the main file)
fsr_withdrawal.py        PO-linked Withdrawal: PO list, quantity rules, Withdrawal workbook
fsr_withdrawal_ui.py     the PO picker on the Item Lists tab
db_mysql.py              optional MySQL storage
app_auth.py              sign in / users, signed account file
fsr_secrets.py           Windows Credential Manager (recovery code, MySQL password)
fsr_backup.py            daily backup copy of the workbook
fsr_save_journal.py      record of each save; finishes a save that stopped halfway
fsr_mysql_guard.py       checks before every write to MySQL; conflicts and replaced versions
fsr_renumber.py          gives a saved report another Control # everywhere on this PC
fsr_test_db_script.py    makes the script for the test database from the real schema
fsr_build_check.py       build check: no account data in the User edition
warehouse/               business logic, no widgets
    periods.py           reporting periods (calendar weeks Mon–Sun)
    transactions.py      reports -> transactions / cargo lines, quantity / unit / weight parsing
    inventory.py         inventory ledger, statuses, aging, issues, matching suggestions
    analytics.py         KPIs, summaries, trends, Bad Order, management summary
    store.py             data loading + warehouse side file (reconciliation log, case status)
    tables.py            table columns + row builders shared by screens and exports
    exports.py           13 Excel / PDF reports
    sample_data.py       isolated TEST data generator (CLI)
warehouse_ui/            presentation layer
    shell.py             navigation sidebar, module switching
    components.py        KPI cards, filter bar, data table, chart panel, data service
    pages.py, analytics_page.py, settings_page.py, dialogs.py, theme.py
migrations/              (moved) see data/schema/migrations/
tests/                   pytest suite (+ gui_harness.py)
data/schema/             optional MySQL scripts and proposal-only schema SQL
data/json/               master lists, JSON sidecars, and private settings/accounts
data/excel/              report templates, workbooks, and Demo Mode workbook
docs/                    data fields, testing report, changes and limitations
```

Where managed data is stored: the Excel data file in `data/excel/` and its
JSON sidecars in the corresponding path under `data/json/`. A workbook
selected outside the managed Excel folder continues to keep its sidecars
beside that workbook. Private settings and local accounts are kept under
`data/json/private/` in a source checkout and in the per-user application
data directory in an installed build.

Environment variables: `FSR_DEMO=1` turns on Demo Mode. `FSR_HOME=<folder>`
isolates every file in that folder, which is what the tests use.

## 9. Building the installer

`build_installer.bat` builds both editions in one run:
`Installer\FieldSurveyReport_Owner_Setup_<date>.exe` and
`Installer\FieldSurveyReport_User_Setup_<date>.exe` (`/owner` or `/user`
builds only one). The two install side by side as separate programs; only
the Owner edition carries the MySQL driver, the MySQL defaults and the SQL
scripts for Workbench. See `BUILD_INSTALLER.txt`.

## 10. PO-linked Withdrawal reports

**When it applies:** Activity = Withdrawal (General > Inspection Schedule
Summary) on the Default Item List form. Every other combination, including
Withdrawal on the Containerized or Loading form, works as before.

**Workflow:** on the Item Lists tab, type a PO Number and click Show Lines.
Double-click a line to add it to the Item List, or click All in the Item List to
add every line shown. Each becomes one Item List line, filled from that Receiving
line (PO + Receiving Ref, never description), and is locked apart from Findings.
Double-click its Quantity to change what is withdrawn. To take a line out, click
it and then Remove Clicked Line. Lines typed by hand may sit beside them; they
have no Received Quantity, so no limit applies and they are not PO-verified.

**PO unavailable, not found or a placeholder** (`n/a`, `Consolidated` ...): type
the lines on the Item Lists as usual. The report saves to the main workbook and
is not linked to a Receiving line.

**Withdrawal reports therefore exist in two places.** PO-linked reports are in
`Withdrawal_Reports.xlsx`, the others in the main workbook. A Control # is in
one of them only (the numbering checks both), and a report is always saved back
to the workbook that holds it. A saved PO-linked report cannot change Activity
or form; a saved main workbook report cannot take PO lines. Start a new report
instead. Historical reports are not moved.

**PO lines:** the picker reads the saved Receiving reports of the main workbook,
so a new Receiving report can be picked as soon as it is saved. A line's PO is
its own PO Number, or else its report's. It is only ever read.

- `Quantity` is what was **received**, not what was ordered, so the program calls
  it Received Quantity. It does not know the original PO quantity.
- A line is identified by its Receiving Ref. The line number shown is only its
  order within the PO.
- A PO cell naming several POs (`1001 / 1002`) cannot be tied to one PO. Its lines
  are not offered; the "not found" message counts them.
- A line whose Quantity is not a number above 0 is left out and counted.

**Item lists:** two files beside the main workbook are rebuilt from the saved
reports after a PO-linked or Receiving save, so edits by hand in them are lost.

- `PO_Master.xlsx`: every Receiving line with something left, its `Quantity` being
  what remains. A fully withdrawn line leaves the list. Rows of reports that are
  not in the main workbook (not imported yet) are kept as they are.
- `Withdrawn_Item.xlsx`: the same columns plus `Date Withdrawn` (the Inspection
  Date) as the last one, one row per withdrawn line, partial withdrawals included.
  `Control #` is that of the Withdrawal. A Withdrawal in the main workbook is listed
  only when it names a Receiving Ref.

If either file is open in Excel, the report still saves, a note says so, and the
next save brings them up to date.

**Withdrawal workbook:** `Withdrawal_Reports.xlsx` beside the main workbook.
In Demo Mode it must stay inside the demo folder.

| Sheet (table) | Rows | Columns |
|---|---|---|
| Withdrawal Reports (`WithdrawalReportsTable`) | one per report; `Control #` is the report ID | the main Reports columns + `Entry Source`, `PO Source File` |
| Withdrawal Lines (`WithdrawalLinesTable`) | one per line; `Line ID` stays with the line through edits | the main Item List columns with `Quantity` named `Withdrawal Quantity` + `PO Line No`, `Source Control #`, `Received Quantity`, `Line ID` |
| Declared Goods (`WithdrawalGoodsTable`) | as in the main workbook | |
| Remarks (`WithdrawalRemarksTable`) | as in the main workbook | |

A file with this name but another layout is reported and left untouched.

**Quantity rules:** a number above 0, starting at what remains of the line, and
no more than that. Remaining = Received Quantity minus what all other saved
Withdrawals took by the same Receiving Ref; it is worked out each time and the
Receiving report is not changed. A line with nothing left is not offered. Decimals
only for `M` and `KG` (and their spellings); every other unit, known or not, must
be whole. Total Price = Unit Price x Withdrawal Qty. On a partial withdrawal the
Weight is cleared, because the listed weight is that of the whole received line.

**Stock:** the warehouse pages also read this workbook, read-only, and a Control
# in both files counts once. The rules in section 4 are unchanged. A picked line carries the Receiving Ref of
its batch, so it reduces that balance when the withdrawal's Location is the
warehouse that received it. Otherwise it goes to Reconciliation and deducts
nothing, because transfers between warehouses are not assumed.

**MySQL:** reports are copied as before with no schema change; `quantity` holds
the withdrawal quantity. PO Line No, Source Control # and Received Quantity are
in Excel only, so a PO-linked report always opens from the Withdrawal workbook.

**Printing:** the existing Default Cargo Details form, with the withdrawal
quantity in Quantity. It has no columns for PO Line No or Received Quantity.
