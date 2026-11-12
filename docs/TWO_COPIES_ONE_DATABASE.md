# Several copies of the program, one MySQL database

Why this exists, what the program does now, and how to set up a test copy.
Code: `fsr_mysql_guard.py`, `fsr_renumber.py`, `fsr_save_journal.py`,
`db_mysql.py`, `fsr_test_db_script.py`.

## The problem (found 11 November 2026)

Every copy of the program has its own Excel workbook, but MySQL is one
database, and MySQL knows a report only by its Control #. A second copy
with an empty workbook numbers its first report `…-0001` again. Saving it
used to replace the real `…-0001` in MySQL without a word. So did the
MySQL catch-up, Import Master Data and Sync to MySQL.

## The rule

A copy of the program never overwrites a MySQL report it does not own.
Before every write to MySQL - Save, the catch-up after MySQL was away,
Import Master Data, Sync to MySQL:

| MySQL holds under this Control # | What happens |
|---|---|
| nothing | The report is written. |
| a report equal in value to mine | Nothing is written; from now on it counts as mine. |
| the report THIS copy wrote last, unchanged since | It is updated. |
| anything else | **Conflict: nothing is written.** Both versions are shown and you decide. |

A conflict never holds up work on the PC: the report is saved in the Excel
file as usual, the note says that MySQL was **not** updated and why, and the
conflict waits under **Account > MySQL Conflicts** (the menu shows how many
wait).

### The three decisions

| Button | What it does |
|---|---|
| **Keep MySQL's (write nothing)** - the default button; Enter does the same | Nothing is written to MySQL. The conflict is closed. Your report stays in your Excel file. |
| **Replace MySQL's with mine...** | Asks once more (the default answer is No). The report that is in MySQL is first kept as a file, then replaced. |
| **Save mine under the next free number...** (when MySQL's report is someone else's) | Asks once more (default No). Your report gets the next number that is free on this PC **and** in MySQL - in the Excel file, the Withdrawal workbook, its incident and item-form files, PO_Master and Withdrawn_Item, the import record and the Bad Order status - and is sent to MySQL under that number. MySQL's report is not touched. Forms already printed keep the old number: print again. |

Closing the window with Close, Esc or the X changes nothing; the conflict
keeps waiting. Nothing is ever deleted from MySQL by any of this.

### "Equal in value"

Two reports are equal when they differ only in how values are shown:

* numbers in quantity and price fields: `0.00` = `0`, `1,250` = `1250.0`
* spaces at the start or end
* an empty field = a missing field; an empty list = no list
* Item List form `Default` = not stated
* the save times, and things MySQL does not store at all (the lines of the
  other Item List forms, notes about unreadable files)

**Not** ignored, because they are real differences: letter case, leading
zeros in document numbers (`0282050` is not `282050`), the order and number
of lines, any text.

### How the program knows what is "mine"

Beside the workbook's JSON data it keeps
`<workbook name>_mysql_ledger.json`: for every report this copy put into
MySQL, a fingerprint of the report as MySQL held it right afterwards. If
MySQL's report still has that fingerprint, nobody else changed it.

* **First start with existing data** (your 10 reports): every report that is
  the same in the Excel file and in MySQL is adopted silently. The same
  happens to reports brought in with Restore Excel from MySQL.
* **Ledger missing, unreadable, or older than the workbook** (a restored
  backup, a workbook edited outside the program): the ledger counts as
  empty. Every report is "not mine" and is asked about - except those that
  are equal in value, which are adopted again. It never falls back to
  overwriting.
* **Two copies at the same moment**: the check and the write are done under
  a MySQL lock on that Control # and in one transaction. The second copy
  waits, then sees the first copy's report and gets a conflict.

### Control numbers

* A new report gets a number that is free in this PC's workbooks **and** in
  MySQL, as far as MySQL was seen ("Server active").
* When Save is clicked on a new report, MySQL is asked again; if another
  copy used the number in the meantime, the report takes the next free one
  before anything is written.
* With MySQL away the number comes from the workbook only. A clash is then
  found when MySQL is back, and you choose (see the three decisions).

### Sync to MySQL and Restore Excel from MySQL

* **Sync to MySQL** first shows: new in MySQL / mine to update / already the
  same / different in MySQL. The different ones are listed **unticked** and
  are not sent unless ticked; ticking asks once more and keeps the replaced
  versions. An empty workbook sends nothing.
* **Restore Excel from MySQL** asks, then adds to the Excel file the reports
  it does not have. It changes nothing in MySQL and never overwrites a
  report already in the Excel file.

## What was replaced, and putting it back

Before a MySQL report is replaced on your decision, it is saved in

    Documents\Field Survey Report\json\MySQL Replaced\
        <Control #>_<date>_<time>.json      the whole replaced report
        replaced_log.csv                    one line per replacement

