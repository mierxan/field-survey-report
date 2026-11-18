# Field Survey Report changelog

## Phase 16 - Withdrawal-to-Receiving sharing, part 3: verification (unreleased, 18 November 2026)

- **Printing (Option B)**: on the printed Cargo Details page the Findings
  column of a line received from a shipment shows "<Packing List> ·
  <Findings>" (e.g. "BAC111126-009 · Good Order and Complete"); other lines
  print as before (`fsr_storage.printed_findings`, `fsr_forms`). Up to 56
  characters print on two wrapped 9 pt lines (a new wrapping style variant
  with its own font, `StyleCloner.wrap_small_index`), longer ones shrink to
  fit as before. Checked with Excel's own rendering.
- **Packing Lists...** (Findings row): each Packing List of the lines with
  its PO numbers and counts of Good Order / with issues / no Findings.
- **Save asks** while lines received from a shipment have no Findings yet
  ("Verification not finished", default No); nothing is filled in by it.

## Phase 15 - Withdrawal-to-Receiving sharing, part 2: the destination (unreleased, 18 November 2026)

- **Findings in one click** (18 November 2026, after the first manual test):
  above the Item Lists, **All Good Order and Complete** writes "Good Order
  and Complete" on every item line (asks before replacing other Findings),
  and **With Issues...** lists every line with its Packing List: tick the
  lines with an issue, type their findings, and Apply writes "Good Order and
  Complete" on every other line (`fsr_findings_ui.py`). The Packing List
  numbers are not touched.
- **Prices travel**: Unit Price, Total Price and Currency are now in the
  shipment file and in the Receiving draft (the owner's decision, reversing
  Phase 1 decision 5 for these three). SO Number, Supplier and the other
  First Page fields still never travel.
- Side panel: Share Shipment... / Receive Shipment... sized so both names
  show.

- **Storage > Receive Shipment...** (Owner and User edition), and a
  double-click on a `.fsrshipment` file: a shipment for THIS PC's destination
  becomes a **new Receiving draft** of the signed-in account, offered to open
  at once (`fsr_shipment.import_shipment`, `fsr_shipment_ui.open_receive`).
  Activity = Receiving, every other First Page field empty; the Item Lists
  hold the shipment's lines; Findings empty for the receiving condition. The
  summary (origin, sender, Packing Lists, lines, POs, "matches") is shown
  before anything is made.
- **This PC's destination**, set once (Receive Shipment, with Change...),
  from the Destination master list: a file for another destination is
  refused with a clear message. A check against mistakes, not security.
- **Duplicates refused**: a shipment whose origin lines are already in a
  draft from an earlier import or in a saved report. A draft discarded by
  mistake can be imported again. Every import is recorded in
  `<workbook>_shipments.json`.
- **Two hidden line fields, Packing List No. and Origin Line** (saved, never
  printed in the Item List columns), kept when Findings is edited; carried by
  the form, drafts, Master Data and hand-over files, MySQL (two optional
  columns via Upgrade MySQL tables). The main workbook's Item List sheet gets
  them as its last two columns on the next save; the Withdrawal workbook is
  unchanged. A line carries them only when they have a value, so existing
  reports read, export and fingerprint exactly as before.
- Unfinished work lists an imported draft as "Shipment from <origin> for
  <destination>". Storage: Share Shipment... and Receive Shipment... share a
  row; a shipment file chosen in Receive Hand-over goes to Receive Shipment.
- The installer registers `.fsrshipment` (opens the program, which asks).
- Tests against the previous version's own code (git archive of the newest
  commit before the fields): its workbooks and databases read the same; it still reads a
  database this version wrote to; it refuses a workbook this version saved
  (the accepted caveat). The real reports read the same by both versions (67
  reports, 386 lines, all Owner fingerprints) - read only.
- Not yet: the verification screen and printing "<Packing List> ·
  <Findings>" (Phase 3), items added at the destination (Phase 4).

