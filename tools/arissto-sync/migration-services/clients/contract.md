# Client migration details

This document describes the implemented `clients` block of the local
Arissto-to-Fineract synchronization engine. It reflects the identity and
KYC/profile expansion verified on 2026-08-12.

## Scope and operating model

The engine is a local, manually triggered CLI under
`fineract-core/tools/arissto-sync`. Arissto is strictly read-only. All client,
identifier and datatable writes use Fineract APIs; direct SQL writes
are denied for this block.

The relational source identity spine is `dbo.AFI_SOCIO`, keyed by:

```text
ID_EMPRESA:ID_SUCURSAL:ID_SOCIO
```

The canonical cross-service client key is the globally unique
`AFI_SOCIO.NUMERO_AFILIACION`. Each source client receives that value directly
as the Fineract external ID:

```text
<NUMERO_AFILIACION>
```

The 2026-08-14 read-only source audit found 1,029 populated and 1,029 distinct
affiliation numbers. Every current value equals the same row's `ID_SOCIO`, but
the migration uses `NUMERO_AFILIACION` because its unique index enforces the
global uniqueness required after removing company and branch from the external
ID. `inspect` blocks planning when this field is missing, blank, or duplicated.

Cross-service linking must preserve the relational meaning of Arissto child
tables. A future credit, savings, contribution, or other service must first
join its source row to `AFI_SOCIO` through the declared composite relationship
(`ID_EMPRESA`, the appropriate socio branch, and `ID_SOCIO`) or through the
declared `ID_ASOCIADO` relationship. It then uses the matched master row's
`NUMERO_AFILIACION` to resolve the client mapping. Child tables must not treat a
bare `ID_SOCIO` as the canonical cross-service key merely because the current
values happen to be globally unique.

The service owns natural-person identity and KYC/profile information. It
excludes loans, deposits, balances, schedules, transactions, penalties,
interest, and all other product or calculated records.

## Fineract destinations

### Core client

| Arissto | Fineract | Rule |
|---|---|---|
| `NOMBRE_SOCIO` | `m_client.firstname` | Trimmed legacy-owned value |
| `APELLIDO_SOCIO` | `m_client.lastname` | Trimmed legacy-owned value |
| `FECHA_NACIMIENTO` | `m_client.date_of_birth` | Date only |
| `SEXO` | `m_client.gender_cv_id` | Resolve `Gender` value by name in each target |
| `TELEFONO_PERSONAL` | `m_client.mobile_no` | Shared values are valid and preserved |
| `EMAIL` | `m_client.email_address` | Trim and validate; malformed values become null |
| `NUMERO_AFILIACION` | `m_client.external_id` | Globally unique canonical client key, stored without a prefix |

Branch `001` maps to office `1` and branch `002` maps to office `2`. New
clients are active and use `legalFormId=1` (`PERSON`). Source relationship
classes `001` (`SOCIO`) and `003` (`CLIENTE`) are both included in this
approved all-active import policy.

`ID_SOCIO` is not copied to `accountNo`; Fineract owns its account number.

### Client relationship tag

Each imported client has exactly one active Fineract tag in group
`tipo_cliente`:

| Arissto rule | Fineract tag |
|---|---|
| `AFI_SOCIO.ID_ESTADO_SOCIO = 003` | `cliente` |
| `ID_ESTADO_SOCIO = 001` and no matching originated credit | `socio` |
| `ID_ESTADO_SOCIO = 001` and a matching `CRD_CARTERA` row exists | `cliente-socio` |

The credit existence check uses the declared party relationship through
`ID_EMPRESA`, `ID_SUCURSAL_SOCIO`, and `ID_SOCIO`. A mere credit application
does not create the combined role. The similarly named `cliente2` and
`CLIENTE` tables are operational and fiscal extensions, respectively, and do
not determine this role.

Target IDs are resolved from active `m_client_tag` rows by normalized group and
name. `inspect` blocks a plan when a required semantic tag is missing,
inactive, or duplicated. Migration `0276_ensure_client_type_tags.xml` provides
the versioned target prerequisite. Creates send the tag with the initial API
request. Updates replace only the managed `tipo_cliente` assignment and retain
active tags from other groups. Reconciliation requires exactly one matching
type tag.

### Legacy external-ID transition

Earlier local runs stored external IDs as
`arissto:afi_socio:<empresa>:<sucursal>:<socio>` and stored composite source
keys in local state. During the transition, planning resolves both that legacy
external ID and the canonical affiliation number. If they resolve to different
Fineract clients, inspection/apply refuses the migration with an identity
collision instead of guessing. Otherwise, the existing target client is
updated in place with the simple external ID.

The engine also falls back to legacy composite mappings and operator links.
After a client succeeds, it saves the mapping under `NUMERO_AFILIACION` and
removes the superseded current mapping/link key. Historical plans, runs, and
items remain immutable audit history. Stale plans created under the old client
contract cannot be applied because the contract hash changes.

