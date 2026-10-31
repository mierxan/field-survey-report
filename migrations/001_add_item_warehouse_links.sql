-- Run ONCE in MySQL Workbench on a database created before the warehouse
-- monitoring update (or use Master Lists & Settings > Upgrade MySQL tables).
-- Adds the Cargo ID and Receiving Ref columns of the Item List.
-- Existing rows are kept; the new columns start empty (NULL).
USE field_survey;
ALTER TABLE item_lines ADD COLUMN cargo_id      VARCHAR(100) NULL AFTER findings;
ALTER TABLE item_lines ADD COLUMN receiving_ref VARCHAR(100) NULL AFTER cargo_id;
CREATE INDEX idx_item_cargo ON item_lines (cargo_id);
