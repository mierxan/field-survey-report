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

Sign-in works as before (`app_auth.py`, `users.json`).

## 3. The modules (left navigation bar)

| Module | What it does |
|---|---|
| **Dashboard** | Inspection KPIs and warehouse activity for the chosen period (with a comparison to the previous period), current inventory balances, plus charts: Receiving vs Withdrawal, Good vs Bad Order, cargo by status, and aging. |
| **Inspection Reports** | The existing form, unchanged: Good/Bad Order, the General / Documents / Item Lists / Additional Details / Incident Report pages, the Weekly Summary, Save (Ctrl+S), Open (Ctrl+O), New (Ctrl+N), Print/PDF (Ctrl+P), and MySQL sync/restore. New: the **Cargo ID** and **Receiving Ref** columns in the Item Lists. |
| **Receiving Transactions** | Daily / Weekly / Monthly summaries (KPIs, breakdowns, comparison with the previous period, lines) and a searchable, sortable, filterable table of all receiving cargo lines. Double-click opens the original report. Excel/PDF export. |
| **Withdrawal Transactions** | The same for withdrawals (consignee / destination breakdowns). Links to the cargo history. |
| **Warehouse Monitoring** | Inventory, Remaining Warehouse Cargo, No Recorded Withdrawal, Inventory Aging (configurable thresholds) and the Reconciliation workflow. Double-click an item for its full Receiving/Withdrawal history. |
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

* the Excel file, Report Forms, settings, master lists and warehouse files
  live in `demo_data\` (workbook `Field_Survey_Reports_DEMO.xlsx`);
* MySQL is switched off and cannot be switched on;
* the Excel file cannot be changed to a file outside `demo_data\`;
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

`tests/test_api_integration.py` needs a running test server and is otherwise
skipped; its first lines say what to set.

```bat
RUN_TESTS.bat          rem or: .venv\Scripts\python -m pytest -v
```

There are 156 tests in `tests/`, covering periods, parsing, the inventory
scenarios, analytics, the side file, the sample data, exports, regression
of the existing storage, MySQL (with a fake connection) and the GUI. The
GUI tests start the real program in a temporary folder, with the sign-in
replaced by a test user; they need a Windows desktop session. No test
touches the real Excel file, settings or MySQL. Results are in
[docs/TESTING_REPORT.md](docs/TESTING_REPORT.md).

## 7. MySQL (optional, unchanged behaviour)

Every save still goes to the Excel file and, when set up, to MySQL. The
dashboards read Excel by default; MySQL can be chosen under Settings.

Databases created before this update need two new columns on
`item_lines`. Either run `migrations/001_add_item_warehouse_links.sql` in
Workbench, or use **Settings → Upgrade MySQL Tables…**. Existing rows are
kept. Until then, reports still save to MySQL without the two link values,
and the program says so. New installations get the columns from
`field_survey_schema.sql`.

## 7a. Central server (optional)

With `api_config.json` beside the program (copy `api_config.example.json`) the
program uses the central API instead of MySQL, and shares its data with the
Android app. Without that file nothing changes.

* Sign-in, master lists, reports, the Weekly Summary and the warehouse modules
  all read from the server. No database login is on the PC.
* Save goes to the server first, which gives the official Control #. The
  number shown on a new form is only a preview. The Excel file is then updated
  as a local backup copy, and the report forms are made as before.
* The free server sleeps when unused and takes about a minute to wake. The program
  keeps it awake while open; the first sign-in may still wait, up to 90 seconds.
* If the server cannot be reached the save is refused with a clear message and
  the report stays on the form. The master lists stay readable from
  `master_list.json`. Signing in needs the server.
* If someone else saved the report first, nothing is overwritten: you choose
  between their copy and yours.
* Inspectors view all reports and edit their own, and may add master names.
  Only the owner and admins edit every report, or remove names.

Setup, deployment and rollback are in `docs/OPERATIONS.md` of the
`field_survey_backend` project. The code is in `fsr_api.py`, which has the same
functions as `db_mysql.py`.

Local accounts for the old mode now come from `auth_seed.json`, which is not in
source control. Keep a copy: a new installation without it creates no Owner.

## 8. Project layout

```
field_survey_report.py   main program: window, inspection form, report forms (existing)
fsr_storage.py           field definitions + Excel storage (moved unchanged out of the main file)
db_mysql.py              optional MySQL storage
fsr_api.py               optional central API storage (same functions as db_mysql.py)
app_auth.py              sign in / users (unchanged)
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
    pages.py, warehouse_page.py, analytics_page.py, settings_page.py, dialogs.py, theme.py
migrations/              MySQL migration for existing databases
tests/                   pytest suite (+ gui_harness.py)
demo_data/               the isolated sample data set (Demo Mode)
docs/                    data fields, testing report, changes and limitations
```

Where data is stored: the Excel data file (path in `settings.json`),
`Incident Reports\` and `Report Forms\` beside it (as before), and
`Warehouse Data\<file>.warehouse.json` beside it (new: reconciliation log,
Bad Order case status, aging thresholds).

Environment variables: `FSR_DEMO=1` turns on Demo Mode. `FSR_HOME=<folder>`
isolates every file in that folder, which is what the tests use.

## 9. Building the installer

`build_installer.bat` / `FieldSurveyReport.spec` work as before; the new
packages and the Matplotlib Tk backend have been added to them. See
`BUILD_INSTALLER.txt`.
