NEW: see README.md (warehouse monitoring, Demo Mode, tests) and the docs folder.

FIELD SURVEY REPORT  (with MySQL)
=================================
START:   pip install -r requirements.txt
         run main.py   (not db_mysql.py, not test_mysql.py)

MYSQL SETUP (once)
1. MySQL Workbench > connect as root > File > Open SQL Script > field_survey_schema.sql
   > run it (lightning bolt). It creates the database field_survey, all tables, the
   login  fsr_app  with password  <your password>.   (f-s-r_app : F S R)
2. db_config.json (this folder) holds the same login. Change both if you change the password.
3. "Open Saved Report..." can open from the MySQL database (default) or the Excel file.
   In the program: "Test MySQL" checks the connection, "Sync to MySQL" copies every
   report of the Excel file into the database. Every "Save to Excel" also saves to MySQL.
   test_mysql.py does the same check from PyCharm (right-click > Run).
UI: dark dashboard (sections menu on the left, commands on the right). The three circles next to MYSQL
    show: 3 colours = MySQL works, 3 red = not working. Click them to check again.
"Restore Excel from MySQL" rebuilds a lost Excel data file from the database (adds missing reports only).
Without db_config.json the program works with Excel only.

FILES NEXT TO main.py:  First_Page.xlsx, Cargo_Details.xlsx, Incident_Report.xlsx,
master_list.json, logo.png (optional)

FEATURES
* Good / Bad Order (Bad Order adds the Incident Report tab, 15 lines per report).
* Activity drop-down: Receiving / Withdrawal.  Types of Goods tick the First Page boxes.
* ONE report workbook Report Forms\<Control #>_Report.xlsx + ONE PDF.
* Keyboard: Up/Down move between boxes, Ctrl+S Save, Ctrl+N New, Ctrl+O Open, Ctrl+P Print/PDF.
