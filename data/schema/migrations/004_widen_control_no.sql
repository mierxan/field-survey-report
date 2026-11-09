-- Run ONCE in MySQL Workbench on a database created before Control # had the
-- inspector's initials (FSR-JDC-202611-0001), or use Master Lists & Settings >
-- Upgrade MySQL tables. Existing rows are kept.
USE field_survey;
ALTER TABLE declared_goods   DROP FOREIGN KEY fk_goods_report;
ALTER TABLE incident_reports DROP FOREIGN KEY fk_incident_report;
ALTER TABLE item_lines       DROP FOREIGN KEY fk_item_report;
ALTER TABLE remarks          DROP FOREIGN KEY fk_remark_report;
ALTER TABLE reports          MODIFY control_no VARCHAR(40) NOT NULL;
ALTER TABLE declared_goods   MODIFY control_no VARCHAR(40) NOT NULL;
ALTER TABLE incident_reports MODIFY control_no VARCHAR(40) NOT NULL;
ALTER TABLE item_lines       MODIFY control_no VARCHAR(40) NOT NULL;
ALTER TABLE remarks          MODIFY control_no VARCHAR(40) NOT NULL;
ALTER TABLE declared_goods   ADD CONSTRAINT fk_goods_report    FOREIGN KEY (control_no) REFERENCES reports (control_no) ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE incident_reports ADD CONSTRAINT fk_incident_report FOREIGN KEY (control_no) REFERENCES reports (control_no) ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE item_lines       ADD CONSTRAINT fk_item_report     FOREIGN KEY (control_no) REFERENCES reports (control_no) ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE remarks          ADD CONSTRAINT fk_remark_report   FOREIGN KEY (control_no) REFERENCES reports (control_no) ON DELETE CASCADE ON UPDATE CASCADE;
