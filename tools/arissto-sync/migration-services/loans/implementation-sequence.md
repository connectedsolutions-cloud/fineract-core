# Loans implementation sequence

The loans service has completed Gates 1 through 4. Gate 5 was completed under
the earlier aggregate-total/native-variance policy and was reopened when the
contract was tightened to require exact source installment dates and component
amounts plus exact historical repayment allocations. The sequence below
records the evidence and the order that must remain intact.

## Current status — 2026-09-01

**Overall status: blocked for full-target or production promotion.** The
service is executable only for reviewed proof work. Passing unit tests and
successful canaries prove individual mechanisms; they do not close Gate 5.

Completed engine capabilities:

- deterministic full-scope extraction below SQL Server's parameter limit;
- source-exact schedules through native pending term variations;
- source-exact ordinary, adjusted, Cobro Movil, reversal, fee, and penalty
  transaction allocation;
- evidence-bounded handling of returned cash, pre-detail debt insurance, and
  net-zero reversed manual adjustments without summing generic `MONTO_OTROS`
  or `MONTO_IVA` into every movement;
- deterministic historical penalty-charge materialization;
- supported native single-predecessor refinance with component-exact payoff,
  outstanding-balance bridge, payoff-shortfall handling, recovery, and
  unchanged canary replay;
- source-derived omission of fully reversed, net-zero refinance attempts with
  preserved provenance, plus fail-closed whole-loan quarantine for partial
  reversal signatures, multi-predecessor consolidations, and loan `83`'s
  orphan repayment reversals; and
- deterministic external identities, bounded retry selection, accounting
  checks, and downstream repayment identity ownership.

Still required to close Gate 5:

1. Resolve the remaining structurally distinct source-exact schedule preview
   and variable-installment modification failures. The generalized
   exact-half-cent class and `2096 -> 2243` are fixed and proved. The reviewed
   operator-adjusted schedules are historical exceptions that Fineract does
   not recreate; loan `2374` remains a separate fail-closed duplicate-date
   anomaly. Loan `1864` exposes the generalized full-leap-year Actual/Actual
   rule, and the all-zero schedule is independently classified.
2. Re-plan after clients and employees are complete. Each `CRD_CARTERA` role is
   synchronized independently to `credesal_loan_staff_assignment`; inactive
   historical staff remain valid references, while missing staff or clients
   are explicit upstream prerequisite gaps. Native loan-officer eligibility is
   not a prerequisite and assignments must not be dropped to bypass gaps.
3. Review and stabilize the remaining non-refinance portfolio quarantines.
   Movement-component residuals and legacy application-date ordering are now
   classified and complete; other rows may remain quarantined only with an
   explicit reviewed classification.
4. Run the strict lifecycle matrix on a clean tenant or never-migrated
   identities. Older local identities created before the exact schedule writer
   are evidence only and must not be rewritten in place.
5. Run a fresh full supported-population `plan -> apply -> reconcile` and meet
   every acceptance criterion below with zero failed supported loans.
6. Build and review a second full plan, proving zero unintended loan,
   transaction, charge, paid-by, transfer, or journal writes.


The 18 fully reversed refinance attempts are reviewed net-zero history, not a
native lifecycle to replay. Their abandoned successors remain visible as
explicit no-write actions while the reversed edges are removed from the
effective graph. Partial signatures still fail closed. The 12 genuine
multi-predecessor successors remain an intentionally unsupported boundary and
must not be forced through the one-predecessor path.

## Gate 1: read-only source inspection

- Extract originated `CRD_CARTERA` loans with their application, client,
  product line, schedule, movements, charges, liquidation, refinance, and
  restructuring relationships.
- Produce coverage and uniqueness checks for every contract identity.
- Inventory transaction codes, null timestamp coverage, reversal candidates,
  schedule variants, and component reconciliation.
- Support one `ID_CREDITO` canary without loading target credentials.

Delivered: `inspect --block loans [--source-key ID_CREDITO]` with no target
credentials, planning, or writes.

## Gate 2: target schema and product contract

- Assume an empty business-data target after schema, chart-of-accounts, and
  catalog bootstrap. Create one native product through the API for each
  reviewed source line required by the selected loans.
- Resolve retries only by `ARISSTO:CRD-LINE:{ID_LINEA_CREDITO}`. Never reuse a
  product by name, short name, target ID, or `id_tipo_linea`.
- Write the versioned `ID_LINEA_CREDITO` crosswalk only after native product
  creation, retaining `ID_EMPRESA` as provenance and rejecting multi-company
  source data.
- Add only the minimal loan/transaction legacy metadata needed for durable
  reconciliation and downstream links.
- Define product terms, transaction-processing strategy, charges, payment
  types, and GL mappings.
- Assign one native portfolio account per product. Preserve source product type
  in `id_tipo_linea`, merge reviewed product/loan dimensions, and verify that
  every generated journal entry carries those dimensions for reporting.
- Validate the schema on both supported target database engines.

Deliverable: Liquibase support and a reviewed product/accounting contract.

## Gate 3: native lifecycle spikes

Gate 3 is complete for every lifecycle applicable to the current linked
portfolio. The entries below are chronological evidence. Statements that an
item was open or blocked describe the result at that point in the investigation
and are explicitly superseded by the later posted-lifecycle, Cobro Movil,
periodic-accrual, and reversal proofs.

Run independent local API proofs for:

1. source-exact schedule generation for every installment date, principal, and interest;
2. approval and effective disbursement;
3. repayment component allocation;
4. debt-insurance calculation, installment assessment, payment allocation, and
   accounting;
5. repayment and disbursement reversal;
6. Cobro Movil clearing-account posting and reversal;
7. refinance payoff; and
8. same-loan restructuring.

First schedule canary result (2026-08-26): source loan `1082`, line `00010`,
weekly, four installments, $100 principal, and 60% nominal annual rate was sent
to local product `3` through the non-posting native calculator. All installment
dates and interest amounts matched; aggregate principal matched at $100.00 and
aggregate interest matched at $2.89. Fineract redistributed principal rounding,
leaving the final principal installment $0.03 above the stored source
installment. Each source installment also contained an `MONTO_OTROS` component
that is reserved for the charge/insurance proof. This is evidence that the
native path preserves totals while applying its own consistent residual-rounding
policy. That earlier totals-only acceptance was superseded by the strict
source-exact contract: installment redistribution is now blocking. The later
pending-variation proof for `1082` reduced those four installment differences
to zero. This historical calculator result does not clear the remaining
lifecycle and accounting proofs.

Debt-insurance calculation update (2026-08-27): Fineract now exposes the
loan-only installment calculation `PERCENT_OF_OUTSTANDING_PRINCIPAL` (enum
`8`). It calculates each future insurance installment from opening principal
outstanding, applies normal currency rounding, excludes non-repayment schedule
rows, and observes the loan charge submitted date as the historical/future
cutover. Unit coverage reproduces the declining `$350.00`, `$323.10`,
`$294.44`, and `$264.11` bases at `0.06%`, verifies the resulting `$0.74` total,
and proves that `$900.00` produces exactly `$0.54` rather than an upward-biased
`$0.55`.

Native calculator proof (2026-08-27): source loan `2068`, quincenal, 12
installments, and `$350.00` principal was sent to local product `4` through the
non-posting native calculator with charge `8` at `0.06%`. The API accepted the
new calculation type and assessed declining installment fees
of `$0.21`, `$0.20`, `$0.18`, `$0.17`, `$0.15`, `$0.13`, `$0.12`, `$0.10`,
`$0.08`, `$0.06`, `$0.04`, and `$0.02`, totaling `$1.46`. Every amount equals
the corresponding Fineract opening principal multiplied by `0.06%` and rounded
normally to USD cents. This clears the charge-definition, calculation, and
schedule-assessment blocker in item 4. It does not treat the source plan's
fixed `MONTO_OTROS=$0.22` projection as authoritative insurance history.

Interim status at this point: Gate 3 item 4 remained partially open only for a
posting lifecycle proof: create
and disburse a loan with the charge, post a repayment, verify native allocation
to the installment charge, and reconcile the resulting accrual/cash journal
entries and reversal. Historical assessed insurance must still use the exact
source charge and paid-by facts described in the loan contract rather than be
recalculated.

Historical compatibility finding (2026-08-27, superseded by the dedicated
strategy proof below): a controlled local
canary combined cumulative declining-balance daily interest, daily interest
recalculation without compounding, past-due interest calculation, and the
dynamic `PERCENT_OF_OUTSTANDING_PRINCIPAL` installment insurance charge. Loan
creation was rejected with Fineract validation code
`installment.loancharge.with.calculation.type.principal.not.allowed`. The same
interest-recalculation product accepted a loan when the dynamic charge was
omitted, proving that the failure is the combined configuration rather than
product creation or interest recalculation alone. Gate 3 item 4 was therefore
blocked for general interest-recalculation loans until Fineract supported this
combination or an explicitly reviewed insurance representation replaces it.
The reviewed resolution is the dedicated transaction strategy
`credesal-accrued-interest-first-strategy`, rather than enabling the
incompatible general interest-recalculation mode. It calculates daily post-due
interest on declining outstanding principal before applying the normal
due-first repayment order.

