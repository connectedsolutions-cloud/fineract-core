# Membership and share-capital implementation sequence

## Current phase status

- Durable sequence: complete.
- Phase 1 Liquibase definition: implemented in
  `0283_add_credesal_share_migration_support.xml`.
- Phase 1 profile projection: implemented for explicit per-class subscribed and
  paid quantities.
- Phase 1 application and local schema verification: pending normal Fineract
  Liquibase startup.
- Phase 0 preservation re-acceptance: pending after migration 0283 is applied.
- Native product/account/transaction work: not started.

## Outcome

Deliver a restartable, auditable Arissto-to-Fineract migration that:

- preserves the complete reviewed membership and certificate domain;
- creates truthful native Fineract share products, accounts, and paid-capital
  transactions;
- retains certificate-specific legal and subscription information that has no
  native Fineract equivalent;
- never creates a redemption, reversal, dividend, or client-status transition
  from ambiguous historical evidence; and
- can be inspected, planned, applied, retried, and reconciled independently for
  local and production targets.

The first native release is deliberately **purchase-only**. It covers current
paid positions and their post-cutover purchase movements. Historical former
positions and unproven closures remain archived without native transactions.

## Source-of-truth boundaries

- Arissto table meaning and evidence belong in
  [`credesal-db-space/docs/learnings/membresia-aportaciones-y-participaciones.md`](../../../../../../credesal-db-space/docs/learnings/membresia-aportaciones-y-participaciones.md).
- Preservation behavior belongs in [`contract.md`](contract.md).
- Lifecycle evidence and field-level native mapping belong in
  [`lifecycle.md`](lifecycle.md).
- This document owns implementation order, decision gates, phase acceptance,
  and the definition of done.
- Fineract schema definitions belong only in versioned tenant Liquibase files.
- Executable status and operator commands belong in
  [`../registry.json`](../registry.json).

## Non-negotiable quality bar

The implementation is unacceptable if it:

- writes to Arissto;
- inserts directly into Fineract core share, savings, accounting, client, or
  transaction tables;
- uses preferred `AFI_ACCION.NUMERO_ACCIONES=1,248` or subscribed shares as
  native approved shares;
- replays daily/monthly snapshots as transactions;
- treats certificate state `PENDIENTE` as proof that no capital was paid;
- uses a PLUS product row as share evidence;
- creates a redemption from disappearance, client status, or an unmatched
  historical event;
- attaches a share account to another client's savings account;
- depends only on the ignored local SQLite state for native idempotency; or
- changes production without an independently inspected plan and exact target
  fingerprint confirmation.

Exact agreement is required for source identity, client, share class, event
date, paid-share quantity, unit price, amount, current position, target
transaction, and accounting effect. Descriptive historical interpretation may
remain uncertain when the source does not prove it.

## Confirmed baseline

The current reviewed projection has:

| Measure | Expected value |
|---|---:|
| Current member profiles | 40 |
| Native share accounts | 57 |
| Common accounts | 17 |
| Preferred accounts | 40 |
| Paid purchase events | 66 |
| Initial purchases | 57 |
| Additional purchases | 9 |
| Paid common shares | 6,375 |
| Paid preferred shares | 848 |
| Total paid shares | 7,223 |
| Paid capital | 36,115.00 |
| Preferred subscribed shares | 2,048 |
| Preferred unpaid subscription | 1,200 |
| Current certificates | 61 |

These are inspection expectations, not hard-coded migration authorization.
Inspection must derive them again and report drift before every plan.

## Architecture decision

Keep preservation and native financial projection as separate services:

1. `membership-share-capital` continues to own the lossless archive and typed
   member profile.
2. A new `native-share-capital` service will own native share products,
   accounts, purchases, certificate projection, and native reconciliation.

This keeps a proven archive run independent from the stricter prerequisites
and irreversible financial effects of native API commands. The native service
will read Arissto directly and verify its selected rows against the archive; it
will not treat a potentially stale archive payload as the financial source.

## Decisions required before native apply

