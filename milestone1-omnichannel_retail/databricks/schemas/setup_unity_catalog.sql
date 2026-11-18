-- Databricks Unity Catalog Setup Script
-- Sets up catalog, bronze/silver/gold/ops schemas, and raw_data volume.

-- 1. Create Catalog
CREATE CATALOG IF NOT EXISTS ${catalog_name};
USE CATALOG ${catalog_name};

-- 2. Create Schemas
CREATE SCHEMA IF NOT EXISTS ${catalog_name}.bronze
COMMENT 'Bronze Layer: Raw ingested data and landing logs';

CREATE SCHEMA IF NOT EXISTS ${catalog_name}.silver
COMMENT 'Silver Layer: Cleaned, deduplicated, and normalized dimensional & fact entities';

CREATE SCHEMA IF NOT EXISTS ${catalog_name}.gold
COMMENT 'Gold Layer: Aggregated analytical datasets, 360 views, and executive KPIs';

CREATE SCHEMA IF NOT EXISTS ${catalog_name}.ops
COMMENT 'Ops Layer: Pipeline execution lifecycle, ingestion records, and quality check audit logs';

-- 3. Create Raw Data Landing Volume
CREATE VOLUME IF NOT EXISTS ${catalog_name}.bronze.raw_data
COMMENT 'Volume storing landed raw JSON and CSV source files';
