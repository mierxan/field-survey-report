# Field Survey Report changelog

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
