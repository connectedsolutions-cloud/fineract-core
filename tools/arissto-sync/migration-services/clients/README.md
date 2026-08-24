# Clients migration service

## Status

- Registry status: `available`
- CLI block: `clients`
- Canonical sync identity: `NUMERO_AFILIACION`
- Relational source identity: `ID_EMPRESA:ID_SUCURSAL:ID_SOCIO`
- Source table: `dbo.AFI_SOCIO`
- Target writer: Fineract API only

The service supports the reviewed natural-person identity and KYC/profile
contract: core client fields, typed identifiers, and seven non-PEP Credesal
client datatables. Home and work addresses remain plain text in those datatables.
Loans, deposits, balances, and other product records are outside this service.

Fineract `externalId` and new sync-state keys use the exact, unprefixed
`AFI_SOCIO.NUMERO_AFILIACION`. The engine recognizes the earlier
`arissto:afi_socio:<empresa>:<sucursal>:<socio>` IDs and composite state keys
only to update existing clients in place. `inspect` requires affiliation
numbers to be populated and globally unique and refuses old/new identity
collisions.

All imported clients are created or maintained as active.
`AFI_SOCIO.FECHA_REGISTRO` maps to Fineract `activationDate`; it is the Arissto
record-creation date used after the client was approved and documentation was
ready. The same date is used as Fineract `submittedOnDate` so the imported
timeline satisfies `submittedOnDate <= activationDate`, including recovery of
clients created during an interrupted run.
Fineract also forbids client activation before the assigned office opening
date. Seventeen branch-002 records predate its 2024-12-11 opening; those use
2024-12-11, the earliest target-valid activation date. All other clients retain
their exact `FECHA_REGISTRO` date.

Every imported client receives exactly one active `tipo_cliente` tag. Current
Arissto relationship `003` maps to `cliente`. Relationship `001` maps to
`socio`, except when an originated `CRD_CARTERA` credit exists, in which case
it maps to `cliente-socio`. Client-extension tables `cliente2` and `CLIENTE`
are not role classifiers and are not used for this decision. Tag IDs are
resolved independently in each target and are never hard-coded.

The implementation is available, but a plan is applicable only when target
readiness passes. Migration `0274` must add the NIT and residency-card types,
migration `0275` must allow the same identifier key on different clients, and
migration `0276` must ensure the three client-type tags exist and are active.
The structured Fineract address module is not required by this service.
See [`contract.md`](contract.md) for the complete service contract. Direct PEP
screening is owned by the dependent
[`client-pep` service](../client-pep/README.md), which can be chained after a
successful client reconciliation with `apply --with-pep`. See
[`../client-system-codes/contract.md`](../client-system-codes/contract.md) for
the catalog/bootstrap contract.

## Check readiness

```bash
./arissto-sync preflight --target local
./arissto-sync inspect --block clients --target local
```

Continue only when `ready: true` and `blockers` is empty.

Known source-data problems are reported as per-client quarantine actions rather
than global readiness blockers. Economic-activity key `0` is an Arissto
missing-value sentinel and becomes null; other unresolved nonzero keys still
quarantine. Shared phone and DUI values are valid. Malformed emails become null
so neither condition quarantines a client.

The API writer accounts for Fineract response/parsing details verified by
the controlled local run: an empty generic datatable result means the row must
be created, identifier status updates require the enum token `ACTIVE`, and
datatable JSON numbers use locale `en` so decimal points are not interpreted as
Spanish thousands separators. Because a `tagIds` update replaces the complete
tag set, the writer preserves active tags outside `tipo_cliente` while replacing
only the managed client-type tag.

Planning and reconciliation use bulk source and PostgreSQL reads rather than
per-client API lookups. The apply command reuses its source connection and HTTP
session. Fresh creates skip existence lookups for child resources; recovered or
updated clients retain lookup-and-upsert behavior for safe retries. Writes remain
sequential by design so one client's failure is isolated and target load stays
bounded.

## Controlled local run

```bash
./arissto-sync plan --block clients --target local \
  --source-key NUMERO_AFILIACION
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync status --block clients --target local
```

To apply the reviewed client plan and then synchronize PEP for exactly the
successfully reconciled client scope:

```bash
./arissto-sync apply --plan PLAN_ID --target local --with-pep
```

The PEP step does not start if client reconciliation fails.

Review the plan before applying it. Omitting every `--source-key` creates a
full-block plan and is not authorized merely by this service being available.

To reconcile the client run and then automatically synchronize family
references belonging only to the successfully processed client affiliations,
use the opt-in dependent workflow:

```bash
./arissto-sync apply --plan CLIENT_PLAN_ID --target local \
  --with-family-references
```

This flag does not make family references part of the client transaction.
Client apply and reconciliation finish first; any client reconciliation error
stops the workflow before the family-reference plan is created. Without the
flag, client apply remains unchanged and client-only. See
[`../client-family-references/README.md`](../client-family-references/README.md)
for the dependent service contract and reconciliation behavior.

Production requires its own preflight/inspection and exact fingerprint
confirmation:

Production readiness and plan applicability are evaluated independently from
the local target. A stale or unavailable local environment does not block a
production plan.

```bash
./arissto-sync apply --plan PLAN_ID --target prod \
  --confirm-production FINGERPRINT
```
