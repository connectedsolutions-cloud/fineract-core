# Loan component alignment and historical pause integration

## Scope separation — 2026-10-26

The user deferred metric alignment to separate tools and a separate sync step.
This design is not an acceptance gate for enabling interest recalculation.
The [recalculation activation contract](interest-recalculation-default.md) owns
that feature's scope and technical checks. The proposals below remain future
alignment work and must not be silently added to recalculation activation.

## Final-step scope — approved 2026-10-26

The [final metric reconciliation contract](loan-metric-final-alignment.md)
owns the new end-of-loans-sync step: finish existing work, compare metrics,
adjust differences without GL postings, and verify the final values. Those
methods are not required to survive later recalculation, reversal or replay.
Rerunning an earlier operation requires running the final step again. The
historical-event planner and canary proposals below do not add prerequisites
to that deliberately narrower final-state correction step.

## Contract and present implementation

The goal is both complete, correctly classified native history and correct
loan state at handoff. Equal balances cannot excuse a missing event; complete
event counts cannot excuse incorrect balances or future accrual.

[The project-wide date and component contract](../../../../../docs/ARISSTO_LOAN_ALIGNMENT.md)
owns inclusive pause ranges, independent interest/mora controls, backend and UI
requirements. This guide owns the loans-service decision pipeline and code
integration. It describes required work; it does not declare the integration
implemented. Status below records the inspected code, not deployed availability.

| Component | Existing primitive | Integration still required |
| --- | --- | --- |
| Mora | `freezeMora`, `unfreezeMora`, ordered history, past dates, interval-aware calculator | Inclusive range adapter, durable source matching, import reconciliation and safe replay; ordinary commands do not reprocess existing charges |
| Ordinary-interest pause | Eligible cumulative-product pause API, inclusive finite intervals, schedule and post-due day exclusion | Guarded historical import; ongoing pauses; source feed classification; replay and read-back |
| Combined pause | Two independent calculators/controls | Atomic server-side installation with identical bounds and durable link to the source event |
| Interest waiver/reduction | Native `waiveinterest`; source canary established a balance reduction | Reviewed dated classifier, authorized historical accounting context, ordering and post-COB proof |
| Due principal / schedule | Source-exact schedule installation/replacement; cutover due-principal comparison | Dated revision history and remaining-principal rebase proof; no generic amount-adjustment shortcut |
| Carried interest | `sourceExactAccrualCatchup` and blocking handoff comparison | Prove catch-up after controls/revisions/waivers reproduces source amount and future accrual |
| Other history | Native source-exact repayment/reversal, charges, refinance, component reallocation and risk-history paths | Include in dependency/order guards; unsupported corrections remain blocked |

## 1. Source extraction and evidence

Extend the existing `arissto_sync/loans.py` extraction/planning pipeline. Keep
source access read-only. Do not put runtime sync code in `credesal-db-space`.

Freeze source identity, effective date, recorded time/order, source revision,
before/after observations, schedule version, component amounts and evidence
references. Keep only necessary non-PII facts/hashes in immutable artifacts;
never copy audit narratives, names, credentials or full sampled records into
the plan or documentation.

- Pause candidates: `AFI_BLOQUEO_CUENTA`, loan product type 3 / restriction 4,
  `BLOQUEO` 1/0, linked by account to `CRD_CARTERA`; corroborate using dated
  state, accrual and mora evidence. Verify exact event identity/ordering columns
  against metadata before defining an extractor. Current `CRD_CONGELADO` and
  freeze date are consistency controls, not sufficient history.
- Schedule/terms revisions: `CRD_REESTRUCTURACION`, archived and subsequent
  `CRD_PLAN_PAGO` versions, effective chronology and principal paid before the
  revision. Same loan ID distinguishes revision from refinance.
- Balance reductions: dated audited edits, movement allocations/reversals,
  before/after total carried interest and intervening accrual. Use source
  bucket differences only to disambiguate, never as a waiver amount.
- Payments and corrections: stable movement IDs, native component allocations,
  PRE/POS state, reversals and liquidation/predecessor relationships.

Use the [source event inventory](../../../../../../credesal-db-space/docs/learnings/loan-historical-adjustment-events.md)
and [mora evidence](../../../../../../credesal-db-space/docs/learnings/mora-y-cargos-de-creditos.md)
rather than duplicating source-domain narratives here.

