# Migration detail: client system codes and reference catalogs

This document defines how Arissto client reference catalogs should be exported,
reviewed, and represented in Fineract for the KYC/profile migration. It reflects
the verified source and local-target state as of 2026-08-12.

It is a design and operating contract. The catalog exporter described here is
implemented and read-only. The proposed Fineract Liquibase catalog migration is
not created or applied by the exporter.

## Outcome

The client migration needs deterministic translations for:

- countries, departments, and municipalities;
- civil status;
- education level;
- profession;
- income source; and
- economic activity.

Fineract must retain the stable Arissto source key as well as the human label.
Matching only by label is not sufficient: labels can be renamed, municipalities
repeat across departments, and two economic-activity labels are duplicated.

## Verified catalog inventory

The following inventory was exported from Arissto using only `SELECT` queries:

| Domain | Arissto table | Rows | Current AFI_SOCIO use | Recommended Fineract model |
|---|---|---:|---|---|
| Country | `dbo.PAIS` | 279 | Home 1,028; birth 1,028; work 18; remittance 5 | Existing `COUNTRY` code plus stable crosswalk |
| Department/state | `dbo.DEPARTAMENTO` | 71 | Home 1,028; birth 1,023; work 17 | Existing `STATE` code plus geography table/crosswalk |
| Municipality | `dbo.MUNICIPIO` | 3,509 | Home 1,028; birth 1,022; work 15 | New hierarchical geography table; address city text |
| Civil status | `dbo.ESTADO_CIVIL` | 5 | 1,017 | Existing `MARITAL STATUS` code plus crosswalk |
| Education level | `dbo.AFI_NIVEL_EDUCATIVO` | 6 | 1,008 | New Fineract code `CREDESAL_EDUCATION_LEVEL` plus crosswalk |
| Profession | `dbo.AFI_PROFESION` | 513 | 457 catalog IDs; 993 free-text professions | Existing `PROFESSION` code plus crosswalk; preserve free-text fallback |
| Income source | `dbo.AFI_FUENTE_INGRESOS` | 13 | Primary 983; secondary 4; remittance 5 | New code `CREDESAL_INCOME_SOURCE` plus crosswalk |
| Economic activity | `dbo.AFI_ACT_ECONOMICA` | 772 | Activity 1: 371 resolved plus 2 orphan IDs; activity 2: 1 | New reference table, not a Fineract code |

The detailed values and per-source-column usage counts are stored in the
reviewable exports under:

```text
credesal-db-space/docs/catalogs/arissto-client/
```

Files:

- `countries.csv`
- `departments.csv`
- `municipalities.csv`
- `civil_statuses.csv`
- `education_levels.csv`
- `professions.csv`
- `income_sources.csv`
- `economic_activities.csv`
- `inventory.json`

`inventory.json` records the table name, row count, maximum label length,
case-insensitive duplicate-label count, and SHA-256 digest for every CSV.

## How the catalog export is triggered

The exporter lives in the read-only exploration repository:

```text
credesal-db-space/explore/export_client_catalogs.py
```

Run it manually from the `credesal-db-space` root:

```bash
.venv/bin/python -m explore.export_client_catalogs
```

The command requires the same read-only Arissto connection settings used by the
exploration CLI. When Codex runs it, external network permission may be needed.

The exporter performs these steps:

1. Executes ordered `SELECT` statements against the eight catalog tables.
2. Trims fixed-width string values.
3. Runs aggregate `COUNT(*)` queries against `dbo.AFI_SOCIO` for every relevant
   source foreign-key column.
4. Rewrites the eight CSV files deterministically.
5. Rewrites `inventory.json` with counts and content hashes.
6. Prints the inventory to standard output for review.

The export is not part of `arissto-sync plan` or `apply`. It must be run
deliberately when source catalogs are being reviewed or refreshed.

## What running the exporter changes

Running the exporter changes only local documentation artifacts under
`docs/catalogs/arissto-client/`.

It does **not**:

- insert, update, or delete anything in Arissto;
- connect to or modify Fineract;
- create a Liquibase changeset;
- modify `config/clients.json`;
- alter a migration plan or run; or
- expose client names, documents, addresses, phones, emails, or other sampled
  PII.

The `USAGE_*` columns contain aggregate counts only. After refreshing the
export, review the CSV diff, row counts, duplicate-label counts, and SHA-256
changes before using the files to generate a Fineract migration.

## Why the catalogs use more than one Fineract mechanism