These decisions do not block building the schema, inspection, or dry-run
planner. They do block product creation and account application.

### 1. Share-product capacity and client limits

- Common emission configuration supplies 50,000 shares at 5.00 and currently
  covers the source population.
- Preferred emission configuration supplies only 100 shares at 5.00, while the
  source already contains 848 paid and 2,048 subscribed shares. It is stale or
  semantically narrower than Fineract product capacity.
- Credesal must approve preferred `totalShares`, nominal shares, minimum client
  shares, and maximum client shares.
- The approved maximum cannot be lower than the largest eligible current paid
  position. If unpaid subscriptions may later be fulfilled natively, the limit
  must also accommodate the relevant subscribed position.

### 2. Native savings prerequisite

Every Fineract share account requires a same-client
`m_savings_account.savings_account_id`. Fineract validates that it is a normal
`SAVINGS_DEPOSIT`, belongs to the same client, uses the share-product currency,
and is active/eligible for lookup. The requirement remains valid even though
Arissto has no individual dividend results to migrate.

Required decision: finish and reconcile the savings migration domain before
native shares. It must preserve real products, accounts, authoritative
ownership, transactions, posted interest, and accrued-interest state through
Fineract's native savings lifecycle. Do not create dummy accounts, create an
account as a side effect of the share service, use another client's account,
use a fixed-term deposit, or weaken Fineract's required relationship.

Arissto currently provides an active `VISTA` account for 34 of 40 shareholders.
Those clients cover 45 of the 57 current share accounts. The six shareholders
without any savings ownership link hold both classes, so their 12 share
accounts must remain blocked until the business legitimately opens eligible
savings accounts. This is not an account-shell migration: 37 of the 38 source
`VISTA` accounts have non-zero provision/accrual state, so the savings service
must define cutoff treatment and reconcile native interest and accounting
results before any of these accounts is used by the share service.

### 3. Accounting mappings

Cash-accounted Fineract share products require:

- `shareReferenceId` — asset;
- `shareSuspenseId` — liability;
- `shareEquityId` — equity; and
- `incomeFromFeeAccountId` — income.

Arissto resolves the following evidence:

- common equity: `311101020001 ACCIONES COMUNES`;
- preferred equity: `311101020002 ACCIONES PREFERIDAS`;
- provision/yield: `222099940101 RENDIMIENTO ACCIONES PREFERIDAS`; and
- cost: `7110040100 INTERESES DE TÍTULOS VALORES`.

The equity candidates are clear. The remaining Fineract roles require an
approved target GL crosswalk; names or account types must not be guessed.

### 4. Operational certificate visibility

Recommended decision: current certificates and beneficiaries should be
queryable Credesal extension records linked to the native share account.
Daily/monthly histories stay only in the lossless archive. This avoids copying
tens of thousands of snapshots into operational tables while retaining all
source data.

## Implementation phases

### Phase 0 — re-accept the narrowed preservation contract

**Purpose:** restore the existing archive service to accepted local status
after the current-party and PLUS exclusions changed its contract hash.

Steps:

1. Run local `preflight` and `inspect`.
2. Generate and review a full local plan.
3. Apply the reviewed plan locally.
4. Reconcile exact source keys, client links, payloads, and hashes.
5. Generate a second plan and require every in-scope row to be `unchanged`.
6. Record acceptance identifiers in the existing README/contract and return
   the registry service to `available` only after all checks pass.

The prior local target contains rows from the older broader contract. The
engine must not delete them. Acceptance must report these pre-existing
out-of-scope rows separately so they cannot be mistaken for current scope.
Production has not been authorized.

**Exit criteria:** current scoped archive is exact and idempotent; no current
PLUS or unresolved-party operation appears in the scoped reconciliation.

### Phase 1 — add versioned migration-support schema

**Purpose:** add only the extension structures that native Fineract lacks.

Implemented tenant migration:

```text
0283_add_credesal_share_migration_support.xml
```

The migration should:

#### A. Expand `credesal_member_profile`