Every financial plan displays **Arissto through** `S` and **Fineract starts**
`T = S + 1 calendar day`, plus `source_observed_at`. Events owned by Arissto
through `S` can be imported only if committed at observation time. A pause
continuing beyond `S` retains its real active state or verified agreed end;
do not synthesize a resume at `T`.

The present mora snapshot reader uses completed source closes. The planned
carry-forward mode cannot use COB closure as an eligibility gate: it needs an
explicit observed-state extractor and observations pinned to that read, rather
than silently falling back to today's balances for an earlier `S`. Keep this
distinction in the selected mode's authoritative contract.

## 2. Deterministic method selection

Build a component alignment planner next to `loans.py` (proposed module:
`loan_alignment.py`). It is a rule-based classifier, not an AI runtime and not
a trial loop that applies adjustments until balances happen to match.

The classifier emits one or more decisions for each logical source event:

| Verified source effect | Method decision | Must not do |
| --- | --- | --- |
| Ordinary interest stopped, mora continues | Historical interest-only pause importer | Infer a pause solely from zero accrual or apply a mora freeze |
| Mora stopped, ordinary interest continues | Historical mora control / normalized adapter | Waive existing mora or stop interest |
| Both stopped for the verified interval | Atomic combined historical control | Substitute general whole-loan freeze or issue two uncoordinated writes |
| Total carried interest reduced after excluding payments, reversals and accrual | Dated native interest waiver/reduction, once its historical canary passes | Use overdue-interest delta or create a synthetic cash payment |
| Interest only moved between overdue/pending buckets; total unchanged | Evidence-only, no native financial command | Waive, pause or reschedule solely to match that bucket |
| Principal due changed due to installment/term revision | Dated schedule transition and reprocess | Pay, forgive or write off outstanding principal |
| New plan represents remaining unpaid principal | Schedule rebase with paid-before-plan baseline | Replay prior principal payments against the reduced plan twice |
| Real repayment/reversal/reallocation | Existing corresponding native movement method | Infer a payment from a close-to-close balance difference |
| Contractual maturity reached | Calculate from effective terms | Add an artificial principal transaction |
| Unexplained balance/interval difference | Quarantine with reason/evidence gap | Guess a scope, overwrite a balance or silently omit the event |

A single source edit can produce several decisions, for example a schedule
revision plus an actual interest reduction. Keep a shared logical event ID,
separate component effects and one economic amount per component to prevent
double counting. Rule order must not make one effect hide another.

Candidate action kinds such as `import-interest-pause`, `import-mora-pause`,
`import-combined-pause`, `waive-interest`, `revise-schedule` and `evidence-only`
are internal plan vocabulary proposed here. They are not registered CLI/API
commands. The planner must resolve every write to an installed authorized
backend capability; missing capability blocks that loan.

## 3. Updated component: mora

Keep the loan's approved monthly mora rate, grace days, last mora payment date,
source mora balance and first Fineract day. Use the daily mora charge-time-19
implementation; normal interest, generic delinquency pauses and other penalties
are separate. A source zero rate is not a missing rate.

For a normalized inclusive interval `[A,B]`, the existing event representation
is freeze on `A`, unfreeze on `B+1`. Existing mora commands reject future event
dates. Therefore an interval ending today or later needs the new range-aware
backend capability; do not send a future unfreeze to the old API or schedule a
hidden job. Ongoing intervals remain frozen without a fabricated resume.

Store stable source event identities and verify ordered read-back. The existing
commands reject duplicate transitions; they do not alone guarantee sync
idempotency. Recover uncertain responses by source identity and normalized
content, not by retrying blindly or matching only dates.

Install historical controls before calculations. For an existing replayed loan,
use guarded reprocessing; backdating `freezeMora` merely saves history and does
not reverse existing charges or rebuild payment allocation. Reconcile opening
mora and unpaid replay-generated penalties together so they are counted once.
Later COB must exclude all paused days, including overlaps, without catch-up.

## 4. Updated component: ordinary-interest pause

Retain eligible cumulative, non-recalculating Credesal products and their
repayment strategy. Do not convert products to progressive. Inclusive request
bounds are already the interest convention; normalize mora adapters to it.

Add the permission-gated historical importer described in the global contract.
It must support a past completed interval and an ongoing pause, preserve native
history, and install before historical payments/catch-up. Do not simply remove
the future-date validator: schedule protections, paid/waived installments,
transaction replay, and historical-accounting authorization require explicit
handling. Guard against reducing a source-exact interest schedule twice if that
schedule already incorporates the pause. Freeze the schedule basis in the plan
and block an unknown basis until the source/native canary resolves it.

