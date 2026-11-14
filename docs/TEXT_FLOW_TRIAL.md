# Automatic text continuation

Approved after the owner's hands-on test on 14 November 2026, on
`improvements/phase-6-drafts`. It applies in both editions. No official
template, schema, workbook layout or installed program is changed.

## Try it safely

Close the earlier TEST COPY and start `START_DRAFT_CHECKS.bat` again from the
project folder. Use the isolated profile and test accounts described in
[DRAFTS.md](DRAFTS.md), with invented reports and MySQL disabled.

1. Choose Good Order or Bad Order. In Documents & Goods, type a long Declared
   Goods description. It should continue at a word boundary onto the next
   row, with the caret following it. Quantity and Packaging stay on the
   original row; continuation rows leave them blank. Existing goods below
   move together with their own Quantity/Packaging.
2. Paste a paragraph into Other Important Remarks. Try an edit near the
   start of a line, and Enter for a manual line break. Text below must stay
   intact. There are still 12 printed remark lines and 5 Declared Goods rows.
3. Repeat in Additional Details and a Bad Order Incident Report. Additional
   Details keeps its existing continuation-page behavior and 60-row limit;
   each Incident card keeps its 15-row limit.
4. Fill the last available row, then enter more text. The full input must
   stay there, with a red inline warning. Normal Save must explain the limit
   and wait for correction. Drafts still retain the entire input. Shorten the
   text or make space, and the warning should clear as you edit.
5. Wait for Draft saved, Keep as draft and restart. Restore and check every
   section. After normal Save, inspect the generated workbook/PDF on invented
   data: the description/remarks should use their ordinary printed font,
   distributed across rows.

## Behavior

One controller in `fsr_text_flow.py` handles all four sections. It reads the
templates' font sizes and column widths, using the narrowest applicable
Additional Details layout. Measurements use fixed pixel font sizes with a
padding allowance, independent of the screen zoom/DPI. Original template
bytes and the existing output styles are retained.

Typing, Backspace/Delete, paste, cut and Enter trigger local text flow. Long
words can split when necessary. Empty rows are used first; occupied rows
move down without being overwritten. The controller keeps the input intact
and warns if a section cannot hold it. Save validates the printed-line fit.
There is no repeating modal message during typing.

Existing reports and restored drafts are loaded as recorded, without being
automatically rewritten. An overlong existing line is checked at Save; edit
or split it before saving. Drafts continue to store the raw entries, including
overflow. Existing Save handling of empty rows is unchanged. Separately
entered rows are kept separate when an earlier line becomes shorter.

The implementation touches `field_survey_report.py`, `fsr_save_ui.py`, and the
new shared module/tests. `data/excel/*.xlsx` and `fsr_forms.py` are unchanged.

If anything is unexpected, record the section, typed/pasted text (invented
data only), steps, row values before/after, and a screenshot of the generated
form. Do not send passwords, password hashes or recovery codes.

## Verification

Final serial `RUN_TESTS.bat`: **1243 passed, 0 skipped**, in 1031.47 seconds
(17 minutes 11 seconds). This includes 39 new text-flow cases and all existing
draft, dropdown, save-safety and Withdrawal checks. The focused rerun also
passed the earlier isolated Tk startup check. Existing tests were retained.
Ruff and `git diff --check` passed. The owner confirmed the feature works
and approved committing it after the hands-on test.
