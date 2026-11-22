-- =====================================================================
--  FIELD SURVEY REPORT  -  MySQL 8.0 table script (PC program)
--  Run in MySQL Workbench:  File > Open SQL Script...  >  lightning bolt
--  Safe to run again: existing tables and data are kept.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS field_survey
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE field_survey;

-- ---------------------------------------------------------------------
-- 1. REPORTS  (one row per report = the "Reports" sheet of the Excel file)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    control_no          VARCHAR(40)  NOT NULL,            -- FSR-JDC-202610-0001
    so_number           VARCHAR(100) NULL,
    inspection_date     DATE         NULL,
    consignee           VARCHAR(200) NULL,
    supplier            VARCHAR(200) NULL,
    brokerage           VARCHAR(200) NULL,
    hauler              VARCHAR(200) NULL,
    location            VARCHAR(200) NULL,
    destination         VARCHAR(200) NULL,
    country_of_origin   VARCHAR(100) NULL,
    activity            VARCHAR(50)  NULL,                -- Receiving / Withdrawal
    commenced_date      DATE         NULL,
    commenced_time      VARCHAR(5)   NULL,                -- 0800H
    completion_date     DATE         NULL,
    completion_time     VARCHAR(5)   NULL,
    vessel_carrier      VARCHAR(200) NULL,
    vehicle_type        VARCHAR(100) NULL,
    vehicle_plate_number VARCHAR(50) NULL,
    shipment_type       VARCHAR(20)  NULL,                -- Local / Import
    container_type      VARCHAR(30)  NULL,                -- Containerized / Non-Containerized
    item_form           VARCHAR(20)  NULL,                -- Item List form: Default / Containerized / Loading
    invoice_number      VARCHAR(100) NULL,
    po_number           VARCHAR(100) NULL,
    jo_number           VARCHAR(100) NULL,
    gatepass_number     VARCHAR(100) NULL,
    bl_awb_number       VARCHAR(100) NULL,
    dr_number           VARCHAR(100) NULL,
    other_documents     VARCHAR(255) NULL,
    cargo_condition     ENUM('Good Order','Bad Order') NOT NULL DEFAULT 'Good Order',
    -- Types of Goods (the six check boxes on the First Page)
    goods_new               TINYINT(1) NOT NULL DEFAULT 0,
    goods_used              TINYINT(1) NOT NULL DEFAULT 0,
    goods_food_stuffs       TINYINT(1) NOT NULL DEFAULT 0,
    goods_vehicle           TINYINT(1) NOT NULL DEFAULT 0,
    goods_pharma_chemicals  TINYINT(1) NOT NULL DEFAULT 0,
    goods_others            TINYINT(1) NOT NULL DEFAULT 0,
    goods_others_text       VARCHAR(255) NULL,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_saved          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (control_no),
    KEY idx_reports_date      (inspection_date),
    KEY idx_reports_so        (so_number),
    KEY idx_reports_consignee (consignee),
    KEY idx_reports_condition (cargo_condition)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 2. DECLARED GOODS  (up to 5 lines print on the First Page)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS declared_goods (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
    control_no  VARCHAR(40)  NOT NULL,
    line_no     SMALLINT UNSIGNED NOT NULL,
    description VARCHAR(500) NULL,
    quantity    VARCHAR(100) NULL,
    packaging   VARCHAR(100) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_goods_line (control_no, line_no),
    CONSTRAINT fk_goods_report FOREIGN KEY (control_no)
        REFERENCES reports (control_no) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

-- If declared_goods already existed with the old number column, fix it:
ALTER TABLE declared_goods MODIFY quantity VARCHAR(100) NULL;

-- ---------------------------------------------------------------------
-- 3. ITEM LIST  (Cargo Details lines; up to 30 per list)
--    Quantity / prices are kept as text too, because the form accepts
--    entries such as "125 pcs" or "n/a".
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS item_lines (
    id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
    control_no      VARCHAR(40)  NOT NULL,
    item_list       VARCHAR(100) NOT NULL DEFAULT 'Item List 1',
    line_no         SMALLINT UNSIGNED NOT NULL,
    description     VARCHAR(500) NULL,
    po_number       VARCHAR(100) NULL,
    packaging       VARCHAR(100) NULL,
    quantity        VARCHAR(100) NULL,
    dimensions      VARCHAR(100) NULL,
    weights         VARCHAR(100) NULL,
    unit_price      VARCHAR(100) NULL,
    total_price     VARCHAR(100) NULL,
    findings        VARCHAR(500) NULL,
    cargo_id        VARCHAR(100) NULL,      -- warehouse link (not printed)
    receiving_ref   VARCHAR(100) NULL,      -- received batch reference
    uom             VARCHAR(30)  NULL,      -- unit of measure of quantity
    currency        VARCHAR(3)   NULL,      -- of unit_price / total_price
    unit_no         VARCHAR(100) NULL,      -- Container No. / Truck Plate No.
    packing_list_no VARCHAR(120) NULL,      -- Packing List No. (shipment import)
    origin_line     VARCHAR(120) NULL,      -- Origin Line (shipment import)
    PRIMARY KEY (id),
    UNIQUE KEY uq_item_line (control_no, item_list, line_no),
    KEY idx_item_cargo (cargo_id),
    CONSTRAINT fk_item_report FOREIGN KEY (control_no)
        REFERENCES reports (control_no) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 4. REMARKS  ("Other Important Remarks" on the First Page and the
--    "Findings and Remarks" lines on the Cargo Details page)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS remarks (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
    control_no  VARCHAR(40)  NOT NULL,
    section     VARCHAR(60)  NOT NULL,   -- 'Other Important Remarks' / 'Findings and Remarks'
    line_no     SMALLINT UNSIGNED NOT NULL,
    remark      TEXT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_remark_line (control_no, section, line_no),
    CONSTRAINT fk_remark_report FOREIGN KEY (control_no)
        REFERENCES reports (control_no) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 5. INCIDENT REPORTS  (Bad Order). One row per incident form, with its
--    header fields; the text lines are in incident_lines (max 15 each).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incident_reports (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
    control_no  VARCHAR(40)  NOT NULL,
    report_no   SMALLINT UNSIGNED NOT NULL,        -- 1 = Incident Report, 2 = Additional 1 ...
    vessel      VARCHAR(200) NULL,
    voyage      VARCHAR(100) NULL,
    client      VARCHAR(200) NULL,
    so_number   VARCHAR(100) NULL,
    port        VARCHAR(200) NULL,
    incident_date DATE       NULL,
    operation   VARCHAR(200) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_incident (control_no, report_no),
    CONSTRAINT fk_incident_report FOREIGN KEY (control_no)
        REFERENCES reports (control_no) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS incident_lines (
    id                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
    incident_report_id  INT UNSIGNED NOT NULL,
    line_no             TINYINT UNSIGNED NOT NULL,     -- 1..15
    line_text           TEXT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_incident_line (incident_report_id, line_no),
    CONSTRAINT fk_incline_incident FOREIGN KEY (incident_report_id)
        REFERENCES incident_reports (id) ON DELETE CASCADE,
    CONSTRAINT chk_incident_line_no CHECK (line_no BETWEEN 1 AND 15)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 6. MASTER LISTS  (replaces master_list.json)
--    list_name: consignee_list, supplier_list, broker_list, hauler_list,
--               location_list, destination_list, country_of_origin_list
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS master_list (
    id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
    list_name  VARCHAR(40)  NOT NULL,
    item_name  VARCHAR(200) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_master (list_name, item_name),
    CONSTRAINT chk_master_list CHECK (list_name IN (
        'consignee_list','supplier_list','broker_list','hauler_list',
        'location_list','destination_list','country_of_origin_list'))
) ENGINE=InnoDB;

INSERT IGNORE INTO master_list (list_name, item_name) VALUES
 ('consignee_list','Energy Development Corporation'),
 ('supplier_list','Kokusai Commerce Co. Ltd.'),
 ('supplier_list','Maxisource Marketing'),
 ('supplier_list','Nielsons Safety'),
 ('supplier_list','ABB PTE LTD'),
 ('supplier_list','HJ Franklin Inc.,'),
 ('broker_list','AC Obsum Brokerage'),
 ('broker_list','Quickflo Forwarders'),
 ('broker_list','Royal Cargo Inc.'),
 ('hauler_list','Sorsogon Commercial'),
 ('hauler_list','T1 Transport'),
 ('hauler_list','RCCe Trucks and Trailer'),
 ('hauler_list','Libcap'),
 ('location_list','EDC-DHL Warehouse'),
 ('destination_list','BGPF'),('destination_list','LGPF'),('destination_list','NGPF'),
 ('destination_list','MGPF'),('destination_list','EBWPC'),('destination_list','HO-RBC'),
 ('country_of_origin_list','Philippines'),('country_of_origin_list','U.S.A'),
 ('country_of_origin_list','China'),('country_of_origin_list','Korea'),
 ('country_of_origin_list','Japan'),('country_of_origin_list','Sweden'),
 ('country_of_origin_list','Italy'),('country_of_origin_list','Singapore');

-- ---------------------------------------------------------------------
-- 7. HANDY VIEW: one flat line per item with the report header
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_item_report AS
SELECT r.control_no, r.so_number, r.inspection_date, r.consignee, r.supplier,
       r.cargo_condition, i.item_list, i.line_no, i.description, i.po_number,
       i.packaging, i.quantity, i.uom, i.dimensions, i.weights, i.currency,
       i.unit_price, i.total_price, i.findings
FROM reports r JOIN item_lines i ON i.control_no = r.control_no;

-- ---------------------------------------------------------------------
-- 8. APP LOGIN  (the program connects with this user, not root)
--    Choose a strong password, run these three lines once as root, and put
--    the same password in db_config.json. Passwords are not kept in this file.
--    CREATE USER IF NOT EXISTS 'fsr_app'@'localhost' IDENTIFIED BY '<your password>';
--    GRANT SELECT, INSERT, UPDATE, DELETE ON field_survey.* TO 'fsr_app'@'localhost';
--    FLUSH PRIVILEGES;
-- ---------------------------------------------------------------------

-- Quick check: should list 7 tables plus the v_item_report view.
SELECT table_name FROM information_schema.tables WHERE table_schema = 'field_survey' ORDER BY 1;
SELECT list_name, COUNT(*) AS items FROM master_list GROUP BY list_name;