### Identifiers

The service upserts one active identifier per configured type:

| Arissto | Fineract `Customer Identifier` value |
|---|---|
| `DUI` | `Id` |
| `PASAPORTE` | `Passport` |
| `NIT` | `NIT` |
| `CARNE_RESIDENCIA` | `Carné de residencia` |

New tenant migration `0274_add_arissto_client_identifier_types.xml` adds the
last two values without changing previously applied migrations. Fineract IDs
are resolved by code/value name and are never hard-coded.

Migration `0275_allow_duplicate_client_identifier_keys.xml` removes the global
cross-client uniqueness constraint on `(document_type_id, document_key)` while
preserving Fineract's one-active-identifier-per-type-per-client rule. Duplicate
DUI values are copied. Duplicate passport, NIT, or residency identifiers remain
quarantined by the sync contract. Duplicate phones are allowed by migration
`0271`.

### Addresses

The migration deliberately keeps addresses simple. Home address text,
municipality, department, and country are stored in
`credesal_client_datos_personales`; work address text and its geography are
stored in the work-related KYC datatables.

The service does not write `m_address` or `m_client_address` and does not
require Fineract's `enable-address` setting. The structured address module can
be evaluated separately later without blocking this migration.

### Credesal KYC datatables

The service maps reviewed fields into seven non-PEP client datatables:

- `credesal_client_datos_personales`
- `credesal_client_trabajo`
- `credesal_client_informacion_laboral`
- `credesal_client_ingresos_egresos_mensuales`
- `credesal_client_remesas`
- `credesal_client_informacion_complementaria`
- `credesal_client_actividad_mensual`

A datatable row is created only when at least one mapped value is non-null.
Catalog-backed text is resolved from the target `0272` snapshot so text and
target IDs come from the same reviewed catalog data.

#### PEP ownership boundary

The `clients` block no longer reads, hashes, writes, or reconciles
`credesal_client_pep`. Direct PEP screening is owned by the separately
registered [`client-pep` service](../client-pep/contract.md), which depends on
this service and can be triggered after successful client reconciliation with
`apply --with-pep`.

The versioned contract is [`config/clients.json`](config/clients.json). It
classifies every destination as `migrate`, `derived`, or `excluded`. Unverified
meanings are excluded rather than guessed, including US citizenship, PEP
relationship/details, housing type/tenure, remittance relationship/time units,
operation-periodicity labels, and inferred financial totals.

### Economic activity and null values

Arissto stores the primary economic-activity lookup in
`AFI_SOCIO.ID_ACT_ECONOMICA1`. When populated with a real activity ID, the
service resolves it against `AFI_ACT_ECONOMICA` and the target catalog snapshot
created by migration `0272`. The resolved description is written to:

- `credesal_client_datos_personales.desc_actividad_economica`; and
- `credesal_client_ingresos_egresos_mensuales.actividad_economica_1`.

The source audit initially reported two unresolved rows. Direct inspection
confirmed that both contain integer `0`; neither contains open text. The
related `ACT_PRINCIPAL` and `CODIGO_ACTIVIDAD` fields are null. In Arissto,
economic activity is commonly absent for students and employees, so profession
must not be used to infer an economic activity.

The migration applies these rules before payload hashing, planning, writing,
and reconciliation:

| Arissto value | Migration result |
|---|---|
| SQL `NULL` | Fineract datatable value remains null |
| Integer `0` or text representation `"0"` | Normalize to null as an Arissto missing-value sentinel |
| Valid nonzero catalog key | Write the resolved economic-activity description |
| Unresolved nonzero key | Quarantine only that client as `unresolved_catalog:economic_activity` |

Null is an accepted value and does not quarantine the client. The migration
does not create a catalog entry or crosswalk for key `0`, does not substitute
`Otros`, and does not derive `Estudiante` or `Empleados` from `PROFESION`.
This preserves the distinction between a person's profession and an
entrepreneurial or commercial economic activity.

The same null rule applies to optional secondary and tertiary activity fields.
A KYC datatable row is skipped only when every mapped value for that table is
null; a null activity by itself does not discard other available KYC values.

## Readiness and quarantine

Run:

```bash
./arissto-sync preflight --target local
./arissto-sync inspect --block clients --target local
```

`inspect` verifies:

- every selected `AFI_SOCIO` column;
- the physical and API-exposed KYC datatable schemas;
- migration `0272` catalog/crosswalk contents;
- required gender and identifier code values;
- every populated source catalog key, with unresolved counts.

Do not apply unless `ready: true` and the global `blockers` list is empty.
Source catalog results with `plan_behavior: quarantine` are per-client data
warnings rather than blockers for every valid client.