Add explicit per-class quantities so the legacy preferred aggregate is never
misread:

- `common_subscribed_share_count`;
- `common_paid_share_count`;
- `preferred_subscribed_share_count`; and
- `preferred_paid_share_count`.

Retain existing columns for compatibility. Document
`preferred_share_count` as the legacy `AFI_ACCION.NUMERO_ACCIONES` aggregate.

#### B. Create `credesal_share_certificate`

Minimum responsibilities:

- stable current source identity using certificate, associate, and share type;
- `client_id` FK to `m_client`;
- nullable `share_account_id` FK to `m_share_account`, populated after native
  account creation;
- optional archive-record link or canonical source key;
- source class/state IDs and reviewed descriptions;
- certificate date, number, series, action range, book, folio, and line;
- unit value, represented, subscribed, and paid shares;
- current, subscribed, paid, pledged, blocked, and available balances;
- printed, blocked, and restricted flags;
- deterministic source hash and audit timestamps; and
- unique constraints and indexes for source identity, client, share account,
  and certificate lookup.

The exact certificate identity must include associate and share type. Never
generalize historical identity to `ID_CERTIFICADO` alone.

#### C. Create `credesal_share_certificate_beneficiary`

Minimum responsibilities:

- FK to `credesal_share_certificate`;
- stable Arissto beneficiary source identity;
- typed fields required for operational use;
- deterministic hash and audit timestamps; and
- a quarantine path for the two beneficiary rows without a current
  certificate.

The lossless archive remains canonical for every source column, including PII.

#### D. Create `credesal_share_native_event_map`

This is the durable, target-side idempotency and reconciliation crosswalk.
It should contain:

- source table and canonical source key;
- source hash;
- client, share product, and share account IDs;
- native share transaction ID when one exists;
- command/event kind such as initial purchase or additional purchase;
- event date, shares, unit price, and amount used by the command;
- apply/reconciliation timestamps and status; and
- a unique source identity constraint plus target transaction uniqueness where
  non-null.

This table does not authorize direct writes to core share transactions. It
records the result returned by successful Fineract API commands.

#### E. Register operational datatables only when useful

Register the certificate tables with Fineract datatable metadata only if the
UI/API must expose them as datatables. The event crosswalk is internal migration
infrastructure and should not be user-editable.

**Migration validation:** process resources, start Fineract with Liquibase on a
clean local database, inspect columns/FKs/unique constraints/indexes,
re-run startup idempotently, and verify supported database-neutral types.

**Exit criteria:** extension schema exists through Liquibase only; no core
Fineract table was altered to carry Arissto-specific certificate fields.

### Phase 2 — define and provision real prerequisites

**Purpose:** make the target truthful before creating a native share account.

Steps:

1. Approve the four product-limit decisions for common and preferred shares.
2. Resolve source accounting evidence to actual target `m_gl_account` IDs.
3. Define two share-product contracts with stable external IDs.
4. Create/update products through Fineract APIs, not SQL or Liquibase seed data.
5. Ensure price history contains 5.00 effective no later than 2023-02-01.
6. Complete the independent native savings migration for the full approved
   savings scope, including products, ownership, accounts, transactions,
   interest postings, accrual state, and accounting reconciliation.
7. Resolve each share account only to an already migrated, active, same-client
   `VISTA`/`SAVINGS_DEPOSIT` account in the same currency.
8. Block the 12 positions belonging to the six shareholders without an eligible
   source savings account; never provision one inside this service.
9. Inspect product capacity, limits, currency, accounting, GL types, price, and
   savings ownership.

**Exit criteria:** exactly two intended products exist, the savings migration
has reconciled independently, each share account selected for migration has an
eligible native savings account, unresolved clients are blocked explicitly,
and every product/accounting check passes.

### Phase 3 — implement read-only native inspection

**Purpose:** prove source and target readiness without creating financial
records.

Create a separate service configuration and module for
`native-share-capital`. Inspection must verify:

