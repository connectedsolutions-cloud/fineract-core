# Savings and fixed-term deposits migration service

## Status

- Registry status: `available`
- CLI block: `savings-deposits` (deterministic inspect, plan, apply, retry,
  reconcile, and status workflows are available)
- Source account identity:
  `AHO_CUENTA_AHORRO|ID_EMPRESA|ID_SUCURSAL|ID_CUENTA_AHORRO`
- Target writers: native Fineract savings/fixed-deposit APIs and jobs only
- Schema prerequisites: tenant migrations
  `0288_add_arissto_savings_migration_support.xml` and
  `0290_add_arissto_savings_product_map.xml`, native command permissions 0292
  and 0299, period-end configuration migration 0296, DPF cycle migration 0300,
  targeted DPF maturity/transfer permissions 0301, and the no-principal-transfer
  DPF migration-link permission 0302

## Business scope

This service migrates Arissto ordinary savings (`VISTA`) and fixed-term
deposits (`PLAZO`) into Fineract's native deposit domain. It owns the complete
financial lifecycle: product definitions, accounts, authoritative ownership,
customer movements, linked DPF interest transfers, interest capitalization,
accrual cutoff state, ISR withholding, closures, reversals, and accounting
reconciliation.

`PROGRAMADO` remains product-catalog inspection only because Arissto currently
has no accounts of that type. Share capital, share dividends, loans, and client
identity are outside this service. Native shares may consume a reconciled
active `VISTA` account, but the share service must never create or repair a
savings account.

Source evidence is maintained in
[`creditos-y-depositos.md`](../../../../../../credesal-db-space/docs/learnings/creditos-y-depositos.md)
and the accounting interpretation in
[`contabilidad-libro-mayor-y-partidas.md`](../../../../../../credesal-db-space/docs/learnings/contabilidad-libro-mayor-y-partidas.md).

## Source and target contract

- `AHO_LINEA_AHORRO` maps `VISTA` to native savings products and `PLAZO` term
  bands to native fixed-deposit products.
- `AHO_PROPIETARIOS` is authoritative for ownership. The account master's
  socio pair selects the native owner only when it matches exactly one row in
  that authoritative set. The one current joint DPF passes this rule. It is
  represented by that native owner plus all source owners in
  `credesal_savings_migration_owner`.
- `AHO_CUENTA_AHORRO` maps to `m_savings_account`. Fineract's
  `deposit_type_enum` distinguishes ordinary savings from fixed deposits.
- Each DPF must reference its already-migrated, active, same-client `VISTA`
  destination with Fineract's native linked-account and
  `transferInterestToSavings` behavior.
- One Arissto DPF position may span multiple renewed native fixed-deposit
  accounts. `credesal_savings_migration_account.savings_account_id` points to
  the current term, while `credesal_savings_migration_cycle` preserves every
  predecessor/current term and renewal boundary.
- Customer-visible `AHO_MOVIMIENTOS` rows map to native deposit transactions or
  native closure/reversal workflows. Interest history type `1` explains native
  interest postings/transfers; type `2` is accrual evidence and is never
  replayed as a second customer transaction.
- The completed-close `AHO_HISTORICO_DIARIO.INTERESES_PROVISIONADOS` amount and cutoff date are retained in
  `credesal_savings_migration_account`. Native accrual transactions and journal
  entries remain in Fineract core; event replay reconstructs native unrounded
  calculation state.
- Every applied source event is linked durably to its native transaction in
  `credesal_savings_native_event_map`; local SQLite state is not the only
  idempotency mechanism.
- Because native savings products have no external ID,
  `credesal_savings_product_map` durably links each Arissto line to exactly one
  native product and retains the source/contract hashes used to create it.

The detailed field, lifecycle, and quarantine rules are in
[`contract.md`](contract.md). The ordered delivery gates are in
[`implementation-sequence.md`](implementation-sequence.md), and the reviewed
native product definitions are in [`product-contracts.md`](product-contracts.md).
The native calendar-day calculation change is specified in
[`actual-actual-design.md`](actual-actual-design.md). The DPF activation-day
monthly schedule and short-month rule are specified in
[`opening-day-interest-schedule.md`](opening-day-interest-schedule.md).

