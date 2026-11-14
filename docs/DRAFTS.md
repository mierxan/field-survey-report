# Drafts and unfinished work (Phase 6)

Unreleased: both Owner and User editions. Drafts preserve unfinished input;
they do not create reports. No MySQL schema, workbook layout or official
OPSF-068 v4.0 template is changed.

## Normal use

- After edits, a checkpoint is queued after 3 seconds without typing, or by
  30 seconds during continuous editing. A worker performs JSON serialization,
  flushing and atomic replacement. Tk widget access stays on the UI thread.
- A small status label says `Draft saved HH:MM:SS` after a completed write.
  Successful autosaves never open notices. A failed write shows a warning
  once until a subsequent successful checkpoint; the previous valid draft
  is preserved and retries continue. A draft failure does not prevent normal
  report Save.
- New Report, Open Saved Report, Change Excel File, Sign Out and Close ask
  **Save / Keep as draft / Discard / Cancel only when there are unsaved
  changes**. An unchanged form proceeds without that question.
- Keep as draft waits for the latest checkpoint before leaving. Discard
  cancels older pending writes before deleting the draft. Cancel stays put.
- Normal Save retires the draft once its data is safely committed/recoverable.
  MySQL or derived Excel work may still be pending in the existing save record.
  Failed validation or an unsuccessful report write keeps the draft.

## What is preserved

Raw text, including incomplete dates/quantities and spaces; every General,
Schedule, Transport, Documents, Declared Goods, remarks and findings field;
checkboxes and their free text; dynamic rows and blanks; all three Item List
forms, including inactive forms; incident headers/lines and manual-header
flags; Bad Order details; and Withdrawal PO links, line IDs and a quantity
still being edited. Restore does not validate or silently normalize this
input. Normal Save still performs the existing validation and stock checks.

## Location and account isolation

Installed normal profiles use:

    %LOCALAPPDATA%\FieldSurveyReport\Drafts\

Each draft is one versioned JSON file identified by an account scope and a
random draft ID. An integrity checksum also detects content damage that still
looks like valid JSON. It contains report input, not passwords, password hashes,
MySQL credentials or recovery codes. It reserves no Control #. A new report
gets a currently available number only through the normal report workflow.
Drafts never enter MySQL, Excel exports, dashboards, search or Master Data.

Signed-in users see only their own drafts. Newly created accounts receive a
random, signed `draft_identity` field in their existing account record; the
account-file version and authentication rules stay unchanged. Existing
accounts keep a stable legacy identity. Deleting and recreating an account
with the same details does not grant access to its previous drafts.

The Owner or Administrator can see drafts of removed accounts, labelled
**Removed account — discard only**. Restore is disabled for those drafts.
Drafts still open in another running process cannot be taken over or deleted;
process creation time avoids mistaking a reused process ID for the old session.

Demo drafts use a separate `Drafts\Demo` folder. `FSR_HOME` puts every draft in
`<sandbox>\LocalAppData\FieldSurveyReport\Drafts`; automated tests also have a
throwaway `FSR_DRAFT_DIR`. No test uses the real Local AppData draft folder.
Normal storage is refused if Local AppData is synchronized or on a network
path; there is no fallback into Documents. The program reports unavailable
draft storage instead of crashing.

## Recovery and conflicts

After sign-in and startup database/save-record recovery, **Unfinished work
found** lists the account's drafts by Control # or New report, SO number and
last change time. Choose Restore, Discard or Later. Account > Unfinished
work... opens the list again. Drafts older than 30 days are flagged for review,
not deleted silently. Unreadable or malformed drafts are preserved under
`Drafts\Damaged` with a notice; they never crash startup.

A draft remembers which workbook it belongs to. Select that workbook before
restoring it; the program will not silently switch report stores. Restoration
only fills the form and leaves it unsaved.

For an existing report, compare the saved version with the draft's baseline
and show field differences before restoring. Check again before Save. SQLite
checks the expected timestamp and database revision inside the transaction;
workbook mode checks its version under a shared writer mutex and again before
replacement. If it changed meanwhile, nothing is overwritten and the draft
remains. MySQL differences or an unavailable MySQL check are explicitly shown;
the existing ownership guard still controls every normal MySQL write.

## Drafts versus the save record

Autosave never opens or replays a save record. Only an explicit report Save
links a draft ID/revision to the existing save journal. The journal retains
its existing report/side-file/MySQL repair responsibilities. Startup repairs
those explicit saves before offering drafts. A locally completed save can
retire its draft while MySQL remains queued. Retirement cannot remove a newer
draft revision, and a failed report write cannot retire the draft.

## Unexpected termination and Windows shutdown