Ordinary interest stops only for paused days, resumes afterward without
backfill, and existing interest stays collectible. Principal due dates and
amounts remain unchanged unless a separate source revision proves otherwise.

## 5. Updated component: interest waiver or reduction

Classify a waiver from a proven **total carried-interest reduction**, adjusted
for actual repayments, reversals, accrual and any schedule revision. An audited
last-interest-payment date edit is evidence, not by itself an instruction to
waive or fake a payment. Do not count a schedule's interest reduction again as
a waiver unless the source proves an additional distinct reduction.

Native `waiveinterest` is a candidate primitive, not blanket permission to
replay every Arissto edit. Stage the loan immediately before the event, establish
the interest available to reduce, apply the dated adjustment, then replay later
events and catch up. Block an amount the primitive cannot represent. Preserve
the source identity, revision and reversal relation; a waiver must not reappear
after retry or be undone by catch-up/COB.

Historical native GL must use the authorized pre-`T` guard; historical Arissto
journals remain with accounting. Acceptance concerns carried interest and
subsequent accounting outcome, not matching the number/shape of source journal
lines or reproducing Arissto overdue-interest buckets.

## 6. Updated component: due principal, schedule and maturity

Due principal is derived from unpaid installments due by the comparison date,
not a freely writable balance. Reconstruct original terms, schedule versions,
dated revisions, paid-before-plan baselines and payments in effective order.
Keep total principal outstanding distinct from principal due.

Existing `sourceExactActiveSchedule` and `sourceExactResyncSchedule` can install
or replace schedules. A final-schedule replacement does not alone reproduce a
dated historical transition. Implement/validate the missing versioned transition
before claiming historical equivalence for those loans. Preserve original and
revised principal totals, already paid counters, interest basis and maturity;
check term-account mapping if maturity changes. Unknown, non-monotonic or
negative-interest plans need their existing narrow reviewed policy or quarantine.

After replay, due principal must match the selected source observation within
the existing $0.01 contract. A difference is a reason to investigate the chain,
not authorization to synthesize a repayment, principal waiver or terminal bridge.

## 7. Updated component: accrued/carried interest

Catch-up uses `sourceExactAccrualCatchup` only after effective schedule, pauses,
payments and reductions are correctly represented. It must not restore waived
interest, charge paused days, or duplicate source schedule interest. Keep
periodic-accrual transactions and carried loan interest conceptually separate;
equal accounting accrual totals alone do not prove the borrower balance.

Compare the existing native due-plus-not-yet-due accrued-interest projection
with source `SALDO_INTERES`, using the snapshot's documented meanings.
`SALDO_INTERES_PENDIENTE` is already included and must not be added again.
`SALDO_VENCIDO_INTERES` and the pending bucket are diagnostic source evidence,
not independent native acceptance targets. Differences over $0.01 block handoff.

## 8. Additional components that affect alignment

- **Repayment allocation and reversals:** preserve exact source movement identity,
  components, economic dates and corrected versions. Replay against effective
  controls/schedules. Zero-cash component corrections are not extra receipts.
- **Insurance, fees and other penalties:** retain source debt, payments, waivers
  and recurrence rules independently. Interest+mora pause must not silently stop
  insurance or every recurring charge. Unsupported source components block.
- **Refinancing and consolidation:** use linked predecessor/successor event
  graphs and native settlement methods. Component revisions propagate through
  the affected graph; current terminal status cannot classify earlier payoffs.
- **Status, risk and delinquency:** preserve source history under its reviewed
  service, derive native delinquency from native due state, and do not use NPA,
  charge-off or closure as a proxy for a pause. Mora suspension does not itself
  stop days-past-due classification.
- **Accounting ownership:** loan events and balances belong to this service;
  historical GL belongs to accounting. Suppress historical native GL through
  authenticated policy and validate post-handoff accrual/GL without importing
  post-`T` Arissto journals over Fineract-owned activity.

## 9. Immutable plan, execution and reconciliation

For each component decision freeze: logical source identity/revision, component,
evidence references/hashes, economic date/order, normalized bounds and scope,
selected method/capability version, expected effect, dependencies, target
precondition signature, and quarantine reason if unresolved. Freeze expected
terminal state separately. Changes after approval require a new reviewed plan.

Execution sequence:

1. Validate source/target signatures, target ownership, backend capabilities and
   permissions; reject stale or unsupported plans before loan writes.
