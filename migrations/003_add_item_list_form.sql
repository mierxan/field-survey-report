-- Run ONCE in MySQL Workbench on a database created before the
-- Containerized / Loading Item List forms (or use Master Lists & Settings >
-- Upgrade MySQL tables for the item_lines column).
-- Adds the Item List form of a report and the Container No. /
-- Truck Plate No. of an item line.
-- Existing rows are kept; the new columns start empty (NULL = Default form).
USE field_survey;
ALTER TABLE reports    ADD COLUMN item_form VARCHAR(20)  NULL;
ALTER TABLE item_lines ADD COLUMN unit_no   VARCHAR(100) NULL;
