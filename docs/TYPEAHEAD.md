# Dropdown type-ahead

All non-date list dropdowns use `fsr_typeahead.Combobox`. The picker keeps
focus in the field and uses case-insensitive prefix matching on each edit,
including Backspace, Delete and paste. The first result is highlighted;
Up/Down change that highlight, and Enter or a click chooses it. Escape
closes the results. No match closes them without replacing editable text.
Clicking the arrow opens the full list. F4 and Alt+Down also toggle it.

The full source list is kept separate from the popup. Selection commits the
highlighted result itself, rather than resolving its row against a different
list. This fixes the Supplier case where a displayed Kokusai result could
commit ABB, the first item in the full list.

## Existing text rules

* Editable: Consignee, Supplier, Brokerage, Hauler, Location, Destination,
  Country of Origin, Activity, Incident Operation, and Item List UOM,
  Weight Unit and Currency. Existing master-name confirmation and formatting
  rules still apply. Withdrawal uses the same Item List widgets; PO-linked
  fields remain locked. Its separate PO table picker is unchanged.
* List only: Shipment Type, Container Type, Open Report search-field selector,
  Weekly Summary Month/Year, all reporting-period and warehouse/dashboard
  filter selectors, Warehouse Monitoring inventory/issue status selectors,
  Report Centre report/cargo selectors, and Settings master-list category.
  Typing in these fields builds a separate query shown above matching
  results. Backspace edits that query. The actual field value remains its
  previous choice until Enter or a click chooses a listed item. Escape,
  no match or leaving the field cannot store an unlisted value. Searching
  or moving the highlight alone does not mark the report changed.
* Dates are unchanged. Commenced/Completion Date allow typed dates in
  `dd-MMM-yyyy` and offer blank, today and the preceding seven days, refreshed
  when opened. Other date widgets retain their calendar popups.

The shared implementation is connected in `field_survey_report.py`,
`fsr_item_lists_ui.py`, `fsr_open_dialog.py`, and the warehouse UI's
`components.py`, `warehouse_page.py`, `analytics_page.py` and
`settings_page.py`. It preserves existing selection callbacks and draft
traces. It caches normalized search keys, refreshes changed sources, and
renders at most 100 popup rows at a time; keyboard/scrollbar navigation
can still reach all results.

## Short hand checks (invented data only)

Use `START_DRAFT_CHECKS.bat` and its isolated test accounts/data, as described
in [DRAFTS.md](DRAFTS.md). Choose Good Order or Bad Order to unlock the form.
Do not run these checks against real data.

1. In the test copy's Supplier master list, add `ABB PTE LTD` and
   `Kokusai Commerce Co. Ltd.` if absent. Type `Kokusai` in Supplier, then
   Enter. Expect **Kokusai Commerce Co. Ltd.**, never ABB.
2. Add invented suppliers `Sun Test`, `Super Test A` and `Super Test B`.
   Type `S`, then `u`, then `per`; press Backspace. Expect prefix-only results
   on each edit. Use Down/Up and Enter; repeat with a mouse click. Focus
   must stay in the field while typing. Repeat with Num Lock on and off;
   Down must move the highlight rather than close or reset the list.
3. Type an unmatched name, then Escape: the text stays and no unrelated
   name is selected. Click the arrow: the full list appears. Check a UOM,
   Weight Unit and Currency field in an Item List too.
4. In Shipment Type, type `Imp` and Enter: expect Import. Type an unmatched
   query and Escape: the previous valid choice stays. Check a dashboard
   filter and Weekly Summary Month in the same way. Dates must still work
   as before.
5. Type and select a supplier, edit an Item List value, and wait for
   `Draft saved`. Keep as draft, reopen the test copy and Restore. Expect
   those values; filtering and moving the highlight alone must not create
   changes on an otherwise unchanged report.

Include these with the drafts first-week checks. If a selection is wrong,
record the field, typed prefix, displayed/highlighted result, actual value,
edition/build and exact steps; a short recording helps. Do not send passwords,
password hashes or recovery codes.

## Automated verification (14 November 2026)

Final serial `RUN_TESTS.bat`: **1192 passed, 0 skipped**, in 1039.10 seconds
(17 minutes 19 seconds). This includes 27 new cases covering the shared
picker and both editions. Existing tests were retained unchanged.

Coverage includes the exact Kokusai/Enter regression, case-insensitive prefix
filtering, Backspace/Delete/paste, pending-input Enter, Up/Down, mouse choice,
Escape, no match, full-list arrow opening, fixed-list queries, PO locks,
large-list lookup and bounded popup rendering, live source refresh, callback
cleanup, draft capture/restore, and unchanged date dropdowns. The full run
also passed the existing drafts, export, save-safety and Withdrawal checks.
Ruff and `git diff --check` passed. No installer was built or installed.

### Windows arrow-key follow-up

The original modifier check treated Windows Num Lock (0x8) as Alt. This
could toggle the list on Down and block fixed-list queries while Num Lock
was enabled. The shared handler now uses Tk's platform-specific Alt mask,
ignores lock/extended flags for ordinary arrows, and recognizes keypad
arrow aliases. Added tests reproduce Windows key flags with Num Lock on
and off, extended-key combinations, fixed-list typing and real Alt+Down.

Follow-up serial `RUN_TESTS.bat`: **1204 passed, 0 skipped**, in 1359.11
seconds (22 minutes 39 seconds). The 39 focused dropdown checks passed in
both editions. Ruff and `git diff --check` also passed.