## Phase 14 - Withdrawal-to-Receiving sharing, part 1: the origin (unreleased, 18 November 2026)

- **Storage > Share with Destination...** (Owner and User edition): choose a
  saved Withdrawal report (normal or PO-linked), give each of its Packing
  Lists a destination, and get **one shipment file per destination**
  holding only that destination's Packing Lists and their item lines
  (`fsr_shipment.py`, `fsr_shipment_ui.py`, format in
  [docs/SHIPMENT.md](docs/SHIPMENT.md)).
- The Packing List No. of a line is read from its Findings, the whole cell
  exactly as written (`BAC111126-001 & 002` stays one entry; never split or
  guessed). Lines without one form the group "(no Packing List)".
- Only the cargo details travel, with the origin reference (Control #,
  location, Inspection Date, inspector, device), a random transfer id, the
  destination, each line's Packing List No. and its Origin Line. No prices,
  Currency, SO Number, Supplier, Cargo ID, Receiving Ref or other First Page
  fields. A file holding any other line field is refused when read.
- The Withdrawal report is only read; nothing in the workbook, the
  database, PO_Master, Withdrawn_Item or MySQL changes. Each file is read
  back and checked; if one cannot be written, the files of that click are
  removed again. An existing file is never overwritten.
- Side panel: Hand Over... and Receive Hand-over... share one row, so the
  panel is no taller with the new button.
- Not yet: importing the file at the destination, verification, items added
  there, the Android screens (later phases). The Android app already reads
  and writes the same file (its `ShipmentCodec`), checked against this
  program's file both ways.

## Phase 13 - Futuristic Dashboard, as on the phone (unreleased, 18 November 2026)

- **Dashboard, Receiving / Withdrawal Transactions and Bad Order
  Monitoring** have the phone app's futuristic look: deep navy, cards whose
  edge glows in their colour, neon icons, glowing bars and lines, rings
  (`theme.NEO`, `neo=True` on Card, KpiGrid, PeriodBar, DataTable and
  ChartPanel). The same in the light and dark theme; the other pages and
  the report form are unchanged.
- **Dashboard:** six cards - Total Inspection Reports, Good Order Reports,
  Bad Order Reports, Bad Order Percentage, Receiving Transactions,
  Withdrawal Transactions (the second row of four, which repeated them, is
  gone). Charts: Overall Transactions, Receiving Transactions, Withdrawal
  Transactions, Warehouse Items / Cargo Status (ring), Bad Order (ring with
  the count and share), Inventory Aging.
- **Receiving / Withdrawal Transactions:** the cards are Total
  Transactions, Total Packages (the Declared Goods quantities added up) and
  Items Inspected (the Item List quantities added up), with the change
  against the period before (`analytics.activity_kpis`), on the Daily /
  Weekly / Monthly Summary and All Transactions. Weekly Breakdown and
  Breakdowns and Comparison in the new look; long week labels tilt.
- **Bad Order Monitoring:** a chart of Bad Order reports per month and a
  list of the reports by month (latest month open; double-click opens the
  report; `analytics.bad_order_by_month`). Good Order vs Bad Order is a
  ring.
