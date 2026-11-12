"""Makes data/schema/field_survey_test_schema.sql from the real schema.

The test script creates the database field_survey_test with exactly the
tables of the real one and gives the login 'fsr_test' rights on that
database ONLY. It contains no password and creates no login: the login is
made in MySQL Workbench first, with a password of your own.

  python fsr_test_db_script.py        rewrites the test script

tests/test_test_copy.py checks that the script on disk is what this makes,
so the test database can never fall behind the real schema unnoticed.
"""
import re
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent / "data" / "schema"
SOURCE = SCHEMA / "field_survey_schema.sql"
TARGET = SCHEMA / "field_survey_test_schema.sql"
TEST_DATABASE = "field_survey_test"
TEST_LOGIN = "fsr_test"

HEADER = f"""-- =====================================================================
--  FIELD SURVEY REPORT  -  TEST database (made from field_survey_schema.sql
--  by fsr_test_db_script.py - do not edit by hand)
--
--  For the copy of the program that runs from the project folder. It is a
--  separate database: nothing here can touch the real one, `field_survey`.
--
--  BEFORE running this script, as root in MySQL Workbench:
--    Server > Users and Privileges > Add Account
--      Login Name:              {TEST_LOGIN}
--      Limit to Hosts Matching: localhost
--      Password:                one of your own (not the fsr_app password)
--    > Apply
--  This script contains no password and does not create the login.
--
--  Then: File > Open SQL Script... > this file > lightning bolt.
--  Safe to run again: existing tables and data are kept.
-- =====================================================================
"""

LOGIN_SECTION = f"""-- ---------------------------------------------------------------------
-- 8. TEST LOGIN  (rights on the TEST database only)
--    Fails with "You are not allowed to create a user with GRANT" if the
--    login {TEST_LOGIN} was not made in Workbench first - see the top.
-- ---------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON {TEST_DATABASE}.* TO '{TEST_LOGIN}'@'localhost';
FLUSH PRIVILEGES;

-- CHECK 1: the login's rights. There must be exactly two lines:
--   GRANT USAGE ON *.* TO `{TEST_LOGIN}`@`localhost`
--   GRANT SELECT, INSERT, UPDATE, DELETE ON `{TEST_DATABASE}`.* TO `{TEST_LOGIN}`@`localhost`
-- No line may name `field_survey` (without _test), and none may say ALL.
SHOW GRANTS FOR '{TEST_LOGIN}'@'localhost';
"""


def build(schema_text):
    text = schema_text.replace("\r\n", "\n")
    # the real script's own header
    start = text.index("CREATE DATABASE")
    text = text[start:]
    # every mention of the database -> the test database
    text = re.sub(r"\bfield_survey\b(?!_)", TEST_DATABASE, text)
    # the commented "create fsr_app" advice -> the real grant for the test
    # login (no password anywhere)
    begin = text.index("-- ---------------------------------------------------------------------\n-- 8. APP LOGIN")
    end = text.index("-- Quick check:")
    text = text[:begin] + LOGIN_SECTION + "\n" + text[end:]
    text = text.replace("-- Quick check:", "-- CHECK 2:")
    return HEADER + "\n" + text


def main():
    TARGET.write_text(build(SOURCE.read_text(encoding="utf-8")),
                      encoding="utf-8", newline="\n")
    print(f"written: {TARGET}")


if __name__ == "__main__":
    main()