After adopting the permissive DUI/email policy, the aggregate read-only audit
of all 1,029 source rows produces:

| Outcome | Clients |
|---|---:|
| Ready | 1,029 |
| Quarantined | 0 |

The two records previously reported as orphan economic activities are included
in the ready count because their sentinel-zero values now normalize to null.

Migration `0274` is applied locally. Migration `0275` must be applied before
the new all-client plan can be used.

The refreshed 2026-08-13 full non-applying plan contains 1,029 unique source
keys: 1,027 creates and 2 updates to the previously migrated test clients. It
has no quarantines. It is deliberately non-applicable until migration `0275`
removes the target constraint.

Plans and local state contain source keys, hashes, actions, target IDs, and
coarse error/quarantine codes. They do not contain names, document numbers,
addresses, phones, emails, or API payloads.

## Using `inspect` and `plan`

These commands apply only to the `clients` block: core client profile fields,
client identifiers, plain-text address/profile information, and the eight
Credesal KYC datatables. They do not include loans, deposits, balances,
transactions, schedules, interest, penalties, or other product data.

Both commands are preparatory and do not write client or KYC records to
Fineract.

### Inspect local readiness

```bash
./arissto-sync inspect --block clients --target local
```

Use `inspect` after applying Fineract migrations or changing the client
contract. It checks the Arissto source columns, local Fineract API and physical
datatable schemas, required catalogs and crosswalks, identifier types, and
target constraints such as the duplicate-identifier constraint removed by
migration `0275`.

Do not proceed to an applicable plan until the result contains:

```json
{
  "ready": true,
  "blockers": []
}
```

### Build the complete client/KYC plan

```bash
./arissto-sync plan --block clients --target local
```

With no `--source-key`, `plan` evaluates every `AFI_SOCIO` client. It compares
the normalized Arissto payload with target-specific mappings and classifies
each source key as `create`, `update`, `unchanged`, `deactivate`, or
`quarantine`. It records a local, target-scoped plan and returns its `plan_id`,
but it does not execute the planned Fineract API writes.

Review at least:

- `applicable` is `true`;
- `readiness_blocker_count` is `0`;
- action `counts` match the expected source population; and
- every quarantine reason, if any, has an approved disposition.

The exact action mix depends on prior controlled or interrupted runs. The
reviewed full population is 1,029 unique source keys with no quarantines.

Only the explicit `apply` command writes the plan:

```bash
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
```

The operational sequence is therefore:

```text
inspect -> plan -> apply -> reconcile
 check      preview   write    verify
```

## Controlled workflow

After readiness passes, create a small explicit plan:

```bash
./arissto-sync plan --block clients --target local \
  --source-key NUMERO_AFILIACION \
  --source-key NUMERO_AFILIACION
```

Review `counts`, every action, and any quarantine reason before applying:

```bash
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync status --block clients --target local
```

Each client is processed independently. A failed or quarantined client does not
stop the remainder. Interrupted creation is recovered through the deterministic
external ID. Replanning unchanged legacy-owned data produces `unchanged` and
performs no repeated API writes.

Within each eligible client, dependency order is fixed:

1. create or update the Fineract core client and obtain its `m_client.id`;
2. create or upsert each available DUI/passport/NIT/residency identifier using
   that client ID and the already-seeded `m_code_value` identifier type; and
3. create or upsert each nonempty KYC datatable row using the same client ID.

Fresh clients use direct API creates for identifiers and datatable rows because
those child resources cannot already exist. Existing clients and clients
recovered after an interrupted create use lookup-and-upsert behavior so retries
remain idempotent. The apply loop reuses one read-only Arissto connection and
one Fineract HTTP session; client writes remain sequential so failures stay
isolated and destination load remains bounded.

All seven KYC datatables and `m_client_identifier` reference `m_client`; the
KYC datatables do not reference one another. A mapping is recorded only after
all writes for the client succeed. If a later API call fails after core client
creation, retry finds the client by deterministic external ID and idempotently
continues the identifier/datatable upserts. Reconciliation then compares core,
identifier, and datatable values with the current normalized source payload.
Planning bulk-loads target client identities, statuses, and tags. Reconciliation
bulk-loads the current source population and required PostgreSQL target fields,
then performs payload comparisons in memory rather than querying once per
client.

Failed items can be retried without rerunning successful ones:

```bash
./arissto-sync retry --run RUN_ID --failed-only --target local
```

An existing Fineract client can be linked only through an explicit reviewed
command:

```bash
./arissto-sync link --block clients \
  --source-key NUMERO_AFILIACION \
  --target-id FINERACT_CLIENT_ID \
  --target local
```

## Full-block and production safeguards

Omitting `--source-key` plans all source clients. Do not apply a full-block plan
until:

1. migrations `0274`, `0275`, and `0276` are applied;
2. the active-import policy is approved; and
3. a controlled local edge-case run has reconciled successfully.