- exact current client mapping through affiliation/external ID;
- one current `AFI_ACCION` per associate/share type;
- certificate ownership and class agree with each movement;
- unit price is positive and each movement amount produces an integral share
  quantity;
- movements ordered by `FECHA`, then canonical movement source key;
- movement shares and amounts reconcile per position to certificate paid
  shares/balance and `AFI_ACCION.SALDO_ACCIONES`;
- no included movement is reversed, negative, PLUS-classified, unresolved, or
  pre-cutover legacy activity;
- each target product is unique and has sufficient capacity;
- each linked savings deposit is active, belongs to the same client, uses the
  same currency, and resolves through the reconciled savings migration;
- existing native account external IDs and durable event mappings have no
  collisions; and
- the target operator has every required share API permission.

Inspection should report expected creates, existing mappings, quarantines, and
drift without printing PII or raw payloads.

**Exit criteria:** the reviewed baseline resolves to 57 eligible accounts and
66 eligible purchases, or all differences are explicitly explained.

### Phase 4 — implement deterministic planning

**Purpose:** produce a reviewable, target-specific plan with no financial side
effects.

Each planned account must contain:

- canonical `AFI_ACCION` source identity;
- client, product, and savings-account target IDs;
- stable proposed account external ID;
- initial purchase source key and command values;
- ordered additional-purchase source keys and command values;
- certificate-projection actions; and
- hashes of every source and target prerequisite used by the decision.

Plan actions should distinguish:

- create account and initial purchase;
- create/approve additional purchase;
- link/update certificate projection;
- unchanged;
- conflict; and
- quarantine.

Plans are target-specific and must expire on contract, source, target,
product, price, savings ownership, GL mapping, or schema drift.

**Exit criteria:** a second plan against unchanged state is deterministic and
contains no PII or source payload.

### Phase 5 — implement native API apply and resume

**Purpose:** create paid capital through supported Fineract business commands.

For each position:

1. Re-read source rows and target prerequisites and require planned hashes.
2. Create the share application with the first paid purchase.
3. Approve and activate it with defensible source dates.
4. Capture the returned account and transaction IDs in the durable crosswalk.
5. Apply and approve each later purchase in deterministic order.
6. Project/link current certificate and beneficiary extensions.
7. Commit local run state only after the corresponding target result and
   durable crosswalk can be read back.

Use the first movement date as the application/approval/activation date only
after confirming Fineract accepts the historical date sequence. The migration
must not move a source date merely to satisfy an existing conflicting target
transaction.

API calls are not one database transaction. Resume logic must inspect account
external ID, native transactions, and the durable event crosswalk before each
command. A timeout after a command is treated as unknown outcome and requires a
read-back before retry.

No redemption, close, transfer, rejection, reversal, dividend, or client
deactivation command belongs in this first release.

**Exit criteria:** interrupted runs resume without duplicating accounts or
transactions; failures quarantine only the affected entity and do not rerun
successful events.

### Phase 6 — reconcile financial and documentary results

**Purpose:** prove that the target represents exactly the approved source
projection.

Reconciliation must prove at least:

- 57 mapped native accounts, separated 17 common / 40 preferred;
- 66 mapped approved purchase transactions;
- 6,375 common and 848 preferred approved shares;
- 36,115.00 total paid capital;
- native purchase date, shares, unit price, and amount equal their source event;
- account approved shares equal purchases minus redemptions, with zero
  migration-created redemptions;
- every native event has one durable source mapping and vice versa;
- certificate paid quantities reconcile to the native account while subscribed
  and unpaid quantities remain extension data;
- all 61 current certificates are projected or explicitly quarantined;
- all resolvable beneficiaries are linked and the two unresolved-certificate
  rows remain quarantined;
- linked savings ownership remains active, same-client, same-currency, and
  traceable to the reconciled savings migration; and
- generated journal entries use the approved product GL mappings and balance by
  transaction and in aggregate.

A full second plan must be entirely `unchanged` unless Arissto legitimately
changed after the accepted run.

