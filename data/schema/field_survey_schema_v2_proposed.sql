-- Field Survey Report schema v2 (proposal only; not applied).
-- Target: MySQL 8.0.16+ / InnoDB. Creates a new, empty database.
-- The current Windows application continues to use Excel as its primary
-- report store and optional MySQL as a mirror; this script is not wired in.
-- No users, reports, master data, imports, or settings are migrated.

CREATE DATABASE IF NOT EXISTS field_survey_v2
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE field_survey_v2;

-- A workspace identifies one future shared-backend dataset (for example,
-- a workbook or an Android/mobile tenant). It is not a local file path.
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id BINARY(16) NOT NULL,
    workspace_key VARCHAR(128) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    source_kind VARCHAR(30) NOT NULL DEFAULT 'excel_workbook',
    schema_version SMALLINT UNSIGNED NOT NULL DEFAULT 2,
    metadata JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id),
    UNIQUE KEY uq_workspace_key (workspace_key),
    CONSTRAINT chk_workspace_source CHECK
        (source_kind IN ('excel_workbook', 'android', 'shared_backend', 'other'))
) ENGINE=InnoDB;

-- The seven editable lists in master_list.json.
CREATE TABLE IF NOT EXISTS master_lists (
    list_key VARCHAR(40) NOT NULL,
    title VARCHAR(60) NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
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
    item_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    workspace_id BINARY(16) NOT NULL,
    list_key VARCHAR(40) NOT NULL,
    item_name VARCHAR(200) NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (item_id),
    UNIQUE KEY uq_master_name (workspace_id, list_key, item_name),
    UNIQUE KEY uq_master_scope (workspace_id, item_id, list_key),
    KEY idx_master_active (workspace_id, list_key, is_active, item_name),
    CONSTRAINT fk_master_item_workspace FOREIGN KEY (workspace_id)
        REFERENCES workspaces (workspace_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_master_item_list FOREIGN KEY (list_key)
        REFERENCES master_lists (list_key) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- Only these report fields may link to master-list entries. The composite
-- foreign keys below prevent (for example) a supplier value linking to a
-- consignee-list item. The report's text value remains the saved snapshot.
CREATE TABLE IF NOT EXISTS report_master_fields (
    field_key VARCHAR(30) NOT NULL,
    list_key VARCHAR(40) NOT NULL,
    PRIMARY KEY (field_key),
    UNIQUE KEY uq_report_master_field_list (field_key, list_key),
    CONSTRAINT fk_report_master_field_list FOREIGN KEY (list_key)
        REFERENCES master_lists (list_key) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

INSERT IGNORE INTO report_master_fields (field_key, list_key) VALUES
    ('consignee', 'consignee_list'),
    ('supplier', 'supplier_list'),
    ('brokerage', 'broker_list'),
    ('hauler', 'hauler_list'),
    ('location', 'location_list'),
    ('destination', 'destination_list'),
    ('country_of_origin', 'country_of_origin_list');

-- Used only by a future shared backend. Current Excel numbering is generated
-- from the workbook and is unchanged. Allocation must lock/update this row
-- atomically in the same transaction that inserts the report.
CREATE TABLE IF NOT EXISTS report_number_counters (
    workspace_id BINARY(16) NOT NULL,
    prefix VARCHAR(10) NOT NULL DEFAULT 'FSR',
    period CHAR(6) NOT NULL,
    last_number INT UNSIGNED NOT NULL DEFAULT 0,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, prefix, period),
    CONSTRAINT chk_counter_period CHECK
        (period REGEXP '^[0-9]{4}(0[1-9]|1[0-2])$'),
    CONSTRAINT fk_counter_workspace FOREIGN KEY (workspace_id)
        REFERENCES workspaces (workspace_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- One report per control number in a workspace. Legacy and imported control
-- numbers remain valid; only newly allocated numbers use FSR-YYYYMM-####.
CREATE TABLE IF NOT EXISTS reports (
    report_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    workspace_id BINARY(16) NOT NULL,
    control_no VARCHAR(40) NOT NULL,
    so_number VARCHAR(100) NOT NULL,
    inspection_date DATE NOT NULL,
    consignee VARCHAR(200) NULL,
    supplier VARCHAR(200) NULL,
    brokerage VARCHAR(200) NULL,
    hauler VARCHAR(200) NULL,
    location VARCHAR(200) NULL,
    destination VARCHAR(200) NULL,
    country_of_origin VARCHAR(100) NULL,
    activity VARCHAR(100) NULL,
    commenced_date DATE NULL,
    commenced_time CHAR(5) NULL,
    completion_date DATE NULL,
    completion_time CHAR(5) NULL,
    shipment_type VARCHAR(100) NULL,
    container_type VARCHAR(100) NULL,
    vessel_carrier VARCHAR(200) NULL,
    vehicle_type VARCHAR(100) NULL,
    vehicle_plate_number VARCHAR(100) NULL,
    invoice_number VARCHAR(100) NULL,
    po_number VARCHAR(100) NULL,
    jo_number VARCHAR(100) NULL,
    gatepass_number VARCHAR(100) NULL,
    bl_awb_number VARCHAR(100) NULL,
    dr_number VARCHAR(100) NULL,
    other_documents VARCHAR(255) NULL,
    cargo_condition VARCHAR(20) NOT NULL,
    item_form VARCHAR(20) NOT NULL DEFAULT 'Default',
    goods_new TINYINT(1) NOT NULL DEFAULT 0,
    goods_used TINYINT(1) NOT NULL DEFAULT 0,
    goods_food_stuffs TINYINT(1) NOT NULL DEFAULT 0,
    goods_vehicle TINYINT(1) NOT NULL DEFAULT 0,
    goods_pharma_chemicals TINYINT(1) NOT NULL DEFAULT 0,
    goods_others TINYINT(1) NOT NULL DEFAULT 0,
    goods_others_text VARCHAR(255) NULL,
    prepared_by_name VARCHAR(200) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_saved DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (report_id),
    UNIQUE KEY uq_report_control (workspace_id, control_no),
    UNIQUE KEY uq_report_workspace_id (workspace_id, report_id),
    UNIQUE KEY uq_report_identity (workspace_id, report_id, control_no),
    KEY idx_report_date (workspace_id, inspection_date),
    KEY idx_report_so (workspace_id, so_number),
    KEY idx_report_consignee (workspace_id, consignee),
    KEY idx_report_supplier (workspace_id, supplier),
    KEY idx_report_location (workspace_id, location),
    KEY idx_report_activity_date (workspace_id, activity, inspection_date),
    KEY idx_report_condition (workspace_id, cargo_condition),
    KEY idx_report_po (workspace_id, po_number),
    KEY idx_report_bl (workspace_id, bl_awb_number),
    KEY idx_report_dr (workspace_id, dr_number),
    KEY idx_report_gatepass (workspace_id, gatepass_number),
    CONSTRAINT chk_report_condition CHECK
        (cargo_condition IN ('Good Order', 'Bad Order')),
    CONSTRAINT chk_report_item_form CHECK
        (item_form IN ('Default', 'Containerized', 'Loading')),
    CONSTRAINT chk_report_commenced_time CHECK
        (commenced_time IS NULL OR commenced_time REGEXP
         '^([01][0-9][0-5][0-9]|2[0-3][0-5][0-9]|2400)H$'),
    CONSTRAINT chk_report_completion_time CHECK
        (completion_time IS NULL OR completion_time REGEXP
         '^([01][0-9][0-5][0-9]|2[0-3][0-5][0-9]|2400)H$'),
    CONSTRAINT chk_report_other_goods CHECK
        (goods_others = 1 OR goods_others_text IS NULL),
    CONSTRAINT fk_report_workspace FOREIGN KEY (workspace_id)
        REFERENCES workspaces (workspace_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS report_master_selections (
    workspace_id BINARY(16) NOT NULL,
    report_id BIGINT UNSIGNED NOT NULL,
    field_key VARCHAR(30) NOT NULL,
    list_key VARCHAR(40) NOT NULL,
    item_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (report_id, field_key),
    KEY idx_report_master_item (workspace_id, item_id, list_key),
    CONSTRAINT fk_report_master_report FOREIGN KEY (workspace_id, report_id)
        REFERENCES reports (workspace_id, report_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_report_master_field FOREIGN KEY (field_key, list_key)
        REFERENCES report_master_fields (field_key, list_key)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_report_master_item FOREIGN KEY
        (workspace_id, item_id, list_key)
        REFERENCES master_list_items (workspace_id, item_id, list_key)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- Declared Goods has five visible input rows on the Windows form. The table
-- intentionally has no five-row cap so imports/future clients never truncate.
CREATE TABLE IF NOT EXISTS declared_goods (
    declared_good_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    report_id BIGINT UNSIGNED NOT NULL,
    line_no SMALLINT UNSIGNED NOT NULL,
    description VARCHAR(500) NULL,
    quantity VARCHAR(100) NULL,
    packaging VARCHAR(100) NULL,
    PRIMARY KEY (declared_good_id),
    UNIQUE KEY uq_declared_line (report_id, line_no),
    KEY idx_declared_description (description(100)),
    CONSTRAINT chk_declared_line CHECK (line_no >= 1),
    CONSTRAINT fk_declared_report FOREIGN KEY (report_id)
        REFERENCES reports (report_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- Each report can keep lists for all three item forms, including empty lists.
-- The selected form is reports.item_form; other forms currently live in JSON.
CREATE TABLE IF NOT EXISTS item_lists (
    item_list_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    report_id BIGINT UNSIGNED NOT NULL,
    item_form VARCHAR(20) NOT NULL,
    list_no SMALLINT UNSIGNED NOT NULL,
    list_name VARCHAR(100) NOT NULL,
    PRIMARY KEY (item_list_id),
    UNIQUE KEY uq_report_item_list (report_id, item_form, list_no),
    UNIQUE KEY uq_item_list_report_id (item_list_id, report_id),
    CONSTRAINT chk_item_list_form CHECK
        (item_form IN ('Default', 'Containerized', 'Loading')),
    CONSTRAINT chk_item_list_number CHECK (list_no >= 1),
    CONSTRAINT fk_item_list_report FOREIGN KEY (report_id)
        REFERENCES reports (report_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- Keep quantity, weight and price text as entered; the form accepts values
-- that are not plain decimals. Weight Unit is stored with Weights; UOM and
-- Currency are separate fields. Cargo ID has no visible entry control today.
CREATE TABLE IF NOT EXISTS item_lines (
    item_line_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    item_list_id BIGINT UNSIGNED NOT NULL,
    line_no SMALLINT UNSIGNED NOT NULL,
    unit_no VARCHAR(100) NULL,
    description VARCHAR(500) NULL,
    po_number VARCHAR(100) NULL,
    packaging VARCHAR(100) NULL,
    quantity VARCHAR(100) NULL,
    uom VARCHAR(100) NULL,
    dimensions VARCHAR(100) NULL,
    weights VARCHAR(100) NULL,
    currency VARCHAR(100) NULL,
    unit_price VARCHAR(100) NULL,
    total_price VARCHAR(100) NULL,
    findings VARCHAR(500) NULL,
    cargo_id VARCHAR(100) NULL,
    receiving_ref VARCHAR(100) NULL,
    PRIMARY KEY (item_line_id),
    UNIQUE KEY uq_item_line (item_list_id, line_no),
    KEY idx_item_cargo (cargo_id),
    KEY idx_item_receiving_ref (receiving_ref),
    KEY idx_item_po (po_number),
    KEY idx_item_description (description(100)),
    CONSTRAINT chk_item_line_number CHECK (line_no >= 1),
    CONSTRAINT fk_item_line_list FOREIGN KEY (item_list_id)
        REFERENCES item_lists (item_list_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS report_remarks (
    remark_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    report_id BIGINT UNSIGNED NOT NULL,
    section VARCHAR(60) NOT NULL,
    line_no SMALLINT UNSIGNED NOT NULL,
    remark TEXT NOT NULL,
    PRIMARY KEY (remark_id),
    UNIQUE KEY uq_report_remark_line (report_id, section, line_no),
    CONSTRAINT chk_remark_section CHECK
        (section IN ('Other Important Remarks', 'Findings and Remarks')),
    CONSTRAINT chk_remark_line CHECK (line_no >= 1),
    CONSTRAINT fk_remark_report FOREIGN KEY (report_id)
        REFERENCES reports (report_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- Metadata from Incident Reports/<Control #>.json, including the JSON
-- envelope's top-level SO Number and saved timestamp.
CREATE TABLE IF NOT EXISTS report_incident_sets (
    workspace_id BINARY(16) NOT NULL,
    report_id BIGINT UNSIGNED NOT NULL,
    source_control_no VARCHAR(40) NOT NULL,
    so_number_snapshot VARCHAR(100) NULL,
    saved_at DATETIME NULL,
    source_metadata JSON NULL,
    PRIMARY KEY (report_id),
    CONSTRAINT fk_incident_set_report FOREIGN KEY
        (workspace_id, report_id, source_control_no)
        REFERENCES reports (workspace_id, report_id, control_no)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS incident_reports (
    incident_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    report_id BIGINT UNSIGNED NOT NULL,
    card_no SMALLINT UNSIGNED NOT NULL,
    vessel VARCHAR(200) NULL,
    voyage VARCHAR(100) NULL,
    client VARCHAR(200) NULL,
    so_number VARCHAR(100) NULL,
    port VARCHAR(200) NULL,
    incident_date_text VARCHAR(100) NULL,
    incident_date DATE NULL,
    operation VARCHAR(200) NULL,
    PRIMARY KEY (incident_id),
    UNIQUE KEY uq_incident_card (report_id, card_no),
    UNIQUE KEY uq_incident_report_id (incident_id, report_id),
    CONSTRAINT chk_incident_card CHECK (card_no >= 1),
    CONSTRAINT fk_incident_set FOREIGN KEY (report_id)
        REFERENCES report_incident_sets (report_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS incident_lines (
    incident_line_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    incident_id BIGINT UNSIGNED NOT NULL,
    line_no TINYINT UNSIGNED NOT NULL,
    line_text TEXT NOT NULL,
    PRIMARY KEY (incident_line_id),
    UNIQUE KEY uq_incident_line (incident_id, line_no),
    CONSTRAINT chk_incident_line CHECK (line_no BETWEEN 1 AND 15),
    CONSTRAINT fk_incident_line_report FOREIGN KEY (incident_id)
        REFERENCES incident_reports (incident_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- Envelope metadata for Item Forms/<Control #>.json. All form lists/lines
-- themselves are in item_lists/item_lines, including unselected forms.
CREATE TABLE IF NOT EXISTS report_item_form_sets (
    workspace_id BINARY(16) NOT NULL,
    report_id BIGINT UNSIGNED NOT NULL,
    source_control_no VARCHAR(40) NOT NULL,
    saved_at DATETIME NULL,
    source_metadata JSON NULL,
    PRIMARY KEY (report_id),
    CONSTRAINT fk_item_form_set_report FOREIGN KEY
        (workspace_id, report_id, source_control_no)
        REFERENCES reports (workspace_id, report_id, control_no)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- Retains the version/envelope metadata of the per-workbook warehouse JSON.
CREATE TABLE IF NOT EXISTS workspace_sidecar_metadata (
    workspace_id BINARY(16) NOT NULL,
    document_type VARCHAR(40) NOT NULL,
    schema_version SMALLINT UNSIGNED NOT NULL,
    metadata JSON NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, document_type),
    CONSTRAINT fk_sidecar_workspace FOREIGN KEY (workspace_id)
        REFERENCES workspaces (workspace_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- The append-only reconciliation JSON log. Subject is deliberately text:
-- it can be a report/list/line key or an inventory item key. Keep the full
-- target JSON as well as indexed/display columns for forward compatibility.
CREATE TABLE IF NOT EXISTS reconciliation_log (
    reconciliation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    workspace_id BINARY(16) NOT NULL,
    event_id VARCHAR(20) NOT NULL,
    subject VARCHAR(400) NOT NULL,
    action VARCHAR(10) NOT NULL,
    target_warehouse VARCHAR(200) NULL,
    target_cargo_id VARCHAR(100) NULL,
    target_receiving_ref VARCHAR(100) NULL,
    target_json JSON NULL,
    note TEXT NULL,
    user_name VARCHAR(300) NULL,
    logged_at DATETIME NOT NULL,
    PRIMARY KEY (reconciliation_id),
    UNIQUE KEY uq_reconciliation_event (workspace_id, event_id),
    KEY idx_reconciliation_subject (workspace_id, subject(191), reconciliation_id),
    KEY idx_reconciliation_action (workspace_id, action, logged_at),
    CONSTRAINT chk_reconciliation_action CHECK
        (action IN ('propose', 'confirm', 'reject', 'exclude',
                    'accept', 'reopen', 'note')),
    CONSTRAINT fk_reconciliation_workspace FOREIGN KEY (workspace_id)
        REFERENCES workspaces (workspace_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS case_status_log (
    case_status_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    workspace_id BINARY(16) NOT NULL,
    report_id BIGINT UNSIGNED NOT NULL,
    control_no VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL,
    note TEXT NULL,
    user_name VARCHAR(300) NULL,
    logged_at DATETIME NOT NULL,
    PRIMARY KEY (case_status_id),
    KEY idx_case_latest (workspace_id, report_id, case_status_id),
    KEY idx_case_status (workspace_id, status, logged_at),
    CONSTRAINT chk_case_status CHECK
        (status IN ('Open', 'Under Review', 'Resolved')),
    CONSTRAINT fk_case_workspace_report FOREIGN KEY
        (workspace_id, report_id, control_no)
        REFERENCES reports (workspace_id, report_id, control_no)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- Shared/workspace settings only. Per-PC theme, paths, login convenience
-- values, and database credentials remain in their current local files.
CREATE TABLE IF NOT EXISTS app_settings (
    workspace_id BINARY(16) NOT NULL,
    setting_key VARCHAR(80) NOT NULL,
    setting_value JSON NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, setting_key),
    CONSTRAINT fk_setting_workspace FOREIGN KEY (workspace_id)
        REFERENCES workspaces (workspace_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

INSERT IGNORE INTO app_settings (workspace_id, setting_key, setting_value)
SELECT workspace_id, 'aging_thresholds', CAST('[7, 30, 60, 90]' AS JSON)
FROM workspaces;

-- Suggestions/options only; typeable values remain valid even if absent here.
CREATE TABLE IF NOT EXISTS application_options (
    field_key VARCHAR(40) NOT NULL,
    option_value VARCHAR(100) NOT NULL,
    sort_order SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    PRIMARY KEY (field_key, option_value),
    KEY idx_option_order (field_key, is_active, sort_order)
) ENGINE=InnoDB;

INSERT IGNORE INTO application_options (field_key, option_value, sort_order) VALUES
    ('activity', 'Receiving', 1), ('activity', 'Withdrawal', 2),
    ('shipment_type', 'Local', 1), ('shipment_type', 'Import', 2),
    ('container_type', 'Containerized', 1),
    ('container_type', 'Non-Containerized', 2),
    ('item_form', 'Default', 1), ('item_form', 'Containerized', 2),
    ('item_form', 'Loading', 3),
    ('currency', 'JPY', 1), ('currency', 'USD', 2), ('currency', 'PHP', 3),
    ('currency', 'SEK', 4), ('currency', 'EUR', 5),
    ('uom', 'PCS', 1), ('uom', 'SET', 2), ('uom', 'UNIT', 3),
    ('uom', 'BOX', 4), ('uom', 'CASE', 5), ('uom', 'CRATE', 6),
    ('uom', 'PALLET', 7), ('uom', 'PKG', 8), ('uom', 'BUNDLE', 9),
    ('uom', 'ROLL', 10), ('uom', 'DRUM', 11), ('uom', 'LOT', 12),
    ('uom', 'LENGTH', 13), ('uom', 'M', 14), ('uom', 'KG', 15),
    ('weight_unit', 'KG', 1), ('weight_unit', 'G', 2),
    ('weight_unit', 'L', 3), ('weight_unit', 'ML', 4),
    ('weight_unit', 'MT', 5), ('weight_unit', 'LBS', 6),
    ('case_status', 'Open', 1), ('case_status', 'Under Review', 2),
    ('case_status', 'Resolved', 3);

-- Phone/Android import idempotency ledger. It records source identifiers and
-- timestamps as text because the source format is versioned JSON.
CREATE TABLE IF NOT EXISTS import_ledger (
    import_ledger_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    workspace_id BINARY(16) NOT NULL,
    source_format VARCHAR(40) NULL,
    source_version SMALLINT UNSIGNED NULL,
    source_metadata JSON NULL,
    device_id VARCHAR(100) NOT NULL,
    phone_control VARCHAR(100) NOT NULL,
    local_control VARCHAR(40) NOT NULL,
    report_id BIGINT UNSIGNED NULL,
    inspector VARCHAR(200) NULL,
    phone_saved VARCHAR(100) NULL,
    pc_saved VARCHAR(100) NULL,
    imported_at VARCHAR(100) NULL,
    PRIMARY KEY (import_ledger_id),
    UNIQUE KEY uq_import_phone (workspace_id, device_id, phone_control),
    KEY idx_import_local (workspace_id, local_control),
    CONSTRAINT fk_import_workspace FOREIGN KEY (workspace_id)
        REFERENCES workspaces (workspace_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_import_report FOREIGN KEY
        (workspace_id, report_id, local_control)
        REFERENCES reports (workspace_id, report_id, control_no)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

-- Optional source archive for the old CSV importer; no CSV or rows are loaded
-- by this schema script.
CREATE TABLE IF NOT EXISTS legacy_import_records (
    legacy_import_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    workspace_id BINARY(16) NOT NULL,
    source_file VARCHAR(255) NOT NULL,
    source_line INT UNSIGNED NOT NULL,
    import_status VARCHAR(20) NOT NULL,
    status_reason VARCHAR(255) NULL,
    report_id BIGINT UNSIGNED NULL,
    total_invoice_value VARCHAR(100) NULL,
    original_rows JSON NOT NULL,
    issues JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (legacy_import_id),
    UNIQUE KEY uq_legacy_source_line (workspace_id, source_file, source_line),
    KEY idx_legacy_status (workspace_id, import_status),
    CONSTRAINT chk_legacy_status CHECK
        (import_status IN ('imported', 'cleared', 'held_duplicate',
                           'skipped', 'dropped')),
    CONSTRAINT fk_legacy_workspace FOREIGN KEY (workspace_id)
        REFERENCES workspaces (workspace_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_legacy_report FOREIGN KEY (workspace_id, report_id)
        REFERENCES reports (workspace_id, report_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;

CREATE OR REPLACE VIEW v_reports AS
SELECT * FROM reports;

-- Warehouse calculations must use only lists matching reports.item_form;
-- other form data is retained for editing/printing but is not inventory.
CREATE OR REPLACE VIEW v_selected_item_report AS
SELECT r.workspace_id, r.control_no, r.so_number, r.inspection_date,
       r.activity, r.cargo_condition, r.location, r.supplier, r.consignee,
       r.destination, r.item_form, l.list_no, l.list_name, i.line_no,
       i.unit_no, i.description, i.po_number, i.packaging, i.quantity, i.uom,
       i.dimensions, i.weights, i.currency, i.unit_price, i.total_price,
       i.findings, i.cargo_id, i.receiving_ref
FROM reports AS r
JOIN item_lists AS l
  ON l.report_id = r.report_id AND l.item_form = r.item_form
JOIN item_lines AS i ON i.item_list_id = l.item_list_id;

-- No account table or credential storage is created. The Windows application
-- continues to use users.json and db_config.json as described above.