### Fineract codes are appropriate for flat selections

`m_code` and `m_code_value` work well when a field is a flat, human-selectable
enumeration. The local Fineract instance already contains these empty system
codes:

- `COUNTRY`
- `STATE`
- `MARITAL STATUS`
- `PROFESSION`

These should be populated rather than duplicated. Education level and income
source need two new non-system code groups:

- `CREDESAL_EDUCATION_LEVEL`
- `CREDESAL_INCOME_SOURCE`

Do not hard-code `m_code.id` or `m_code_value.id`. Resolve code groups by
`m_code.code_name` and values through the stable crosswalk described below.

### A stable crosswalk is required

Standard Fineract code values contain a generated integer ID and a label, but
they do not contain a dedicated external/source key. Store the Arissto key in a
new table instead of encoding it into the label or relying on
`code_description` parsing:

```text
credesal_catalog_code_value_map
  source_system       VARCHAR(30)   -- ARISSTO
  catalog_name        VARCHAR(50)   -- COUNTRY, STATE, etc.
  source_key          VARCHAR(50)   -- e.g. 0222, 01, 0005
  code_value_id       INT           -- FK to m_code_value.id
  source_label        VARCHAR(300)
  active              BOOLEAN
```

Required constraints:

- primary key or unique constraint on
  `(source_system, catalog_name, source_key)`;
- unique constraint on `(source_system, catalog_name, code_value_id)`; and
- foreign key from `code_value_id` to `m_code_value.id` with `RESTRICT` delete.

This makes planning and reconciliation deterministic even when labels change.

### Geography needs hierarchy

Fineract addresses already accept `country_id` and `state_province_id`, both
pointing to `m_code_value`, so `COUNTRY` and `STATE` code values should be
seeded for native address compatibility.

Municipalities cannot be modeled safely as one flat code:

- there are 3,509 rows;
- 1,296 labels are duplicates when compared case-insensitively; and
- municipality identity depends on its department.

Create hierarchical reference tables:

```text
credesal_geo_country
  arissto_country_id  VARCHAR(4) PK
  name                VARCHAR(75)
  iso2                VARCHAR(2)
  iso3                VARCHAR(3)
  demonym             VARCHAR(75)
  country_cv_id       INT UNIQUE NULL FK -> m_code_value.id

credesal_geo_department
  arissto_department_id VARCHAR(2) PK
  arissto_country_id    VARCHAR(4) FK -> credesal_geo_country
  name                  VARCHAR(75)
  zone_code             VARCHAR(3)
  state_cv_id           INT UNIQUE NULL FK -> m_code_value.id

credesal_geo_municipality
  arissto_municipality_id VARCHAR(4) PK
  arissto_department_id   VARCHAR(2) FK -> credesal_geo_department
  municipality_code      VARCHAR(2)
  name                   VARCHAR(100)
  district               VARCHAR(100)
  settlement_type        VARCHAR(75)
  postal_code             VARCHAR(25)
  region_code             VARCHAR(4)
```

For a migrated home address:

- `m_address.country_id` receives `credesal_geo_country.country_cv_id`;
- `m_address.state_province_id` receives
  `credesal_geo_department.state_cv_id`;
- `m_address.city` or `county_district` receives the municipality name; and
- the stable municipality ID should also be retained in the client profile
  linkage/datatable so it can be reconciled without relying on text.

The Arissto `Mundo` pseudo-country and foreign-department sentinel values need
explicit review; they must not be treated as ISO countries simply because they
exist in the source catalog.

### Economic activity needs its own table

Economic activity should not use `m_code_value`:

- the source key is business-significant;
- two labels are duplicated;
- labels can exceed the `m_code_value.code_value` limit of 100 characters; and
- the catalog may later need a separate Ministerio de Hacienda code or
  regulatory classification.

Create:

```text
credesal_economic_activity
  arissto_activity_id  INT PK
  description          VARCHAR(300)
  mh_activity_code     VARCHAR(6) NULL
  active               BOOLEAN
```

Do not populate `mh_activity_code` from the Arissto ID. The investigation has
not established that `AFI_ACT_ECONOMICA.ID_ACT_ECONOMICA` is a Ministerio de
Hacienda code.

The two currently orphaned `AFI_SOCIO.ID_ACT_ECONOMICA1` values must be
reported during planning and quarantined or explicitly mapped; they must not
silently become ad-hoc catalog rows.

## Proposed source-to-Fineract mappings