- **18 November 2026, revised:** Dashboard: Warehouse Items / Cargo
  Status shows Total Line Items Stored and Total Line Items Withdrawn (the
  Item List lines of the period's Receiving and Withdrawal reports).
  On screen a Bad Order report is an **Incident Report**: the Bad Order
  Monitoring page is now **Incident Reports** (sidebar), and the Dashboard
  cards and ring say Incident Reports / Incident Report Percentage. The
  report's Cargo Condition stays "Bad Order" (data). The page no longer
  shows Affected Cargo Lines, Unresolved Bad Order Cases, Bad Order by
  Cargo Type or the Bad Order Records table; Set Case Status, Open
  Inspection Report and the summary exports work from the list by month.
- **Stored vs In Stock made clear:** Warehouse Items / Cargo Status adds a
  third bar, **Total Line Items In Stock** - the Item List lines with cargo
  left today, all dates - which equals the Inventory Aging total. Stored
  and Withdrawn stay the lines of the selected period. Inventory Aging now
  counts "Item List lines in stock" and says that a fully withdrawn line is
  not counted and that the period does not apply.
- **Inventory Aging List:** under Inventory Aging on the Dashboard. Click a
  bar (e.g. 0-7 Days) and the list shows that age group's Item List lines
  still in stock: Control Number, Date, Line Item (List / Line), Description,
  PO, Qty in Stock, UOM and Age (Days), oldest first. "Show All Ages" lists
  every age group; double-click a line to open its report. The Warehouse
  filter applies, as on the chart.
- The Excel and PDF exports are unchanged.

## Phase 12 - Dashboards that fit (unreleased, 17 November 2026)

- **Excel Dashboards (Weekly / Monthly reports and the interactive
  Weekly Summary): every chart now fits its place.** Charts are pinned to
  their cells, with a small gap between two side by side, so they no
  longer run under the next chart on PCs with display scaling, in WPS
  Office or on phones. The chart title and the legend ("Selected / Other
  days") each have their own place and no longer print on top of each
  other; legends sit under the chart.
- A month of days is labelled 1 ... 31 (the 31 dates ran together).
- White numbers inside the blue and purple bars of the interactive
  Dashboard; card texts shrink to fit their card.
- Printed, no chart is cut between two pages, and nothing is cut at the
  right edge.
- **Removed: Top 10 Suppliers by Total Value (PHP)** and its **Exchange
  Rates to PHP...** window, from the Owner edition's Dashboard page
  (Phase 10). Rates already entered stay in the settings file, unused.
  The missing-Currency question when saving stays: its message now says
  the price cannot be added to the Summary report's totals.
- The phone app's dashboards have the same changes (next phone release).

## Phase 11 - Open a hand-over file (unreleased, 17 November 2026)

- **Double-click a hand-over file.** Hand Over now saves
  `FSR_Handover_<Control #>_<date>.fsrhandover`. The installer tells
  Windows that this file type opens Field Survey Report. After sign-in,
  the program shows the usual Receive Hand-over question; nothing is
  brought in without Yes.
- If the program is already open, the file goes to that window, and the
  new start closes at once (`fsr_incoming.py`). It waits in the
  "Incoming hand-overs" folder beside the settings until it is answered,
  also if the program is closed first.
- **Receive Hand-over...** opens both `.fsrhandover` and the older `.json`
  files.
- The phone app 1.9.0 makes and opens the same `.fsrhandover` files.
- **Fix: the file sent back was confused with the one sent out.** Both
  had the same name (same report, same day), so the first inspector
  could open their own file, see only "nothing changed", and the report
  stayed handed over. The name now ends with the sender's initials
  (`..._2026-11-17_from_BRV.fsrhandover`), and opening your own file says
  "This is the file you sent to <name>. Open the file <name> sent back
  to you instead." (Phone app 1.9.1 the same.) A PC no longer makes a
  second draft from its own draft file.
- **Fix:** the list of reports databases (`databases.json`) is saved with
  the same two-second retry as the other files. A virus scanner reading
  it at that moment made the first move into the database stop with
  "Access is denied" (seen twice in the tests).
- `installer.iss`: the file type is registered per edition and removed on
  uninstall. Installers built 17 November 2026 (version
  2026.11.17.102123), all 1364 tests passing.

## Phase 10 - Top suppliers by value (unreleased, 17 November 2026)

- Owner edition, **Dashboard**: a new chart, **Top 10 Suppliers by Total
  Value (PHP)**, from the Receiving reports of the chosen period and
  warehouse. A cargo line's value is its Total Price (Unit Price x
  Quantity when the Total Price is empty), in its Currency.
- **Exchange Rates to PHP...** (button on the chart): the owner enters how
  many pesos one USD, JPY, EUR, SEK (or any other currency found in the
  reports) is worth. The rates are kept with the warehouse settings, with
  who changed them and when. Nothing is guessed: lines in a currency
  without a rate, or with a price but no currency, are left out and
  counted in the note under the chart.
- **Saving a report:** a line with a price but no Currency is caught. The
  form opens the Item Lists tab and names the lines (e.g. "Item List 1:
  line 3"); the inspector chooses the Currency, or saves anyway. A code
  typed with the price ("usd 100") counts as its currency.
- **Fix:** a Weight (or Quantity) saved as a number with a thousands comma
  or decimals and no unit, e.g. "18,400", was split into "18" and ",400"
  when the report was opened again, and saved back as "18 ,400". It now
  stays whole, as on the phone.
- Demo Mode data now has invented prices on its Receiving lines.
- **Fix:** the Bad Order **Case Status** window could not open with
  ttkbootstrap 2 (`unknown option "-bootstyle"`); it uses ttkbootstrap's
  own labels now.

## Phase 9 - Dashboard sheet for the client (unreleased, 16 November 2026)

- Weekly and Monthly Receiving and Withdrawal Excel reports (Summary
  Report Excel and Export Excel, Owner and User editions) start with a
  **Dashboard** sheet: a banner with the period and site, four KPI cards
  with the change against the previous period, charts (per day / per
  week, Good / Bad Order, quantity or cargo lines, top suppliers or
  consignees, sites), the comparison with the previous period, and the
  figures behind the charts. See [DASHBOARD.md](docs/DASHBOARD.md).
- Classic Excel charts only: checked in Excel 2007.
- The phone app 1.7.0 adds the same sheet to its Weekly Summary and asks
  for Receiving or Withdrawal.
- Withdrawal dashboards highlight the **delivery destinations**: a chart of
  shipments per destination and a table of shipments, total packages and
  cargo line items per destination.
- Inspection Reports > Weekly Summary > **Export** starts with an
  **interactive Dashboard**: dropdowns for Activity, Week, Cargo Condition
  and Supplier change the cards and charts at once (Excel formulas, no
  macros). The page now counts reports by Control # ("N line(s) from N
  report(s)"), not by SO Number and date.

## Phase 8.1 - phone drafts on a PC (unreleased, 16 November 2026)

- Receive Hand-over now takes an unfinished report (draft) from the phone
  app: it becomes a draft in Account > Unfinished work. Restored, it shows
  the phone's Control # and keeps it on its first save (the next free one,
  same initials, if another report here has it). Earlier the PC refused
  phone drafts.
- It stays the phone's report: its identity and next revision are recorded
  at the first save, so a hand-back to the phone updates the phone's copy
  and the Owner's import recognises it. Handed on from the PC as a draft,
  its number and identity go along.
- The conversion is the app's own Master Data export of the report, checked
  against a file written by the app's tests. The form that is open while
  the file is received is left exactly as it was. No new Android release is
  needed: drafts from app 1.6.0 are read.
- Windows drafts are still continued on a PC only.
## Phase 8 - hand-over to the next inspector (unreleased, 16 November 2026)

- Storage > **Hand Over...** writes one file with a saved report or one of
  the account's drafts, for the inspector who finishes it; **Receive
  Hand-over...** brings such a file in. Both editions, and the Android app
  (1.6.0) reads and writes the same file: completed reports move between
  PCs and phones, drafts between devices of the same kind.
- Numbering: a saved report keeps the Control # it was first given; only
  when that number is used by another report where it arrives does it get
  the next free one (initials kept, Receiving Refs follow). A draft of a
  new report takes the finishing inspector's number at its first save.
- The sender's copy is kept, marked handed over: opened and printed, not
  saved, until it comes back or the hand-over is cancelled.
- Handed-over reports carry a permanent identity and revision, also in
  Master Data files; the Owner's import recognises them whichever
  inspector sends them (also when sent the old way before), so nothing is
  doubled. The import fingerprint now leaves out Control #, Last Saved and
  identity fields (earlier fingerprints still recognised).
- PO-linked Withdrawal reports are not handed over yet. See
  [HANDOVER.md](docs/HANDOVER.md).
- Import Master Data, Hand Over and Receive Hand-over wait until the
  one-time move into the reports database has finished.
- Full suite: 1294 passed, 0 skipped. Android 1.6.0: 56 unit tests and 22
  device tests passed.

## Phase 7 - location identity, revisions and Import Review (unreleased, 16 November 2026)

- Recognise a report by its permanent location + report id when the file
  carries them: it follows its Owner number after a renumber, a replaced or
  restored phone, or a renamed location, and identical Control #s from two
  locations stay two reports.
- Hold a newer revision of a completed report in Import Review instead of
  overwriting the Owner's copy. The review shows the user's changes, the
  Owner's own changes since the last accepted revision, and fields both
  changed. Accept applies the user's changes and keeps the Owner's other
  edits; Keep My Version records the revision as received.
- Leave unchanged and older revisions alone; refuse a revision number that
  arrives with different content.
- Record every import decision in an append-only history beside the
  workbook; carried with the workbook, followed by renumbering, kept out of
  code backups. Files without the new fields are imported as before.
- What sending apps must add: [IMPORT_REVIEW.md](docs/IMPORT_REVIEW.md).
  The Android app and the Windows User edition do not send it yet.
- Full suite: 1269 passed, 0 skipped.

## Phase 7 - import change details (unreleased, 15 November 2026)

- After Import Master Data updates completed reports, show an
  "Imported Report Changes" window listing every changed field with its
  previous and imported value, including added and removed rows and
  entries (for example an item list growing from 1 to 7 rows).
- Compare a report sent twice in one file in the copy that is saved; several
  updated reports share one read of the workbook or database.
- Full suite: 1247 passed, 0 skipped with the committed Incident Report
  template.
- Incident Report template: larger print chosen by the Owner (incident text
  11 to 17 pt, header details 14 to 16 pt, title and signature lines 16 to
  18 pt; row heights unchanged). Text continuation measures the new size,
  so fewer characters fit on each incident line. Text-flow checks: 39 passed.

## Phase 6 - automatic text continuation (unreleased, 14 November 2026)

- Continue typed and pasted text onto the next row in Declared Goods,
  Other Important Remarks, Additional Details and Incident Reports.
- Measure against the official printed line widths and fonts; keep goods
  Quantity/Packaging on the original row and preserve occupied rows below.
- Retain excess text and drafts at the row limit, with an inline warning
  and a check before normal Save. Official templates and layouts are unchanged.
- Approved after the owner's hands-on test. Full suite: 1243 passed,
  0 skipped. See [text-flow checks](docs/TEXT_FLOW_TRIAL.md).

## Phase 6 - dropdown type-ahead (unreleased, 14 November 2026)

- Correct Windows Num Lock handling so Up/Down move the highlighted result
  and list-only fields remain searchable with Num Lock enabled. Preserve
  real Alt+Down and support keypad arrow names.
- Use one shared prefix picker for every non-date list dropdown in both
  editions, including Item Lists, Withdrawal lines, filters and settings.
- Keep typing focus, update on each edit, and commit the highlighted filtered
  value on Enter or click; fix Kokusai incorrectly becoming ABB.
- Preserve free-text rules, fixed-list choices, PO locks and drafts autosave.
  Date dropdowns and calendar pickers are unchanged.
- Add isolated checks and the field inventory: [TYPEAHEAD.md](docs/TYPEAHEAD.md).

## Phase 6 ? drafts (unreleased, 14 November 2026)

- Autosave unfinished raw form input locally after 3 idle seconds or by
  30 seconds during editing, without creating a report or reserving a number.
- Recover account-owned drafts after sign-in; review stale saved reports
  before restoring/saving, and preserve damaged or old drafts for review.
- Add Save / Keep as draft / Discard / Cancel only for unsaved changes;
  success uses a small status label, while failures get a warning.
- Allow administrators to discard removed-account drafts without restoring
  them into their own account. New accounts get a non-secret signed draft
  identity so deletion/recreation cannot reuse an earlier account's drafts.
- Coordinate draft retirement with explicit Save and the existing save
  record; checkpoint during Windows session end and recover abrupt exits.
- Add isolated test-copy hand checks, including second-account creation,
  approval and removal: [DRAFTS.md](docs/DRAFTS.md).

## Unreleased — release housekeeping

- Installer builds now receive a timestamp and UUID per invocation, shared
  by the Owner and User editions. A second build gets new filenames, even
  on the same day. Windows' numeric file version is kept separately.
- Recorded the completed improvement phases below and the original cleanup
  proposal in [HOUSEKEEPING_REVIEW.md](docs/HOUSEKEEPING_REVIEW.md).
- Approved cleanup removed unused tracked packaging/setup/probe files, the
  superseded schema proposal, and the legacy root Demo marker. Unused
  untracked artifacts were moved aside rather than deleted; actively
  referenced output folders were kept. The per-item dependency findings
  are in [CLEANUP_REFERENCE_AUDIT.md](docs/CLEANUP_REFERENCE_AUDIT.md).
- No installers have been rebuilt for these phases as part of housekeeping.
  The retained 11 November 2026 installers contain Phase 1 only.

## Phase 5 — SQLite reports database (13–14 November 2026)

- Store both report workbooks in a local SQLite database, with transactions
  for report writes and Excel exports in the existing workbook layout.
- On first start, back up the workbooks and side files, copy the reports,
  compare reports field by field and exports cell by cell, and use SQLite
  only when the checks pass. Unsupported workbook content keeps workbook
  mode in use; a save in Excel during migration postpones the move.
- Keep databases in Local AppData, outside network and synchronized
  folders. Recognize moved workbooks by database ID; give copies their own
  database and protect against exports from another PC's database.
- Detect Excel changes made outside the application, keep conflicting
  versions for review, retry locked exports, and wait for export on close.
- Add checked SQLite daily/pre-import backups, the Reports Database window,
  and `GO_BACK_TO_WORKBOOK.bat` for returning to workbook storage.
- Preserve typed quantity formatting in reopened reports, Excel exports,
  and Weekly Summary without changing sheets, columns, or MySQL tables.
- Keep incident texts, other item-form lines, and save/import/MySQL ledger
  records as side files. MySQL continues through the ownership guard.
- Add verified Git-bundle code backups; remove the GitHub workflow after
  the remote repository was deleted.

Evidence: [SQLITE.md](docs/SQLITE.md),
[PERFORMANCE_BASELINE.md](docs/PERFORMANCE_BASELINE.md),
[BACKUP_CODE.md](docs/BACKUP_CODE.md); commits `313b5a9`, `3813198`,
`bb99a38`, `8327ad6`, `df21d2f`, `8af6c07`, `42c148a`, `b17afdd`, `e3e2f97`.

## Phase 4 — maintainability (13 November 2026)

- Introduce a storage interface used by the window, dashboards, export,
  Demo Mode, and Withdrawal panel, with shared storage-contract tests.
- Split forms, item lists, Weekly Summary, Open Saved Report, and Save
  handling into modules; importing the main module no longer builds a window.
- Pin dependencies, remove unused packages, add Ruff configuration, and
  enforce Windows line endings for batch files.
- Address silently swallowed exceptions and document the remaining broad
  fallback handlers as an explicit deferred decision.
- Expand account, export, save, summary, GUI, and MySQL integration tests.
  Add fast and coverage modes to the test runner.

Evidence: [OPEN_DECISIONS.md](docs/OPEN_DECISIONS.md),
[STORAGE_PROPOSAL.md](docs/STORAGE_PROPOSAL.md), section 10; commits
`d46578f`, `cb49591`, `60b604a`, `e70c298`, `f157356`, `2c1070f`,
`5f0fd89`, `c7bf28a`, `7a3150c`.

## Phase 3 — performance (12–13 November 2026)

- Send reports to MySQL in the background over one connection per round,
  retaining the ownership guard and visible waiting/conflict status.
- Keep the window responsive while closing with reports still sending.
- Import a batch with one workbook load and write, with progress shown.
- Reduce repeated workbook reads and save-journal writes; rebuild
  PO_Master and Withdrawn_Item in the background.
- Fix contention between the application's own reads and atomic workbook
  replacements; measure saves, opens, imports, and larger report sets.
- Preserve the approved OPSF-068 v4.0 forms, including the intentionally
  hidden Control # in First Page A5; add regression checks for that layout.

Evidence: [PERFORMANCE_BASELINE.md](docs/PERFORMANCE_BASELINE.md),
[DATA_SAFETY.md](docs/DATA_SAFETY.md); commits `4687779`, `7d51744`,
`cbe0f82`, `6a01b21`, `de176b9`, `503a1ea`, `4aaf01c`, `e2939a8`.

## Phase 2 — data safety (11–12 November 2026)

- Make daily workbook backups before the day's first save, retaining the
  newest 14 by default.
- Record saves before writing and repair interrupted work at a later save
  or startup. Match each save by its exact planned Last Saved timestamp
  and preserve newer reports during recovery.
- Treat Control #s without regard to letter case across relevant workflows.
- Guard every MySQL write: adopt equal data, update this copy's unchanged
  reports, and require a decision for conflicts. Keep replaced versions and
  support safe renumbering and restoration.
- Correct ledger freshness so this copy's own saves remain recognized
  between saves, including after offline catch-up.
- Mark the source-folder program TEST COPY and refuse `field_survey` by
  default. Integration tests use `field_survey_test`.
- Report skipped tests explicitly and fail builds when GUI tests cannot run.

Evidence: [DATA_SAFETY.md](docs/DATA_SAFETY.md),
[TWO_COPIES_ONE_DATABASE.md](docs/TWO_COPIES_ONE_DATABASE.md); commits
`27818af`, `f39e15f`, `130bee1`, `feaf2e9`, `4a5832f`, `7fa6af0`,
`05d4a3a`, `33be8e7`, `d36a924`.

## Phase 1 — account and installer security (November 2026)

- Ship the User edition without accounts or owner credentials; first run
  creates a local Administrator. Stop packaging if private account data
  is found in the User build.
- Use 600,000-iteration PBKDF2 for new/updated passwords; retain compatible
  verification and upgrade older accounts on successful sign-in.
- Add increasing waits for wrong passwords and a 15-minute account lock.
- Sign account files, detect external changes or missing files, and provide
  administrator review and recovery-code handling.
- Remove the obsolete built-in second account. Require the legacy Owner
  account on site PCs to set a new password before opening the program.
- Store MySQL passwords in Windows Credential Manager and bundle the
  Windows modules needed by installed builds.
- Refresh MySQL status immediately after settings are saved.

Evidence: [ACCOUNT_FILE_SECURITY.md](docs/ACCOUNT_FILE_SECURITY.md),
[PHASE1_ROLLOUT.md](docs/PHASE1_ROLLOUT.md); commits `b98f133`, `39c8d92`,
`4db1932`, `f7ae9d0`, `2ff4797`, `106294a`, `473d450`, `aa1b744`.
The Phase 1 status fix is `80c3262`, copied forward as `48931e4`.

These entries summarize the code and documentation, not published releases.
Branch ancestry and copied-forward changes must be audited before the
Step 3 merge proposal; this changelog does not assert that audit is complete.
