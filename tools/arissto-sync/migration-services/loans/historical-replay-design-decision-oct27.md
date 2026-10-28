# Historical replay and post-migration recalculation — October 27 decision

> Implementation update: commit `9d021d4efd` implements the historical-off
> direction, guarded refinance staging and complete-plan replay barrier. The
> earlier audit and investigation status below is preserved as historical
> evidence. Full native acceptance follows the requested clean run; consult the
> [progress tracker](loan-sync-updates-progress-oct27.md) for its current result.

## Direction and implementation status

Use **interest recalculation OFF during historical migration**. Replay the
recorded source history, reconcile complete loan lifecycles and their refinance
chains, then apply explicit migration corrections at the end of the complete
loan-service replay. Interest recalculation may operate after handoff only
through a separately supported, date-bounded activation that preserves the
accepted migrated history and opening balances.

**This is a design direction, not an implemented runtime change.** The current
planner still creates daily-recalculation-enabled products/loans. Existing
products, loans, settings, cycle, accounting boundary and checkpoints have not
been changed by this review. Do not interpret this note as an instruction to
flip an existing product flag, modify active loans or resume the current cycle.

The operator stopped further experiments and requested a decision based on the
existing evidence. No new replay, paired experiment, test suite, reset, plan or
workflow action was executed for this decision. A separate temporary PostgreSQL
instance and Fineract process were bootstrapped in preparation, with an empty
baseline and synthetic configuration identities, then stopped before any loan
history replay. They used ports 55477/18443 and databases `lsreg_*`; the existing
sandbox services were not stopped or reconfigured. No complete new lifecycle
regression baseline is claimed. Building and executing that baseline remains
deferred under the operator's latest direction.

## Why this direction follows from the evidence

The importer declares the source schedule, transaction identities, dates and
four allocation components as frozen facts. Native interest recalculation can
regenerate a different installment calendar, repeatedly process prior payments
and charges, and ask the source-exact processor to allocate against an unfinished
prefix of that generated calendar. The prefix's available components can differ
from the recorded source payment, even when the full source history is valid.
Those are two competing ways of reconstructing the same historical servicing.

The [earlier paired canary](interest-recalculation-canary.md) showed successful
ordinary-interest replay for all five off controls, while four on histories
initially failed. Subsequent processor repairs completed the on histories, but
only one of five on copies matched source handoff interest. That experiment
excluded insurance and refinance ancestors, so it does not prove that switching
off fixes every complete chain.

The [remaining LS-01 evidence](investigations/ls01-remaining-cohort-investigation-retry-oct27.json)
provides the stronger warning about our previous acceptance unit: all 28 eligible
original empty-prefix payments passed, yet four root histories failed later.
The 65-loan attempt finished with 49 successful/recovered loans, eight failures
and eight dependency blocks; reconciliation was false. A cleared first error
was not a completed service repair. The [progress tracker](loan-sync-updates-progress-oct27.md)
retains the individual outcomes and all unresolved cases.

Disabling recalculation addresses the historical schedule-regeneration conflict.
It is **not evidence that all fee, penalty, reversal, refinance or balance issues
are solved**. Ordinary reprocessing may still rebuild derived paid/outstanding
state with the flag off. Historical source facts must remain invariant under
that internal processing.

## Phase boundary

| Phase | Required behavior | Completion condition |
| --- | --- | --- |
| 1. Freeze | Freeze the source window, financial terms, schedule versions, ordered events and complete refinance/dependency graph. | No missing settlement predecessor/successor, unsupported after-boundary source event or invented historical snapshot. |
| 2. Replay source facts | Keep historical interest recalculation off; import genuine source disbursements, payments, charges, reversals, schedule changes and refinance settlements at their recorded dates. | Every recorded event in every required financial chain is represented with the exact source identity, date, amount and allocation. |
| 3. Reconcile complete service | Check complete histories, reversals, charge ownership, payoff/net-cash conservation, final states and all required dependencies. | No failed or blocked financial chain. Reviewed nonfinancial omissions must not remove required financial history. An early successful payment or zero mismatch entries among partial successes is insufficient. |
| 4. End-of-replay corrections | Compute and apply explicit, auditable final migration adjustments against the frozen targets after the preceding barrier. | Exact final metrics and native opening state verified; no interim compensation used to make a later historical event runnable. |
| 5. Handoff | Keep accepted history closed through the source-through day. Activate future native behavior only through a supported forward-only handoff. | The first Fineract-owned day and all protected migrated state remain exact. |

A payment necessarily updates paid and outstanding balances. A genuine source
reversal, reschedule or refinance closure also has its recorded historical effect.
These are source facts, not migration corrections to postpone. The restriction
is on unrecorded compensating payments/credits, migration balance/charge
realignments and native schedule rewrites inserted while historical replay is
still in progress. Historical charge ownership must not be fabricated, reset or
waived to force acceptance.