Posted lifecycle proof (2026-08-27): source loan `2068` was reproduced locally
with the dynamic `0.06%` debt-insurance charge and the dedicated strategy. Its
first `$40.00` repayment, posted one day after the 2026-06-28 due date, matched
the source allocation exactly: `$0.21` insurance, `$12.89` interest—including
`$0.81` for the additional day—and `$26.90` principal. Submit, approval,
disbursement, repayment, repayment reversal, and undo-disbursement succeeded.
All journals balanced after posting and every GL account netted to zero after
the reversals. Unit coverage also proves no additional interest on an exact due
date, no duplication on later installment due dates, replay reset, sequential
late repayments, and exclusion of flat-interest loans. This clears Gate 3
items 2 through 5 for the reviewed normal-payment canary; Cobro Movil,
refinance, and restructuring proofs remained open at that stage.

Product-crosswalk and Cobro Movil proof (2026-08-27): the controlled local
target now binds source line `00010` to native loan product `4` with review
status `reviewed-local`. A non-leap-year canary selected that product through
the crosswalk, posted its first `$40.00` repayment with the `Cobro Móvil`
payment type, and reproduced the source allocation exactly: `$0.21` insurance,
`$12.89` interest, and `$26.90` principal. The repayment debited
`222099940104 CUOTAS PENDIENTES DE APLICAR` for `$40.00`; its journal balanced,
repayment reversal and undo-disbursement succeeded, and every affected GL
account returned to zero. This accepts Gate 3 item 6 for the reviewed canary:
Cobro Movil changes the repayment fund-source account, not the allocation or
the ownership of the native repayment.

Periodic-accrual completion proof (2026-08-28): the V17 controlled local run
used actual outstanding principal for post-due accrual and recognized the same
`$12.89` interest later cleared by repayment. Loan submission persisted all 12
dynamic installment-insurance rows without accrual creating a duplicate. The
first `$0.21` assessment posted debit `1530` insurance/fee receivable and credit
`222007020102 SEGURO DE DEUDA` through the product's charge-specific native GL
mapping. The `$40.00` Cobro Movil repayment then allocated exactly `$26.90`
principal, `$12.89` interest, and `$0.21` insurance, debiting
`222099940104 CUOTAS PENDIENTES DE APLICAR`. Repayment reversal and
undo-disbursement returned every affected GL account to zero. This accepts the
periodic-recognition portion of Gate 3 item 4 and reconfirms item 6 for the
reviewed canary.

Source reversal-pairing proof (refreshed 2026-08-29): movements are frozen in
`FECHA_OPERACION`, then zero-padded `ID_MOVIMIENTO_CARTERA` order. A reversal
consumes the most recent earlier, unpaired movement on the same loan with the
eligible transaction family and exact full component signature. The live audit
paired all 148 valid repayment reversals and all 57 disbursement reversals,
including one LIFO-disambiguated repayment, with no reused original. It found
two orphan duplicate repayment-reversal notes on loan `83`; that whole loan is
quarantined. Active `4/00013 PAGO CREDITO (AJUSTADO)` rows remain repayment
facts with their stored components, rather than inferred replacement pointers.

Line `00001` manual-adjustment decision (2026-08-28): loans `24`, `435`, and
`945` are an explicit non-blocking allowlist. Their historical schedule shape
is retained as evidence but is not a native-generation requirement. Planning
accepts Fineract's native schedule without synthesizing missing installments or
adjustment transactions, provided source movement identities and component
totals, cutover balances, and terminal status reconcile exactly. This policy
does not apply automatically to any other loan or product.

Deliverable: automated tests showing source input, API operations, resulting
loan state, and journal entries.

## Gate 4: planner and sequential writer — completed for supported lifecycles

- Planner completed: build immutable, target-specific plans with source and
  contract hashes. Each plan freezes the complete reviewed loan-product API
  payload after resolving target GL accounts, charges, payment types, strategy,
  and reporting dimensions.
- Planner completed: emit only products required by the selected loans as
  `create-product`, `unchanged-product`, or a blocking `conflict-product`.
  Product actions are ordered before loans; every `create-loan` declares its
  namespaced `product:{ID_LINEA_CREDITO}` dependency. Loan journal keys are
  independently namespaced as `loan:{ID_CREDITO}`.
- Product writer completed: create the frozen product through the API, write
  `credesal_loan_product_map` only after successful creation or exact-ID crash
  recovery, and leave every dependent loan unattempted when its product action
  fails. Hard-crash retry treats unjournaled plan items as unfinished.
- Loan writer completed for reviewed normal, adjusted, Cobro Movil, repayment
  reversal, and disbursement-reversal events. Plans freeze the application,
  approval, schedule evidence, ordered events, component evidence, reversal
  links, dependency IDs, expected state, and lifecycle hash.
- Sequential apply completed: a failed movement stops all later movements for
  that loan; product failure blocks every dependent loan. The reopened Gate 5
  contract adds a non-posting native schedule calculation before a new loan is
  submitted and an exact schedule guard before a recovered loan continues.
- Recovery completed: retries resolve the loan and transactions by external ID,
  inspect partial state, and use a per-run bounded idempotency suffix to escape
  cached failed API commands without duplicating successful operations.
- Reconciliation now blocks structural lifecycle drift, source event total or
  component-allocation drift, schedule count/date/principal/interest drift,
  reversal drift, terminal-state drift, and unbalanced journals. Only reviewed
  balance interpretations and the three line `00001` manual schedule anomalies
  remain variances.
- Single-predecessor refinance is implemented as a native Fineract top-up with
  chain expansion, deterministic cutover bridges, recovery, and reconciliation.
  Unsupported graph shapes remain whole-loan quarantines. Same-loan
  restructuring is not applicable to the current linked portfolio.

Controlled local evidence (2026-08-29): plan
`9dbddd1712b54ef4bfd131e56db9d925` replayed source loan `2068` into native loan
`31` with one disbursement and four Cobro Movil repayments. Recovery run
`1836284067904252ac7be797213203a1` reconciled with zero blocking mismatches;
idempotency run `bccea81db7f547c3b32c648297c179ce` recovered the same loan and
left exactly five source-identified transactions.

Deliverable: locally applicable canary plans with no delete path.

## Gate 5: exact reconciliation and promotion — reopened

- Reconcile schedules, movements, allocations, balances, status, charges, and
  accounting.
- Prove zero duplicates and zero new financial entries on a second run.
- Run the acceptance matrix in the contract against controlled local data.
- Only then register the CLI block and consider `export-ready`, followed by
  `available` after a controlled local apply/reconcile.

### Gate 5 issue register

This table is the authoritative checklist for the reopened Gate 5. Keep one
row per independently diagnosable discrepancy or promotion proof. Do not mark a
row complete merely because one canary progressed past it: completion requires
the row-specific proof in the final column and an update to the supporting
[loan reconciliation evidence](loan-reconciliation.md).

Status meanings:

- `COMPLETE`: implemented, tested, canary-proved, reconciled, and replayed when
  the item can create financial state;
- `PENDING`: a supported-path defect or required proof remains open;
- `REVIEW`: source data or quarantine policy needs an explicit classification,
  even if no engine change is ultimately approved;
- `BOUNDARY`: deliberately unsupported behavior is fail-closed and is not part
  of the current supported population; and
- `BLOCKED`: work cannot start until another listed item is complete.