| Arissto key | Fineract catalog/reference | Client destination |
|---|---|---|
| `ID_PAIS` | `COUNTRY` + `credesal_geo_country` | `m_address.country_id`, KYC country/nationality text |
| `CODIGO_DEPARTAMENTO` | `STATE` + `credesal_geo_department` | `m_address.state_province_id`, KYC department text |
| `CODIGO_MUNICIPIO` | `credesal_geo_municipality` | Address city/district text plus stable profile reference |
| `ID_ESTADO_CIVIL` | `MARITAL STATUS` | KYC `estado_civil` selection/text |
| `ID_NIVEL_ACADEMICO` | `CREDESAL_EDUCATION_LEVEL` | KYC `nivel_educativo` selection/text |
| `ID_PROFESION` | `PROFESSION` | KYC profession selection; `AFI_SOCIO.PROFESION` remains free-text fallback |
| `ID_FUENTE_ING*` | `CREDESAL_INCOME_SOURCE` | Income/remittance source selection |
| `ID_ACT_ECONOMICA*` | `credesal_economic_activity` | Income activity reference and description |

## Relationship to existing KYC datatables

The current Credesal KYC tables store catalog-backed fields as text. Preserve
those columns during the catalog-bootstrap phase so existing APIs and forms do
not break.

The local configuration `constraint-approach-for-datatables` is disabled.
Fineract-created dropdown datatable columns therefore use generated
code-qualified column names rather than a normal physical FK constraint.

For that reason, do not change current text columns in place. Use two phases:

1. Seed the authoritative catalogs and crosswalk/reference tables.
2. Add new code/reference columns, backfill them, update API/UI consumers, and
   only then decide whether the old text columns remain as snapshots or can be
   retired.

During migration, text snapshots and stable IDs must be produced from the same
resolved catalog row so they cannot disagree.

## What Liquibase migration 0272 changes

The migration:

1. Populate the existing `COUNTRY`, `STATE`, `MARITAL STATUS`, and `PROFESSION`
   code groups without assuming their database IDs.
2. Create and seed `CREDESAL_EDUCATION_LEVEL` and
   `CREDESAL_INCOME_SOURCE`.
3. Create `credesal_catalog_code_value_map` and link every seeded flat catalog
   value to its Arissto key.
4. Create and seed the three hierarchical geography tables.
5. Create and seed `credesal_economic_activity`.
6. Add indexes and restrictive foreign keys needed for lookup and
   reconciliation.
7. Leave current client KYC data unchanged; client rows are populated later by
   an explicitly scoped `arissto-sync` plan/apply run.

Seeding should be idempotent by source key and code-group name. Production must
receive the same reviewed catalog snapshot through version-controlled
Liquibase, not by copying generated local integer IDs.

## What it must not change

The catalog migration must not:

- write to Arissto;
- create or update Fineract clients;
- activate clients;
- overwrite existing non-Credesal code values with the same label;
- infer MH activity codes;
- flatten municipality identity to name alone; or
- delete catalog values that are referenced by client/profile data.

## Review and acceptance checks

Before catalog migration approval:

1. Re-run the exporter and review the catalog CSV/inventory diff.
2. Confirm the eight source row counts and hashes.
3. Verify every populated client source key resolves, except explicitly listed
   orphans.
4. Verify every Fineract crosswalk row points to the intended code value.
5. Verify municipality-to-department and department-to-country referential
   integrity.
6. Verify country/state code-value IDs are resolved independently in local and
   production.
7. Verify repeated execution of Liquibase produces no duplicate codes or
   reference rows.
8. Verify existing KYC datatable APIs still expose their original columns.

After the catalog migration, `arissto-sync inspect --block clients --target
local` should report catalog readiness and exact unresolved-key counts before a
KYC client plan is considered applicable.

## Current implementation status

Implemented:

- read-only catalog exporter;
- reviewed CSV files with aggregate usage counts; and
- hash/count inventory;
- versioned, one-time Fineract Liquibase migration
  `0272_seed_arissto_client_catalogs.xml`;
- migration-owned reference CSVs and checksum manifest under
  `parts/data/0272/`;
- the geography, economic-activity, and code-value crosswalk tables;
- all six Fineract code groups/value sets; and
- PostgreSQL and MariaDB/MySQL generated-ID-safe seed logic.

Not yet implemented:

- client-contract catalog lookup declarations;
- identifier/address/profile stable-ID writes; and
- catalog reconciliation in `inspect`, `plan`, or `reconcile`.
