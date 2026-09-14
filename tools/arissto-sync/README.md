# Arissto → Fineract local sync

Local, manually started, one-way migration tooling. It is not a web application,
hosted service, scheduler, or Fineract runtime component. Dependency-driven local
workflows can run in a detached one-shot process and persist their progress in the
same local SQLite state store.

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
The proposed dependency-driven daily workflow is defined separately in
[`migration-services/orchestration.md`](migration-services/orchestration.md);
machine-readable local workflow definitions live under [`workflows/`](workflows/).

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

### Dependency-driven local workflows

Inspect a workflow definition without connecting to either database:

```bash
./arissto-sync workflow list
./arissto-sync workflow inspect --workflow local-party-profile
```

## Sync run modes

Use one explicit run mode when discussing or planning a workflow:

- **Fresh/clean run** restores the entire disposable tenant from the approved
  baseline, creates a new cycle, verifies the target is clean, and performs the
  initial migration from one frozen cutoff.
- **Full re-sync** keeps an already reconciled database and applies only source
  deltas after the last accepted checkpoints. It never cleans the target or
  replays already mapped history. This mode must remain unavailable for any
  service that does not yet implement a reviewed incremental contract.
- **Resumed sync** continues an incomplete migration in the same cycle and
  target lifetime. It skips already completed and still-valid service groups
  and continues pending, failed, blocked, or newly selected downstream groups.

The definitive cross-project contract is
[`ARISSTO_SYNC_RUN_MODES.md`](../../../docs/ARISSTO_SYNC_RUN_MODES.md). Avoid the
ambiguous terms **new run**, **full sync**, and **rerun** without naming one of
these modes.

The commands below describe the currently implemented fresh/clean workflow.
Create an immutable local workflow plan after target preflight, then start it in
a detached process:

```bash
./arissto-sync workflow cycle create \
  --cycle sandbox-2026-09-02-a \
  --baseline-ref sandbox-clean-baseline-2026-09-02 \
  --target local

./arissto-sync workflow plan \
  --workflow local-party-profile \
  --cycle sandbox-2026-09-02-a \
  --target local

./arissto-sync workflow start \
  --workflow-plan WORKFLOW_PLAN_ID \
  --cycle sandbox-2026-09-02-a \
  --target local
```

To run only selected services, repeat `--include-service`. The planner adds and
freezes every registry prerequisite. For example, this selection runs Clients,
Employees, and Loans, but not Savings Deposits or Mobile Collections:

```bash
./arissto-sync workflow plan \
  --workflow local-credit-collections \
  --include-service loans \
  --cycle sandbox-2026-09-02-a \
  --target local
```

To continue the same target lifetime without replaying already reconciled
prerequisites, create a resumed plan from a completed, failed, or interrupted
workflow run. The runner
reconciles those parent services again and skips their plan/apply phases only
when that validation remains successful:

```bash
./arissto-sync workflow plan \
  --workflow local-full-sync \
  --include-service accounting-journal-entries \
  --resume-from-workflow-run WORKFLOW_RUN_ID \
  --cycle CYCLE_ID \
  --target local
```

The workflow plan freezes an accounting cutoff equal to its creation date in
`America/El_Salvador`. Add `--cutoff-date YYYY-MM-DD` when an explicit boundary
is required; child plans, apply, retry, and reconciliation retain that value.

`start` returns a workflow run ID immediately. The process continues after the
terminal command returns. Progress, child plan/run IDs, item failures, dependency
failure links, and crash state remain queryable:

```bash
./arissto-sync workflow status --workflow-run WORKFLOW_RUN_ID --cycle sandbox-2026-09-02-a --target local
./arissto-sync workflow history --workflow local-party-profile --target local
./arissto-sync workflow resume --workflow-run WORKFLOW_RUN_ID --cycle sandbox-2026-09-02-a --target local
./arissto-sync workflow stop --workflow-run WORKFLOW_RUN_ID --cycle sandbox-2026-09-02-a --target local
```

Pass `--cycle sandbox-2026-09-02-a` to `status`, `resume`, and `stop`. Omitting
`--cycle` from `history` compares the workflow across every preserved cycle;
supplying it limits the report to one cycle.

For a visual view of preserved workflow runs and their failure records, start
the local dashboard:

```bash
.venv/bin/python sync-dashboard/server.py
```

Open <http://127.0.0.1:8787>. The dashboard reads the same per-cycle SQLite
state, defaults to the latest service attempts, and can also show the full retry
history. Reporting is read-only. Its guarded **Fresh/clean run** flow creates a
fresh cycle after the operator confirms local Fineract was reset or restored. An
optional guarded step can stop local Fineract, restore a captured disposable
tenant baseline, restart it, and verify readiness first. The flow then lets the
operator check desired services, visibly adds and locks their prerequisites,
and prepares an immutable plan. Approving the reviewed plan immediately starts
the existing orchestrator against local Fineract. The cycle record itself only
tracks state; the optional pre-step is what performs the reset. The dashboard
never offers a production target and Arissto remains read-only.

Every tenant reset or recreation must be followed by a new `workflow cycle
create`. Each cycle gets a separate SQLite file under `.arissto-sync/cycles/`,
so mappings and run statuses from an older target lifetime cannot be reused.
Close a finished cycle without deleting its evidence:

```bash
./arissto-sync workflow cycle close --cycle sandbox-2026-09-02-a
```

Inspect disk consumption and retention risks without loading source or target
credentials:

```bash
./arissto-sync health
```

The command is read-only. It reports SQLite and runner-log bytes, unusually
large logs, repeated local TLS warnings, and inactive cycles that may have been
left open. It exits with status `2` when it finds a warning so it can serve as a
local or CI health gate. Use `--max-total-mb`, `--max-run-log-mb`, and
`--stale-open-days` to adjust its local thresholds.

Preview and then explicitly apply the retention policy without loading database
credentials:

```bash
./arissto-sync retention plan --scope all
./arissto-sync retention apply --scope all --confirm APPLY-RETENTION
```

For local workflows, only the newest cycle is retained. Creating a new cycle
automatically runs local retention after the replacement baseline is established:
every older cycle database, runner log, summary, failure archive, and catalog entry
is removed. The newest cycle remains complete, including every plan, run, item,
mapping, and log. Cycle replacement is refused while any cataloged workflow is
queued or running. Legacy local rows in the shared pre-cycle state database are
also removed once no legacy run is marked active; production rows are isolated by
their recorded target fingerprint and remain untouched.

Production is handled separately inside the shared legacy state database. It
retains durable operational mappings and links, plus only the single latest run
globally and that run's plan and items. All older and unexecuted production plans,
run history, items, and inspections are removed except for the newest inspection.
The policy runs automatically after every production apply, leaving the completed
or failed run available for reconciliation and retry until the next run. Use
`--scope prod` to apply only that policy manually. Production
fingerprints are discovered from recorded inspections; `--prod-fingerprint` can
be repeated when an older fingerprint lacks inspection history.

Workflow orchestration accepts only `--target local`. Individual block commands
retain their existing explicit local/production behavior. A per-target file lock
prevents overlapping workflow writers, and a missing runner process converts a
queued/running workflow into `interrupted` when status is inspected. Resume keeps
completed steps and creates a new attempt only for failed, blocked, or interrupted
steps.

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