| ID | Status | Individual discrepancy or proof | Known affected scope | Current evidence and interpretation | Required evidence to mark complete |
|---|---|---|---|---|---|
| `G5-SCH-001` | `COMPLETE` | Exact-half-cent periodic-interest rounding | Bounded cohort of 18 cent-residual loans, including `2182`, `2243`, `2249`, `2288`, and `2346`; decisive refinance chain `2096 -> 2243` | Arissto selects the lower cent when raw actual/365 interest ends exactly in `.005`. Fineract now applies `HALF_DOWN` only to the dedicated Credesal migration strategy. Plan `2b986e0021a142969eac817b9cdf15ec`, run `75c5795f91854e51adb5a682c61eeeca`, stored source-exact principal `786.00` and interest `369.19` for `2243`; replay `6d72bc623ad34c229e5494be39384347` remained mismatch-free. | Already satisfied: targeted tests, full three-loan lifecycle, zero reconciliation mismatches, and unchanged replay. Retain as a regression case. |
| `G5-SCH-002` | `COMPLETE` | Operator-adjusted historical schedule | `1484` | Arissto records two explicit `CRD_REESTRUCTURACION` edits by the same user and daily close, 153 seconds apart: archived 36-installment biweekly and intermediate 36-installment monthly plans precede the current 18-installment monthly plan. This is historical operator activity, not a source formula for Fineract to reproduce. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos-inconsistencia-base-360-365.md#1484-secuencia-de-ajustes-operativos-no-formula-general). | Satisfied by explicit reviewed-exception policy: the sync accepts only loan `1484` as a visible non-blocking native-schedule variance, never replays the two archived edits or synthesizes installments/transactions, and still requires exact source movement identities, component totals, cutover balances, and terminal status. Existing generalized reconciliation tests cover this policy; no dedicated financial canary is required because the change creates no new financial behavior. |
| `G5-SCH-003` | `COMPLETE` | Reviewed operator-adjusted non-monotonic schedules and one unclassified duplicate | Live audited population of 9 loans. Reviewed manual exceptions: `945`, `1117`, `1743`, `1748`, `2069`, `2241`, `2254`, and `2355`. Fail-closed source anomaly: `2374`. | All eight reviewed exceptions have operator-created `CRD_REESTRUCTURACION` rows and archived plans. Their final installment is pinned to the contractual maturity date even though lower-numbered installments occur later. Seven carry negative final interest, confirmed operationally as manual interest dispensation; `2241` has the same date behavior without negative interest. Arissto does not populate its standalone waiver flag, so the operator review establishes intent while the database establishes the adjustment structure. Loan `2374` has neither adjustment history nor an archived plan and remains outside the exception. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos-inconsistencia-base-360-365.md#planes-actuales-con-fechas-de-cuota-no-monotonicas). | Satisfied by the explicit entity allowlist and focused contract/planner tests. Fineract retains its native schedule and does not reproduce archived edits, non-monotonic dates, or negative interest; exact source movements, component totals, cutover balances, and terminal status remain blocking. Loan `2374` continues to emit `non_monotonic_source_schedule_dates`. No Fineract date override or dedicated financial canary is required because this classification adds no new target financial behavior. |
| `G5-SCH-004` | `COMPLETE` | All-zero contractual schedule | `2120` | Read-only history proves `2120` is an undisbursed source-error shell: its approved application retained `$527.00`, but the loan, all 100 schedule rows, 69 daily snapshots, and 3 period snapshots stayed at zero; it has no movement, liquidation, payment, reversal, or paid charge. A same-user type-1 plan adjustment was recorded 11 minutes after creation, and valid replacement loan `2121` was created 13 minutes 56 seconds later for the same borrower with the same `$527.00`, 100 dates, real disbursement and movements. The refinance graph correctly links `2064 -> 2121`; `2120` is not part of it. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamo-2120-plan-cero.md). | Satisfied by an exact contract allowlist and planner quarantine: source loan `2120` always emits `quarantine-loan` with replacement `2121`, creates no target loan or financial state, remains visible in plan/apply/reconciliation reporting, and cannot be generalized to another zero schedule. Unit and scoped-plan tests retain this as a regression case. |
| `G5-SCH-005` | `COMPLETE` | Post-lifecycle interest presentation and penalty-only extension periods | Clean namespaced replays of `1934` and `2262` | The old identities used native repayment allocation, so post-due interest was calculated from already-divergent principal balances. Clean source-exact replays preserve every payment component and balance. Fineract adds materialized post-due interest to current interest while preserving contractual interest in the original-due field. A specified-due-date penalty after maturity can also create a zero-principal/zero-interest charge-only period; it is not a source repayment-plan installment. | Reconciliation compares only periods carrying original contractual principal or interest and continues to reconcile penalty identity, amount, paid-by allocation, balances, and journals independently. Both clean runs and their unchanged replays are mismatch-free and variance-free. Retain both loans as regression cases. |
| `G5-SCH-006` | `COMPLETE` | Full-leap-year Actual/Actual interest denominator | `1864`; source audit found 5,289 discriminating rows across 897 current loans | Arissto consistently uses 365 or 366 from the period-start year; this is a generalized rule, not a manual exception. Fineract cumulative daily-interest schedules now resolve `ACTUAL` from each period start while fixed-365 and fixed-360 remain unchanged. Unit coverage proves a normal 2027 period, a 2027-to-2028 period (365), a 2028-start period (366), and both fixed-basis controls. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos-inconsistencia-base-360-365.md#1864-regla-general-de-ano-bisiesto). | Satisfied by scoped plan `098dfdc61d5f4e47a8613a3ec6a12634`: loan `1864` preview reproduced aggregate interest `2071.05`; run `cefea617cc97417e892e160a873921df` recovered the full lifecycle and reconciled the exact schedule, source movements, terminal state, and balanced journals with no blocking mismatch. Same-plan replay `e1712be224184eb196c2d89b36d5f416` produced the same zero-mismatch result. |
| `G5-SCH-007` | `COMPLETE` | Legacy inclusive first-accrual-day schedule | Formula-derived cohort of 44 early monthly line `00010` loans, IDs `1-48` except `3`, `9`, `23`, and `24`; clean preview canaries `5` and `40`; posted lifecycle canary `5` | A read-only source audit found that the first installment interest for all 44 loans equals `principal * annual rate * (DATEDIFF(day, origination, first due) + 1) / 365`, rounded to currency: Arissto counted both the origination date and first due date. Later periods use ordinary exclusive day counting. Loan `5` therefore stores first principal/interest `30.11/26.30` where an unadjusted native preview produces `30.93/25.48`; loan `40` stores `60.23/52.60` where an unadjusted preview produces `61.87/50.96`. The signature is bounded to originations from `2023-03-23` through `2023-05-19`; comparable line `00010` originations from `2023-05-25` use the normal exclusive rule. None of the 44 current schedules carries an `ID_REESTRUCTURACION`; only four loans have any separate adjustment-history row, and neither `5` nor `40` does. Loan `5` also has the same complete schedule as neighboring loan `6`. This is a coherent early schedule-generation behavior, not an approval-date rule, two isolated discrepancies, or evidence of manual adjustment. | Satisfied by a source-derived classifier with explicit near-match quarantine, the native loan-level combination `interestChargedFromDate = origin - 1 day` and `daysInYearType = 365`, exact full previews for loans `5` and `40`, and normal exclusive loan `51` as regression control. Fresh namespaced plan `871e3b5aa06749caba5e157fa83491cb` created and completed loan `5` as run `cd4ab91fb4814e7fb4b63027dd0a1536`; reconciliation returned zero mismatches, variances, adjustments, failures, or quarantines. Same-plan replay `831e1c25556541ccb17a403d196ea758` recovered the existing loan and independently reconciled with the same all-zero result, proving no duplicate financial state. |
| `G5-SCH-008` | `PENDING` | Contractual first-period accrual anchor differs from the financial disbursement event or nominal repayment interval | 48 supported-path loans within the residual 62-preview cohort after separating nine archived-plan adjustments, loan `26`, and four terminal charge-only rows; includes 32 loans whose first disbursement precedes origination and 16 date-aligned long/short or month-end first periods | Source interest is anchored to `CRD_CARTERA.FECHA_OTORGAMIENTO`, while the target application correctly preserves the earlier real disbursement movement and `repaymentsStartingFromDate` can still infer one nominal interval backward from the first due date. Across all 62 residual failures, 59 source first-interest values reproduce exactly from origination; the three exceptions are already explained by the inclusive rule (`3`), archived manual edits (`23`), or the anomalous zero-principal plan (`26`). Month-end cohorts `280-286`, `646-649`, and `1001-1002`, long monthly first periods `331`/`341`, and long biweekly first period `1046` prove this is not manual adjustment. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos-inconsistencia-base-360-365.md#cohorte-residual-de-62-previsualizaciones-no-exactas). | Prove the smallest native representation that keeps the actual disbursement transaction date but anchors exclusive contractual interest at `FECHA_OTORGAMIENTO` (and composes correctly with `G5-SCH-007`'s `origin - 1 day`). Add normal/inclusive, monthly/biweekly, month-end, short-first-period, and long-first-period regression tests; require exact full previews for all 48 loans, followed by lifecycle/reconciliation/replay canaries for both a date-gap and a date-aligned case. Do not add an entity allowlist or tolerance. |
| `G5-SCH-009` | `REVIEW` | Residual operator-adjusted schedules with archived versions | Nine loans: closed/state-`3` `23`, `90`, `317`, `340`, `359`; active/state-`1` `479`, `1738`, `1841`, `1869` | Every loan has `CRD_REESTRUCTURACION` history and one or more archived plans. The five closed loans now use the historical-reference policy established for `1484`: source schedules remain frozen and visible, archived edits are not replayed, no installments or adjustment transactions are synthesized, and Fineract retains its native schedule. The four active loans remain fail-closed because their adjusted schedules still define future obligations; `1738`, `1841`, and `1869` also differ between initial and current terms. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos-inconsistencia-base-360-365.md#limite-para-descartar-ajustes-manuales). | Complete the closed subgroup with a scoped plan and at least one apply/reconcile/replay canary proving visible reviewed schedule variances plus zero blocking movement, allocation, charge, cutover-balance, status, accounting, or idempotency findings. For each active loan, either prove a native representation of remaining obligations or obtain explicit approval to use Fineract's native future schedule and canary it. Archived edits must never be replayed or generalized into calculator rules. |
| `G5-SCH-010` | `COMPLETE` | Terminal source row contains only `MONTO_OTROS` after principal is fully settled | `381`, `1775`, `1871`, `2006` | The source has respectively 7, 48, 48, and 48 rows, but each final row carries zero principal and zero interest while retaining only `MONTO_OTROS`. Variable-schedule preview correctly omits that charge-provenance row from the repayment schedule. The engine classifies it as `historical-reference-only` only when there is exactly one terminal zero-core row, its `MONTO_OTROS` is positive, contribution/restructuring/deferred markers are absent, preceding rows allocate the full principal, installment numbers are sequential, and dates are strictly increasing. No installment, payment, adjustment, or charge is synthesized from the row. Near-matches return to the blocking exact-source-schedule path. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos-inconsistencia-base-360-365.md#cohorte-residual-de-62-previsualizaciones-no-exactas). | Satisfied by four-entity regression coverage, nine fail-closed near-match mutations, and all 299 sync-engine tests. Sandbox plan `578ee952e59b4515897b585a1c4be190` expanded the four requested loans to eight dependency-complete loans; run `e74a6f9629644ec0aad3e908f0dde9e3` completed all eight, and strict reconciliation returned `ok=true` with zero failures, quarantines, or blocking mismatches. The terminal rows remain visible as reviewed schedule variances while historical charge/paid-by facts, cutover insurance, active future recurrence, movements, status, balances, and accounting remain independent checks. Same-plan replay `39a2022411cb42ae82e0fad855a79fd0` recovered all eight and reconciled identically. The canary used tenant `sandbox` backed by `fineract_sandbox`; the local default database was not targeted. |
| `G5-SCH-011` | `COMPLETE` | Closed loan with zero contractual principal but nonzero interest and no archived plan | `26` | The approved and disbursed principal is nonzero, but all six current schedule rows carry zero principal. This is not a no-write shell: ordinary repayments plus the refinance payoff into successor `108` allocate the complete principal and leave zero source cutover balances. The single restructuring row was created with the disbursement but retains no dates, amount, or archived plan. The sync classifies only the complete closed-lifecycle signature as `historical-reference-only`: closed state, nonzero principal, zero schedule principal with positive interest, one disbursement, one refinance payoff, and exact full-principal allocation outside disbursement. A near-match emits `historical_reference_schedule_signature_mismatch` and returns to the blocking exact-schedule path. All 297 sync-engine tests pass. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos-inconsistencia-base-360-365.md#26-calendario-malformado-dentro-de-un-ciclo-financiero-real). | Satisfied by fresh namespaced plan `7a17f6aa3dd240f0943aade2d92eadfe`, which expanded requested loan `26` to the complete `26 -> 108` refinance chain. Loan `26` planned with `historical-reference-only`, no schedule writer, and no quarantine while successor `108` retained exact schedule reconstruction. Run `c4178dc31c4c4990922003ab2652277a` created both loans and reconciled with `ok=true`, zero failures/quarantines, and zero blocking mismatches; the malformed schedule remained visible only as reviewed `historical_reference_only_schedule_variance` entries. Same-plan replay `0af70695cce942909fe943b3f26ffbbd` recovered both loan identities without duplicate state and independently produced the same clean reconciliation. The canary used tenant `sandbox` backed by `fineract_sandbox`; the local default database was not targeted. |
| `G5-SCH-012` | `COMPLETE` | Multiple trailing source installments have zero principal and zero interest | `8`, `1739`, `1795`, `1893`, `2063`, `2111`, `2482` | Each current source plan is monotonic, allocates the full approved principal before its tail, and then retains two to ten zero-core rows. None has `ID_REESTRUCTURACION`, a deferred-installment flag, duplicate installment number, or other manual-adjustment signature. Six tails retain only `MONTO_OTROS`; `2482` has two completely empty rows. Fineract correctly rejects zero-valued variable-installment modifications. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos-inconsistencia-base-360-365.md#cohorte-de-siete-colas-contractuales-sin-capital-ni-interes). | Satisfied by a seven-entity `historical-reference-only` allowlist. The engine freezes the complete source schedule but emits no schedule writer, synthetic installment, zero payment, or adjustment transaction. All 296 sync-engine tests pass. Namespaced plan `02e9795bb96447bb909e29014ec23672` expanded the seven requested loans to their 19-loan dependency graph; run `d9353281d02f40d6a3e31eaacc8abdac` succeeded for all 19 and reconciled with `ok=true`, zero blocking mismatches, and visible native-schedule variances. Same-plan replay `a72186d261f3410fa21fcb8ca5700f08` recovered all 19 without duplicate state and reconciled identically. |
| `G5-LCY-001` | `PENDING` | Refinance predecessors left open when their successor did not complete | Historical population of 29 loans: `1379`, `1920`, `1928`, `1931`, `1948`, `1952`, `1958`, `1961`, `1965`, `1972`, `1991`, `2011`, `2022`, `2025`, `2026`, `2046`, `2055`, `2059`, `2064`, `2075`, `2088`, `2093`, `2094`, `2096`, `2119`, `2123`, `2130`, `2226`, `2279` | The missing movement in all 29 historical cases is the final `4/00019 PAGO CREDITO-REFINANCIAMIENTO`. The predecessor action freezes but deliberately does not post that event; the successor top-up disbursement creates it atomically. When the successor failed or was quarantined, the predecessor correctly remained active and reconciliation emitted four correlated symptoms: missing movement, terminal status, principal balance, and cutover total. This is a regression cohort owned by the successor's root issue, not an independent Fineract lifecycle defect. [Source interpretation](../../../../../../credesal-db-space/docs/learnings/refinanciamientos.md#10-interpretacion-de-la-cohorte-historica-g5-lcy-001). | Re-plan the complete chains on fresh identities after the owning schedule, prerequisite, and graph classifications are settled. Publish only the residual supported population; require every completed successor to create the exact payoff and close its predecessor with balanced journals. Do not add a standalone payoff or terminal-state repair to the predecessor. |
| `G5-CHG-001` | `COMPLETE` | Historical debt-insurance assessment creates terminal cutover adjustment | Primary canaries `1934`, `2262`, and `945`; source-wide audit found 12,345 paid debt-insurance details across 1,960 loans, including a bounded 55-row legacy representation across 48 loans | Two related symptoms expose the same historical-versus-future insurance boundary. `945` has seven operator-created plan revisions, but its eleven `$0.66` insurance applications are ordinary `4/00001` payments independently linked by `CRD_DETALLE_CARGOS`; the manual schedule history does not invalidate those financial facts. In contrast, `1934` and `2262` have no source charge instance, detail, movement allocation, scheduled `MONTO_OTROS`, or insurance balance, so their target fee is entirely migration-created. The population audit found no paid insurance detail linked to an adjusted-payment transaction. It also found 55 normal-payment details from 2023-05-23 through 2023-06-26 where the typed detail equals `MONTO_OTROS` and `MONTO_SEGURO` is empty; this is a legacy storage transition, not a manual adjustment. [Source evidence](../../../../../../credesal-db-space/docs/learnings/g5-chg-001-seguro-historico.md). | Satisfied by exact native historical charges and paid-by allocations, a flat cutover balance, and an opt-in recurring `PERCENT_OF_OUTSTANDING_PRINCIPAL` charge whose optional `submittedOnDate` excludes every pre-cutover installment. Null preserves normal Fineract behavior and loans outside the insurance predicate do not receive the field or charge. Fresh namespaced plan `61e5ed103f5645b4bede79218923a060`, run `0491040cc4f24ebdaa86dc7424e52b4f`, and unchanged replay `e6befe1bd8e543cba18cd8968cc2524f` all reconciled with `ok=true` and zero mismatches. The final audit found eleven historical charges and paid-by rows totaling `$7.26`, a `$1.32` cutover balance, `$0.54` of recurring insurance only on installments due after `2026-08-31`, no duplicate identities, and zero unbalanced journal transactions. Automated coverage retains the bounded 55-row legacy fallback, fail-closed near-matches, cutoff behavior, and the unchanged default path. |
| `G5-PRE-001` | `COMPLETE` | Missing target prerequisites | Dismissed as an independent Gate 5 loan issue after removal of the retired native-loan-officer projection | Arissto has no generic loan-officer relationship. The loan contract now preserves promoter, account executive, and collections manager independently in `credesal_loan_staff_assignment`, does not populate native `loanOfficerId`, and accepts inactive staff or `is_loan_officer = false`. Genuinely missing client or staff identities remain explicit, fail-closed upstream synchronization gaps rather than a loan-engine defect. | Closed by the lossless three-role assignment contract and planner tests covering non-loan-officer, inactive, and independently resolved staff relationships. Future plans must continue to quarantine genuinely missing client/staff references without reopening this item. |
| `G5-DAT-001` | `COMPLETE` | Source movement component residuals | Historical diagnostic: 107 movements before typed insurance classification. Current reviewed cohort: 55 movements across 40 loans; zero unclassified residuals. | The current cohort has three proven classes: 41 rows are gross receipts where components equal `MONTO_PAGADO` and `MONTO - MONTO_PAGADO = REINTEGRO_MONTO`; 12 rows are pre-detail debt insurance where `MONTO_OTROS` is confirmed independently by exact PRE/POS other-balance movement and one matching insurance-account credit; and two rows on loan `9` are one exact net-zero adjusted-payment/reversal pair and are discarded as manual-adjustment history. Generic `MONTO_IVA` is zero throughout. `MONTO_OTROS` is never summed blindly because it can duplicate separately itemized insurance. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos.md#g5-dat-001-residuos-de-componentes). | Satisfied by fail-closed classifiers, five focused regression tests, and full 40-loan plan `33ba1eacf71042f1b15a90701856d945`: 39 applied-after-refund events, two fully refunded rows omitted, 12 legacy insurance charges, one discarded manual pair, and zero component residuals. Local proof run `a1a06df48b6c4cffafdf2c9969845f4c` synced and reconciled refund loan `241`, manual-adjustment loan `9`, and refinance successor `577` with zero mismatches; loan `3` stopped only on the separate exact-schedule preview guard. Replay `841e0dc93d234cf6b010dd52d777c7f7` recovered all three successful identities and reproduced only loan `3`'s independent guard. Replacement legacy-insurance run `c13ee2b678f3433286b764ab4884c7ef` synced loans `6` and `217` and reconciled with `ok=true`, zero mismatches, failures, or quarantines; replay `75dada70399b4a9c8d468764fc3c73bb` recovered both and reconciled identically. |
| `G5-DAT-002` | `COMPLETE` | Legacy approval stamp after effective disbursement | Current regression cohort: loans `1-48` except `21`, plus `55` (48 total); classification is rule-based for future cases | All 48 violate only `approval > disbursement`; submission, the first/effective `4/00002` movement, first due date, and movement order are coherent. The first 47 share approval/resolution `2023-05-25` and same-technical-user `DT_CREO`/`DT_MOD` stamps on `2023-05-29`; loan `55` was modified on `2023-08-18`, matching its changed approval/resolution date. This is a later conversion/edit stamp, not a manual schedule adjustment or true post-disbursement approval. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos.md#fechas-de-aprobacion-tardias-en-la-cohorte-inicial). | Satisfied by migrations `0312`-`0313`, rule-based classification, raw-date persistence in `credesal_loan_legacy_timeline`, strict date-array reconciliation, and fail-closed near-match tests. Plan `3cf9aca18a9f4558a7dfc07c4129fd0a` classified all 48 with zero date-order quarantines. After `G5-SCH-007` was fixed, fresh loan-`5` run `cd4ab91fb4814e7fb4b63027dd0a1536` persisted the provenance and completed the lifecycle with `legacy_timelines: 1` and zero reconciliation findings; replay `831e1c25556541ccb17a403d196ea758` recovered and reconciled identically. General operator backdating remains separate in [`HISTORICAL_EFFECTIVE_DATE_REQUIREMENTS.md`](../../../../../docs/HISTORICAL_EFFECTIVE_DATE_REQUIREMENTS.md). |
| `G5-DAT-003` | `COMPLETE` | Source component reallocation represented by two otherwise-orphan reversal notes | Exactly loan `83`: reversals `0000005037` and `0000005038`, followed by repayment `0000005039` | The atomic classifier requires one loan, operation date, daily close, actor, and payment type; every orphan signature must duplicate a previously proved reversal pair; exactly one later active repayment must consume the same cash total; all unsupported components must be zero; and the batch must move an equal positive amount from interest to principal. The proved batch nets cash to zero and reallocates `$2.15`; near-matches remain quarantined. Fineract exposes only permission `SOURCEEXACTCOMPONENTREALLOCATION_LOAN`, requires `ARISSTO` identities, persists all three movement references, changes schedule components atomically, and posts debit interest receivable / credit loan portfolio. No Mifos operational path is exposed. Loan `83`'s separate incomplete six-row schedule is retained as historical reference only, not classified as a manual adjustment or reproduced as a Fineract schedule rule. Its refinance payoff insurance detail is assessed under its original Arissto identity before the native top-up quote. | Satisfied by the source classifier and near-match test, deterministic external identity/idempotent writer recovery, focused domain replay test, balanced-journal test, successful loan/provider compilation, 13 loan-domain tests, 4 accounting tests, and all 289 sync-engine tests. Scoped plan `3fbb059359dd431bb20e6227e1b6520e` completed the `83 -> 934` chain in run `e37ee645d1404d1e9db761e94eceacfd`; reconciliation returned `ok=true`, zero mismatches, and no failed or quarantined items. Same-plan replay `8bf19a85838640ffa1eaaf35d3537911` recovered both loans without duplicate financial state and reconciled identically. Direct PostgreSQL verification found one reallocation transaction with all three provenance IDs and two balanced `$2.15` journal rows. |
| `G5-DAT-004` | `COMPLETE` | Loan application dates precede migrated client activation | 17 direct failures: loan `625`, plus branch-002 loans `868`, `870`, `871`, `872`, `873`, `874`, `882`, `884`, `887`, `889`, `890`, `891`, `892`, `893`, `894`, and `902`; 30 downstream refinance loans were dependency-blocked | Loan `625` has submission/approval `2024-05-23`, client activation and real first `4/00002` disbursement `2024-05-24`, and no earlier financial movement. It is a bounded legacy application-stamp compatibility case. The 16 branch-002 loans differ materially: their migrated client activation was `2024-12-11`, after source disbursement, because the client service floored activation at the target office opening date. A 2026-09-01 source audit disproved the transfer hypothesis for all 16: loan branch, party branch at origination, active loan branch, and current/active party branch are all `002`. Office-002 client/application activity begins `2024-11-27`, accounting begins `2024-11-28`, and disbursement begins `2024-11-30`. Loan `869` is the distinct office-1-party/office-2-loan transfer control. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos.md#cronologia-apertura-sucursal-002). Moving the 16 loans' financial dates would falsify source history; the target office date was corrected instead. | Satisfied by guarded Liquibase migration `0318_correct_arissto_office_2_opening_date.xml`, the reviewed client activation floor `2024-11-27`, and the fail-closed planner compatibility/provenance rule. Client plan `fe1720e9f3494552b555f3bd42c5cb08` updated all 17 affected clients; run `90bb7b7825624b928281a1d770d77de1` and replay `4a31553ca76c422e8eb865fb50e9d0fd` each reconciled `matched: 17`. Dedicated loan-`625` plan `f8e527161e5c470995280b1fee72ad7a` completed run `97ed00465f2f453c87144145562a5d1e` and recovered unchanged replay `9fb2d64e70ea4a62be1f7404ea7fe559`; both reconciled with `ok=true`, zero mismatches, and one persisted `legacy-pre-client-activation-application-stamp` timeline. Fresh affected-graph plan `4d5510f22adf435e9cdc1b08a4bf52f4` expanded the 17 roots to 47 loans with zero activation-date chronology quarantines; all 17 direct loans succeeded in run `9814055df80643b184d0419987396d5b`. Its one authorization quarantine and three failed/blocked descendants are independently classified cross-client refinance and schedule-preview issues, not `G5-DAT-004`. |
| `G5-GRF-001` | `COMPLETE` | Voided refinance attempts inflate the effective refinance graph | 18 reversed refinance links; 16 predecessors also have a later active successor; 2 have no later successor | All 18 are complete net-zero operational reversals: the predecessor payoff has an exact compensating `4/00004`, the abandoned successor has a `4/00002` disbursement plus `4/00030` reversal and no other transaction type, and the successor is canceled with zero disbursement and balance. Sixteen predecessors were subsequently refinanced through a different active successor, so the raw graph's apparent ambiguity is an annulled attempt followed by a valid refinance. This is not a schedule or payment-rule variation for Fineract to reproduce. [Source evidence](../../../../../../credesal-db-space/docs/learnings/refinanciamientos.md#11-clasificacion-de-g5-grf-001-reversos-anulados-versus-consolidaciones). | Satisfied by a source-derived, fail-closed classifier for the complete net-zero signature. It preserves all four movement IDs as provenance, omits both reversed financial pairs, marks only the abandoned successor as a reviewed no-write action, and removes only the reversed edge from the effective graph. Full plan `8567fd648ada4edc99cc6aa769ecf946` classified all 18 attempts with 18 omitted successors, zero reversed or ambiguous graph quarantines, and all 12 `G5-GRF-002` consolidations still quarantined. Scoped plan `3b2dff35aa2c4b39b236c3367520caf1` proved `186 -> [voided 346] -> active 347`; plan `3f68a7d075b94309b4f0bc82436464d8` proved no-replacement predecessors `278` and `1521` remain migratable while successors `549` and `1765` are omitted. All 285 sync-engine tests pass, including partial-signature and ordinary reversal regressions. No Fineract core rule or financial canary is required because the classification creates no target financial state. |
| `G5-GRF-002` | `PENDING` | Multi-predecessor loan consolidations | 12 successors, each with exactly 2 active predecessors (24 links) | These are genuine consolidations, not manual adjustments: each pair belongs to the same definitive liquidation, successor principal exceeds the combined source payoffs, and all 12 deliver positive net cash from `$0.34` to `$118.73`. Three successors (`2252`, `2402`, `2406`) consolidate two loans of the successor client; the other nine each include one predecessor owned by another client. Fineract now retains the compatibility refinancing header and persists one settlement per predecessor; the migration planner, writer, reconciliation, API, and Mifos flows support same-client refinancing and consolidation. The successor's ordinary loan terms independently control rate, payment schedule, and installment count. [Source evidence](../../../../../../credesal-db-space/docs/learnings/refinanciamientos.md#los-12-sucesores-con-dos-anteriores-no-son-ajustes-descartables). [Implementation contract](../../../../docs/LOAN_REFINANCING_AND_CONSOLIDATION.md). | Same-client consolidation is proved by namespaced plan `fe97d37686904e1bbc75e1904ca1e3fa` for `2042 + 2205 -> 2406`. Run `3b2e253daee3432dafd03e66a178957e` and unchanged replay `4f8cb9a347a645b98ebc0814d717f891` both returned `ok=true`, zero failed/quarantined items, and zero blocking mismatches; replay recovered all six chain loans without duplicate financial state. Audit plan `922175c4a44740b18cd9b75fb9bc564d` proves cross-client successor `2472` is quarantined before write. The full item remains pending because nine cases cross client ownership. Completion requires an approved participant/authorization model (or an explicit migration-only policy) plus a cross-client canary and replay; the same-client ownership validation must not be weakened silently. |
| `G5-OPS-001` | `PENDING` | Clean strict lifecycle acceptance matrix | All supported lifecycle classes on fresh or never-migrated identities | Older approved or active proof loans may contain pre-writer schedules and cannot be repaired in place. Individual canaries do not prove the complete matrix. | Run active, paid, approved-undisbursed, normal/Cobro Movil repayment, reversal, insurance, terminal closure, and supported refinance cases with exact schedule, allocation, balance, status, charge, transfer, accounting, and journal reconciliation. |
| `G5-OPS-002` | `BLOCKED` | Fresh full supported-population execution | Entire supported loan population after prerequisite and discrepancy work | Historical full-run counts mix since-fixed defects, stale target identities, prerequisites, reviewed quarantines, and still-open schedule classes. They are not a current acceptance baseline. | After all supported-path rows above are complete, run fresh `plan -> apply -> reconcile`; require zero failed or dependency-blocked supported loans, zero blocking mismatches, and an explicitly reviewed quarantine report. |
| `G5-OPS-003` | `BLOCKED` | Full unchanged replay and promotion review | Same plan and target population as `G5-OPS-002` | Idempotency is proved for individual canaries but not yet for the final supported population. | Build/review the second plan or replay the accepted plan as required by the contract; require zero new loans, transactions, charges, paid-by rows, transfers, or journal entries; then review registry promotion. |