## Preconditions

- The `clients` service has reconciled every selected owner to exactly one
  Fineract client.
- Migrations 0288 and 0290 are applied through normal Fineract Liquibase
  startup.
- Savings and fixed-deposit product, tax, and GL mappings are approved.
- A completed `CIERRE_DIARIO` snapshot exists with exactly one daily row per
  selected account.
- One controlled account simulation proves Fineract reproduces the source
  transaction, interest, tax, balance, and journal results.
- Every joint account has exactly one owner row matching the account master's
  socio pair; ambiguity is a hard inspection blocker.

The 2026-08-26 local inspection verifies migrations 0288 and 0290 and both native schema
families. It also shows that the two existing local products are not migration
templates: the ordinary-savings product is configured at 8% and named as a
term deposit, while the fixed-deposit product is configured at 0%. Neither is
the reviewed 3% `VISTA` contract or the complete set of Arissto DPF term/rate
bands. Phase 3 must therefore create approved native products rather than
attach migrated accounts to these approximate products.

## Commands

The complete reviewed workflow is available:

```bash
./arissto-sync preflight --target local
./arissto-sync inspect --block savings-deposits --target local
./arissto-sync plan --block savings-deposits --target local
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync retry --run RUN_ID --failed-only --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync status --block savings-deposits --target local
```

Planning never writes Fineract or Arissto. Apply writes only the explicitly
selected Fineract target; Arissto remains read-only.

Inspection also requires exactly one
`EXPLICITINTERESTPOSTING_SAVINGSACCOUNT` permission and reports the effective
native type-3 command contract. A target without migration `0299` is therefore
blocked before any historical VISTA replay can be planned.

The local-only VISTA acceptance proof remains available for focused diagnosis:

```bash
./arissto-sync prove-vista-lifecycle --target local \
  --source-key 001:001:0000000100
./arissto-sync prove-vista-lifecycle --target local \
  --source-key 001:001:0000000100 --execute
./arissto-sync prove-vista-lifecycle --target local \
  --source-key 001:001:0000000100 --reconcile-existing
```

The local-only DPF acceptance proof covers linked VISTA transfer, event-level
ISR, renewals, maturity, cancellation, reversed source corrections, joint
ownership, and cutoff state:

```bash
./arissto-sync prove-dpf-lifecycle --target local \
  --source-key 001:001:0000000141
./arissto-sync prove-dpf-lifecycle --target local \
  --source-key 001:001:0000000141 --execute
```

Scoped plans remain available with `--source-key`; every selected DPF scope
must also include its linked VISTA source key.

## Reconciliation and acceptance

Acceptance requires exact reconciliation at four layers:

1. source accounts, owner links, statuses, terms, rates, and linked destinations;
2. transaction count/order/type/date/amount/reversal and ending balance;
3. posted interest, ISR, accrued-but-unposted interest, and next posting date;
4. native accounting entries by source product and configured GL account.

A second plan after successful reconciliation must be empty. Unknown movement
types, missing clients/products/destinations, ownership ambiguity, unsupported
backdating, cutoff drift, and any financial mismatch are blockers, not warnings.

## Performance and access pattern

Inspection and planning bulk-load product lines, account masters, owners,
movements, interest history, cutoff snapshots, source clients, and target
identities once per bounded scope. They build normalized in-memory indexes by
canonical source key. Target products, clients, accounts, extension mappings,
and transactions are read in chunks; no per-account catalog or schema lookup is
allowed.

Writes remain sequential by account. Within an account, source events are
strictly chronological and each successful native command is durably mapped
before the next event. Fresh creates may skip recovery reads when the external
ID proves the account cannot exist; retries must bulk-resolve the account and
event map before issuing any command.

## Resolved implementation decisions

