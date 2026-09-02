# Native share-capital migration service

## Status

`available`, executable for reviewed local runs. Inspect, deterministic plan,
API apply, failed-only retry, reconciliation, and status are implemented.
Tenant migration `0306_add_share_transaction_payment_type.xml` is deployed
locally and the controlled common/preferred lifecycle proof passed.

This service is the native financial projection separated from the lossless
`membership-share-capital` archive. It derives the current purchase-only
projection directly from Arissto and verifies target prerequisites. It never
uses daily/monthly certificate snapshots as transactions and never creates a
redemption from an inferred former position.

## Inspect

```bash
./arissto-sync inspect --block native-share-capital --target local
./arissto-sync inspect --block native-share-capital --target local \
  --source-key 'AFI_ACCION|ID'
```

## Plan, apply, retry, and reconcile

```bash
./arissto-sync plan --block native-share-capital --target local
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync retry --run RUN_ID --failed-only --target local
./arissto-sync status --block native-share-capital --target local
```

Planning has no financial side effects. It deterministically selects the
earliest-opened reconciled active same-client VISTA account, then freezes its
client, savings, product, source, contract, target, and schema prerequisites.
Positions without an eligible real savings account are quarantined; this never
causes the service to create a dummy savings account.

Apply provisions the two reviewed products through the Fineract API, creates
and approves purchase-only share lifecycles through native commands, and writes
only provenance/certificate extensions directly. Account external IDs and
event maps are read before every command so interrupted runs resume without
duplicating financial transactions.

Inspection checks source schema and the reviewed 57-account/66-purchase
projection, separates common paid shares from preferred paid and subscribed
shares, validates whole shares at 5.00, and reports product, permission,
certificate, event-map, and independently reconciled VISTA prerequisites.

The first live local inspection passed source acceptance on 2026-08-26:

- 17 common and 40 preferred positions;
- 24 common and 42 preferred purchase events;
- 6,375 common and 848 preferred paid shares;
- 2,048 preferred subscribed shares, with the unpaid 1,200 retained outside
  native approved capital;
- 36,115.00 total paid capital; and
- 61 current certificates.

All seven required native share permissions exist locally. The savings service
currently supplies 38 reconciled active VISTA accounts for 34 shareholding
clients. The remaining six shareholders are expected quarantines.

Credesal approved the native accounting policy on 2026-08-27. Tenant migration
`0295_seed_native_share_accounting.xml` provisions the target-only controls and
payment types required to express that policy:

| Fineract role or channel | Approved GL code |
|---|---|
| default `shareReferenceId` fallback | `1250990901 COBROS DE ACCIONES POR IDENTIFICAR` |
| `shareSuspenseId` | `2220070303 APORTES DE CAPITAL PENDIENTES DE APROBAR` |
| common `shareEquityId` | `311101020001 ACCIONES COMUNES` |
| preferred `shareEquityId` | `311101020002 ACCIONES PREFERIDAS` |
| inactive mandatory `incomeFromFeeAccountId` | `6423 INGRESO POR COMISIONES - NORMAL` |
| cash and third-party cheque override | `1110010199 CAJA` |
| Banco Atlántida override | `111004020101` |
| Banco Cuscatlán override | `111004020102` |

There is one canonical cash account across Credesal. Office is carried by the
native journal's `office_id` dimension; neither the product nor payment-channel
mapping selects an office-specific GL account. Banks remain distinct because
they represent distinct settlement accounts, not office variants.

The service keeps Fineract's native apply-then-approve flow. A paid purchase
first debits the payment-channel asset and credits approval suspense; approval
then debits suspense and credits the class equity account. The final net entry
therefore matches Arissto: debit cash/bank and credit share capital. Both the
fallback reference and approval suspense must reconcile to zero. No share
charges are configured, so detail account `6423` is an inert API-required
mapping. Header `6420` must never be assigned directly to a product.

The class-specific equity candidates remain `311101020001` (common) and
`311101020002` (preferred). Preferred equity is supported by both
`AFI_TIPO_ACCION` and later purchase journals. Common equity is supported by
the source configuration, but its historical journals are inconsistent: the
initial mixed batch credited 27,000.00 entirely to preferred equity and later
common purchases credited 7,000.00 to `125001010003 INGRESO DE SOCIOS`.
Fineract must preserve the intended two-product separation and reconcile this
as a historical exception rather than copy the misclassification.

