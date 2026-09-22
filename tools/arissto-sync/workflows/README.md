# Workflow orchestration

This directory owns the machine-readable definitions for dependency-driven
Arissto-to-Fineract sync workflows. See `migration-services/orchestration.md` for
the operating and safety contract.

The workflow files select services and policies. They do not duplicate dependency
edges: the runner derives those from `migration-services/registry.json` and uses
the listed service order only to break ties between independent nodes.

Financial workflows select `accounting_cutoff_policy: activate-frozen-plan`.
Before their first service step, the runner idempotently configures and activates
the cutoff frozen in the parent plan. It reuses an exact active match and rejects
a mismatched active or sealed cutoff before financial writes.

Workflow definitions may also declare reviewed target prerequisites. Workflows
that select loans require Fineract financial activity `100` (`ASSET_TRANSFER`)
to map to active detail asset account `1510`. Workflows that select
`savings-deposits` require activity `200` (`LIABILITY_TRANSFER`) to map to active
detail liability account `2130050101`. The runner creates only these mappings through
the Fineract API when the accounts already exist. It never seeds the chart of
accounts, never replaces a conflicting mapping, verifies each result, and records
the actions before any service step begins.

Version 1 is sequential, full-block, and fail-closed. Local definitions may
support fresh/clean, resumed migration, or checkpointed `full-resync`. A
production definition may support only `full-resync`. Every service selected
by either local or production full re-sync must explicitly declare a reviewed
full re-sync contract.
By default, services whose registry status is not `available`, or whose dependencies
were not selected, prevent a workflow plan from being created. A reviewed local
acceptance workflow may use `unavailable_services: allow-executable` to exercise its
actual dependency graph while a selected service remains registry-blocked. The plan
surfaces that condition as a warning, and a non-executable service is never allowed.

## State cycles

A workflow never uses the legacy shared `state.sqlite3` directly. Before planning,
create a named cycle tied to the exact disposable-tenant baseline:

```bash
./arissto-sync workflow cycle create \
  --cycle sandbox-2026-09-02-a \
  --baseline-ref sandbox-clean-baseline-2026-09-02 \
  --target local
```

For a disposable local tenant with a captured baseline, cycle creation can
optionally restore the baseline first:

```bash
./arissto-sync workflow cycle create \
  --cycle sandbox-2026-09-02-b \
  --baseline-ref sandbox-restored-baseline-2026-09-02 \
  --target local \
  --reset-tenant sandbox \
  --reset-confirm sandbox:fineract_sandbox
```

The reset refuses the default tenant, remote targets, or any queued/running
workflow. It stops Fineract, restores the whole tenant snapshot, restarts the
service, verifies readiness, and creates the cycle only after success.

The base `ARISSTO_SYNC_STATE` setting determines the parent directory. Cycle
state is stored at `.arissto-sync/cycles/<cycle-id>/state.sqlite3`, while
`.arissto-sync/cycles.sqlite3` catalogs every cycle, its baseline reference,
target fingerprint, status, timestamps, and state path.

Use the same cycle ID to continue the same target lifetime. After restoring or
recreating the Fineract test tenant, create a new cycle. Never copy mappings or
active statuses forward: the old cycle remains available for failure comparison.
Closing a cycle prevents new workflow plans or runs without deleting its SQLite
file.

A new downstream selection in the same target lifetime must name its completed,
failed, or interrupted parent with
`workflow plan --resume-from-workflow-run WORKFLOW_RUN_ID`. The
resulting resumed plan freezes parent child-run identities. At execution time it
reruns reconciliation for those services and skips their plan/apply phases only
when reconciliation still passes; all newly selected services continue normally.

Inspect local state and runner-log growth without loading source or target
credentials:

```bash
./arissto-sync health
```

The health report measures total, SQLite, and workflow-log bytes; highlights
large logs and inactive cycles left open; and reports repeated local TLS warning
output. It is read-only and never deletes rows or files. The reported local
sandbox retention baseline keeps the newest cycle complete and removes every
older cycle database, runner log, summary, failure archive, and catalog entry.

Apply that policy only after reviewing its exact actions:

```bash
./arissto-sync retention plan --scope local
./arissto-sync retention apply --scope local --confirm APPLY-RETENTION
```

The creation of a new cycle applies local retention automatically after the new
baseline cycle is established. Retention never prunes rows inside the newest
cycle, and replacement is refused while any cataloged workflow is queued or
running.

The durable `.arissto-sync/change-tracker.sqlite3` database is outside this
cycle-retention boundary. Commit/change records, impacted loan IDs, and decisions
remain available across fresh/clean runs; only operational cycle state is removed.

## Definitions

- `prod-party-resync`: production-only, checkpointed source-hash delta sync for
  Clients, Employees, current client-staff assignments, PEP, and accepted family
  references. It does not reset the target, perform deletes, or include financial
  services. Each service requires an accepted production reconciliation
  checkpoint before planning.
- `prod-full-resync`: production-only, checkpointed delta sync for all 15
  registry-available services in the same dependency order as
  `local-full-resync`. It preserves the production target, freezes the accepted
  accounting cutoff shared by every checkpoint, skips unchanged source hashes,
  and requires exact fingerprint confirmation plus a versioned release. Its
  existence does not enable the production timer; deployment promotion remains
  a separate reviewed operation.

- `local-full-sync`: all 16 available registry services in one dependency-complete
  local workflow. Accounting journal entries run immediately before native share yield.
  Dashboard runs default to the complete ledger through the inclusive
  source-through date; the engine derives the first Fineract-owned date as the
  following day. Operators may supply a source period to narrow a test. This is
  the dashboard default for a fresh run.
- `local-full-resync`: all 16 registry services in one checkpointed
  local delta workflow. It requires the current open cycle and one accepted
  reconciliation checkpoint per selected service, preserves the sandbox target,
  skips unchanged source hashes, and does not infer deletions.
- `local-party-profile`: clients, employees, current client-level promoter,
  account-executive and collections-manager assignments, PEP, and family
  references.
- `local-membership-financial`: clients, membership records, savings/deposits,
  and native shares.
- `local-credit-collections`: clients, employees, client-level staff assignments,
  savings, loans (including the separate loan-level staff assignment), and Mobile
  Collections plus fiscal DTE history. All selected services are registry-available;
  runtime inspection and reconciliation gates still apply.

## Failure identity and privacy

Workflow diagnostics store the service ID, execution phase, item status, error
code, and the existing opaque Arissto `source_key`. A deterministic failure
fingerprint makes the same failure comparable across runs. Names, documents,
addresses, source rows, destination payloads, and credentials must not be copied
into orchestration state.

When an upstream failure prevents a dependent service from starting, the runner
creates a service-level `blocked` failure and links it to the upstream failure.
The schema supports more detailed links later, but version 1 does not guess that
two differently shaped source keys identify the same business entity.

## Durable state

Each cycle SQLite database contains state identity plus five orchestration tables
in addition to the block-level plan/run state:

- `workflow_plans`: immutable definition, ordering, preflight, and target identity;
- `workflow_runs`: parent lifecycle, PID, heartbeat, current phase, and summary;
- `workflow_steps`: one row per service attempt with child plan and run IDs;
- `workflow_failures`: comparable service/phase/source-key failure facts; and
- `workflow_failure_links`: `blocked-by` and exact `same-source-key` relationships.

`workflow history` groups the deterministic fingerprints across runs and, when
no cycle is supplied, across preserved cycle databases. This makes it
possible to distinguish newly introduced, recurring, and no-longer-observed
failures without retaining source payloads.
