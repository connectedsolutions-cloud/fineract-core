# Migration services registry

This directory is the durable catalog of Arissto-to-Fineract migration
services. It answers three questions before an operator runs anything:

1. What services exist?
2. Which services are actually executable and ready?
3. What is the reviewed command sequence and documentation for each service?

The machine-readable index is `registry.json`. Each service also has a folder
with its guide and detailed contract.

## Documentation ownership

This directory is the single front door for migration-service information:

| Information | Canonical location |
|---|---|
| Service list, lifecycle, executability, and document pointers | `registry.json` |
| Business scope and operator workflow | `<service-id>/README.md` |
| Detailed source-to-target mapping, readiness, quarantine, and reconciliation contract | `<service-id>/contract.md` |
| Completed delivery gates and independent production sequence, when needed | `<service-id>/implementation-sequence.md` |
| Multi-service dependency and daily-run orchestration design | `orchestration.md` |
| Reusable shape for a future service | `_template.md` |
| Arissto table meanings, source evidence, and business-domain research | `credesal-db-space/docs/` |
| Fineract schema implementation | Versioned Liquibase changes in `credesal-sistema` |

Do not copy source-research narratives into this directory. Link to the relevant
learning note and record only the migration decision here. Likewise, do not
store service status, plan snapshots, or operator instructions in the
exploration repository. Cross-project facts should have reciprocal links.

## Check available services

From `tools/arissto-sync`:

```bash
./arissto-sync services
./arissto-sync services --service clients
./arissto-sync services --service client-pep
./arissto-sync services --service client-family-references
./arissto-sync services --service employees
./arissto-sync services --service client-staff-assignments
./arissto-sync services --service membership-share-capital
./arissto-sync services --service savings-deposits
./arissto-sync services --service native-share-capital
./arissto-sync services --service aml-alerts
./arissto-sync services --service loans
./arissto-sync services --service mobile-collections
./arissto-sync services --service accounting-journal-entries
```

The first command lists every registered service. The second returns one
service with its status, documentation, configuration, and commands.

The registry is informational. It does not bypass `preflight`, `inspect`,
explicit plans, target selection, production confirmation, or any other safety
guard.

## Run a service

Only services with `executable: true` can be run through the sync engine. Use
the command sequence in that service's `README.md`. The standard block workflow
is:

```bash
./arissto-sync preflight --target local
./arissto-sync inspect --block BLOCK --target local
./arissto-sync plan --block BLOCK --target local --source-key REVIEWED_KEY
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync status --block BLOCK --target local
```

Never interpret a registry entry as authorization for a full-block or
production apply.

Dependencies are declared with `depends_on`. A dependency declaration is not
itself a scheduler: when a service exposes an `apply_after_clients` command,
the CLI executes the documented synchronous chain and stops if the parent
reconciliation fails. Registry loading rejects missing, self-referential, and
cyclic dependencies.

The planned generic composition model, including the first
`clients → employees → client-staff-assignments` flow, is documented in
[`orchestration.md`](orchestration.md). It also owns the currently required
[manual loans-to-mobile-collections sequence](orchestration.md#current-manual-loans-to-mobile-collections-flow).
Individual service guides continue to own their block-specific behavior.

## Status values

| Status | Meaning |
|---|---|
| `available` | Implemented in the CLI and eligible for reviewed local runs |
| `export-ready` | A read-only discovery/export step exists; target migration is not implemented |
| `planned` | Design exists but the service cannot be run |
| `blocked` | Implementation exists but a documented prerequisite prevents use |
| `retired` | Kept for historical reference and must not be run |

## Batch-first sync design

Design read paths around bounded batches, not one database or API request per
entity. A new service should avoid N+1 access patterns in inspection, planning,
apply preparation, and reconciliation:

- extract the reviewed source scope once, or in explicit chunks when the scope
  is too large for one result set;
- collect destination identities first and resolve them with parameterized bulk
  queries such as `ANY`/`IN`, then build in-memory indexes by source and target
  identity;
- load catalogs, schema metadata, statuses, and reconciliation fields once per
  phase or batch instead of once per entity;
- reuse database connections and authenticated HTTP sessions for the complete
  workflow phase;
- reconcile from bulk source and target snapshots and compare normalized
  payloads in memory; and
- use direct child-resource creates when a freshly created parent proves the
  child cannot exist, while retaining lookup-and-upsert recovery for existing
  or interrupted entities.

Batching must not weaken safety. Queries remain parameterized and read-only on
Arissto, every applied entity must still match its reviewed source hash, and
large batches must be chunked to respect driver, statement-parameter, memory,
API, and target-capacity limits. Per-entity reads are acceptable only when the
destination API lacks a bulk alternative or when they enforce a documented
consistency/recovery invariant.

Writes remain sequential by default for deterministic failure isolation.
Introduce bulk writes or bounded concurrency only when the target contract is
idempotent, partial failures can be attributed and retried safely, and measured
API/database capacity supports the chosen limit. Tests should cover the normal
batch path, the interrupted-run recovery path, and bounded query/request counts
so later changes do not accidentally reintroduce N+1 calls.

## Add a service

1. Create `SERVICE_ID/README.md` from `_template.md` and add
   `SERVICE_ID/contract.md` when detailed mapping is needed.
2. Add the service to `registry.json`.
3. Implement its contract, extraction, inspection, planning, writer, and
   reconciliation behavior when it is an executable sync block. Document its
   batch boundaries and any justified per-entity calls.
4. Add the block to the CLI choices only after tests and readiness checks exist.
5. Set `executable: true` and `status: available` only after a controlled local
   run reconciles successfully.
6. Never place credentials, client data, generated plans, or state databases in
   this directory.

The service ID must remain stable because plans and operational documentation
may refer to it.