2. Create/verify the loan, approve and disburse through the existing lifecycle.
3. Install verified pause history and the appropriate pre-event schedule basis
   before any calculation can visit those days. The historical importer must
   install without prematurely replaying against an unrelated final schedule.
4. Merge payments, reversals, schedule transitions, waivers and settlements into
   one effective event order. Use source time/sequence and dependencies to order
   same-day events; ambiguous noncommuting events block rather than receive an
   arbitrary ID-based order. Catch up to a reduction event only as required to
   establish that event's balance, then continue replay.
5. Perform final accrual catch-up and explicit mora/fee opening-state alignment
   under existing contracts, without introducing a generic residual adjustment.
6. Read back native events, controls, schedules and component balances. Mark
   the loan accepted only if event and terminal-state checks both pass.

Reconcile normalized bounds and scope, effective active state, one current
native representation per source event/revision, principal outstanding and due,
carried interest, mora and other component balances, allocations, maturity and
terminal status. Verify no duplicate economic effect across methods. A reviewed
exception must remain narrow and visible; do not silently widen existing
manual-adjustment exceptions to cover new pause or waiver classes.

On retry, recover by source identity plus revision/hash and verify read-back.
Changed/missing/reordered source events require an explicit revision plan,
target signatures and guarded atomic reprocess. Do not delete history, append
earlier mora events to an already later history, or overwrite Fineract-owned
activity. A combined request must not leave half the control installed.

## 10. Code locations and implementation order

| Location | Planned update |
| --- | --- |
| `arissto_sync/loans.py`: extraction, `compose_loan_plan`, lifecycle builder | Read verified source feeds, freeze classifications and controls, include them in source hashes and immutable plan |
| Proposed `arissto_sync/loan_alignment.py` | Pure interval normalization, event/effect classification, capability selection and component dependency decisions |
| `loans.py`: `_apply_loan_lifecycle`, schedule/catch-up helpers | Install controls after disbursement, dispatch dated effects in order, recover retries by native source identity |
| `loans.py`: reconciliation and apply guards | Read-back event completeness, bounds, state, allocation and monetary checks; reject old plans missing the new contract |
| Fineract interest-pause service and shared interval/calculation domain | Historical and ongoing intervals, atomic combined operation, identity/revision, preservation/reprocess validation |
| Fineract mora service / `LoanMoraFreezePeriods` | Inclusive-range adapter, idempotent import and normalized read-back; keep old event-date semantics |
| Fineract source-exact schedule/waiver paths | Dated transition and historical reduction acceptance; authenticated accounting ownership |
| Mifos mora and interest-pause forms/history | Shared range labels, derived resume date, scope/history filtering and migration-event restrictions |
| Carry-forward hashes/ownership inventory and seed graph | Include pause histories/identities and any new persisted relations so changed history is not falsely retained as unchanged |

Schema additions, if needed, belong in versioned Fineract migrations; the sync
must not create tables or dynamically alter schema. Register implementation
commits and decisions in the durable [change tracker](change-log.md), with
affected source loan IDs only when established by actual reviewed plans/runs.
This design document is not an implemented-code tracker entry.

## 11. Validation before enabling the integration

1. Date tests: one-day ranges, month/year/leap-day boundaries, inclusive end,
   resume day, same-day legacy freeze/unfreeze (zero paused days), adjacent and
   overlapping agreements, ongoing pauses and snapshot clipping for calculation
   without changing the stored agreement.
2. Classification tests: interest-only, mora-only, both, bucket-only interest
   relief, real total-interest reduction, schedule revision/rebase, mixed edit,
   missing evidence and contradictory source flags. Each must select the right
   method or quarantine, never a convenient balance patch.
3. Backend tests: permissions, rollback of combined failure, unchanged retries,
   identity collision, changed revision, stale target signatures, closed source
   loans replayed while active, and paid/waived schedule protections.
4. Replay tests: payment during pause, later reversal, reduction before later
   repayment, changed maturity, schedule already net of pause, refinance-linked
   effects, and repeated catch-up with no duplicate interest/mora/charges.
5. Controlled local `sandbox:fineract_sandbox` canaries: verify every component
   at `S`, first native COB at `T`, COB during and after pauses, a repayment,
   and unchanged replay with zero duplicate events/effects. Test full frozen
   state separately from interest+mora scope.
6. UI and accounting checks described in the global contract. Record observed
   results and remaining blockers; unit tests do not prove live balance parity.

Use the documented workflow control plane and reviewed immutable plan for any
state-changing test. This documentation authorizes no reset/start/retry and
does not claim the still-missing historical methods are available.