For the current cycle, **Arissto through is October 26, 2026; Fineract starts is
October 27, 2026**. Payment `0000034318` and all other Arissto activity dated on
or after October 27 stay excluded or source-quarantined. A future activation
starting October 27 would govern Fineract-owned operation; it would not authorize
importing those excluded Arissto payments. No boundary advance or reset follows
from this decision.

## Shared implementation findings

| Location | Observed current behavior | Consequence for implementation |
| --- | --- | --- |
| `LoanTransactionProcessingServiceImpl.getRecalculatedSchedule` → `AbstractCumulativeLoanScheduleGenerator.rescheduleNextInstallments` | Rebuilds schedules and passes generated prefixes to the transaction processor when recalculation is enabled. | Historical import needs a frozen-history mode rather than more component-specific prefix exceptions. |
| `AbstractLoanRepaymentScheduleTransactionProcessor.reprocessLoanTransactions` | Resets charge-paid and installment-derived components before replay. This is separate from the interest-recalculation flag. | Switching the flag off must not be presented as disabling every internal replay. Preserve source transaction components and legitimate charge ownership; do not restore over pending caller/staff state. |
| `_ensure_refinance_prepayment_ready` | Uses a dated native payoff quote and may post `sourceExactGoodwillCredit` with a `CRD-REFI-CUTOVER` identity before successor disbursement. | This interim bridge conflicts with the new end-only correction rule. Do not merely move it later: the historical settlement path must honor the recorded source payoff and net cash without depending on that bridge. |
| `fetchPrepaymentDetail` / `getTotalOutstandingOnLoan` | The non-recalculation path sums outstanding scheduled components, including future interest. | Recalculation-off is not permission to replace the recorded source payoff with an ordinary full-schedule quote. Historical payoff validation needs explicit source/as-of semantics. |
| `_apply_loan_lifecycle(finalize=True)` | Can create/verify cutover insurance and post terminal adjustments during per-loan finalization. | Separate source event replay from end-of-service migration corrections. Do not let a loan finishing early advance the global correction phase. |
| `apply_loan_plan` final-metric loop | Runs after worker attempts, but adjusts successful loan outcomes even when other loans are failed or blocked. | Being the last loop is not a global success barrier. Gate corrections on complete financial-service readiness. Preserve the existing dependency and source-boundary guards. |
| `_replay_refinance_component` | Stages predecessor prefixes and successor disbursements before finalizing the component's remaining history. | The unit of financial acceptance must remain the entire connected refinance component, including later predecessor repayments, partial paydowns and consolidations. |
| `Loan` / `LoanAssemblerImpl` | A loan has its own flag and recalculation details. A product change can copy its flag and requests schedule regeneration. | Updating a product is not safe date-bounded activation for existing migrated loans. Do not switch products as a workaround. |

## Can recalculation be enabled after migration?

**Yes as the intended capability; it is not a verified existing migration
handoff operation.** New loans created under an enabled product are a different
case from converting already-disbursed migrated loans.

For existing migrated loans, a future activation operation must start at
**Fineract starts**, use the verified opening principal, accrued interest,
insurance, mora and remaining contractual terms, preserve earlier source
transactions and allocations, and leave completed final migration adjustments
intact. It must also preserve legitimate post-handoff activity already recorded
in Fineract. Activation cannot regenerate from original disbursement, undo the
accepted opening state or silently resubmit past source events.

The current code stores a loan-level flag/details and does not establish that
forward-only boundary. The ordinary product-switch path requests a schedule
recalculation. Therefore do not promise that toggling the product or loan flag
after migration is sufficient. Implement and review a dedicated handoff before
using this capability; no setting was changed in this investigation.

This does not turn off interest charging, waive accrued interest, remove debt
insurance or change the source rates. Interest recalculation, normal accrual,
source accrual controls and accounting ownership are distinct concerns.

## Next implementation boundary

Replace the historical daily-recalculation policy and its planner/writer/retry
assumptions together. Keep existing loan conversions explicit and guarded;
changing a product alone does not safely convert partially replayed loans.
Resolve historical refinance payoff semantics and eliminate dependency on
interim compensation. Add a real complete-service completion barrier before
final adjustments. Preserve source identities, ownership, accounting dates,
current-office dependencies, source quarantines and exact final reconciliation.

When implementation resumes, its acceptance unit must include complete histories
and connected refinance chains, plus idempotent retry and protection of unrelated
or later activity. A known failing component stays failing; single-event unit
tests and mocked phase sequencing cannot certify native full-lifecycle behavior.
No new experiment or baseline implementation is authorized by this documentation
commit; further work follows the operator's next implementation instruction.
