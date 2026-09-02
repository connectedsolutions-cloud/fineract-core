# Test tenant reset workflow

Fineract financial writes fan out into schedules, transactions, charges,
journals, mappings, datatables, and migration support tables. Deleting only
rows with an Arissto-looking external ID cannot return a tenant to an exact
pre-sync state and can leave invalid financial history. Test-cycle reset is
therefore implemented as a whole tenant-database snapshot and restore.

The operator tool is [`scripts/reset-test-tenant.sh`](../scripts/reset-test-tenant.sh).
It is intentionally separate from `arissto-sync`: the sync engine remains
one-way and contains no delete operation.

## Safety rules

The tool:

- refuses tenant `default` and database `fineract_default`;
- resolves the database through the Fineract tenant registry rather than
  accepting a database name from the command line;
- refuses remote PostgreSQL hosts;
- requires Fineract to be stopped for capture, reset, and recreation;
- requires exact `TENANT:DATABASE` confirmation for destructive actions;
- verifies the snapshot checksum before restore;
- archives the selected sync SQLite state file before reset; and
- compares core table counts after restore with the captured baseline.

It is only for local disposable test tenants. It must not be adapted into a
production cleanup command.

## One-time preparation for a clean tenant

For a newly migrated and bootstrapped tenant, stop Fineract and capture the
baseline before the first sync cycle:

```bash
./scripts/reset-test-tenant.sh capture sandbox \
  --state-file tools/arissto-sync/.arissto-sync/state.sqlite3
```

The ignored baseline is stored under `.tenant-baselines/`. Keep it for as long
as the tenant schema and required bootstrap configuration remain compatible.
Capture a new baseline after an intentional Liquibase or bootstrap change.

## Reset after a test cycle

1. Stop Fineract cleanly.
2. Inspect the target and expected confirmation:

   ```bash
   ./scripts/reset-test-tenant.sh status sandbox
   ```

3. Restore the baseline:

   ```bash
   ./scripts/reset-test-tenant.sh reset sandbox \
     --confirm sandbox:fineract_sandbox \
     --state-file tools/arissto-sync/.arissto-sync/state.sqlite3
   ```

4. Restart Fineract and run `status` again. Then run sync preflight and inspect
   before producing new plans.

Successful restore means the PostgreSQL dump was accepted and the captured
counts for `databasechangelog`, clients, staff, loans, savings accounts, and
share accounts match exactly.

## Recreate when no baseline exists

An already-used tenant with no pre-cycle snapshot cannot be rolled back
exactly. Recreate it instead:

```bash
./scripts/reset-test-tenant.sh recreate sandbox \
  --confirm sandbox:fineract_sandbox \
  --state-file /path/to/the/cycle-state.sqlite3
```

Then restart Fineract with Liquibase enabled. Once migrations and intentional
test prerequisites are complete, stop Fineract and capture the new baseline.
The `recreate` action does not modify the tenant registry row.

## Connection configuration

The script uses standard `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, and
`PGMAINTDB` values. When they are absent, it reads the local PostgreSQL settings
from `fineract-core/.env`, matching the provisioning workflow. PostgreSQL CLI
programs (`psql`, `pg_dump`, `pg_restore`, `dropdb`, and `createdb`) must be on
`PATH`.
