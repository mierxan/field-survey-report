-- =====================================================================
--  FSR Phase 5.7 - item_lines shipment columns
--  TARGET DATABASE: fsr_phase5_isolated_test   (ONLY)
--
--  Adds two OPTIONAL, NULLable columns to item_lines:
--      packing_list_no  VARCHAR(120) NULL   -- Packing List No. (shipment import)
--      origin_line      VARCHAR(120) NULL   -- Origin Line (shipment import)
--
--  These columns are expected by db_mysql.LINK_COLUMNS; they were missing from
--  the generated isolated schema (fixed in the base schema in Phase 5.6).
--
--  IDEMPOTENT: each column is added ONLY if it is not already present
--  (information_schema check). Safe to run again. No DROP / TRUNCATE / DELETE,
--  no table or database recreation, no other table touched.
--
--  All statements are FULLY QUALIFIED to `fsr_phase5_isolated_test`, so they
--  cannot affect `field_survey` (production) or `field_survey_test` (existing).
--  DO NOT run this against, or while relying on, either protected database.
--
--  Run in MySQL Workbench while connected to fsr_phase5_isolated_test.
-- =====================================================================

-- Confirm the connection (should print fsr_phase5_isolated_test):
SELECT DATABASE() AS current_database;

-- ---------------------------------------------------------------------
-- packing_list_no  (VARCHAR(120) NULL)
-- ---------------------------------------------------------------------
SET @col := 'packing_list_no';
SET @ddl := (SELECT IF(
    (SELECT COUNT(*) FROM information_schema.columns
      WHERE table_schema = 'fsr_phase5_isolated_test'
        AND table_name = 'item_lines'
        AND column_name = @col) = 0,
    'ALTER TABLE `fsr_phase5_isolated_test`.`item_lines` '
      'ADD COLUMN `packing_list_no` VARCHAR(120) NULL',
    'SELECT ''packing_list_no already exists'' AS note'));
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------
-- origin_line  (VARCHAR(120) NULL)
-- ---------------------------------------------------------------------
SET @col := 'origin_line';
SET @ddl := (SELECT IF(
    (SELECT COUNT(*) FROM information_schema.columns
      WHERE table_schema = 'fsr_phase5_isolated_test'
        AND table_name = 'item_lines'
        AND column_name = @col) = 0,
    'ALTER TABLE `fsr_phase5_isolated_test`.`item_lines` '
      'ADD COLUMN `origin_line` VARCHAR(120) NULL',
    'SELECT ''origin_line already exists'' AS note'));
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------
-- Verify: both columns now exist, VARCHAR(120), NULLable.
-- Expected: two rows (packing_list_no, origin_line), each VARCHAR(120)/YES.
-- ---------------------------------------------------------------------
SELECT column_name, column_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'fsr_phase5_isolated_test'
   AND table_name = 'item_lines'
   AND column_name IN ('packing_list_no', 'origin_line')
 ORDER BY column_name;

-- =====================================================================
-- NOTE (if you prefer a plain ALTER instead of the idempotent form above):
-- MySQL 8.0 has no "ADD COLUMN IF NOT EXISTS", so an unconditional
--   ALTER TABLE `fsr_phase5_isolated_test`.`item_lines`
--       ADD COLUMN `packing_list_no` VARCHAR(120) NULL,
--       ADD COLUMN `origin_line`     VARCHAR(120) NULL;
-- will ERROR (duplicate column) if either column already exists.
-- If you use the plain form, FIRST run the SELECT above (or the check below)
-- and include only the columns that are actually missing:
--   SELECT column_name FROM information_schema.columns
--    WHERE table_schema='fsr_phase5_isolated_test'
--      AND table_name='item_lines'
--      AND column_name IN ('packing_list_no','origin_line');
-- =====================================================================