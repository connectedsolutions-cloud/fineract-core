# One-time client catalog Liquibase bootstrap

## Status

- Service registry: intentionally not registered
- CLI block: none
- Arissto access: read-only catalog export
- Fineract catalog migration: implemented in Liquibase `0272`

This directory documents the reviewed catalog snapshots needed by the client
KYC and profile migration. The bootstrap is a one-time, versioned Fineract
database migration. It is not an `inspect -> plan -> apply` sync service and
does not appear in `migration-services/registry.json`.

## Run the read-only export

From `tools/arissto-sync`:

```bash
cd ../../../../credesal-db-space
.venv/bin/python -m explore.export_client_catalogs
```

The command rewrites only the local catalog CSV files and `inventory.json`
under `credesal-db-space/docs/catalogs/arissto-client/`. It does not write to
Arissto or Fineract.

Review [`contract.md`](contract.md) for:

- the catalog inventory and usage counts;
- Fineract code versus reference-table decisions;
- proposed geography and economic-activity tables;
- the stable code-value crosswalk; and
- Liquibase acceptance requirements.

The versioned migration is
`fineract-provider/src/main/resources/db/changelog/tenant/parts/0272_seed_arissto_client_catalogs.xml`.
Its migration-owned CSV snapshot and checksum manifest are under
`parts/data/0272/`. Fineract applies it once through normal Liquibase startup.
The exporter remains only for reviewing or deliberately refreshing the source
snapshot before release.
