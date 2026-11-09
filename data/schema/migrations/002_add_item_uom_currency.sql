-- Run ONCE in MySQL Workbench on a database created before the UOM /
-- Currency update (or use Master Lists & Settings > Upgrade MySQL tables).
-- Adds the UOM and Currency columns of the Item List.
-- Existing rows are kept; the new columns start empty (NULL).
-- Works whether or not 001_add_item_warehouse_links.sql was run.
USE field_survey;
ALTER TABLE item_lines ADD COLUMN uom      VARCHAR(30) NULL;
ALTER TABLE item_lines ADD COLUMN currency VARCHAR(3)  NULL;
