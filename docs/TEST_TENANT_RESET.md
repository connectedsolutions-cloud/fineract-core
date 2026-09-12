# Test tenant reset workflow

Fineract financial writes fan out into schedules, transactions, charges,
journals, mappings, datatables, and migration support tables. Deleting only
rows with an Arissto-looking external ID cannot return a tenant to an exact
pre-sync state and can leave invalid financial history. Test-cycle reset is
therefore implemented as a whole tenant-database snapshot and restore.

The baseline must be captured before any loan product, loan, ledger posting, or
invoice is created. Capture and reset reject a tenant containing any row in
`m_product_loan`, `m_loan`, the native journal, imported-journal provenance,
the derived ledger tables, or the invoice/DTE transaction tables. This
guarantees that a fresh cycle plans
`create-product` actions from the current reviewed contract, including current
principal limits, instead of inheriting products or dependent loan data from an
older sync run. The reset does not delete products or their dependency graph row
by row; it restores a baseline captured before that entire graph existed.

Versioned, product-independent prerequisites such as reviewed charges, payment
types, chart-of-account rows, and code values belong in Liquibase and are part
of the baseline. They are not sync output and remain available when the loan
service recreates its products.

The operator tool is [`scripts/reset-test-tenant.sh`](../scripts/reset-test-tenant.sh).
It is intentionally separate from `arissto-sync`: the sync engine remains
one-way and contains no delete operation.

The optional orchestration reset wraps this tool with
[`scripts/local-fineract.sh`](../scripts/local-fineract.sh) to stop and restart
the local Gradle development server. Process control does not replace or
duplicate the database reset.

## Safety rules

The tool:

- refuses tenant `default` and database `fineract_default`;
- resolves the database through the Fineract tenant registry rather than
  accepting a database name from the command line;
- refuses remote PostgreSQL hosts;
- requires Fineract to be stopped for capture, reset, and recreation;
- requires exact `TENANT:DATABASE` confirmation for destructive actions;
- verifies the snapshot checksum before restore;
- rejects capture or restore when the baseline contains any loan product, loan,
  native GL journal entry, imported-journal provenance row, trial-balance row,
  annual journal summary, journal aggregation row/watermark, invoice, invoice
  issuer, invoice receiver, invoice line, related invoice document, or invoice
  summary;
- can archive the selected legacy sync SQLite state file before reset; and
- compares core table counts after restore with the captured baseline.

It is only for local disposable test tenants. It must not be adapted into a
production cleanup command.

## One-time preparation for a clean tenant

For a newly migrated and bootstrapped tenant, stop Fineract and capture the
baseline before the first sync cycle:

```bash
./scripts/reset-test-tenant.sh capture sandbox
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

3. Restore the baseline. Do not restore a previous workflow-cycle SQLite file:

   ```bash
   ./scripts/reset-test-tenant.sh reset sandbox \
     --confirm sandbox:fineract_sandbox
   ```

4. Restart Fineract and run `status` again.
5. Create a fresh, named orchestration state cycle tied to the restored baseline,
   then run sync preflight and inspection before producing plans:

   ```bash
   cd tools/arissto-sync
   ./arissto-sync workflow cycle create \
     --cycle sandbox-YYYY-MM-DD-a \
     --baseline-ref sandbox-restored-baseline-YYYY-MM-DD \
     --target local
   ```

Continue using that cycle only while the target remains in the same lifetime.
After any later reset or recreation, create another cycle. Previous cycle files
remain under `.arissto-sync/cycles/` for run and failure comparison and must not be
copied over the fresh cycle.

Successful restore means the PostgreSQL dump was accepted, the captured counts
for `databasechangelog`, clients, staff, loans, savings accounts, and share
accounts match exactly, and every ledger and invoice/DTE transaction table
present in the restored schema is empty. `status` reports the native journal,
imported-journal provenance, trial balance, annual summary, journal aggregation,
and invoice-table counts separately so the operator can verify the
post-Liquibase state as well. DTE configuration in `m_mh_company_config` and
`m_mh_dte_item_component` is intentionally preserved.

## Recreate when no baseline exists

An already-used tenant with no pre-cycle snapshot cannot be rolled back
exactly. Recreate it instead:

```bash
./scripts/reset-test-tenant.sh recreate sandbox \
  --confirm sandbox:fineract_sandbox
```

Then restart Fineract with Liquibase enabled. Once migrations and intentional
test prerequisites are complete, stop Fineract and capture the new baseline.
The `recreate` action does not modify the tenant registry row.

After the new baseline is captured and Fineract is restarted, create a new sync
cycle as shown above. Never use a prior cycle's SQLite file with the recreated
tenant.

## Connection configuration

The script uses standard `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, and
`PGMAINTDB` values. When they are absent, it reads the local PostgreSQL settings
from `fineract-core/.env`, matching the provisioning workflow. PostgreSQL CLI
programs (`psql`, `pg_dump`, `pg_restore`, `dropdb`, and `createdb`) must be on
`PATH`.