Atomic replacement keeps the previous complete checkpoint until the next
one is flushed and ready. A killed process or power cut can recover the last
completed checkpoint, not keystrokes entered afterward.

Windows session-query handling queues a checkpoint promptly. If Windows
confirms session end/logoff, the app attempts a bounded final local flush,
without a question, report Save, export or network operation. Forced shutdown
may still prevent that final write. The callback-error handler also attempts
a checkpoint where possible. This follows Microsoft's guidance for
[WM_QUERYENDSESSION](https://learn.microsoft.com/en-us/windows/win32/shutdown/wm-queryendsession)
and [WM_ENDSESSION](https://learn.microsoft.com/en-us/windows/win32/shutdown/wm-endsession).

## Five short hand checks — invented data only

Use `START_DRAFT_CHECKS.bat` in the project folder. This starts a User-edition
**TEST COPY** with a separate profile at `D:\FSR_Drafts_HandChecks_2026-11-14`.
It does not use the installed program, Documents data, real accounts, real
Local AppData databases, or MySQL. Accounts and recovery information persist
inside this sandbox across restarts. Do not enable MySQL or change its Excel
file to a real workbook. Both editions are covered by automated process tests.

On the first start, Set Up This PC creates a test Administrator. Use initials
`TCA`, email `draft-admin@example.invalid` and a test-only password you choose
in the dialog. Do not reuse your real Owner password. Keep the sandbox's
recovery code privately if you want to retain this profile.

1. **Unexpected close:** Type a new report with SO `DRAFT-HANDCHECK`, leave a
   quantity partly typed, and wait for `Draft saved`. In Task Manager end only
   this TEST COPY's process. Relaunch the batch, sign in and Restore. Expect
   the typed work, still unsaved, and no saved report created by autosave.
2. **All sections and PO lines:** On invented Receiving/Withdrawal reports,
   edit incidents, remarks and each Item List form, including a linked
   Withdrawal quantity. Keep as draft, restart and restore. Expect every
   section and PO link; normal Save must still validate the quantity.
3. **Choices and normal Save:** On an unchanged form start another report:
   no question. Make an edit; try Cancel, Keep as draft and Later. Reopen
   Account > Unfinished work. Restore and save normally: the draft disappears.
   Successful autosaves must show only the small status text.
4. **Second account and cleanup:** Sign out of `TCA`. From Sign In choose
   Create Account and register initials `TDR`, email `draft-user@example.invalid`,
   using another test-only password you choose. Sign in as `TCA`, Account >
   Manage Users, select `TDR` and Approve. Sign out, sign in as `TDR`, type SO
   `SECOND-ACCOUNT-DRAFT` and Keep as draft on sign-out. Sign in as `TCA`:
   the active user's draft must not appear. In Manage Users delete **only
   `TDR`**, then Account > Unfinished work: its draft is now listed as a
   removed-account draft, with Restore disabled. Discard that test draft.
   This removes the extra account and its unfinished work without changing
   any real accounts. Keep `TCA` if repeating the sandbox checks.
5. **Conflict and damaged file:** On invented data, make a draft of an
   existing report, keep it and change/save that report from another test
   session. Restore the draft: expect the differences and a choice, with no
   automatic overwrite. Separately, close all sandbox windows and damage one
   sandbox `.draft.json` file. Restart: expect a notice and its preserved copy
   under Damaged. Never do this corruption check on real work.

Use these five checks in the first-week release checklist. Record the check
number, time, edition/build, Control # or SO, exact message and relevant log.
Never send passwords, password hashes or recovery codes. If a recovery result
is unexpected, preserve the files and pause wider rollout.


## Automated verification (14 November 2026)

Final serial `RUN_TESTS.bat`: **1165 passed, 0 skipped**, in 1205.40 seconds
(20 minutes 5 seconds). This includes 51 additional test cases over the
1114-test Phase 5 baseline. Existing automated cases were retained.

Coverage includes idle/deadline scheduling; raw sections and inactive forms;
PO links and an uncommitted quantity; quiet success and failure notices;
unchanged navigation without a question; removed/recreated account isolation;
orphan discard-only UI; malformed and valid-JSON corruption; age review;
normal-save and save-journal interruption boundaries; stale-save rejection in
both stores; automatic renumbering; no report-number/MySQL/export side effects;
and no Discard resurrection while close waits. Disposable GUI processes were
abruptly killed and recovered in fresh processes in both editions. Windows
session-end messages were simulated on only the test window; no actual
Windows shutdown/logoff was performed.

Ruff and `git diff --check` passed. No MySQL schema, official template or
workbook layout was changed. No installer was built or installed.
