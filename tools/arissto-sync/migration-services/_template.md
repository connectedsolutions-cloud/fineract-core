# SERVICE_NAME migration service

## Status

- Registry status: `planned`
- CLI block: none
- Source identity: pending
- Source table(s): pending
- Target writer: pending

## Business scope

Describe what business entity/process this service migrates and what it
explicitly excludes.

## Source and target contract

Document source keys, destination identities, ownership, catalogs, and
idempotency behavior. Link the detailed mapping document and configuration.
When the service belongs to a client, document how its declared Arissto
relationship resolves to `AFI_SOCIO.NUMERO_AFILIACION`; do not use a child
table's bare `ID_SOCIO` as a cross-service key without that master join.

## Preconditions

- Read-only source access verified.
- Target fingerprint verified.
- Required Fineract schema/API resources exist.
- Mapping and catalog translations reviewed.
- Controlled source identities selected.

## Commands

Add the exact `preflight`, `inspect`, `plan`, `apply`, `reconcile`, and `status`
commands only after the CLI block exists.

## Reconciliation and acceptance

Define field/resource checks, expected counts, quarantine behavior, retry
rules, and an idempotent second run.

## Performance and access pattern

Document the bounded batch strategy for source extraction, target identity
resolution, catalog loading, apply preparation, and reconciliation. State:

- which source and target reads are bulk-loaded or chunked;
- which database connections and HTTP sessions are reused;
- how normalized in-memory indexes avoid N+1 database/API calls;
- any unavoidable per-entity call and the consistency or recovery invariant
  that requires it;
- how fresh creates differ from update/interrupted-create recovery; and
- why writes are sequential, or the measured capacity and retry guarantees that
  make bounded concurrency safe.

Add tests that bound query/request counts for a multi-entity scope as well as
tests for partial-failure recovery. Batching must preserve read-only Arissto
access, source-hash verification, parameterized queries, and target-specific
identity resolution.

## Open decisions and blockers

List unresolved semantics or target prerequisites. Keep `executable: false`
until they are resolved and locally verified.
