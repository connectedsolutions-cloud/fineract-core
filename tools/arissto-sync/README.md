# Arissto → Fineract local sync

Local, manual, one-way migration tooling. It is not a web application, server,
scheduler, or Fineract runtime component.

For the verified client mapping, operator workflow, expected output, and current
limitations, see the
[`clients` service contract](migration-services/clients/contract.md).

## Migration service registry

For the registry of available and planned migration services, run:

```bash
./arissto-sync services
./arissto-sync services --service clients
./arissto-sync services --service client-pep
./arissto-sync services --service employees
```

Service operating guides and the reusable service template live in
[`migration-services/`](migration-services/README.md).

### Documentation ownership

`migration-services/` is the canonical home for the service registry, service
contracts, readiness/lifecycle status, operating commands, quarantine policy,
reconciliation, and implementation status. Source-table meanings, relationship
evidence, business-domain narratives, hypotheses, and read-only catalog exports
remain in `credesal-db-space/docs/`. Link to that evidence instead of copying it
into service documents. Versioned Fineract schema changes remain authoritative
in their Liquibase files; service documents explain prerequisites and link to
the implementation.

## Safety model

- Arissto is opened read-only and only a single `SELECT`/`WITH` statement is accepted.
- Every command selects exactly one target: `local` or `prod`.
- Readiness and plan applicability are evaluated only against the explicitly selected target; local and production schema signatures are not compared.
- Production apply requires the target fingerprint printed by `preflight`.
- Plans store source keys and normalized hashes, not names, documents, addresses, or payloads.
- Runtime state is local SQLite under `.arissto-sync/` and is separated by target fingerprint.
- No deletes exist. Only explicitly mapped legacy statuses can request deactivation.
- API writes are the default. The direct-SQL allowlist is empty for clients.
- The engine never creates or alters Fineract schema.

## Setup

```bash
cd tools/arissto-sync
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Use a SQL Server login with database-level read-only permissions. Set distinct local
and production profiles. `EXPECTED_HOST` is mandatory and must equal the API URL host.

The Arissto connection is implemented entirely inside this tool and does not import
the exploration repository or require its local HTTP service. Test the source by
itself before configuring either Fineract target:

```bash
./arissto-sync source-check
```

This command needs only the `ARISSTO_*` variables. It reports a non-secret source
fingerprint, SQL Server version, ODBC driver, and whether the login belongs to common
write-capable roles. Passwords containing `$` are preserved literally; quote them in
`.env` when they contain leading/trailing spaces.

## Workflow

```bash
./arissto-sync preflight --target local
./arissto-sync inspect --block clients --target local
./arissto-sync plan --block clients --target local
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync status --block clients --target local
```

To run the reviewed clients plan and then automatically scope PEP to the
successfully reconciled parent clients:

```bash
./arissto-sync apply --plan PLAN_ID --target local --with-pep
```

This synchronous chain stops before PEP if client apply or reconciliation does
not complete successfully.

For controlled test batches, scope the plan to explicit source identities. Repeat
`--source-key` to include more than one client:

```bash
./arissto-sync plan --block clients --target local \
  --source-key AFFILIATION_NUMBER \
  --source-key AFFILIATION_NUMBER
```

The resulting plan contains only those identities; `apply` cannot expand its scope.

For production, inspect first and then type the fingerprint explicitly:

```bash
./arissto-sync apply --plan PLAN_ID --target prod --confirm-production FINGERPRINT
```

Failed entities do not stop the run:

```bash
./arissto-sync retry --run RUN_ID --failed-only --target local
```

### Performance behavior

The client workflow reuses one HTTP session for Fineract requests and one
read-only Arissto connection for the full apply loop. Planning resolves target
client identities, statuses, and tags with a bulk PostgreSQL query.
Reconciliation bulk-loads the source rows and required target fields, then
compares them in memory instead of issuing requests and SQL queries per client.

For a newly created client, identifiers, addresses, and datatable rows are
created directly because they cannot already exist. If an interrupted create is
recovered, the engine deliberately returns to lookup-and-upsert behavior so a
retry remains idempotent.

Client writes are still sequential. This preserves deterministic failure
isolation and avoids overwhelming Fineract or the production database. Add
bounded write concurrency only after measuring API and database capacity in a
controlled environment.

An existing Fineract client can be linked only through an explicit operator action:

```bash
./arissto-sync link --block clients --source-key AFFILIATION_NUMBER \
  --target-id FINERACT_CLIENT_ID --target local
```

## Client block status

`config/clients.json` establishes `dbo.AFI_SOCIO` as the identity spine and
defines the reviewed natural-person identity and KYC/profile mapping. It writes
standard Fineract client fields, identifiers, and sparse rows in seven non-PEP
Credesal client datatables. Home/work addresses stay as plain text in those
datatables. It does not migrate loans,
deposits, balances, schedules, or other product data.

Direct PEP screening is a separate registered `client-pep` service. It depends
on `clients`, owns only `credesal_client_pep`, and can run independently after
the parent clients exist or through the guarded `--with-pep` chain.

The `employees` block implements the reviewed `PERSONAS_EMPRESA` to Fineract
staff-profile contract. It writes core contact data and the complete legacy HR
profile to `credesal_staff_profile`, while excluding application-user creation,
credentials, permissions, and client/loan assignments. It remains registry-blocked until a controlled local
API create/update/reconcile run succeeds. See
[`migration-services/employees/README.md`](migration-services/employees/README.md).

The canonical client key is the exact `AFI_SOCIO.NUMERO_AFILIACION`, stored
without a prefix in Fineract `externalId` and local current mappings. The
company/branch/socio composite remains the Arissto relational join: services
that originate from child tables must join to `AFI_SOCIO` first and then use
the matched affiliation number to resolve the Fineract client.

Before expanded client writes are enabled:

1. Apply tenant migration `0274_add_arissto_client_identifier_types.xml`.
2. Apply tenant migration `0275_allow_duplicate_client_identifier_keys.xml`.
3. Run `inspect` and require an empty global `blockers` list.
4. Add a valid Fineract closure reason under `deactivation.closure_reason_id` before
   applying legacy deactivations.
5. Review plan-level quarantines before every apply.

`inspect` reports fields as core, datatable, missing, derived, or excluded. Plans may
still be generated for review, but are marked non-applicable until readiness gaps are
resolved; missing required source columns block extraction entirely. Supplying
`FINERACT_*_PG_URL` enables physical PostgreSQL
column checks; without it, database existence is reported as unknown rather than
assumed.

Catalog-backed fields are resolved through the target database crosswalk created
by migration `0272`; generated target IDs are never copied between environments.
Plans quarantine unresolved nonzero catalog keys and duplicate passport, NIT,
or residency identifiers without storing their values. Economic-activity key
`0` is treated as null. Duplicate phone/DUI values are allowed, and malformed
emails are omitted rather than quarantining the client.

## Adding a block

Implement a contract, extraction, readiness inspection, planner, and writer. Every field
must be classified as `migrate`, `derived`, or `excluded`, and migrated fields must be
`legacy-owned` or `new-system-owned`. Direct SQL requires a named allowlist entry and
tests covering transaction rollback and post-write verification. Follow the
[`batch-first sync design`](migration-services/README.md#batch-first-sync-design):
bulk-load or chunk source and target reads, reuse connections/sessions, and test
that multi-entity workflows do not regress into unnecessary N+1 database or API
calls.