`replaced_log.csv` records when, which Control #, who (the signed-in
user), which computer, which copy (its workbook path and copy id), why, and
the name of the kept file. The same line goes into the program log. If the
file cannot be written, nothing is replaced.

**Put one back:** Account > MySQL Conflicts > "Put back a replaced
report...", choose the file, confirm. The report MySQL holds under that
number at that moment is kept first, in the same folder.

## Limits

* The guard protects against copies that **have** it. The installed
  11 November program does not; see the end of this page.
* The MySQL parts (the lock, the check inside the transaction) were tested
  with a stand-in database, not against a real MySQL server. The hand checks
  below are their first real run.
* "Keep MySQL's" leaves your Excel file and MySQL different for that
  report. Editing it again later asks again.
* Renumbering changes several files one after another. If the PC stops in
  between, finish by choosing the same decision again.
* A workbook changed outside the program (opened and saved in Excel, a
  restored backup) makes the ledger out of date: the next changes to
  reports that differ from MySQL are asked about once.
* The first start on a large workbook compares every report with MySQL
  once.

## Later option, not built: a column that records the writer

Stricter and simpler to reason about: add a column to `reports`, for
example `written_by_copy VARCHAR(40)`, set on every write to the id of the
copy that wrote it.

* "Mine" would then be a fact stored in MySQL, not a comparison with a
  local file: no ledger to lose, and every PC could see which copy owns a
  report.
* It is a schema change: a migration script, the upgrade step with an admin
  login, and the same column in the test database. Rows written before it
  would have no owner and would need the adoption step once.
* It fits best together with the storage change proposed for Phase 3, where
  the question of several PCs writing to one database is looked at as a
  whole.

## The test copy

A program started from the project folder (START_FSR.bat, PyCharm) is a
**test copy**:

* Its title bar starts with `TEST COPY`.
* It does not connect to a database named `field_survey`. MySQL Settings >
  Test Connection then says: "TEST COPY: this copy of the program runs from
  the source folder and will not connect to the real database", and the
  status stays "Server inactive".
* The only way round is `"allow_real_database": true` in its
  `db_config.json`, typed by hand; the title bar then says
  `TEST COPY (REAL DATABASE)`. Saving from MySQL Settings removes it again.
* The installed program is not affected in any way.

### Create the test database (once)

1. MySQL Workbench, connect as `root`.
2. Server > Users and Privileges > **Add Account**: Login Name `fsr_test`,
   Limit to Hosts Matching `localhost`, a password of your own (not the
   `fsr_app` one) > **Apply**.
3. File > Open SQL Script... >
   `D:\Build Build Build\PythonProject\data\schema\field_survey_test_schema.sql`
   > the lightning bolt. The script holds no password and creates no login.
4. Look at the result tab of `SHOW GRANTS` (CHECK 1). It must show exactly:

       GRANT USAGE ON *.* TO `fsr_test`@`localhost`
       GRANT SELECT, INSERT, UPDATE, DELETE ON `field_survey_test`.* TO `fsr_test`@`localhost`

   No line names `field_survey` without `_test`, and none says `ALL`.
5. Proof that the login cannot reach the real data: in Workbench make a new
   connection with user `fsr_test`, open it and run

       SELECT COUNT(*) FROM field_survey.reports;

   It must fail with "SELECT command denied to user 'fsr_test'". Then
   `SELECT COUNT(*) FROM field_survey_test.reports;` must answer `0`.
6. In the project-folder copy: Account > MySQL Settings > tick "Use MySQL",
   User `fsr_test`, its password, Database `field_survey_test` > Test
   Connection ("Connected. The database has 0 report(s).") > Save. The
   status turns to "Server active" at once.

If the real schema changes later, run `python fsr_test_db_script.py` and the
script again; a test fails if the two scripts are out of step.

## The installed 11 November program

It has neither Phase 2 nor this fix. Until a new build is installed:

* It writes to MySQL without the check. That is safe **as long as it is the
  only program writing to `field_survey`** - which it is, now that the test
  copy refuses that database.
* Do not install or run a second Owner program against the same database
  (another PC, another Windows login).
* "Sync to MySQL" there overwrites every same-numbered report in MySQL after
  one general question. Use it only with your real workbook open - never
  after "Change Excel File" to another workbook.
* It has no daily backup: copy `Field_Survey_Reports.xlsx` by hand before
  anything risky.
* A save that says "saved to Excel, but NOT to MySQL" is not sent later by
  itself: click Save again or use Sync to MySQL.
* If a save is cut off (power, a file open in Excel), nothing finishes it:
  open the report and save it again.
* Control #s that differ only in letter case are still treated as different
  reports by its import.

When the new build is installed, its first start adopts your 10 reports
(they are the same in the Excel file and in MySQL) without a question.