Production requires its own `preflight` and `inspect` and its exact target
fingerprint:

```bash
./arissto-sync apply --plan PLAN_ID --target prod \
  --confirm-production FINGERPRINT
```

Local plans, runs, mappings, links, and errors are stored in the ignored
`.arissto-sync/state.sqlite3` and remain target-scoped.

## Verification completed

The original two-client basic run, one client per branch, created inactive
natural-person clients and reconciled successfully; a repeated plan/apply was a
no-op.

After the KYC expansion, a new non-applying plan for those same two clients
successfully extracted and normalized core fields, identifiers, and datatable
payloads and classified both as updates. No KYC client records were written
during this verification.

After adopting the economic-activity, duplicate-DUI, and malformed-email
policies, the full read-only plan covers all 1,029 clients with no quarantine
actions. All economic-activity catalog inspections report zero unresolved keys
and rows. Automated coverage includes duplicate DUI copying, malformed-email
omission, integer/string activity zero, continued quarantine of unknown nonzero
activity keys, and duplicate protection for the other identifier types.

The 2026-08-13 controlled local run then migrated 10 exact source keys and
reconciled all 10 across core client fields, identifiers, and KYC datatables.
Replanning the same scope classified all 10 as unchanged. That run also added
regression coverage for empty generic datatable results, identifier-status enum
tokens, and decimal-safe datatable locale handling. With the simple-ID
transition coverage, the suite now passes 38 tests.

On 2026-08-14, the client-type remediation first updated and reconciled a
balanced 10-client local canary: four `socio`, four `cliente`, and both observed
`cliente-socio` parties. The full local plan then completed with 1,019 updates,
10 unchanged canary clients, zero failures, and zero quarantines. Full
historical-contract reconciliation matched all 1,029 clients. An independent
aggregate check found 989 `cliente`, 38 `socio`, and 2 `cliente-socio`, with no
missing or multiple `tipo_cliente` assignments. Automated coverage for client
type derivation, unrelated-tag preservation, exact reconciliation, and the
subsequent affiliation-ID transition brings the current suite to 38 tests.

The approved active-import policy treats every Arissto client as active in
Fineract, including clients with current loans, clients eligible for future
loans, and delinquent clients requiring legal follow-up.
`AFI_SOCIO.FECHA_REGISTRO` is the required source for Fineract
`m_client.activation_date`: all 1,029 source rows populate it, and Arissto
creates the record after approval and document completion. Existing mapped
pending clients are activated idempotently, and existing active clients have
their activation date reconciled to this source field during update/recovery.
The same source date is written to `submittedOnDate`; although
`FECHA_SOLICITUD_INGRESO` is complete, four source rows place it after
`FECHA_REGISTRO`, which violates Fineract's required timeline ordering.
Fineract additionally prohibits activation before the assigned office's
opening date. Branch 002 has 17 records dated 2024-11-27 through 2024-12-10,
before target office 2 opened on 2024-12-11. Those 17 use the office opening
date as the earliest representable activation/submission date; the other 1,012
clients retain `FECHA_REGISTRO` exactly.

The completed full local run reconciled all 1,029 clients across active status,
activation/submission dates, core profile fields, identifiers, and KYC
datatables. Its final reconciliation returned 1,029 matched and zero failed,
missing, mismatched, or quarantined records. A subsequent full plan classified
all 1,029 clients as unchanged.

The 2026-08-14 simple-ID transition inspection found 1,029 populated and
distinct source affiliation numbers, 1,029 legacy-prefixed local target IDs,
zero canonical-ID collisions, and no readiness blockers. The reviewed full
plan classified all 1,029 rows as updates with existing target client IDs, zero
creates, and 1,029 simple source keys.

The local transition then updated all 1,029 existing clients in place and
reconciliation matched all 1,029 with zero missing, mismatched, failed, or
quarantined clients. An independent audit found 1,029 unique target external
IDs matching the 1,029 source affiliations, zero legacy-prefixed IDs, 1,029
simple current state mappings, and zero composite current mappings. A final
full plan classified all 1,029 clients as unchanged.

One earlier terminal-detached invocation continued concurrently and recorded
1,028 successful updates plus one redacted `OperationalError`; the complete
persistent run subsequently processed all 1,029 successfully and is the run
used for reconciliation. Operators must not launch concurrent applies for the
same plan, even though this transition's idempotent recovery produced a fully
reconciled final state.

For source evidence and field-by-field semantic decisions, see the exploration
note `credesal-db-space/docs/learnings/client-kyc-profile-migration.md`. For the
affiliation-number identity evidence, see
`credesal-db-space/docs/learnings/clientes.md#affiliation-number-trace`. For the
catalog architecture, see
[`../client-system-codes/contract.md`](../client-system-codes/contract.md).
