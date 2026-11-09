-- =====================================================================
--  FIELD SURVEY REPORT - schema v2 (PROPOSED, not applied anywhere yet)
--  SUPERSEDED: do not apply this earlier draft. Use
--  field_survey_schema_v2_proposed.sql, which removes centralized accounts
--  and includes the corrections in the current schema review.
--  MySQL 8.0 (verified on 8.0.46). Run as an admin account.
--  Creates a NEW database, field_survey_v2. The current database
--  field_survey is not touched. Safe to run again.
--
--  Conventions
--    NULL      = the box was left blank on the form.
--    Text such as 'n/a' or '0' is the user's own entry and is kept as typed.
--    Quantity, prices, dimensions and weights are text because the form
--    accepts entries such as "n/a" and "1,250 KG"; the warehouse code parses
--    them when it needs numbers.
--    Foreign keys use RESTRICT: nothing is removed by a cascade.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS field_survey_v2
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE field_survey_v2;

-- ---------------------------------------------------------------------
-- 1. ACCOUNTS (users.json). Referenced by created_by / modified_by.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_users (
    user_id        INT UNSIGNED NOT NULL AUTO_INCREMENT,
    first_name     VARCHAR(100) NOT NULL,
    middle_name    VARCHAR(100) NULL,
    last_name      VARCHAR(100) NOT NULL,
    initials       VARCHAR(6)   NOT NULL,
    email          VARCHAR(254) NOT NULL,
    password_salt  VARCHAR(128) NOT NULL,
    password_hash  VARCHAR(128) NOT NULL,
    role           VARCHAR(10)  NOT NULL DEFAULT 'user',
    status         VARCHAR(10)  NOT NULL DEFAULT 'pending',
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                   ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id),
    UNIQUE KEY uq_user_email (email),
    UNIQUE KEY uq_user_initials (initials),
    CONSTRAINT chk_user_role CHECK (role IN ('owner', 'user')),
    CONSTRAINT chk_user_status CHECK (status IN
        ('pending', 'approved', 'rejected', 'disabled')),
    CONSTRAINT chk_user_initials CHECK (REGEXP_LIKE(initials, '^[A-Z0-9]{2,6}$', 'c'))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 2. MASTER LISTS (master_list.json)
--    Removing a name only hides it (is_active = 0); saved reports keep it.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS master_lists (
    list_key   VARCHAR(40)  NOT NULL,      -- key in master_list.json
    title      VARCHAR(60)  NOT NULL,      -- Master Lists page
    PRIMARY KEY (list_key)
) ENGINE=InnoDB;

INSERT IGNORE INTO master_lists (list_key, title) VALUES
 ('consignee_list', 'Consignees'),
 ('supplier_list', 'Suppliers'),
 ('broker_list', 'Brokerages'),
 ('hauler_list', 'Haulers'),
 ('location_list', 'Locations / Warehouses'),
 ('destination_list', 'Destinations'),
 ('country_of_origin_list', 'Countries of Origin');

