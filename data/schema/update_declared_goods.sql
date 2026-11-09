-- Run once in MySQL Workbench (you already created the tables):
-- lets Declared Goods quantity hold text such as "12 boxes".
USE field_survey;
ALTER TABLE declared_goods MODIFY quantity VARCHAR(100) NULL;