### `G5-SCH-007` implementation progress

The source-derived classifier is implemented without loan IDs or a date cutoff.
It applies only to monthly line `00010` schedules whose first interest matches
the fixed-365 inclusive formula and differs from the exclusive result, whose
later installments match fixed-365 exclusive day counting, whose dates are
strictly increasing, and which carry no current restructuring or deferred-row
marker. A partial signature emits
`ambiguous_first_accrual_day_signature`. The source-wide read-only audit found
exactly the documented 44 inclusive loans, 1,309 normal exclusive loans, and
zero ambiguous near-matches. [Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos.md#interes-inicial-inclusivo-en-la-cohorte-legada).

The native representation requires two existing loan-level fields:

- `interestChargedFromDate = FECHA_OTORGAMIENTO - 1 day`, which includes the
  source start date only in the first accrual period; and
- `daysInYearType = 365`, which preserves this legacy cohort's fixed denominator
  instead of applying the later period-start Actual/Actual rule.

Calculator-only proofs showed that the first field changed loan `5` from
`25.48` to the exact source interest `26.30` and loan `40` from `50.96` to
`52.60`. Pending proof applications `475` and `476` then combined both fields
with the existing variable-installment writer; the complete previews for both
loans had zero date, principal, interest, or aggregate-total differences. No
variation was persisted and neither pending application has accounting effect.

The posted acceptance proof used fresh namespace `g5-sch007e-20260901`. Plan
`871e3b5aa06749caba5e157fa83491cb` applied loan `5` through its complete
disbursement/reversal lifecycle as run `cd4ab91fb4814e7fb4b63027dd0a1536`.
Reconciliation returned `ok: true`, one loan, one product, one legacy timeline,
one staff assignment, and no mismatches, variances, adjustments, failures, or
quarantines. Applying the same immutable plan again produced replay run
`831e1c25556541ccb17a403d196ea758` with `loans_recovered: 1`; its independent
reconciliation returned the same zero-finding result. The replay created no
duplicate loan or financial state. `G5-SCH-007` and its dependent
`G5-DAT-002` acceptance are therefore complete. Loan `51` remains the normal
exclusive regression control; its independent movement-component residual does
not change its schedule classification.

### `G5-DAT-001` implementation sequence

The implementation preserves the earlier `G5-CHG-001` boundary. Typed
`CRD_DETALLE_CARGOS` remains authoritative, and generic `MONTO_OTROS` and
`MONTO_IVA` are not added to the component formula. A residual is released
only through one of these evidence-complete paths:

1. A returned-cash movement requires non-null source `MONTO_PAGADO` and
   `REINTEGRO_MONTO`, exact equality between components and `MONTO_PAGADO`, and
   exact equality `MONTO - MONTO_PAGADO = REINTEGRO_MONTO`. The target event
   posts only the applied amount and retains gross/refund provenance. A zero
   applied amount is omitted as a fully refunded, unapplied collection.
2. A pre-detail legacy-insurance movement requires a repayment role, no typed
   charge detail, zero `MONTO_SEGURO`, an exact PRE-to-POS decrease in
   `SALDO_OTROS`, an equal increase in `SALDO_PAGADO_OTROS`, and exactly one
   matching credit to `SEGURO DE DEUDA` or the older combined
   `INTERESES Y OTROS POR COBRAR` account. It creates one deterministic flat
   historical insurance charge. A near-match remains a component-residual
   quarantine.
3. Manual adjustment is discarded only as an exact reversal pair: the source
   original is `4/00013`, is marked reversed, the compensating `4/00004` note
   matches its full component signature under the existing one-to-one LIFO
   reversal contract, and the pair is net zero. Both source identities remain
   in the plan's `discarded_manual_adjustments` audit collection.

The source-wide plan `33ba1eacf71042f1b15a90701856d945` covered all 40
affected loans and their required refinance chains. It produced zero
`component_residual` reasons. Its two quarantines, loans `1` and `2`, were only
`ambiguous_first_accrual_day_signature` and therefore belong to the independent
schedule classifier.

The controlled local proof used fresh identities. Run
`a1a06df48b6c4cffafdf2c9969845f4c` successfully created refund representative
`241`, manual-adjustment representative `9`, and required successor `577`; all
three reconciled with zero mismatches. Legacy representative `3` was rejected
before creation by an unrelated exact-schedule preview mismatch. A smaller
replacement proof then created legacy-insurance representative `6` and its
required successor `217` as run `c13ee2b678f3433286b764ab4884c7ef`;
reconciliation returned `ok=true` with zero mismatches, failures, or
quarantines. The accepted native allocation balance variances on successor
`217` remain part of the existing refinance contract and are not component
residuals. Same-plan replays `841e0dc93d234cf6b010dd52d777c7f7` and
`75dada70399b4a9c8d468764fc3c73bb` recovered, respectively, all three
successful refund/manual identities and both legacy-insurance-chain identities
without duplicate financial state. The first replay again stopped only loan
`3` on its independent schedule preview guard; the second reconciled with
`ok=true` and no failures, quarantines, or mismatches.

### `G5-CHG-001` implementation sequence

The required outcome is one clean cutover boundary: source history is represented
by exact flat native fee charges and their paid-by allocations, while the
declining outstanding-principal charge is responsible only for future periods.
Manual schedule provenance remains visible but cannot erase an independently
identified source charge or payment.

#### 1. Freeze the source fact model before changing target behavior

Extend the read-only loan extraction with:

- the matching `CRD_CARGOS_CARTERA` instance and its stable
  `ID_RECARGO_CARTERA`, copied charge identity, state, amount, issued, collected,
  pending, vencido, and date fields;
- every `CRD_DETALLE_CARGOS` row joined through its declared composite key to
  the exact `CRD_MOVIMIENTOS_CARTERA` event; and
- the existing movement identity, ordering, transaction label, reversal state,
  `MONTO_SEGURO`, and `MONTO_OTROS` fields.

Classify and freeze two different facts:

1. a **historical paid assessment** for every typed debt-insurance detail; and
2. a **cutover outstanding assessment** for a supported nonzero source
   insurance balance not already represented by a paid detail.

For paid history, `CRD_DETALLE_CARGOS.MONTO_COBRADO` is authoritative.
`MONTO_SEGURO` must equal it when populated. The only initially accepted legacy
fallback is a typed debt-insurance detail whose amount equals `MONTO_OTROS` while
`MONTO_SEGURO` is empty; the read-only audit bounded that representation to 55
rows across 48 loans from 2023-05-23 through 2023-06-26. Express the rule from
the row facts, not from a loan-ID allowlist, and fail closed on every near-match.

Do not infer paid insurance from `CRD_PLAN_PAGO.MONTO_OTROS`. Do not discard a
detail merely because its loan has `CRD_REESTRUCTURACION` rows or a reviewed
manual-schedule exception. Preserve the movement's reversal state and reject
duplicate detail-to-movement identities.

#### 2. Extend the target contract and deterministic identities

Add one reviewed flat, specified-due-date **fee** definition for Arissto
historical debt insurance. It is distinct from both the current dynamic
`PERCENT_OF_OUTSTANDING_PRINCIPAL` insurance definition and the existing
historical **penalty** definition, but it must use the reviewed insurance
income/liability GL mapping.

Freeze deterministic identities for:

- the historical charge application, using the source charge instance plus
  movement/detail identity;
- any cutover outstanding charge snapshot; and
- the future dynamic charge attachment.

Include exact amount, due/cutover date, source movement identity, reversal
state, and classification in the plan hash. A retry must recover an existing
charge only by its external ID and must reject changed amount, date, fee versus
penalty classification, or source ownership.

Remove the unconditional dynamic insurance entry from every historical loan's
application payload. Its later attachment is an explicit lifecycle decision,
not an origination default during migration.

#### 3. Prove the native Fineract path in isolation

Before changing the general writer, run a clean local spike that:

1. creates and disburses a loan without the dynamic insurance charge;
2. posts a flat specified-due-date fee through
   `POST /loans/{loanId}/charges` with exact amount, date, and external ID;
3. posts the corresponding `sourceExactRepayment` with the exact
   `feeChargesPortion`;
4. verifies the resulting loan charge, `LoanChargePaidBy`, transaction
   allocation, repayment-schedule fee state, and balanced fee journals;
5. reverses the repayment and verifies that the charge balance, paid-by state,
   and journals return correctly; and
6. replays the same commands and proves that no charge, paid-by row,
   transaction, schedule period, or journal is duplicated.

Run a second spike that attaches the reviewed dynamic insurance charge only
after historical replay. Prove that its effective cutover excludes every
pre-cutover installment and assesses the first eligible future period exactly
once. If the loan is already source-closed or has no supported future insurance
obligation, prove that no dynamic charge is attached.

Fineract Java changes are justified only if one of these native proofs fails for
the proved source contract. Record the exact missing invariant before changing
domain behavior.

#### 4. Apply history in financial order

For each supported loan, the writer must execute this order:

1. create the loan without the dynamic insurance charge;
2. approve and disburse through the existing native lifecycle;
3. before each repayment, ensure every historical insurance charge referenced
   by that source movement exists with its deterministic identity and exact
   amount;
4. post the existing source-exact repayment so its fee portion produces the
   native paid-by allocation;
5. process repayment reversals through the existing original/reversal pairing;
6. after all historical movements, create a deterministic flat cutover charge
   for any supported source insurance amount still outstanding and not already
   represented; and
7. only then attach the dynamic insurance charge for an eligible active loan,
   with a cutover that cannot assess historical periods.

The final repayment of a source-closed loan must close naturally. A terminal
`goodwillCredit` is forbidden when its only purpose is clearing insurance that
the migration itself created. `1934` and `2262` are the negative canaries: both
must finish closed with no historical or dynamic insurance charge and no
terminal adjustment. `945` is the positive/manual-schedule canary: its exact
historical charge facts remain required even though its archived plan edits are
not replayed.

#### 5. Reconcile charge ownership, not only transaction totals

Add blocking reconciliation for:

- one target charge per planned historical/cutover external identity;
- exact amount, due/cutover date, fee classification, active/paid state, and
  source ownership;
- exact `LoanChargePaidBy` ownership and amount for every source detail;
- equality between each repayment's target fee portion and the source detail
  total selected by the contract, including the legacy `MONTO_OTROS` fallback;
- source-versus-target outstanding insurance at cutover;
- reviewed insurance GL accounts, reporting dimensions, and balanced journals;
- absence of an insurance-only terminal goodwill adjustment; and
- unchanged replay counts for loans, transactions, charges, paid-by rows,
  schedule periods, transfers, and journals.

Do not accept aggregate fee equality when charge identity or paid-by ownership
differs. Do not hide a fee mismatch under the reviewed manual-schedule variance
policy.

#### 6. Close with progressively wider evidence

The smallest complete proof is:

1. unit coverage for exact `CRD_DETALLE_CARGOS` extraction, the 55-row legacy
   predicate, reversal propagation, duplicate rejection, and manual-schedule
   independence;
2. the two native charge spikes above;
3. fresh clean-identity runs for `1934`, `2262`, and `945`;
4. unchanged replay of all three canaries; and
5. a source-wide plan audit that reports every supported paid, reversed, and
   outstanding insurance fact plus every fail-closed near-match.

Only after those checks pass may the full supported-population Gate 5 run use
the new path. The completion evidence must be recorded in the existing
requirement row rather than weakening any charge mismatch into an accepted
schedule variance.

#### 2026-08-31 implementation and proof status

The historical and cutover-flat portions of this sequence are implemented in
the loan migration engine:

- extraction now freezes typed `CRD_DETALLE_CARGOS` debt-insurance rows and
  their `CRD_CARGOS_CARTERA.ID_RECARGO_CARTERA` identity;
- `MONTO_COBRADO` is authoritative, with exact `MONTO_SEGURO` agreement or the
  bounded typed-detail/`MONTO_OTROS` legacy fallback;
- missing and mismatched typed details quarantine the whole loan;
- historical applications explicitly contain no dynamic insurance charge;
- every historical detail creates a deterministic flat fee before its
  `sourceExactRepayment`; and
- an active source loan with `SALDO_SEGURO > 0` receives one deterministic
  flat cutover-outstanding charge after replay.

The focused Python suite passes `83` tests. The isolated native flat-fee spike
created one `$0.66` fee, one exact `$0.66` `m_loan_charge_paid_by` row, reversed
the repayment, reopened the same charge, retained the audit link, and recovered
unchanged on replay.

Fresh local canaries produced these results:

- loan `1934`, run `216f44be83ac48bbb9531c790df198cb`: reconciliation
  `ok=true`, no mismatches, no insurance charge;
- loan `2262`, run `2d6c8569bfb449278f9bcf9ae0fe7108`: reconciliation
  `ok=true`, no mismatches, no insurance charge; and
- loan `945`, run `1520f7d21064489897b68fd63e93bc7f`: eleven historical
  flat charges totaling `$7.26`, eleven exact paid-by rows totaling `$7.26`,
  one cutover charge with `$1.32` outstanding, zero dynamic charges, and no fee
  reconciliation variance. Reapplying the same immutable plan produced run
  `18a4b58793b9459e89265faf43640817` with `loans_recovered=1` and no duplicate
  charge or paid-by rows.

The focused Fineract change is implemented and `G5-CHG-001` is `COMPLETE`. The loan
charge API accepts an optional `submittedOnDate`; only an installment charge
whose calculation is `PERCENT_OF_OUTSTANDING_PRINCIPAL` uses it as the first
eligible installment due date. A null date preserves the previous behavior.
The boundary is enforced in cumulative schedule generation, progressive
schedule generation, single-charge reprocessing, and installment-charge
regeneration. Liquibase change `0314` seeds the reviewed flat historical
insurance definition against GL `222007020102`.

The migration plan freezes one `migration_cutover_date`. Only an active source
loan with `SALDO_SEGURO > 0` receives the deterministic recurring charge
`ARISSTO:CRD-INS-FUTURE:{ID_CREDITO}` with that `submittedOnDate`; loans without
the historical-insurance condition keep the normal path and never send the new
field. Replay validates the external identity, percentage, and cutoff before
continuing.

Automated evidence after this change:

- 12 focused loan-domain tests pass, including a schedule-reprocessing test
  that proves a pre-cutover installment receives zero and a post-cutover
  installment receives the charge;
- 2 assembler tests prove the API copies an explicitly supplied cutoff and
  leaves an ordinary charge unchanged when it is absent;
- all 273 sync-engine tests pass, including deterministic recurring-charge
  creation and cutoff persistence; and
- the changed XML parses, the changed-file whitespace check passes, and the
  loan/progressive Spotless checks pass.

After restart, fresh namespaced plan `61e5ed103f5645b4bede79218923a060`
created loan `945` in run `0491040cc4f24ebdaa86dc7424e52b4f`; reconciliation
reported `ok=true`, no mismatches, and no failed or quarantined entity. The
database/API audit proved eleven historical `$0.66` charges and eleven exact
paid-by rows (`$7.26` paid, zero outstanding), one `$1.32` flat cutover charge,
and one recurring `0.06%` charge with `submitted_on_date=2026-08-31`. The
recurring charge assessed only installments 15-18, due from `2026-09-30`
through `2026-12-30`, totaling `$0.54`; it created no pre-cutover assessment or
paid-by row. All 55 journal lines belonged to balanced transaction groups.

Reapplying the immutable plan produced run
`e6befe1bd8e543cba18cd8968cc2524f` with `loans_recovered=1`. Reconciliation
again returned `ok=true` with zero mismatches, and the repeated database audit
retained exactly 13 charge identities, 11 historical paid-by rows, the same
four post-cutover installment allocations, and no duplicates. The focused
four-test charge-schedule suite and two-test assembler suite both passed after
restart; the latter explicitly proves that omitting `submittedOnDate` leaves a
normal loan charge unchanged.

The affected-loan lists and counts above record the latest known evidence, not
eternal constants. Whenever a fresh plan changes a population, update the same
row with the new plan/run evidence and explain why the count changed. Do not
create a second competing checklist elsewhere.

Scoped local plan `b992ad92435242d49a97bd3fa7f52d4f` emitted exactly one
`quarantine-loan` action for source `2120` with reason
`reviewed_source_error:superseded-undisbursed-shell:replacement-loan-2121` and
no `create-loan` action. The current local tenant already contains target loan
`249` from the earlier failed pre-quarantine attempt; the new policy neither
created nor changed it. Clean-tenant acceptance must prove that no target
identity is created for `2120`.

The earlier 2026-08-29 run completed the lifecycle matrix under the former
aggregate-total/native-variance rule. Controlled local canaries covered the
full applicable
matrix: active, paid, approved-undisbursed, normal and Cobro Movil repayments,
repayment and disbursement reversals, insurance, terminal closure, and a
single-predecessor refinance chain. Exact source transaction totals, reversal
state, terminal state, refinance relationship, and balanced journals are
blocking. That evidence remains useful for lifecycle and idempotency, but no
longer completes Gate 5 because schedule and historical allocation differences
are now blocking.

Closed refinance plan `c1b0bd0b1fda40abbf8acf6338f82ebe` migrated `1245` to
`1375`. Run `a148848aaea34a47aa599de629b285cf` reconciled with no blocking
mismatch. Replaying the identical plan as run
`ed15965531e04f5aa9f0c1f3a3ddb149` remained clean and created no duplicate
financial entry.

The source-wide inspection covers 2,490 uniquely identified loans and reports
the refinance graph, reversal exceptions, and restructuring applicability.
All 6,603 restructure-tagged rows are unlinked archival snapshots, so the
acceptance-matrix restructure item is formally not applicable. Future linked
rows and unsupported refinance graph shapes are quarantined. The registry is
now `blocked` with `executable: true`: controlled proof runs remain possible,
but production promotion is disabled until the reopened Gate 5 passes.

Gate 5 is complete again only after a controlled local matrix proves, for every
regular selected loan:

- exact installment count, number, due date, principal, and interest;
- exact aggregate scheduled principal and interest;
- exact historical repayment total and principal/interest/penalty/fee
  allocation;
- the existing reversal, terminal-state, refinance, accounting, and journal
  requirements; and
- an unchanged second plan with no duplicate financial entry.

The mixed 360/365 schedule on loan `2068` is the first required proof case. Its
repayment allocation is already exact; its contractual schedule must now be
preserved source-exact or the loan remains blocking.

Fresh strict proof (2026-08-30): plan
`9da30c11808f4b6d8e32857e66ee1b78` expanded `2068` to predecessor `1779`.
Run `82864df368814b459605ff06b3073bff` demonstrated that exact validation is
necessary: `1779` retained matching due dates but had multiple installment
principal/interest differences, aggregate source/target interest of
`$49.75/$51.81`, and several historical allocation differences. The run is
rejected. Because it occurred before the source-exact writer was added, it left
a partial local proof loan. New plans may now create a non-posting pending
application to preview and persist exact term variations; recovered approved or
active loans still stop before continuing if their schedule differs.

Retry `6bf94a43880d4033a02c99bac44e3170` verified the recovery guard: it rejected
existing loan `1779` with `existing_loan_schedule_mismatch_before_continue`,
blocked dependent `2068`, and made no further financial lifecycle write.

Source-exact writer implementation proof (2026-08-30): migration products now
enable native variable installments (`minimumGap=1`, `maximumGap=366`). The
writer creates at most a non-posting pending application, previews source-derived
installment-total variations, persists them only after an exact comparison, and
checks the stored schedule again before approval. Pending proof application
`44` reduced source loan `1082` from four base differences to zero; pending
proof application `45` reduced the decisive mixed 360/365 source loan `2068`
from 22 base differences to zero. Both had zero transactions. Replaying both
proofs recovered the same exact schedules without duplicate variation writes.

The schedule-writing mechanism is therefore implemented and locally proved.
Gate 5 remains open until a fresh target can run the complete strict matrix:
posted normal and Cobro Movil repayments with exact source allocations,
reversals, the complete `1779 -> 2068` refinance chain, accounting/journal
checks, reconciliation, and an unchanged second run. The current local target's
older active loans `1779` and `2068` predate this writer and are intentionally
not rewritten in place; use a fresh tenant or reviewed clean canary identities
for that matrix.

Full non-empty default-tenant exercise (2026-08-30): preflight selected local
tenant `default` (`264d304e2927f694`). Full planning first found and fixed a
production-scale extraction defect: binding all 2,490 loan IDs exceeded SQL
Server's 2,100-parameter ceiling, including a refinance query that bound every
ID twice. Lifecycle facts are now extracted in deterministic 900-loan batches
and cross-batch refinance results are deduplicated. Regression coverage proves
that no statement crosses the SQL Server limit.

The first applicable full plan exposed two more operator-scale defects. Eighty-
two loans were rejected because their 20.833333% periodic rate exceeded the
reviewed line `00010` maximum of 20%; the frozen portfolio actually reaches
30%. The product envelope is now 30%, and an exact migration product may widen
only that ceiling without repricing existing loans. Failed-only retry also
expanded a healthy product prerequisite into all sibling loans. Retry selection
now follows failures/crash gaps and only their blocked dependency descendants.
Both fixes have regression coverage, and full safe Fineract validation details
are retained for diagnosis.

Historical full plan `1eeadbdec4a04d76b02cef67c7dddeee` applied the rate-envelope
update. Run `e8bbff21f3bf42e2abdaf1496eb73c7b` synchronized 138 loans and
recovered 27; 987 were directly quarantined, 1,238 were dependency-blocked,
and 100 had root failures. Rate-ceiling failures were eliminated. Remaining
root classes were 67 strict refusals to continue old pre-writer schedules, 15
source-exact preview mismatches, 13 native top-up amount/outstanding domain
rejections, three refinance payoff shortfalls, and two variable-installment API
edge cases.

That historical strict run reconciliation remained blocking: 2,101 historical repayment
allocation mismatches dominated 2,222 total mismatches across 155 executed
loans. Only five were installment-schedule mismatches; 58 represented cutover
balance/terminal outcomes. Those counts are the baseline that motivated the
source-exact repayment and refinance work; they are not the current remaining
defect count. Source-exact historical allocation, penalty handling, the
single-predecessor outstanding-balance boundary, payoff-shortfall handling, and
the exact-half-cent schedule class have since been implemented and
canary-proved. The current remaining work is the structurally distinct
schedule/API edge population plus a new full clean run and unchanged replay,
as listed in the current-status section above. Complete Mobile
Collections repayment linking remains downstream of that clean loan run.

This completes implementation acceptance, not a full-target portfolio apply.
Before Mobile Collections can reach complete native loan and repayment links,
the selected target still needs a fresh full-scope loan plan, apply,
reconciliation, and unchanged second plan. Follow the canonical
[manual loans-to-mobile flow](../orchestration.md#current-manual-loans-to-mobile-collections-flow).