CREATE TABLE IF NOT EXISTS master_list_items (
    item_id    INT UNSIGNED NOT NULL AUTO_INCREMENT,
    list_key   VARCHAR(40)  NOT NULL,
    item_name  VARCHAR(200) NOT NULL,
    is_active  TINYINT(1)   NOT NULL DEFAULT 1,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
               ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (item_id),
    -- the collation ignores case, like the program's duplicate check
    UNIQUE KEY uq_master_item (list_key, item_name),
    CONSTRAINT fk_master_item_list FOREIGN KEY (list_key)
        REFERENCES master_lists (list_key)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 3. CONTROL NUMBERS. FSR-YYYYMM-#### from one locked counter row, in the
--    same transaction as the report, so two PCs can never get one number.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS control_number_counters (
    prefix     VARCHAR(10) NOT NULL,       -- FSR
    period     CHAR(6)     NOT NULL,       -- YYYYMM
    last_number INT UNSIGNED NOT NULL,
    PRIMARY KEY (prefix, period),
    CONSTRAINT chk_counter_period CHECK (REGEXP_LIKE(period, '^[0-9]{4}(0[1-9]|1[0-2])$'))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 4. REPORTS. One row per report.
--    Names are saved exactly as printed. The *_item_id columns link to the
--    master list when the name is in it; they stay NULL for a name the user
--    declined to add, which the form allows.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    report_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    -- Not format-checked: FSR-YYYYMM-####, FSR-YYYY-####, OLD-YYMM-XXXXXX
    control_no           VARCHAR(30)  NOT NULL,
    so_number            VARCHAR(100) NOT NULL,
    inspection_date      DATE         NOT NULL,
    consignee            VARCHAR(200) NULL,
    supplier             VARCHAR(200) NULL,
    brokerage            VARCHAR(200) NULL,
    hauler               VARCHAR(200) NULL,
    location             VARCHAR(200) NULL,
    destination          VARCHAR(200) NULL,
    country_of_origin    VARCHAR(100) NULL,
    consignee_item_id    INT UNSIGNED NULL,
    supplier_item_id     INT UNSIGNED NULL,
    brokerage_item_id    INT UNSIGNED NULL,
    hauler_item_id       INT UNSIGNED NULL,
    location_item_id     INT UNSIGNED NULL,
    destination_item_id  INT UNSIGNED NULL,
    country_item_id      INT UNSIGNED NULL,
    activity             VARCHAR(50)  NULL,   -- typeable drop-down: no fixed list
    commenced_date       DATE         NULL,
    commenced_time       CHAR(5)      NULL,   -- 0800H; 2400H is valid, so not TIME
    completion_date      DATE         NULL,
    completion_time      CHAR(5)      NULL,
    shipment_type        VARCHAR(20)  NULL,
    container_type       VARCHAR(30)  NULL,
    vessel_carrier       VARCHAR(200) NULL,
    vehicle_type         VARCHAR(100) NULL,
    vehicle_plate_number VARCHAR(50)  NULL,
    invoice_number       VARCHAR(100) NULL,
    po_number            VARCHAR(100) NULL,
    jo_number            VARCHAR(100) NULL,
    gatepass_number      VARCHAR(100) NULL,
    bl_awb_number        VARCHAR(100) NULL,
    dr_number            VARCHAR(100) NULL,
    other_documents      VARCHAR(255) NULL,
    cargo_condition      VARCHAR(10)  NOT NULL,
    item_form            VARCHAR(20)  NOT NULL DEFAULT 'Default',
    goods_new              TINYINT(1) NOT NULL DEFAULT 0,
    goods_used             TINYINT(1) NOT NULL DEFAULT 0,
    goods_food_stuffs      TINYINT(1) NOT NULL DEFAULT 0,
    goods_vehicle          TINYINT(1) NOT NULL DEFAULT 0,
    goods_pharma_chemicals TINYINT(1) NOT NULL DEFAULT 0,
    goods_others           TINYINT(1) NOT NULL DEFAULT 0,
    goods_others_text    VARCHAR(255) NULL,
    row_version          INT UNSIGNED NOT NULL DEFAULT 1,  -- stops lost updates
    created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_saved           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                         ON UPDATE CURRENT_TIMESTAMP,
    created_by_user_id   INT UNSIGNED NULL,
    modified_by_user_id  INT UNSIGNED NULL,
    deleted_at           DATETIME     NULL,   -- soft delete
    deleted_by_user_id   INT UNSIGNED NULL,
    PRIMARY KEY (report_id),
    UNIQUE KEY uq_report_control (control_no),
    KEY idx_report_date (inspection_date),
    KEY idx_report_so (so_number),            -- not unique: real SOs repeat
    KEY idx_report_consignee (consignee),
    KEY idx_report_supplier (supplier),
    KEY idx_report_location (location),
    KEY idx_report_activity_date (activity, inspection_date),
    KEY idx_report_condition (cargo_condition),
    KEY idx_report_po (po_number),
    KEY idx_report_bl (bl_awb_number),
    KEY idx_report_dr (dr_number),
    KEY idx_report_gatepass (gatepass_number),
    KEY idx_report_deleted (deleted_at),
    CONSTRAINT chk_report_condition CHECK (cargo_condition IN ('Good Order', 'Bad Order')),
    CONSTRAINT chk_report_form CHECK (item_form IN ('Default', 'Containerized', 'Loading')),
    CONSTRAINT chk_report_commenced CHECK (commenced_time IS NULL OR
        REGEXP_LIKE(commenced_time, '^([01][0-9][0-5][0-9]|2[0-3][0-5][0-9]|2400)H$', 'c')),
    CONSTRAINT chk_report_completion CHECK (completion_time IS NULL OR
        REGEXP_LIKE(completion_time, '^([01][0-9][0-5][0-9]|2[0-3][0-5][0-9]|2400)H$', 'c')),
    CONSTRAINT fk_report_consignee FOREIGN KEY (consignee_item_id) REFERENCES master_list_items (item_id),
    CONSTRAINT fk_report_supplier FOREIGN KEY (supplier_item_id) REFERENCES master_list_items (item_id),
    CONSTRAINT fk_report_brokerage FOREIGN KEY (brokerage_item_id) REFERENCES master_list_items (item_id),
    CONSTRAINT fk_report_hauler FOREIGN KEY (hauler_item_id) REFERENCES master_list_items (item_id),
    CONSTRAINT fk_report_location FOREIGN KEY (location_item_id) REFERENCES master_list_items (item_id),
    CONSTRAINT fk_report_destination FOREIGN KEY (destination_item_id) REFERENCES master_list_items (item_id),
    CONSTRAINT fk_report_country FOREIGN KEY (country_item_id) REFERENCES master_list_items (item_id),
    CONSTRAINT fk_report_created_by FOREIGN KEY (created_by_user_id) REFERENCES app_users (user_id),
    CONSTRAINT fk_report_modified_by FOREIGN KEY (modified_by_user_id) REFERENCES app_users (user_id),
    CONSTRAINT fk_report_deleted_by FOREIGN KEY (deleted_by_user_id) REFERENCES app_users (user_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 5. DECLARED GOODS. Five print; extra lines from a phone are kept too.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS declared_goods (
    declared_good_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    report_id   BIGINT UNSIGNED NOT NULL,
    line_no     SMALLINT UNSIGNED NOT NULL,
    description VARCHAR(500) NULL,
    quantity    VARCHAR(100) NULL,
    packaging   VARCHAR(100) NULL,
    PRIMARY KEY (declared_good_id),
    UNIQUE KEY uq_declared_line (report_id, line_no),
    KEY idx_declared_description (description(100)),
    CONSTRAINT chk_declared_line CHECK (line_no >= 1),
    CONSTRAINT fk_declared_report FOREIGN KEY (report_id) REFERENCES reports (report_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 6. ITEM LISTS AND LINES. Every form of a report is stored here, replacing
--    the Item Forms JSON files. Stock counts only the lists whose item_form
--    equals reports.item_form. A list with no lines keeps its number.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS item_lists (
    item_list_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    report_id    BIGINT UNSIGNED NOT NULL,
    item_form    VARCHAR(20)  NOT NULL,
    list_no      SMALLINT UNSIGNED NOT NULL,
    list_name    VARCHAR(100) NOT NULL,        -- Item List 1
    PRIMARY KEY (item_list_id),
    UNIQUE KEY uq_item_list (report_id, item_form, list_no),
    CONSTRAINT chk_item_list_form CHECK (item_form IN ('Default', 'Containerized', 'Loading')),
    CONSTRAINT chk_item_list_no CHECK (list_no >= 1),
    CONSTRAINT fk_item_list_report FOREIGN KEY (report_id) REFERENCES reports (report_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS item_lines (
    item_line_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    item_list_id  BIGINT UNSIGNED NOT NULL,
    line_no       SMALLINT UNSIGNED NOT NULL,
    unit_no       VARCHAR(100) NULL,      -- Container No. / Truck Plate No.
    description   VARCHAR(500) NULL,
    po_number     VARCHAR(100) NULL,
    packaging     VARCHAR(100) NULL,
    quantity      VARCHAR(100) NULL,
    uom           VARCHAR(30)  NULL,
    dimensions    VARCHAR(100) NULL,
    weights       VARCHAR(100) NULL,      -- number and Weight Unit: 1,250 KG
    currency      VARCHAR(10)  NULL,      -- typeable drop-down
    unit_price    VARCHAR(100) NULL,
    total_price   VARCHAR(100) NULL,
    findings      VARCHAR(500) NULL,
    cargo_id      VARCHAR(100) NULL,      -- warehouse link, not printed
    receiving_ref VARCHAR(100) NULL,      -- received batch, not printed
    PRIMARY KEY (item_line_id),
    UNIQUE KEY uq_item_line (item_list_id, line_no),
    KEY idx_line_cargo (cargo_id),
    KEY idx_line_receiving (receiving_ref),
    KEY idx_line_po (po_number),
    KEY idx_line_description (description(100)),
    CONSTRAINT chk_item_line_no CHECK (line_no >= 1),
    CONSTRAINT fk_line_list FOREIGN KEY (item_list_id) REFERENCES item_lists (item_list_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 7. REMARKS (Other Important Remarks; Additional Details)
--    The Additional Details tab is saved under its older name, Findings and
--    Remarks, as it is in the Excel file and in phone files.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS report_remarks (
    remark_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    report_id  BIGINT UNSIGNED NOT NULL,
    section    VARCHAR(60) NOT NULL,
    line_no    SMALLINT UNSIGNED NOT NULL,
    remark     TEXT NOT NULL,
    PRIMARY KEY (remark_id),
    UNIQUE KEY uq_remark_line (report_id, section, line_no),
    CONSTRAINT chk_remark_section CHECK (section IN
        ('Other Important Remarks', 'Findings and Remarks')),
    CONSTRAINT chk_remark_line CHECK (line_no >= 1),
    CONSTRAINT fk_remark_report FOREIGN KEY (report_id) REFERENCES reports (report_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 8. INCIDENT REPORTS (Bad Order): a card with up to 15 lines per form.
--    The date box is not validated by the form, so text that is not a date
--    is kept in incident_date_raw for printing.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incident_reports (
    incident_id   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    report_id     BIGINT UNSIGNED NOT NULL,
    card_no       SMALLINT UNSIGNED NOT NULL,  -- 1 = Incident Report, 2 = Additional 1
    vessel        VARCHAR(200) NULL,
    voyage        VARCHAR(100) NULL,
    client        VARCHAR(200) NULL,
    so_number     VARCHAR(100) NULL,
    port          VARCHAR(200) NULL,
    incident_date DATE         NULL,
    incident_date_raw VARCHAR(50) NULL,
    operation     VARCHAR(200) NULL,
    saved_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                  ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (incident_id),
    UNIQUE KEY uq_incident_card (report_id, card_no),
    CONSTRAINT chk_incident_card CHECK (card_no >= 1),
    CONSTRAINT fk_incident_report FOREIGN KEY (report_id) REFERENCES reports (report_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS incident_lines (
    incident_line_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    incident_id BIGINT UNSIGNED NOT NULL,
    line_no     TINYINT UNSIGNED NOT NULL,
    line_text   TEXT NOT NULL,
    PRIMARY KEY (incident_line_id),
    UNIQUE KEY uq_incident_line (incident_id, line_no),
    CONSTRAINT chk_incident_line CHECK (line_no BETWEEN 1 AND 15),
    CONSTRAINT fk_incident_line FOREIGN KEY (incident_id) REFERENCES incident_reports (incident_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 9. WAREHOUSE DECISIONS (Warehouse Data\*.warehouse.json). Append-only.
--    subject is text because it is a line ID (control/list/line) or an item
--    key, not a row. REC-00001 is derived from reconciliation_id.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reconciliation_log (
    reconciliation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    subject        VARCHAR(400) NOT NULL,
    action         VARCHAR(10)  NOT NULL,
    target_warehouse     VARCHAR(200) NULL,
    target_cargo_id      VARCHAR(100) NULL,
    target_receiving_ref VARCHAR(100) NULL,
    target_extra   JSON NULL,               -- any other key found in target
    note           TEXT NULL,
    user_name      VARCHAR(300) NULL,       -- as recorded, even if renamed later
    user_id        INT UNSIGNED NULL,
    logged_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (reconciliation_id),
    KEY idx_recon_subject (subject(191), reconciliation_id),
    CONSTRAINT chk_recon_action CHECK (action IN
        ('propose', 'confirm', 'reject', 'exclude', 'accept', 'reopen', 'note')),
    CONSTRAINT fk_recon_user FOREIGN KEY (user_id) REFERENCES app_users (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS case_status_log (
    case_status_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    report_id  BIGINT UNSIGNED NOT NULL,
    status     VARCHAR(20) NOT NULL,
    note       TEXT NULL,
    user_name  VARCHAR(300) NULL,
    user_id    INT UNSIGNED NULL,
    logged_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (case_status_id),
    KEY idx_case_report (report_id, case_status_id),
    CONSTRAINT chk_case_status CHECK (status IN ('Open', 'Under Review', 'Resolved')),
    CONSTRAINT fk_case_report FOREIGN KEY (report_id) REFERENCES reports (report_id),
    CONSTRAINT fk_case_user FOREIGN KEY (user_id) REFERENCES app_users (user_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 10. SHARED SETTINGS AND DROP-DOWN VALUES
--     Per-PC settings stay in settings.json; the login stays in db_config.json.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_settings (
    setting_key   VARCHAR(60) NOT NULL,
    setting_value JSON NOT NULL,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                  ON UPDATE CURRENT_TIMESTAMP,
    updated_by_user_id INT UNSIGNED NULL,
    PRIMARY KEY (setting_key),
    CONSTRAINT fk_setting_user FOREIGN KEY (updated_by_user_id) REFERENCES app_users (user_id)
) ENGINE=InnoDB;

INSERT IGNORE INTO app_settings (setting_key, setting_value) VALUES
 ('aging_thresholds', CAST('[7, 30, 60, 90]' AS JSON));

CREATE TABLE IF NOT EXISTS dropdown_options (
    field_key    VARCHAR(30) NOT NULL,
    option_value VARCHAR(50) NOT NULL,
    sort_order   SMALLINT UNSIGNED NOT NULL,
    is_active    TINYINT(1) NOT NULL DEFAULT 1,
    PRIMARY KEY (field_key, option_value)
) ENGINE=InnoDB;

INSERT IGNORE INTO dropdown_options (field_key, option_value, sort_order) VALUES
 ('activity','Receiving',1),('activity','Withdrawal',2),
 ('shipment_type','Local',1),('shipment_type','Import',2),
 ('container_type','Containerized',1),('container_type','Non-Containerized',2),
 ('currency','JPY',1),('currency','USD',2),('currency','PHP',3),('currency','SEK',4),('currency','EUR',5),
 ('uom','PCS',1),('uom','SET',2),('uom','UNIT',3),('uom','BOX',4),('uom','CASE',5),
 ('uom','CRATE',6),('uom','PALLET',7),('uom','PKG',8),('uom','BUNDLE',9),('uom','ROLL',10),
 ('uom','DRUM',11),('uom','LOT',12),('uom','LENGTH',13),('uom','M',14),('uom','KG',15),
 ('weight_unit','KG',1),('weight_unit','G',2),('weight_unit','L',3),
 ('weight_unit','ML',4),('weight_unit','MT',5),('weight_unit','LBS',6);

-- ---------------------------------------------------------------------
-- 11. IMPORT RECORDS
--     import_ledger: phone files (*_imported_reports.json).
--     legacy_import_records: every record of Old_Master Data.csv with its
--     original row, including those held back, so nothing is lost. This is
--     the only home of the CSV's Total invoice value.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_ledger (
    ledger_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id      VARCHAR(100) NOT NULL,
    phone_control  VARCHAR(30)  NOT NULL,
    local_control  VARCHAR(30)  NOT NULL,   -- text: may be deleted here later
    report_id      BIGINT UNSIGNED NULL,
    inspector      VARCHAR(200) NULL,
    phone_saved    VARCHAR(60)  NULL,       -- the phone's own text
    pc_saved       VARCHAR(40)  NULL,
    imported_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ledger_id),
    UNIQUE KEY uq_ledger_phone (device_id, phone_control),
    KEY idx_ledger_local (local_control),
    CONSTRAINT fk_ledger_report FOREIGN KEY (report_id) REFERENCES reports (report_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS legacy_import_records (
    legacy_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source_file    VARCHAR(255) NOT NULL,
    source_line    INT UNSIGNED NOT NULL,   -- first CSV line of the record
    import_status  VARCHAR(20)  NOT NULL,
    status_reason  VARCHAR(255) NULL,
    report_id      BIGINT UNSIGNED NULL,    -- NULL while it is not imported
    total_invoice_value VARCHAR(100) NULL,  -- no box or cell in the program
    original_rows  JSON NOT NULL,           -- the CSV rows, unchanged
    issues         JSON NULL,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (legacy_id),
    UNIQUE KEY uq_legacy_line (source_file, source_line),
    KEY idx_legacy_status (import_status),
    CONSTRAINT chk_legacy_status CHECK (import_status IN
        ('imported', 'cleared', 'held_duplicate', 'skipped', 'dropped')),
    CONSTRAINT fk_legacy_report FOREIGN KEY (report_id) REFERENCES reports (report_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 12. VIEWS. The live reports; one flat line per stock item line.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_active_reports AS
SELECT * FROM reports WHERE deleted_at IS NULL;

CREATE OR REPLACE VIEW v_item_report AS
SELECT r.control_no, r.so_number, r.inspection_date, r.consignee, r.supplier,
       r.cargo_condition, l.item_form, l.list_no, l.list_name, i.line_no,
       i.unit_no, i.description, i.po_number, i.packaging, i.quantity, i.uom,
       i.dimensions, i.weights, i.currency, i.unit_price, i.total_price,
       i.findings, i.cargo_id, i.receiving_ref
FROM reports r
JOIN item_lists l ON l.report_id = r.report_id AND l.item_form = r.item_form
JOIN item_lines i ON i.item_list_id = l.item_list_id
WHERE r.deleted_at IS NULL;

-- ---------------------------------------------------------------------
-- 13. APP LOGIN. Run once as admin with your own password:
--   CREATE USER IF NOT EXISTS 'fsr_app'@'localhost' IDENTIFIED BY '<password>';
--   GRANT SELECT, INSERT, UPDATE, DELETE ON field_survey_v2.* TO 'fsr_app'@'localhost';
-- ---------------------------------------------------------------------
