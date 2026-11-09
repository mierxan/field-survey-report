-- Run ONCE in MySQL Workbench if your database was created before
-- "Local / Import" and "Containerized" were added.
USE field_survey;
ALTER TABLE reports ADD COLUMN shipment_type  VARCHAR(20) NULL AFTER vehicle_plate_number;
ALTER TABLE reports ADD COLUMN container_type VARCHAR(30) NULL AFTER shipment_type;
