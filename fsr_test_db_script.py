"""Makes data/schema/field_survey_test_schema.sql from the real schema.

The test script creates the database field_survey_test with exactly the
tables of the real one and gives the login 'fsr_test' rights on that
database ONLY. It contains no password and creates no login: the login is
made in MySQL Workbench first, with a password of your own.

  python fsr_test_db_script.py            rewrites the test script
  python fsr_test_db_script.py --isolated rewrites the Phase 5 isolated script

tests/test_test_copy.py checks that the script on disk is what this makes,
so the test database can never fall behind the real schema unnoticed.
"""
import argparse
import re
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent / "data" / "schema"
SOURCE = SCHEMA / "field_survey_schema.sql"
TARGET = SCHEMA / "field_survey_test_schema.sql"

TEST_DATABASE = "field_survey_test"
TEST_LOGIN = "fsr_test"

# Phase 5.2: the dedicated, disposable integration-test database.
ISOLATED_DATABASE = "fsr_phase5_isolated_test"
ISOLATED_LOGIN = "fsr_phase5"
ISOLATED_TARGET = SCHEMA / "fsr_phase5_isolated_test_schema.sql"


def header(database, login):
    return f"""-- =====================================================================
--  FIELD SURVEY REPORT  -  TEST database (made from field_survey_schema.sql
--  by fsr_test_db_script.py - do not edit by hand)
--
--  For the copy of the program that runs from the project folder. It is a
--  separate database: nothing here can touch the real one, `field_survey`.
--
--  BEFORE running this script, as root in MySQL Workbench:
--    Server > Users and Privileges > Add Account
--      Login Name:              {login}
--      Limit to Hosts Matching: localhost
--      Password:                one of your own (not the fsr_app password)
--    > Apply
--  This script contains no password and does not create the login.
--
--  Then: File > Open SQL Script... > this file > lightning bolt.
--  Safe to run again: existing tables and data are kept.
-- =====================================================================
"""


def login_section(database, login):
    return f"""-- ---------------------------------------------------------------------
-- 8. TEST LOGIN  (rights on the TEST database only)
--    Fails with "You are not allowed to create a user with GRANT" if the
--    login {login} was not made in Workbench first - see the top.
-- ---------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON {database}.* TO '{login}'@'localhost';
FLUSH PRIVILEGES;

-- CHECK 1: the login's rights. There must be exactly two lines:
--   GRANT USAGE ON *.* TO `{login}`@`localhost`
--   GRANT SELECT, INSERT, UPDATE, DELETE ON `{database}`.* TO `{login}`@`localhost`
-- No line may name `field_survey` (without _test), and none may say ALL.
SHOW GRANTS FOR '{login}'@'localhost';
"""


def build_for(schema_text, database, login):
    text = schema_text.replace("\r\n", "\n")
    # the real script's own header
    start = text.index("CREATE DATABASE")
    text = text[start:]
    # every mention of the database -> the target database
    text = re.sub(r"\bfield_survey\b(?!_)", database, text)
    # the commented "create fsr_app" advice -> the real grant for the test
    # login (no password anywhere)
    begin = text.index("-- ---------------------------------------------------------------------\n-- 8. APP LOGIN")
    end = text.index("-- Quick check:")
    text = text[:begin] + login_section(database, login) + "\n" + text[end:]
    text = text.replace("-- Quick check:", "-- CHECK 2:")
    return header(database, login) + "\n" + text


def build(schema_text):
    return build_for(schema_text, TEST_DATABASE, TEST_LOGIN)


def build_isolated(schema_text=None):
    if schema_text is None:
        schema_text = SOURCE.read_text(encoding="utf-8")
    return build_for(schema_text, ISOLATED_DATABASE, ISOLATED_LOGIN)


def main():
    parser = argparse.ArgumentParser(description="Generate FSR test schemas.")
    parser.add_argument("--isolated", action="store_true",
                        help=f"write the {ISOLATED_DATABASE} schema instead")
    args = parser.parse_args()
    if args.isolated:
        ISOLATED_TARGET.write_text(build_isolated(), encoding="utf-8",
                                   newline="\n")
        print(f"written: {ISOLATED_TARGET}")
    else:
        TARGET.write_text(build(SOURCE.read_text(encoding="utf-8")),
                          encoding="utf-8", newline="\n")
        print(f"written: {TARGET}")


if __name__ == "__main__":
    main()