**Exit criteria:** zero unexplained mismatch, duplicate, failure, or
unclassified event.

### Phase 7 — controlled local acceptance

Use a disposable or restorable local tenant/database because native API writes
are intentionally not deleted by the sync engine.

Acceptance sequence:

1. Apply the Liquibase migration through normal Fineract startup.
2. Run preservation-service acceptance from Phase 0.
3. Run native preflight and inspect.
4. Exercise a reviewed common position and preferred position on an isolated
   target when possible.
5. Restore the controlled target or use a fresh tenant before the full run.
6. Run full native plan, apply, reconcile, retry simulation, and second plan.
7. Test an injected timeout/read-back scenario and at least one quarantine.
8. Record plan/run IDs, contract/schema hashes, counts, and evidence in the
   service documentation.
9. Mark the new service `available` only after all acceptance criteria pass.

### Phase 8 — production execution

Production requires a fresh, independent sequence:

1. confirmed database backup/restore procedure outside the sync engine;
2. production preflight and inspection;
3. production-specific plan and human review;
4. exact production fingerprint confirmation;
5. apply with monitored entity-level progress;
6. immediate reconciliation;
7. failed-only retry only after the failure cause is understood; and
8. final second plan proving idempotency.

The sync engine does not implement destructive rollback. Any business
correction after a successful native command must use an approved Fineract
business workflow, not direct SQL deletion or transaction deactivation.

## Explicitly deferred scope

The following remain outside the first native release:

- the 46 former historical positions without proven financial closure events;
- the January 2023 documentary closure with no trusted financial event;
- all pre-February-2023 legacy withdrawals, reversals, and liquidations without
  an exact current-class crosswalk;
- PLUS SILVER, PLUS PLATINUM, and PLUS INFINITE rows;
- unresolved historical `OPR_OPERACIONES` parties;
- treating unpaid subscription as native approved or pending shares;
- native share transaction reversal;
- holder-to-holder transfer without both proven legs;
- historical or inferred dividends;
- DPF principal, maturity, or cancellation; and
- client deactivation based only on share or DPF state.

Future redemption work starts as a separate contract revision with its own
evidence grades, commands, reconciliation, and local acceptance.

## Required automated coverage

At minimum, tests must cover:

- 17 common + 40 preferred account classification;
- preferred 2,048 subscribed / 848 paid / 1,200 unpaid distinction;
- rejection of preferred legacy aggregate 1,248 as approved shares;
- 57 first purchases + 9 additional purchases;
- amount-to-share calculation at 5.00 and non-integral rejection;
- same-client savings ownership enforcement;
- insufficient product capacity;
- missing/incorrect GL roles;
- certificate number reuse across historical identities;
- PLUS and unresolved-party exclusion;
- source row/hash change after planning;
- account external-ID collision;
- timeout after API success followed by read-back without duplicate retry;
- durable event-map uniqueness;
- reconciliation mismatch and failed-only retry; and
- second-plan idempotency.

## Definition of done

The sequence is complete only when:

- the preservation service is re-accepted under its narrowed contract;
- the Liquibase extension migration is applied and verified;
- business decisions for product limits and GL mappings are recorded, and the
  native savings prerequisite is independently reconciled;
- `native-share-capital` implements inspect, plan, apply, retry, reconcile, and
  status;
- all automated and controlled local acceptance checks pass;
- the registry and service documents accurately reflect readiness;
- production, if authorized, reconciles exactly and a second plan is
  idempotent; and
- deferred historical lifecycle events remain archived without fabricated
  native transactions.

## Immediate next work

1. Apply migration 0283 through normal local Fineract startup and inspect the
   resulting schema.
2. Re-accept the narrowed preservation service locally, including the expanded
   member profile.
3. Define and implement the native savings migration sequence, including
   transaction, interest-posting, accrual, and accounting reconciliation.
4. Resolve the remaining share gates: preferred product limits and target GL
   mappings.
5. Scaffold the separate `native-share-capital` registry/service contract as
   `planned`, then implement inspection before any native writer.