- The cutoff-field decision is resolved. Inspection freezes the latest
  completed `CIERRE_DIARIO` and requires one `AHO_HISTORICO_DIARIO` row per
  account. Both retained opening-accrual columns use
  `INTERESES_PROVISIONADOS`; native replay supplies calculation precision.
- Historical ISR classification is resolved and machine-checked from
  `APLICA_RENTA=1`, its 10% amount, and its linked VISTA debit. The explicit
  native linked-VISTA transaction-type-18 command is implemented. Migration
  0292 supplies its permission; the target tax group must be linked while
  automatic product/account withholding remains disabled. Its controlled local
  lifecycle passed on 2026-08-26: post, idempotency-key replay, source-reference
  recovery, tax-component detail, balance processing, ISR-payable/control
  journals, and native reversal all reconciled. The remaining controlled-
  lifecycle gate covers the other savings/DPF paths, not this ISR command.
- Historical VISTA capitalization is resolved. The source posting amount is an
  authoritative ledger fact and is not always equal to a new calculation from
  the retained movement stream; the controlled account includes a 4.17 source
  posting where a fresh native calculation is 4.16. The narrow
  `command=explicitInterestPosting` path creates native type `3`, preserves the
  exact source date/amount/reference, and uses Fineract balance and accounting
  services. Referenced manual postings are retained during later native
  recalculation; future interest remains normally Fineract-calculated.
- The native activation-anchored monthly posting/compounding option is
  implemented as enum value `9`, using the shared immutable anchored-month
  primitive also consumed by loans. The dedicated implementation blocker is
  cleared. Its linked transfer, renewal, maturity, cancellation, and journal
  paths passed the controlled DPF matrix on 2026-08-28.
- Resolve each Arissto line's GL roles to target `m_gl_account` IDs.
- The controlled VISTA subproof passed locally on 2026-08-27. Account 12
  reconciled all 25 events: 16 deposits, one withdrawal, six type-3 interest
  postings, and two type-18 ISR debits. Every type/date/amount/running balance
  matched Arissto, the ending balance was 972.70, and every native journal was
  balanced.
- The controlled DPF matrix passed locally on 2026-08-28. It proves a
  four-cycle renewal/maturity chain, gross linked-VISTA interest transfers and
  ISR, a source-authoritative cancellation, a reversed opening correction
  pair recorded as an audit no-op, the joint DPF owner constellation, and both
  cutoff strategies. All native journals balance. For an active DPF with prior
  source postings, the exact Arissto cutoff is retained as migration state and
  the newly derived Fineract amount remains diagnostic; no artificial financial
  transaction is created for the difference.

The deterministic implementation gate passed locally on 2026-08-29. The final
full plan contained 155 `unchanged`, 2 reviewed `quarantine`, and no writable
actions. Run `5945601248a64b90a2c485b88fd3313a` reconciled all 155 eligible
accounts with zero failures and zero mismatches. The quarantines are stable
`SUBMITTED_UNFUNDED` DPF placeholders with zero principal; no artificial native
positions are created for them.

The accepted engine also proves stale native-transaction recovery, finite
snapshot cleanup of Fineract-generated VISTA interest/tax artifacts, atomic
reversal of transferred DPF interest, and shared provenance for DPF interest
and ISR transactions posted on linked VISTA accounts. Proof-era business-ID
aliases are retained as `SUPERSEDED`, not counted as active events.
Each plan freezes the latest completed-close cutoff in its immutable source
hash. A later completed close is legitimate source drift and produces a new
plan; it is not treated as nondeterministic replay.

The direct line-specific GL crosswalk is now verified locally: all 19 distinct
Arissto codes used for principal control, interest expense, accrued-interest
liability, and ISR exist as enabled target GL accounts. The shared target roles
are also resolved from the convention already used by both local deposit
products: reference `1110040202`, transfer suspense `213005`, fee/penalty
income `6420`/`6430`, and receivables `1530`/`1540`. Inspection verifies that
all are enabled with the required classifications, so the GL-selection blocker
is cleared.
