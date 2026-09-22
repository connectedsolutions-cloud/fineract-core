# Loans contract

## Scope and ownership

The loans service is the sole migration owner of native Fineract loans and their
historical financial lifecycle. It will create originated Arissto loans,
approve and disburse them, replay supported repayments and reversals, preserve
charges and restructuring history, and reconcile the resulting native balances
and accounting.

The service includes only originated rows in `CRD_CARTERA`. Under reviewed
scope decision [`SCOPE-001`](../scope-decisions.md#scope-001--standalone-credit-applications),
standalone applications in `CRD_SOLICITUD_CREDITO` without a portfolio row are
not synchronized for now. The source table remains
available in Arissto, and fields needed to construct an originated loan may
still be read through that loan's application relationship. A separate
application-history service should be reconsidered only if rejected,
withdrawn, or otherwise non-originated application history becomes a business
requirement. Daily and period snapshots are reconciliation evidence, not
transactions to replay.

For each originated loan, the service also owns the personal-guarantor rows in
`CRD_SOLICITUD_FIADOR`. Each source guarantor resolves through its declared
`AFI_SOCIO` relationship and then through the clients service's
`m_client.external_id = AFI_SOCIO.NUMERO_AFILIACION` contract. The target is
one active `m_guarantor` row with `type_enum=1` and
`entity_id=m_client.id` for every source row. Relationship code values and
guarantor-funded savings details are intentionally out of scope.

The same loan-owned boundary applies to pledged collateral in
`CRD_SOLICITUD_GARANTIA`. Collateral is not a separate registry service because
the currently populated source records belong to originated applications and
must be attached to the native loan at creation. Internally it remains a
distinct, idempotent subphase: resolve or create the shared collateral product,
resolve or atomically create each client asset and its selected final
valuation, then include those identities in the loan application payload.

No downstream service may create a second financial transaction for an Arissto
loan movement. In particular, `mobile-collections` may link to repayments
created here but cannot call a repayment, adjustment, reversal, teller, or
journal endpoint.

## Source graph

```text
AFI_SOCIO
  -> CRD_SOLICITUD_CREDITO
      -> CRD_SOLICITUD_FIADOR -> AFI_SOCIO (guarantor)
      -> CRD_SOLICITUD_GARANTIA
          -> CRD_GARANTIA_VALUO
          -> CRD_GARANTIA_INSCRIPCION
      -> CRD_CARTERA
          -> CRD_PLAN_PAGO
          -> CRD_MOVIMIENTOS_CARTERA
              -> CRD_MOVIMIENTO_PRE_POS
              -> CRD_DETALLE_CARGOS
              -> CRD_MOV_CARTERA_CONTABLE

CRD_LINEA_CREDITO
  -> CRD_CARGOS_CREDITO
  -> CRD_CARGOS_CARTERA

CRD_ENC_LIQUIDACION
  -> CRD_DET_LIQUIDACION
      -> disbursement or prior-loan refinance payoff
```

Source meaning and population evidence remain in the exploration repository:

- `docs/learnings/prestamos.md`;
- `docs/learnings/refinanciamientos.md`;
- `docs/learnings/mora-y-cargos-de-creditos.md`;
- `docs/learnings/seguro-de-deuda.md`;
- `docs/learnings/prestamos-inconsistencia-base-360-365.md`; and
- `docs/learnings/prestamo-2120-plan-cero.md`.

### Guarantor multiplicity and historical insertion

Guarantors have no separate migration service and no synthetic relationship
external ID. The frozen loan plan retains one entry per source row, including
repeated occurrences of the same guarantor client. Apply compares the desired
and target active-row counts by `(loan_id, type_enum=1, entity_id)`, creates
only the missing count, and fails closed if the target count exceeds the
source. It never deletes a target guarantor.

Normal Fineract guarantor creation continues to reject a duplicate active
customer and a closed loan. Migration uses only the separately authorized
`POST /loans/{loanId}/guarantors?command=sourceExactCreate` command, protected
by `SOURCEEXACTCREATE_GUARANTOR`. That path accepts only an existing customer
guarantor, no relationship code, and no savings/funding details. It may add
repeated rows and may attach historical evidence to a closed loan. Reconcile
requires the exact source multiplicity for every loan with source guarantors.

The four current guarantor rows attached to applications without
`CRD_CARTERA` remain outside synchronization under the same reviewed scope
decision. They should be reconsidered together with standalone application
history if that scope is added later.

### Collateral subphase

The reviewed source population contains 34 guarantee rows on 31 originated
loans. Five are mortgages (`002`: three land and two housing) and 29 are
pledges (`004`: 25 vehicles and four motorcycles). A loan may have two source
guarantees, so the frozen lifecycle retains an ordered collection rather than
a single field.

The first implementation deliberately uses one migration-owned Fineract
collateral product named `ARISSTO-COLLATERAL`. Its quantity is always `1.00`,
base price is `1.00`, percentage to base is `100.00`, and the selected source
appraisal carries the actual pledged and eligible value. The product is a
top-level plan action and a prerequisite only for loan actions that contain
source collateral. It is created once and recovered by its exact name and
contract on retry; a conflicting product blocks the plan.

Each client collateral is created atomically through
`POST /clients/{clientId}/collaterals` with its asset detail and initial final
valuation. Retry resolves it through the asset external ID before writing, so a
timeout after a successful create cannot duplicate it. The resulting
`clientCollateralId`, `valuationId`, and quantity are attached through the
permission-gated `sourceExactAttach` migration command only after the native
loan application exists. This separates collateral reservation from the larger
loan-create transaction. New and recovered loans must have the exact same
collateral set or apply fails closed.

Plans contain only source IDs, type/subtype, stable external IDs, appraisal
date/value, and a hash of the full payload. Addresses, vehicle identifiers,
registry numbers, owner detail, and appraisal narrative are re-read only after
the apply-time source hash guard passes and are held in memory for the API
write. They are never persisted in the plan or run ledger.

Local proof namespaces apply to the loan, transaction, collateral asset, and
collateral valuation external IDs together. A scoped canary therefore creates
an isolated collateral set and never reuses a canonical asset left by an older
failed or completed run.

The current `CRD_GARANTIA_VALUO` and `CRD_GARANTIA_INSCRIPCION` populations are
empty. If either child table becomes populated, inspection blocks the loans
service until ordering, supersession, and loan-association semantics are
reviewed. The parent row's current appraisal is mapped as the selected `FINAL`
valuation for now. Its appraisal date is optional, and aggregate appraised
value may cover only part of the approved principal. Zero and negative source
valuation amounts are preserved exactly and do not quarantine the collateral,
loan, or refinance chain. An unsupported type/subtype still quarantines only
its loan. Source vehicle-type and quality
codes remain unmapped until their catalog semantics are verified; the reviewed
subtype label is retained in the descriptive vehicle/property field instead.

## Deterministic identities

### Loan

| Purpose | Value |
|---|---|
| Source owner | `CRD_CARTERA` |
| Source key | `ID_CREDITO` |
| Fineract identity | `m_loan.external_id = ARISSTO:CRD:{ID_CREDITO}` |
| Display account number | trimmed `CRD_CARTERA.NO_PRESTAMO` |

`ID_CREDITO` is the technical cross-table identity. The declared six-column
portfolio key remains preserved for evidence, but it is not used as the target
external ID. `NO_PRESTAMO` is a business account number, not the idempotency
key. Target preflight must reject collisions in either `external_id` or
`account_no`.

Example:

```text
ID_CREDITO = 1234
m_loan.external_id = ARISSTO:CRD:1234
```

### Loan transaction

| Purpose | Value |
|---|---|
| Source owner | `CRD_MOVIMIENTOS_CARTERA` |
| Source key | trimmed `ID_MOVIMIENTO_CARTERA` |
| Fineract identity | `m_loan_transaction.external_id = ARISSTO:CRD-MOV:{ID_MOVIMIENTO_CARTERA}` |

`ID_MOVIMIENTO_CARTERA` has a unique source index and is populated uniquely in
the reviewed population. The declared seven-column movement primary key and
`ID_CRD_MOVIMIENTO` are retained as reconciliation evidence. The external ID
fits within Fineract's 100-character limit and is globally namespaced.

This identity is the only automatic transaction link exposed to downstream
services. For example:

```text
MCD_MOVIMIENTOS.ID_MOVIMIENTO_CARTERA = 0000123456
    -> m_loan_transaction.external_id = ARISSTO:CRD-MOV:0000123456
```

No service may resolve a transaction from date and amount when this identity is
absent.

### Collateral asset and valuation

| Purpose | Value |
|---|---|
| Source asset owner | `CRD_SOLICITUD_GARANTIA` |
| Source asset key | `ID_SOLICITUD_GARANTIA` |
| Fineract asset identity | `ARISSTO:CRD-GUAR:{ID_SOLICITUD_GARANTIA}` |
| Initial valuation identity | `ARISSTO:CRD-VAL:{ID_SOLICITUD_GARANTIA}` |

Asset and valuation identities are global and deterministic. They do not use
mutable description, plate, registry number, date, or amount fields.

### Client, staff, office, and product

- Client: resolve the declared application relationship to `AFI_SOCIO`, then
  use `AFI_SOCIO.NUMERO_AFILIACION = m_client.external_id`.
- Staff: use `ID_EMPRESA:ID_PERSONA = m_staff.external_id`.
- Office: use the reviewed Arissto branch-to-Fineract office crosswalk; never
  treat an Arissto branch code as a Fineract numeric ID.
- Loan product: use `ID_LINEA_CREDITO` through a versioned product crosswalk.
  Do not select products by mutable display name.

### Loan product

The product identity is:

```text
source_key = {ID_LINEA_CREDITO}
m_product_loan.external_id =
    ARISSTO:CRD-LINE:{ID_LINEA_CREDITO}
```

`ID_EMPRESA` is retained in the crosswalk as source provenance, but it is not
part of the product identity. This migration has exactly one Arissto company
and one Fineract tenant; inspection must reject a second distinct company
before planning rather than silently broadening the identity.

The refreshed 2026-08-29 source inspection found 12 configured credit lines,
but only two currently own portfolio rows: `001:00001` has 14 loans and
`001:00010` has 2,476. All 12 remain inspectable because a line with no current portfolio may
still be needed to interpret historical or future data. A migration plan
creates products only for reviewed lines required by its selected loans. It
does not create empty products merely because a source configuration row
exists.

The engine is designed as if the Fineract target has an empty business-data
portfolio after its versioned schema, chart of accounts, permissions, and
required catalogs are bootstrapped. The loans service owns creation of every
native loan product it requires. It creates the product through the Loan
Products API with the deterministic Arissto external ID, then writes the
crosswalk row. It never reuses or auto-binds an unowned product by name, short
name, numeric target ID, or `id_tipo_linea`.

On retry, an existing product is reusable only when it has the exact expected
`ARISSTO:CRD-LINE:{ID_LINEA_CREDITO}` external ID and its reviewed immutable
contract matches. This permits recovery if product creation succeeded but the
crosswalk write did not. An unrelated product is ignored; an external-ID or
crosswalk collision is a blocking target conflict. Local manually created test
products therefore have no role in migration planning and need not resemble a
production baseline.

The immutable plan exposes and freezes the complete target-specific product
payload before apply. It emits only the products required by the selected
loans: a one-loan `00001` scope contains only `product:00001`, while the full
reviewed portfolio contains both `product:00001` and `product:00010`. Product
actions always precede loan actions. Every `loan:{ID_CREDITO}` action declares
its `product:{ID_LINEA_CREDITO}` dependency so a failed or conflicting product
prevents all dependent loan attempts.

Each created product also stores migration `0315` API field `numberingCode`.
The value is the verified account-number family `3<first letter of
NOMBRE_LINEA>1`, currently `3C1` for line `00001` and `3M1` for line `00010`.
A retry may backfill a blank code on the exact migration-owned product, but a
different nonblank code is a blocking contract conflict.

`CRD_LINEA_CREDITO` supplies defaults and ranges, while the approved terms on
each application/portfolio loan remain authoritative for historical accounts.
The product must allow the reviewed source range; it must not rewrite a loan's
principal, rate, term, frequency, or installment count to the line's current
default. Null or zero line ranges are not interpreted as literal zero limits
without evidence from the actual loan population.

The frozen product envelope must also contain the complete reviewed historical
population. Line `00010` therefore permits a maximum periodic rate of `30.00`,
the maximum frozen loan rate, even though the current source-line ceiling is
lower. Increasing only `maxInterestRatePerPeriod` on an exact-identity
migration product is a safe reviewed update: it admits historical contracts
but does not change any existing loan rate or schedule. Lowering the ceiling or
changing another immutable product term remains a blocking contract conflict.

The reviewed accounting mode is periodic accrual because all 12 lines have
normal interest provisioning enabled and source daily accounting evidence.
The transaction-processing strategy is
`credesal-accrued-interest-first-strategy`. For declining-balance loans using
daily interest calculation, it materializes post-due interest from the latest
schedule date covered by contractual interest through the repayment date, then
uses due-first allocation: penalty, fee, interest, principal, followed by
advance principal. This preserves the source priority of insurance before
interest and principal while preventing future interest or insurance from
being consumed before advance principal.

Post-due interest uses the outstanding principal immediately before the
repayment, the loan's annual nominal rate, and its configured days-in-year
basis. It is not added on an exact installment due date, does not apply before
the first due date, and is not applied to flat-interest or non-daily-interest
loans. Replay removes previously derived post-due interest before recalculating
transactions, preventing duplicate materialization after reversal or replay.

The basis is not hard-coded to 365. The calculator honors Fineract's native
loan-product setting: fixed `360`, `364`, or `365` divides elapsed calendar
days by that denominator; `ACTUAL` splits a cross-year interval and divides
each segment by the actual length of its calendar year. The reviewed migration
product payload currently uses actual days in month and `ACTUAL` days in year.
Changing that product term requires a new product-contract proof.

This daily post-due rule resolves the `$0.81` payment-allocation difference in
source loan `2068`; it does not reproduce Arissto's separate mixed schedule
formula, which used a 360-day periodic rate to derive the uniform installment
but 365-day interest inside that installment. Fineract deliberately keeps a
single coherent basis for loans originated natively after cutover. Migrated
historical repayment identity, date, total amount, component allocation, and
reversal state remain exact.

Accounting roles must be frozen from source postings, not column names alone.
For example, `ID_CUENTA_CARGO_PROVI` consistently resolves the interest
receivable family, but `ID_CUENTA_CARGO_DESEMBOLSO` does not by itself identify
the loan-portfolio asset. The final mapping must review, per line:

- fund source and payment-channel overrides;
- loan portfolio asset;
- interest receivable and interest income;
- penalty receivable and penalty income;
- fee/insurance income or liability accounts;
- overpayment and transfer suspense; and
- Cobro Movil's clearing-liability override.

#### Single portfolio account and reporting dimensions

Each native loan product uses exactly one `loanPortfolioAccountId`. The
reviewed primary mappings are:

| Source line | Native portfolio GL | Historical alternate retained only as evidence |
|---|---|---|
| `00001` consumer | `1141040101` | `1142040101` |
| `00010` microcredit | `1141030101` | `1142030101` |

The service does not switch portfolio accounts dynamically and does not split a
source line into multiple native products merely to reproduce Arissto's
historical account classification. Alternate source accounts are included in
reconciliation output, not posted as synthetic adjustments.

Reporting segmentation uses Fineract's native classification and dimensions.
`CRD_LINEA_CREDITO.ID_TIPO_LINEA` populates
`m_product_loan.id_tipo_linea`; product dimensions preserve
`arisstoCreditLineId` and `arisstoCreditLineTypeId`. Loan dimensions preserve
the source `ID_TIPO_CREDITO` as `arisstoCreditTypeId` and `ID_SLU` as
`arisstoSluId`. Product and loan JSON dimensions merge onto `m_loan` and are
propagated to `acc_gl_journal_entry.dimensions`, where reporting can filter by
JSON containment. Native `office_id` remains the office dimension and is not
duplicated in this JSON.

Dimension values preserve source codes and must not assert an unverified
business meaning. In particular, the historical `1141…`/`1142…` account split
is not itself turned into a dimension unless its
classification rule is independently proven.

### Minimal versioned target metadata

Migration `0293_add_arissto_loan_product_map.xml` owns the only new Gate 2
table: `credesal_loan_product_map`. It preserves `ID_LINEA_CREDITO`, company
provenance, source and contract hashes, native product ID, and review status
with one-to-one uniqueness on both sides. The crosswalk is an idempotency and
audit record produced after native product creation, not a bootstrap list that
must point at pre-existing products.

No loan or transaction shadow table is introduced. Native Fineract already has
unique external IDs on `m_product_loan`, `m_loan`, and `m_loan_transaction`;
the sync engine state preserves immutable plan/run hashes, and downstream
Cobro Movil links directly to the native transaction. Adding duplicate event
metadata would create competing identities without improving reconciliation.

## Native target ownership

| Arissto concept | Native Fineract target | Rule |
|---|---|---|
| Originated portfolio account | `m_loan` through Loans API | One target per `ID_CREDITO` |
| Contractual installments | native repayment schedule | Regular migrated loans require exact installment count, number, date, principal, interest, and aggregate totals; only the three documented line `00001` manual anomalies are exceptions |
| Effective disbursement | native loan disbursement | Source event is `CRD_MOVIMIENTOS_CARTERA`, not a liquidation header |
| Normal/mobile/refinance payment | native repayment | Exactly one target transaction per source movement |
| Reversal | native reversal/adjustment lifecycle | Never import as an unrelated second payment |
| Debt insurance and other charges | native loan charges and paid-by allocation | Preserve specific charge allocation from `CRD_DETALLE_CARGOS` |
| Current balances and arrears | native calculated loan state | Source portfolio and snapshots are reconciliation evidence |
| Source-only identifiers and classifications | versioned Credesal extension | Must not overwrite native calculated fields |

Core loan and transaction writes use Fineract APIs. Controlled SQL is limited
to versioned mapping/extension tables explicitly introduced by the final schema
contract.

## Lifecycle reconstruction

### 1. Create and approve

Create one individual-client loan from the originated `CRD_CARTERA` row and its
declared `CRD_SOLICITUD_CREDITO` parent. Preserve the source application,
approval, expected disbursement, first-payment, maturity, principal, rate,
frequency, installment count, purpose, product mapping, and all three current
staff relationships.

Arissto does not define Fineract's generic loan-officer concept. Preserve
`CRD_CARTERA.ID_PROMOTOR`, `ID_EJECUTIVO_CUENTA`, and `ID_GESTOR_COBRO`
independently in `credesal_loan_staff_assignment` and resolve each to
`m_staff.external_id = ID_EMPRESA:ID_PERSONA`. Do not populate the native loan
officer by guessing among these roles.

The source application may have a stale current workflow state even when a
portfolio loan exists. Presence of `CRD_CARTERA`, not the current application
status alone, determines that a loan was originated.

#### Rule-based legacy approval-date compatibility

The 2026-08-31 read-only audit identified exactly 48 loans where the stored
application approval/resolution date is after the effective `4/00002`
disbursement movement: loans `1` through `48`, except `21`, plus loan `55`.
All 48 violate only `approval > disbursement`; their submission date,
disbursement movement, first due date, and movement order are coherent.

The first 47 share approval/resolution date `2023-05-25` and were stamped in
the newer `DT_CREO`/`DT_MOD` fields by the same technical user on
`2023-05-29`, after their financial events. Loan `21` retains a valid timeline
and lacks those newer audit stamps. Loan `55` was modified on `2023-08-18`,
when its approval/resolution dates were also changed to `2023-08-18`, although
it had been disbursed on `2023-05-25`. This is reviewed evidence of later
conversion or editing, not true post-disbursement approval. The source evidence
is in
[`docs/learnings/prestamos.md`](../../../../../../credesal-db-space/docs/learnings/prestamos.md#fechas-de-aprobacion-tardias-en-la-cohorte-inicial).

The 48 loans are the current regression cohort, not an ID allowlist. Any current
or future loan with `approval > effective disbursement` uses the compatibility
path only when all of these source facts are true: submission is on or before
disbursement; a real `4/00002` disbursement exists; it is the first financial
movement and no movement predates it; and the first contractual due date is
after disbursement. A case that fails any predicate remains a whole-loan
quarantine.

For a qualifying case, migration uses the effective disbursement date as
Fineract `approvedOnDate` and `expectedDisbursementDate`. It also upserts one
loan-linked `credesal_loan_legacy_timeline` provenance row containing the raw
source submission, approval, resolution, and disbursement dates, the effective
approval date used by migration, and classification
`legacy-late-approval-stamp`. Reconciliation requires this row to match the
frozen plan. The source dates are therefore not silently discarded or
presented as the effective financial approval.

This compatibility rule does not depend on later audit timestamps, does not
replay manual schedule edits, and does not
weaken the general historical-effective-date requirements in
[`HISTORICAL_EFFECTIVE_DATE_REQUIREMENTS.md`](../../../../../docs/HISTORICAL_EFFECTIVE_DATE_REQUIREMENTS.md).

#### Rule-based pre-client-activation application compatibility

Fineract requires a loan submission to be on or after the target client's
activation/office-joining date. The loan planner therefore reads
`m_client.activation_date` and compares it with the frozen source application
and financial timeline.

When both the raw submission and approval predate client activation, migration
may use the client activation date as the effective Fineract submission and
approval only if activation is on or before the effective disbursement, a real
`4/00002` disbursement is the first financial movement, no movement predates
it, and the first contractual due date is after it. The raw submission,
approval, resolution, and disbursement remain in
`credesal_loan_legacy_timeline`; `effective_approved_on` records the activation
date and the classification is
`legacy-pre-client-activation-application-stamp`.

This rule is intentionally not available when target client activation is
after effective disbursement. Such a case emits
`target_client_activation_after_effective_disbursement` and remains an upstream
office/client chronology prerequisite. Moving a disbursement or subsequent
financial history forward to fit a later target activation date is prohibited.
Any partial or near-match signature emits
`invalid_target_client_activation_date_order` and remains quarantined.

### 2. Reproduce the contractual schedule

`CRD_PLAN_PAGO` is authoritative migration evidence for contractual dates and
component totals; its `PAGADO_*` columns are not payment history. Only rows
linked by `ID_CREDITO` belong to an originated loan.

The service may use Fineract's native schedule generator only after inspection
proves that it reproduces the stored schedule, including:

- immutable monthly anchors and short-month clipping/restoration;
- daily, weekly, and fortnightly frequencies;
- irregular first or final periods;
- grace periods; and
- restructured schedules.

Acceptance for a regular migrated loan requires the same installment count,
installment number, exact due date, principal amount, and interest amount for
every source installment, plus matching aggregate principal and interest at
currency precision. A native residual or interest-distribution difference is
therefore blocking for the migrated schedule even when the aggregate cash or
principal is unchanged.
`MONTO_OTROS` and `MONTO_APORTACION` are excluded from this core comparison and
must pass their separate charge or contribution contracts.

A different date, component-total drift, or another material difference makes
the plan non-applicable until reviewed. The writer must never silently
normalize source dates or discard a source component.

Both the non-posting `prove-loan-schedule` command and lifecycle reconciliation
enforce this schedule boundary. Lifecycle reconciliation reads the native
repayment periods and blocks on count, number, date, principal, interest, or
aggregate-total drift. It does not convert these differences into accepted
native variances.

Apply also enforces the boundary before mutating the new loan. Migration loan
products enable native variable installments with a one-day minimum and
366-day maximum gap. For an incoming refinance, the writer first applies the
already-contracted, component-exact predecessor bridge because Fineract's
non-posting calculator enforces top-up validation whenever `loanIdToClose` is
present. For a new loan the writer then runs Fineract's non-posting base
calculator. When the base schedule differs, it may create only a submitted,
pending application, which has no accounting effect. It then converts each
source installment except the native residual period into an installment-total
term variation, previews the complete result through
`loans/{id}/schedule?command=calculateLoanSchedule`, and persists the variations
only when every date, principal, interest, and aggregate total is exact. It
reads the stored schedule again and will not approve or disburse until that
second comparison is also exact.

The final installment is never forced directly because Fineract reserves it to
settle residual principal; the strict preview must nevertheless prove its exact
source principal and interest. A failed preview leaves at most a pending,
non-posting application for inspection and retry. A lost response after a
successful variation write is safe: recovery observes the already-exact
schedule and does not add the variations twice. An existing approved or active
loan with schedule drift remains blocking and is never rewritten in place.
Plans freeze schedule writer version `fineract-variable-installments-v1`; older
plans must be rebuilt.

Arissto rounds exact half-cent periodic interest toward the lower cent. To
preserve source-exact migrated schedules, Fineract uses `HALF_DOWN` for
installment interest only when the loan product uses the dedicated
`credesal-accrued-interest-first-strategy`. Other products continue using the
tenant monetary rounding mode. This rule applies in application preview and in
persisted schedule regeneration; it is not a reconciliation tolerance.

A bounded legacy cohort uses a different first-period boundary and denominator.
The planner derives this behavior from the frozen schedule rather than source
loan IDs or a historical cutoff: the first interest must equal fixed-365 daily
interest including both the origin and first-due dates, differ from the
exclusive result, and every later period must equal fixed-365 exclusive daily
interest. Dates must be strictly increasing and current rows must carry no
restructuring or deferred-installment marker. A partial signature is a blocking
`ambiguous_first_accrual_day_signature` quarantine. A complete signature sets
the native loan-level `interestChargedFromDate` to one day before the source
origin and `daysInYearType` to `365`, while retaining the actual financial
disbursement date independently. The financial disbursement may precede the
contractual origin; that difference does not invalidate an otherwise complete
source-derived signature. Normal loans inherit the product's Actual/Actual
behavior and receive neither override. The ordinary source-exact variable-
installment preview and persisted-schedule guards remain mandatory.

Loan `3` is a separate line-`00001` signature, not a member of that line-`00010`
legacy cohort. Its effective disbursement is exactly one day before source
origination, its first interest matches fixed-365 accrual from that effective
date, and every later period matches fixed-365 exclusive counting. Only the
complete monthly, monotonic, non-restructured, non-deferred signature sets
`interestChargedFromDate` to the effective disbursement and `daysInYearType` to
`365`; a near-match remains blocking. If a closed loan reversed an earlier
disbursement but later reissued an effective disbursement, that paired reversal
does not suppress the bounded terminal cutover adjustment. A loan whose only
disbursement was terminally reversed remains excluded from that adjustment.
The terminal adjustment is a non-cash, source-exact goodwill transaction. At
apply time the engine computes the principal, interest, fee, and penalty deltas
between Fineract's post-replay balances and the terminal component balances
frozen from Arissto, submits all four portions explicitly, and then re-reads the
loan. Apply and reconciliation fail unless every component and the terminal
status match Arissto. Fineract must not choose the adjustment allocation from a
single undifferentiated total.

Loan `2068` remains the known diagnostic for Arissto's mixed 360/365 schedule
formula. The dedicated transaction strategy makes its actual late repayment
allocation exact, but that does not authorize a different migrated contractual
schedule. Local pending-application proofs now preserve this schedule exactly,
including the mixed 360/365 case. This clears the schedule-writing
implementation gap, but does not by itself renew Gate 5 promotion: the full
posted lifecycle, accounting, refinance, repayment-allocation, and
unchanged-replay canary matrix must still pass. Loans originated natively in
Fineract after cutover may use Fineract's coherent schedule rules; migrated
Arissto installments remain source-exact.

#### Reviewed historical schedule exceptions for line `00001`

Source loans `24`, `435`, and `945` are entity-level historical exceptions,
not product-generation requirements. Loan `24` is an early closed loan whose
five stored installments contain the full approved principal despite a
six-installment header. Its native Fineract shell is created with the reviewed
six-installment header, not the five-row manual plan; the migrator then replays
the authoritative source movements and reconciles the closed terminal state.
This is an identity-scoped migration override and does not change Fineract's
product or schedule-generation rules. Loan `435` is a closed refinancing loan whose truncated
plan belongs to the refinance lifecycle. Loan `945` is active and has a
modified stored plan whose first-payment date, maturity, and scheduled
principal no longer agree uniformly with its header.

These loans do not block review of the line `00001` product and must not be
used as native schedule-generation canaries. The plan preserves their source
header, stored schedule, movements, and exception classification as historical
evidence; it never manufactures missing installments to make the records look
regular. Closed loans `24` and `435` may replay to their observed terminal
state without regenerating an artificial contractual schedule. Active loan
`945` follows the same reviewed exception: Fineract may retain its own native
schedule after replaying the authoritative source lifecycle. A difference in
installment count, dates, or installment-level allocation does not quarantine
loans `24`, `435`, or `945` and does not create synthetic installments or
adjustment transactions.

Acceptance remains strict at the financial-lifecycle boundary. Every source
movement identity and component total must be preserved, and cutover balances
and terminal status must reconcile at currency precision. The plan records the
source schedule and native difference as `manual-adjustment` evidence. This
allowlist must not be generalized to another loan or product merely because a
native schedule differs. New exceptions require their own reviewed evidence
and contract change. The source evidence is documented in
`docs/learnings/prestamos.md` in the exploration repository.

Line `00010` loans `301`, `1117`, `1182`, `1484`, `1743`, `1748`, `2069`,
`2241`, `2254`, and `2355` are separately reviewed manual-adjustment exceptions. Loan `1484`
has two archived edits before its current 18-installment monthly plan. The
other seven have operator-created `CRD_REESTRUCTURACION` rows and archived
plans followed by a final installment pinned to the contractual maturity date
even though lower-numbered installments occur later. Loans `1117`, `1743`,
`1748`, `2069`, `2254`, and `2355` also carry operator-reviewed negative final
interest used to dispense interest; loan `945` has the same behavior under the
line `00001` exception, while `2241` has the date adjustment without negative
interest.

These schedules and archived versions are historical provenance, not financial
events and not schedule-generation rules to reproduce in Fineract. The
migration accepts Fineract's native schedule as a visible, non-blocking
variance and does not replay archived edits, synthesize installments, reproduce
negative interest, or create adjustment transactions. Source movement
identities and component totals, cutover balances, and terminal status remain
blocking and exact. Loan `2374` is not covered by the manual-adjustment policy:
it has no adjustment row or archived plan. Its separate guarded source-exact
rule combines only the exact duplicate-date terminal pair into one 99th period;
after a later refinance closes the loan, the rule also requires one
disbursement, one final payoff with a named successor, full principal
settlement, and zero terminal source balances. Any changed or partial signature
remains quarantined. Full replay
`b946bacae2d54fbfa4bdf3610eb77d44` recovered it successfully after that
cardinality fix.

Closed loans `23`, `90`, `317`, `340`, and `359` are an additional reviewed
line `00010` manual-adjustment cohort. Every loan has operator adjustment
history and one or more archived schedule versions. Their current schedules
are retained as historical provenance under planner policy
`reviewed-manual-adjustment`. This policy has historical-reference-only
behavior: archived edits are not replayed, no missing
installments or adjustment transactions are synthesized, and no calculator
rule is inferred from the edited shape. Exact source movements and component
allocations, charges, cutover balances, terminal status, and accounting remain
blocking. This exception is limited to these closed source identities.

A separate source-derived terminal classifier covers a closed loan whose
header retains only stale debt-insurance residue. It applies when source state
is `3`, `SALDO_TOTAL`, `ULTIMO_SALDO`, both interest balances, mora, recargos,
and CxC are all exactly zero, while `SALDO_SEGURO` alone remains positive. The
planner freezes the exact residue and authoritative zero terminal total,
requires a non-empty source-exact event reconstruction, and expects Fineract to
remain closed with zero native fee balance. Every actual disbursement, charge,
payment, reversal, allocation, terminal adjustment, and journal remains strict;
the header residue is never synthesized as collectible debt. This rule is not
limited to `23`, `317`, and `359`: any future loan receives the same treatment
only when the complete signature matches. A partial signature uses ordinary
strict reconciliation, and a matching header without reconstructable events is
quarantined.

Active loans `479`, `1738`, `1841`, and `1869` are not covered by the
historical-only extension because their current adjusted schedules still define
obligations. They use a reviewed source-exact active-schedule import instead:
create, approve, and disburse the native loan; install the current frozen
Arissto principal/interest schedule before any servicing; then replay movements,
charges, balances, status, and accounting normally. Archived adjustment
operations and archived schedule versions remain provenance and are never
replayed or generalized into a calculator rule. The import is identity-scoped
and requires the reviewed source state, line, adjustment count, schedule row
count, sequential monotonic dates, no deferred rows, and exact full-principal
allocation. Any signature drift quarantines the loan.

`G5-SCH-009` acceptance is enforced by
`check-loan-adjusted-schedule-cohort`. The checker requires both state-specific
planner contracts, a completed or recovered run, strict reconciliation, and an
independently reconciled unchanged same-plan replay. Only
`reviewed_manual_adjustment_schedule_variance` is permitted, and only for the
five closed loans. Active-loan schedule variances, any other reviewed variance,
or any blocking movement, allocation, charge, cutover-balance, status,
accounting, or journal finding rejects acceptance. This replaces the obsolete
requirement for a separate closed-subgroup apply.

Loan `1738` has one additional bounded representation detail: its 19th source
row has zero principal and interest and retains only `MONTO_OTROS`. The full
19-row source plan remains frozen as provenance, while the source-exact active
schedule imports the 18 financial rows. The charge is migrated and reconciled
through its native charge identity rather than synthesized as an empty loan
installment.

The 20 closed refinance predecessors `281`, `283`-`286`, `315`, `331`, `632`,
`634`-`636`, `639`-`641`, `648`, `971`, `983`, `992`, `995`, and `998` are a
separate historical-reference cohort. They are not manual-adjustment
exceptions: their current schedules are monotonic, allocate the complete
approved principal, and have no restructuring or deferred-installment marker.
Fineract may retain its native closed-loan schedule because the source schedule
no longer defines future servicing. The source schedule stays frozen in the
plan as provenance and any target difference remains a visible
`historical_reference_only_schedule_variance`.

This exception is accepted only when the source identity still has state `3`,
positive principal, sequential installments with increasing due dates, one
disbursement, exactly one native refinance payoff, exact full-principal
allocation outside disbursement, and zero `ULTIMO_SALDO` and `SALDO_TOTAL`.
Any signature drift returns the loan and its refinance component to quarantine.
Movement identities, repayment components, refinance transfers, charges,
cutover balances, terminal status, and balanced journals remain strict.

The closed-refinance historical-schedule regression canary is fixed at these
20 roots plus their 57 known refinance descendants. It is not the separate
`G5-SCH-014` contractual-anchor cohort. `check-loan-reference-canary` rejects a
plan if any expected identity is missing, any root lacks the historical-
reference policy, or any of the 77 loans is quarantined. With `--run`, it
additionally requires every affected item to be succeeded, recovered, or
unchanged and performs strict reconciliation with no blocking finding.

Loans `301`, `1117`, and `1182` have a narrower creation rule in addition to
their historical-schedule classification. Their current approved
`CRD_CARTERA.INTERES_MONTO_APROBADO` rate is lower than the stale
`CRD_CARTERA.PORC_INTERES_APROBADO` value retained after operator
restructuring. The current portfolio rate is therefore used only to
create Fineract's native staging schedule for these three identities. The
source schedules and archived versions remain provenance; movements,
allocations, charges, balances, status, and accounting remain exact. A partial
pending application created by the older payload may be updated to the frozen
staging rate before lifecycle recovery. The engine must fail on a conflicting
approved, active, or completed loan rather than rewrite it.

Loan `805` has a separate reviewed early-payoff cutover rule. Its `3,500.00`
principal is within line `00010`'s `6,800.00` product maximum, but its frozen
36-month source schedule carries `4,312.62` of contractual interest. Arissto
closed the loan after collecting `396.78` of interest, leaving `3,915.84` of
unearned future interest for Fineract's migration-only terminal goodwill
credit. For this identity only, the adjustment safety ceiling is derived from
the frozen source-schedule total instead of approved principal. Exact source
payments, component allocations, zero terminal balances, closed status,
balanced journals, and idempotent replay remain mandatory.

Loan `1638` uses the same identity-scoped early-payoff cutover rule for its own
independently reviewed source shape. Its `3,500.00` principal is fully allocated
by the frozen Arissto movements, while its 48-installment source schedule carries
`5,785.14` of contractual interest and `101.28` of other scheduled amounts.
Arissto closes the loan with every component balance at zero; after the exact
source movements are replayed, Fineract retains `4,524.83`, all as interest:
`4,291.13` of unpaid contractual future interest plus `233.70` of post-due
interest materialized by Fineract while replaying the dated source payments.
The migration-only terminal goodwill event is therefore an explicit
interest-only `4,524.83` bridge to Arissto's zero interest balance, bounded by
the frozen `9,386.42` source-schedule total rather than approved principal.
Source cash, component allocations, zero terminal balances, closed status,
balanced journals, and idempotent replay remain mandatory.

Loan `1441` is explicitly not a manual-adjustment exception. Its first source
installment (`principal + interest`) remains `205.29`. Non-posting Fineract
calculator proofs established that `205.29` produces 76 native periods and
`205.31` produces exactly 75. Loan `1441` therefore uses `205.31` only for
native creation cardinality. After its sole disbursement and before any
servicing, the identity-guarded `sourceExactActiveSchedule` command installs
the exact 75 source rows and the engine re-reads every date, principal, interest,
and total. The source value is checked as a fail-closed precondition before the
staging override is used. This override is limited to `1441`; it neither changes
the product calculator nor weakens exact schedule reconciliation.

Loan `83` is a separate, entity-level historical-reference exception and is
not classified as a manual adjustment. Its six stored rows carry only
`500.71` of principal against the `1,000.00` approved amount, so they cannot be
written as a complete contractual schedule. Fineract retains its native
schedule while the plan keeps the Arissto rows as provenance. This does not
change transaction behavior: every source movement and component remains
exact, including the atomic `5037`/`5038`/`5039` reallocation, and cutover
balances, terminal status, and journals remain blocking reconciliation checks.
The exception is limited to loan `83` and must not become a product rule.

Loan `26` is a separate closed historical-reference exception with a stricter
runtime signature. Its approved and disbursed principal is nonzero, every
stored schedule row carries zero principal, and the source lifecycle closes
the complete principal through ordinary repayments plus one refinance payoff.
The planner accepts the native Fineract schedule only when the source loan is
closed, the stored plan has zero principal and positive interest, exactly one
disbursement and one refinance payoff exist, and all non-disbursement principal
allocations equal the approved principal. A failed predicate emits
`historical_reference_schedule_signature_mismatch` and restores the ordinary
exact-schedule path. The exception does not synthesize a schedule, payment, or
adjustment and remains limited to the reviewed `26 -> 108` chain.

Loans `8`, `1739`, `1795`, `1893`, `2063`, `2111`, and `2482` form a
separate reviewed historical-reference cohort. Each current Arissto plan has a
monotonic trailing zero-core segment: principal and interest are both zero
after the preceding rows have already allocated the full approved principal.
The rows have no `ID_REESTRUCTURACION`, are not deferred installments, and do
not duplicate installment numbers. They therefore are not manual adjustments
or financial events to reproduce. Five tails retain scheduled
`MONTO_OTROS`, loan `2111` retains `MONTO_OTROS` with independently proved
historical insurance payments, and loan `2482` has two completely empty tail
rows.

Fineract rejects a zero-valued variable-installment modification, so these
seven loans retain the complete Arissto plan as historical provenance and use
the native target schedule. The migration must not synthesize zero payments,
installments, schedule edits, or adjustment transactions. Source movement
identities and component totals, independently proved charges, cutover
balances, terminal status, and accounting remain exact blocking checks. This
exception is an entity allowlist for the seven reviewed loans, not a general
rule for every zero-valued row or line `00010` schedule.

Loans `381`, `1775`, `1871`, `1926`, and `2006` are the narrower single terminal
charge-only cohort. Their preceding installments allocate the full approved
principal, then exactly one final monotonic row carries zero principal, zero
interest, positive `MONTO_OTROS`, zero contribution, no restructuring link,
and no deferred marker. The terminal row is scheduled charge provenance, not
an additional loan repayment obligation. It is retained in the frozen plan as
historical reference while Fineract keeps its native repayment count.

The runtime predicate requires the complete signature above, sequential unique
installment numbers, and strictly increasing due dates. A near-match emits
`historical_reference_schedule_signature_mismatch:terminal-zero-core-charge-only-row`
and returns to exact schedule enforcement. Historical charge details and paid-by
allocations, cutover insurance balance, the native future recurring charge for
active loans, source movement components, terminal state, and accounting remain
independently blocking. No installment, zero payment, schedule edit, charge, or
adjustment transaction is synthesized from `CRD_PLAN_PAGO.MONTO_OTROS`.

Loan `1926` also closes through the independently reconstructed refinance into
loan `2135`. Its terminal row falls on `2028-04-18`, after the source payoff on
`2026-06-24`, so it cannot be interpreted as an additional realized repayment
or charge. The same terminal-row runtime predicate applies, while the payoff,
historical insurance paid-by allocations, successor dependency, balances, and
terminal state remain exact blocking reconciliation facts.

### 3. Disburse from the effective movement

The definitive `CRD_ENC_LIQUIDACION` and its details describe allocation of
funds, but `CRD_MOVIMIENTOS_CARTERA` transaction `4/00002 DESEMBOLSO` is the
effective disbursement event. A portfolio row still awaiting disbursement must
remain approved/undisbursed in Fineract and must not receive a synthetic
transaction.

Disbursement amount, date, payment channel, and refinance allocations must
reconcile to the definitive liquidation before apply.

### 4. Replay movements in deterministic order

Within each loan, process source movements by effective business timestamp and
then by the source technical ID as a stable tie-breaker. The exact timestamp
precedence must be frozen in executable configuration after a null-coverage
inspection of `FECHA_OPERACION`, `FECHA_VALOR`, `FECHA_PAGO`, `DT_MOVIMIENTO`,
and `DT_CREO`.

Initial transaction mapping:

| Arissto transaction | Native intent | Status |
|---|---|---|
| `4/00002 DESEMBOLSO` | Disbursement | Native mapping and reversal pairing accepted |
| `4/00001 PAGO CREDITO` | Repayment | Native mapping identified |
| `14/00011 CD-PAGO CREDITO` | Repayment with Cobro Movil payment type | Native clearing mapping and reversal accepted for line `00010` |
| `4/00019 PAGO CREDITO-REFINANCIAMIENTO` | Prior-loan payoff funded by new loan | Native single-predecessor refinancing and atomic multi-predecessor settlement accepted, including reviewed cross-client and partial-paydown evidence; unknown graph shapes quarantine the whole chain |
| `4/00013 PAGO CREDITO (AJUSTADO)` | Repayment using its stored component allocation | Active rows are independent repayment facts; a marked reversal pairs like other repayments |
| `4/00004 NOTA DE CARGO (REVERSION)` | Reverse an earlier repayment | Exact deterministic pairing accepted |
| `4/00030 DESEMBOLSO (REVERSION)` | Reverse an earlier disbursement | Exact deterministic pairing accepted |

Rows with `REVERSION='1'` cannot be treated as normal active transactions.
Fineract represents reversal state on the original transaction, so the engine
orders movements by `FECHA_OPERACION` and then zero-padded
`ID_MOVIMIENTO_CARTERA`. Each reversal consumes the most recent earlier,
unpaired movement on the same loan with the same eligible transaction family
and exact component signature. Repayment notes may consume `4/00001`,
`4/00013`, `4/00019`, or `14/00011` rows marked `REVERSION=1`;
disbursement-reversal notes consume `4/00002` rows, whose originals are not
consistently marked. Matching by amount alone is prohibited.

The refreshed audit paired ordinary repayment and disbursement reversals without
reusing an original. Two additional repayment-reversal notes on loan `83`
(`0000005037` and `0000005038`) had no remaining eligible originals because an
earlier valid pair had already restored the same payments. They are accepted
only as one composite atom with later same-close repayment `0000005039`: the
three rows net cash to zero and move exactly `2.15` from interest to principal.
The classifier requires matching loan, date, close, actor, and payment type,
previously proved reversal signatures, exactly one later repayment, zero
unsupported components, and an equal signed principal/interest delta. Any
partial or near-match signature retains the ordinary orphan quarantine.

### 5. Preserve payment components

`CRD_MOVIMIENTOS_CARTERA` is authoritative for the source allocation among
principal, interest, pending interest, mora, insurance, recargos, CxC, savings,
contributions, and IVA. `MONTO_OTROS` must not be added to `MONTO_SEGURO` when
it is the same legacy aggregate, because that would double-count insurance.

Native allocation must reconcile at least:

```text
source total
  = principal
  + interest and supported pending-interest treatment
  + penalty/mora
  + mapped loan charges
  + any explicitly supported cross-product component
```

Debt insurance is a native charge, not principal or penalty. Its exact paid-by
relationship comes from `CRD_DETALLE_CARGOS`. Savings and contribution
components are currently unpopulated in the reviewed credit flow; if future
inspection finds them, the loans service must depend on the corresponding
native account service and create an explicit cross-product transaction rather
than absorb them into a loan fee.

### Debt-insurance calculation and cutover

Already-assessed insurance is migration history, not a value to recalculate.
For every assessment before the migration cutover, import the exact supported
source charge and its payment allocation from `CRD_DETALLE_CARGOS` and the
authoritative movement components. Do not derive those historical amounts from
`CRD_PLAN_PAGO.MONTO_OTROS`; the stored plan component can contain fixed or
upward-biased projections that do not match the charge actually collected.

Future debt insurance uses Fineract's loan-only installment charge calculation
`PERCENT_OF_OUTSTANDING_PRINCIPAL` (enum `8`). For each normal repayment
installment:

```text
insurance due = opening principal outstanding * configured percentage / 100
```

The result uses the tenant currency precision and normal Fineract rounding. It
is not rounded upward merely to reproduce an Arissto projection. Down-payment,
additional, and re-aged schedule rows are excluded. The charge's submitted date
is the cutover boundary: installments due before that date are not assessed by
the dynamic charge, while installments due on or after it are. If future
installment charges are regenerated, principal already completed or written
off is removed from their calculation base.

The writer must therefore keep the two paths disjoint: source-exact historical
charge facts before cutover, and one dynamic native charge from cutover onward.
It must quarantine a loan if the same installment would receive both paths.

For full re-sync, a later source repayment may reduce the carried
`source_insurance_cutover_outstanding` snapshot. The writer must allocate that
repayment's exact insurance component to the existing cutover charge when, and
only when, the sum of newly observed post-cutover insurance components exactly
equals the decrease from the target charge's current outstanding amount to the
newly frozen `SALDO_SEGURO`. It must preserve the cutover charge's external
identity and immutable original amount. Creating and immediately settling a new
historical charge does not reduce the carried balance and is forbidden for this
case. Ambiguous deltas and conflicting existing payment ownership fail closed.

Fineract's general interest-recalculation configuration remains incompatible
with the dynamic `PERCENT_OF_OUTSTANDING_PRINCIPAL` installment charge and is
not enabled for this contract. The reviewed transaction strategy provides the
required post-due daily interest behavior without enabling that incompatible
schedule-recalculation mode. A local posted lifecycle for source loan `2068`
proved the combined behavior: a `$40.00` payment one day after the first due
date allocated `$0.21` insurance, `$12.89` interest, and `$26.90` principal,
matching the source movement exactly. Repayment and disbursement reversal left
every affected GL account at zero net movement.

## Refinancing and restructuring

Refinancing creates a new loan and pays one or more prior loans. The verified
source relationship is:

```text
new definitive liquidation detail
  -> prior CRD_MOVIMIENTOS_CARTERA payoff
  -> prior CRD_CARTERA loan
```

`NO_PRESTAMO_ANTERIOR` and `CRD_CREDITO_VINCULADO` are not authoritative. The
writer preserves the explicit definitive-liquidation relationship and expands
any selected scope to include the complete predecessor/successor chain. For one
predecessor it submits the successor through the native refinancing aggregate
with one settlement. For a consolidation it classifies each verified source
settlement as `FULL_CLOSE` or `PARTIAL_PAYDOWN`, submits only the full-close
predecessors in `loanIdsToClose`, and submits one source-exact settlement row
for every predecessor. Fineract atomically creates every loan-to-loan transfer
before disbursing the exact remaining net cash. Full-close predecessors must
end closed without a material balance; partial-paydown predecessors must remain
active with a positive residual and retain any later source transactions.
Because Fineract recalculates each full-close predecessor at the historical
payoff date, deterministic goodwill-credit bridges separately capture each
dated prepayment-quote difference and any post-settlement residual; no bridge
is represented as customer cash. Partial paydowns use their exact source
allocation and never receive a closure bridge.

The fail-closed partial classifier requires all three facts: the source
predecessor is currently active, its current balance is material, and it has an
unreversed posted payment after the consolidation date. Otherwise the
settlement remains `FULL_CLOSE`. A mixed consolidation must contain at least
one full-close settlement; an all-partial group is quarantined rather than
invented as refinancing.

A fully reversed refinance attempt is omitted only when the predecessor
payoff has an exact compensating reversal, the abandoned successor contains
only an exact disbursement/reversal pair, and that successor is canceled with
zero disbursement and every material balance at zero. The plan preserves all
four source movement IDs as provenance, emits a reviewed no-write action for
the abandoned successor, and removes only that reversed edge from the
effective graph. A partial signature remains quarantined. The writer never
flattens a real consolidation or an uncertain reversal into ordinary
repayments. See the cross-stack
[refinancing and consolidation contract](../../../../docs/LOAN_REFINANCING_AND_CONSOLIDATION.md).

`ID_REESTRUCTURACION` describes a same-credit schedule version, not a new loan
identity. The current source contains 6,603 tagged schedule rows across 174
snapshots, but every row has null `ID_CREDITO`; zero rows link to a current
`CRD_CARTERA` loan. Same-loan restructure migration is therefore not applicable
to this executable portfolio. The planner still quarantines any future linked
row as `native_restructure_proof_pending` rather than guessing.

## Accounting and payment channels

The service does not copy `CRD_MOV_CARTERA_CONTABLE` or general-ledger rows into
Fineract. Those rows are source evidence used to configure and reconcile native
loan-product accounting.

Each payment channel must map to the reviewed Fineract payment type and fund
source. For Cobro Movil, the intended repayment posting is:

```text
Debit  CUOTAS PENDIENTES DE APLICAR
Credit principal, interest, mora, insurance, and mapped charges
```

The controlled local proof for source line `00010` accepts this payment-channel
mapping. A `$40.00` Cobro Movil repayment debited the clearing liability for
`$40.00`, credited the exact principal, interest, and insurance allocation, and
returned every affected GL account to zero after repayment and disbursement
reversal. Cobro Movil therefore does not require a separate financial-event
writer; it is a payment-type/fund-source override on the repayment owned by the
loans service.

The V17 controlled local proof also accepts the complete periodic-accrual cycle
for this canary. Periodic accrual and repayment both use `$12.89` interest; all
12 dynamic insurance installments persist without duplication; and the first
`$0.21` assessment posts debit to insurance/fee receivable `1530` and credit to
liability `222007020102`. The product owns that credit through its native
charge-specific fee mapping. Repayment clears the exact receivables and uses
the Cobro clearing liability as its fund source; reversal leaves zero net GL
movement.

## Plan safety and quarantine

A scoped plan is non-applicable when any selected loan has:

- a missing client, office, employee, or product dependency;
- duplicate or conflicting loan/account identity;
- missing or duplicated `ID_MOVIMIENTO_CARTERA`;
- an unsupported transaction code;
- an ambiguous reversal or adjustment relationship;
- a generated schedule outside the strict proof tolerance without a reviewed
  variance classification or an explicit historical manual-adjustment
  exception;
- an unexplained component-total difference;
- application dates outside native lifecycle order unless they match the
  reviewed `legacy-late-approval-stamp` cohort and frozen evidence above;
- a refinance dependency outside the selected/available loan graph; or
- target data under the same external ID that fails the source and contract
  hashes.

Quarantine is entity-scoped where possible. A transaction failure cannot leave
later movements applied to an invalid earlier balance; the loan and all of its
remaining movements must stop together. Refinancing is the exception to the
single-loan boundary: if any predecessor or successor has an intrinsic source
quarantine, the planner marks the entire connected refinancing component with
`refinance_chain_quarantined:<root>:<reason>`. It must not import a predecessor
whose terminal payoff can only be produced by a quarantined successor. Missing
target prerequisites such as a client or employee do not become permanent
chain quarantines because a new plan can resolve them after prerequisite
services run.

## Idempotency and recovery

- Journal product and loan actions with typed keys such as `product:00001` and
  `loan:24`; raw source IDs are not safe because the state journal is unique by
  `run_id, source_key`.
- Resolve a product retry by its exact deterministic external ID before any
  create call. If an exact contract match proves that creation succeeded before
  a crash, repair the missing `credesal_loan_product_map` row and do not create
  a duplicate. Write the crosswalk only after the native product exists.
- The bounded worker pool records dependent loans as `blocked` when the product
  fails. After product resolution, it may run independent loans concurrently,
  but it submits, approves, disburses, and replays each individual lifecycle in
  source order only after the non-posting native schedule matches the frozen
  source schedule. Refinance successors wait for their predecessor outcomes.
  A hard-crash retry includes plan actions with no journal row, not only
  explicit failures.
- Each worker owns its Fineract HTTP session and never writes SQLite state.
  The main thread journals completed outcomes. A transient connection/time-out
  or HTTP 429/5xx failure opens a shared pause gate; one lifecycle probes
  recovery after the configured delay before the remaining workers resume.
  Non-transient validation failures are not automatically retried.
- Failed-only retry starts from explicit failures and unjournaled crash gaps,
  then adds only blocked descendants of those actions. A healthy product added
  solely as a failed loan's prerequisite does not select every sibling loan on
  that product; an explicitly failed product still selects its dependants.
- Resolve loans and transactions only through their namespaced external IDs.
- Persist source and contract hashes in sync state and the approved target
  mapping extension.
- Re-read the complete selected loan lifecycle before apply and reject source
  drift from the reviewed plan.
- Never delete a Fineract loan or transaction.
- A retry continues only after reconciling the target state already created.
- API idempotency keys include a bounded run-attempt suffix. This permits a
  reviewed retry after Fineract cached a failed command; deterministic external
  IDs and pre-write recovery remain the duplicate-prevention mechanism.
- Persist a bounded safe Fineract error response (up to 4,000 characters) so
  the concrete validation code is not lost behind the generic API envelope.
- A second unchanged run produces zero new native loans, transactions, charges,
  or journal entries.

## Reconciliation and acceptance

For every selected loan, reconciliation compares:

- client, office, product, staff, dates, principal, rate, frequency, and status;
- the frozen source schedule against every native installment number, due date,
  principal amount, and interest amount, plus aggregate principal/interest
  totals;
- movement count and every source-to-target external ID;
- transaction date, type, amount, reversal state, and component allocation;
- charge creation, outstanding amounts, and paid-by allocations;
- principal, interest, penalty, fee, overpayment, and total balances;
- closed/active/undisbursed outcome;
- refinance predecessor/successor relationships; and
- the exact migrated collateral set, asset and valuation identities, final
  appraisal amount/date/status, loan quantity, and immutable pledged/eligible
  valuation snapshot; and
- native journal entries against the reviewed accounting roles.

Transaction identity, date, total amount, principal/interest/penalty/fee
allocation, reversal state, terminal status, schedule count/dates/amounts, and
journal balance are blocking mismatches. Only explicitly reviewed
point-in-time balance interpretations and the three line `00001` manual
schedule exceptions are emitted as non-blocking variances. A correct payment
total never excuses a different historical component allocation.

Acceptance requires a controlled local lifecycle run that covers at least:

- one active normal loan;
- one fully paid loan;
- one undisbursed approved loan;
- one normal repayment and one Cobro Movil repayment;
- one repayment reversal;
- one disbursement reversal;
- one debt-insurance charge and payment;
- one refinanced predecessor/successor chain;
- one mortgage collateral and one vehicle collateral, including an unchanged
  retry that recovers their deterministic asset and valuation identities;
- a portfolio proof that either covers a linked restructure or establishes
  that no linked restructure exists; and
- an idempotent second run.

## Residual entity quarantines

Source loan `2120` is a reviewed source error and must always produce a
`quarantine-loan` action. It is an undisbursed, all-zero shell superseded on the
same day by valid replacement loan `2121`, which carries the `$527.00` balance,
100-installment schedule, disbursement, movements, and the real refinance link
from loan `2064`. The service must never create a target loan for `2120`, infer
its principal from the stale approved application, or omit the quarantine from
the plan and reconciliation report. Loan `2121` remains independently eligible
for the normal supported refinance lifecycle.

- source loan `83`, whose two orphan repayment reversals have no eligible
  original;
- partial or non-zero reversed-refinance signatures that do not satisfy the
  reviewed provenance-only omission contract; and
- any future schedule linked to both `ID_CREDITO` and
  `ID_REESTRUCTURACION` until its native same-loan reschedule is proved.

These are surfaced in plans and reconciliation. They do not silently broaden
the supported contract and do not block unrelated reviewed loans.