Fineract previously discarded the payment channel for share purchases and
always journaled through the fallback reference account. Tenant migration
`0306_add_share_transaction_payment_type.xml` plus the corresponding narrow
share API/domain change preserve `paymentTypeId` on each purchase and pass it
to the existing product-to-GL mapper. This is required before local acceptance;
without it, cash and bank overrides cannot be proven.

The controlled local proof completed on 2026-08-29. Common account
`AFI_ACCION|6` reconciled in run `fa372c9a476b46e589d14776eb2a4e65`;
preferred account `AFI_ACCION|7` reconciled with zero mismatches in run
`929340c48c8a447d894ca7e27d3b34fb`. The follow-up scoped plan
`e47b2b141bca47b0bf3f6aadc22dda92` classified the preferred account as
entirely unchanged. These proofs cover native account creation, approval,
activation, payment-type persistence, payment-specific asset debit, transient
zero-balance suspense, class-specific equity credit, certificate projection,
reconciliation, and read-back idempotency.

Full reviewed local plan `7adc29d0fc734074b2ad9094c2352ded` was applied to
the retained default development tenant on 2026-08-30. Run
`d4ca31cf17ca4b6bb54752cdc1ed3a0c` completed with 43 successful/resumed
positions, 2 unchanged positions, 12 expected quarantines, and no apply
failures. Reconciliation matched 42 of the 45 supported positions. The only
three mismatches are development-canary accounts `AFI_ACCION|1`,
`AFI_ACCION|2`, and `AFI_ACCION|5`, whose purchases were posted through the
fallback reference before the payment-mapping fix. Their historical journals
are intentionally not rewritten or deleted by the engine.

Second full plan `31c2711ea1b54edba05ea5e252e1c2aa` proves the clean
population is idempotent: 42 unchanged, the same 3 pre-fix canaries marked for
resume, and the same 12 savings-prerequisite quarantines. A restored/clean
controlled tenant is required only to demonstrate a literal zero-mismatch
57-position acceptance; it is not required to exercise the engine safely in
the retained default tenant.

`222099940101 RENDIMIENTO ACCIONES PREFERIDAS` is also excluded from the
Fineract share-suspense role. Its 1,303 source lines are system-22 yield credits
totaling 612.94, and no purchase journal uses it. It belongs in the broader COA
crosswalk as a yield/provision liability.

Live inspection also derives the non-negotiable product-limit floors:

| Class | Current paid total | Subscribed total | Largest paid client | Largest subscribed client | Source emission |
|---|---:|---:|---:|---:|---:|
| Common | 6,375 | 6,375 | 375 | 375 | 50,000 |
| Preferred | 848 | 2,048 | 225 | 825 | 100 |

Credesal approved the native limits on 2026-08-27. Common shares are closed to
future growth: `totalShares=6,375` and `maximumShares=375`. Preferred shares use
`totalShares=50,000` and `maximumShares=825`, which accommodates the largest
currently subscribed position. Both products use `minimumShares=1` and
`nominalShares=1`; nominal is only Fineract's account-opening default, while the
migration submits each member's actual paid quantity. Inspection validates
`minimum <= nominal <= maximum <= total` and the subscribed population floors
before treating this gate as satisfied.

## Release gates

- approved limits for both native share products — satisfied 2026-08-27;
- approved GL and payment-channel policy — approved 2026-08-27; inspection
  clears it only after migration `0295` resolves all accounts and payment types;
- independently migrated and reconciled native VISTA savings accounts;
- deterministic planning and API writers with durable target event mappings;
- deployed `0306` share-transaction payment-channel support — satisfied
  locally 2026-08-29;
- controlled product/account/purchase/retry/reconciliation lifecycle proof —
  satisfied for both classes 2026-08-29.

The six shareholders without a real eligible savings account remain blocked.
The service must not create dummy savings accounts or weaken Fineract's native
same-client savings relationship.

Detailed lifecycle and implementation rules remain in the membership service's
[`lifecycle.md`](../membership-share-capital/lifecycle.md) and
[`implementation-sequence.md`](../membership-share-capital/implementation-sequence.md).
