# Paired ordinary-interest recalculation canary

Observed 2026-10-26. **Update: the source-exact replay blocker has been repaired
and all ten proof histories now complete.** Exact interest parity remains a
separate open result: only one of the five on copies matches at handoff.
Insurance work remains deferred. The original failed experiment is preserved
below, followed by the [repair and recovery result](#repair-and-same-loan-recovery).

## Frozen scope

- Target: existing disposable local `sandbox`, database `fineract_sandbox`,
  fingerprint `b9f6834b66790744`.
- **Arissto through 2026-10-19**; **Fineract starts 2026-10-20**. The active
  accounting boundary was checked before planning and execution.
- Scoped canary in the existing target lifetime. No composed workflow,
  tenant reset, replacement cycle, canonical loan replay or boundary change.
- Five source loans, each copied twice: recalculation off and on, **10 proof
  loans total**. Source ordinary interest differed from the scheduled-interest
  projection for every selected loan.
- Only the selected loan's current life was recreated. Refinance ancestors
  were not replayed; copies start with standalone disbursements of the current
  loan principal. Existing sandbox clients were referenced, not recreated.

Executable immutable plan:
`2ad55240b3247d9d36ceb12852d5146c9aca0670a197fc3f01541d5c4aef1f10`.
The durable change-tracker observation is `14` (an experimental observation,
not a repair commit).

It is stored under ignored `.arissto-sync/loan-recalculation-canaries/`;
the matching `-result.json` preserves private financial evidence and each
captured daily schedule and transaction prefix.

## Controlled settings and exclusions

Products 3 (off) and 4 (on) are dedicated `PROOF:recalc-oct19-a:PRODUCT:*`
products. Both use the existing Credesal accrued-interest-first transaction
strategy, cumulative schedules, actual day count, and no accounting. They
have no insurance, fee or mora charges. The only financial setting difference
is recalculation and its required configuration; product identity and numbering
codes necessarily differ. Existing canonical products were not modified.

The on product was read back and verified:

- Daily rest frequency, interval 1.
- No interest compounding.
- Reschedule next repayments, keeping arrears based on the original schedule.
- Pre-close interest calculated through the pre-close date.

`ADJUST_LAST_UNPAID_PERIOD` was rejected by the product validator as
progressive-only; it was not silently used on these cumulative loans.
Earlier setup plans failed product validation before loans were created and
are retained as immutable history. The on/off product pair was then created
with the final configuration above.

Repayments use `sourceExactRepayment`, preserving the source principal and
ordinary-interest components. Their experimental total is principal plus
ordinary interest; non-interest components are deliberately excluded.
Only loan 2647 has a nonzero excluded mora payment component in this cohort.
There is no opening waiver, upward interest adjustment, fee or penalty charge
to hide a calculation difference.

## Original experiment results (before repair)

| Source | Off proof | On proof | Off replay | On replay |
| --- | ---: | ---: | --- | --- |
| 2612 | 2754 | 2755 | All 9 repayments; 25 daily snapshots | First repayment rejected; 1 daily snapshot before rejection |
| 2647 | 2756 | 2757 | All 7 repayments; 20 daily snapshots | All 7 repayments; 20 daily snapshots; handoff interest still below source |
| 2581 | 2758 | 2759 | All 10 repayments; 29 daily snapshots | First repayment rejected on disbursement day; no completed daily snapshot |
| 2597 | 2760 | 2761 | All 7 repayments; 27 daily snapshots | First repayment rejected; 1 daily snapshot before rejection |
| 2593 | 2762 | 2763 | All 21 repayments; 27 daily snapshots | First repayment rejected; 1 daily snapshot before rejection |

Thus all five off controls replayed successfully, but no complete on loan
passed exact handoff interest equality. The rejected on loans do not have
valid final comparisons and must not be described as final-balance mismatches.
The refusal code is `error.msg.loan.source.exact.allocation.not.representable`;
the unrepresented remainder is in the requested principal component, not
insurance. The failed transactions did not commit. This establishes a
compatibility failure between the tested source-exact replay path and the
recalculation mode, not a conclusion that every native repayment strategy fails.

For 2647, recalculation-on matches the first seven source daily interest
closes. The first partial ordinary-interest collection on October 7 introduces
a difference that persists through handoff. The on loan matches principal on
all 20 inspected closes and preserves all seven repayment component splits.
Its dated prepayment quote agrees with the dated collectible-interest schedule
projection at the final boundary, so the remaining difference is not just the
live summary's business date being compared with an old source close.

## Why four source-exact replays fail

Follow-up code and stack-trace inspection on 2026-10-26 narrows the failure
beyond the generic API refusal. The recorded exceptions pass through:

```text
LoanTransactionProcessingServiceImpl.getRecalculatedSchedule
  -> AbstractCumulativeLoanScheduleGenerator
       .handleRecalculationForTransactions (line 549)
       or .handleRecalculationForNonDueDateTransactions (line 895)
  -> CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor
       .processSourceExactRepayment (line 222)
```

The generator adds each installment to a growing temporary list before calling
the repayment processor (`generate`, lines 361–376). In those recalculation
calls, the processor receives the installments built so far, not the complete
future schedule. The generator explicitly expects the processor to **return
unprocessed early-payment money**; the following branch uses it to reduce the
outstanding principal and adjust later installments (lines 549–570, with a
parallel path at 893–900).

Our custom source-exact processor instead tries to place the full declared
principal/interest/fee/penalty allocation into the supplied list and throws if
any component remains (lines 190–224). A requested principal payment exceeding
the principal in the temporary installment list is therefore rejected before
the generator can handle the excess as early principal. For 2612, the first
payment's source principal exceeds the first scheduled principal installment;
the exact difference equals the principal remainder in its captured refusal.
The off copy can allocate across its full schedule and completes.

This is an incompatibility in the custom integration's intermediate processing
contract, not evidence that the loan has insufficient total outstanding
principal or that native ordinary-interest recalculation is financially wrong.
It is not related to insurance: both products have zero charges.

A targeted compatibility fix is worth testing so the four histories can reach
an interpretable financial result. It must distinguish provisional schedule
rebuilding from final source-exact settlement, preserve the original component
split at final reconciliation, and allow the native generator to handle early
principal. Simply deleting the strict allocation check would risk silently
losing imported principal. The implementation and validation are recorded in the repair section below.
Even a successful fix would not eliminate the separate source interest-date
behavior observed on the completed 2647 on copy.

## Newly isolated source behavior

The [source investigation](../../../../../../credesal-db-space/docs/learnings/loan-interest-basis-2612.md)
records the calculation and the partial-payment evidence. Movement
`0000032665` on October 7 increases the source's paid-interest counter by its
full ordinary-interest collection, while `FECHA_ULTIMO_PAGOINT` moves from
September 30 only to October 4. The source then calculates collectible
interest from that date; native recalculation instead credits the collected
interest against the accrued amount. Source October 7 collectible interest is
not simply October 6 interest less the full collection plus the new provision.

An independent source audit reproduces the ordinary-interest formula for all
20 closes on 2647. Whole-covered-day handling is a hypothesis for the date
advance, not a verified application rule. The source application routine that
selects the new interest date remains unidentified. No insurance implementation
was changed to address this finding.

## Verification and limits

- 128 source close comparisons across the five off controls; 20 through a
  complete on replay and 3 additional pre-failure on comparisons.
- Principal matches every recorded daily comparison. The four rejected on
  histories remain partial, with no committed repayments.
- Direct API/SQL verification confirms each loan's recalculation flag, no
  charges, no interest waiver, and **zero loan-transaction-linked GL rows**.
  Both proof products have accounting rule `NONE`.
- The paired copies initially use the same source-exact pending schedule.
  Recalculation is allowed to change later schedule values; forcing the
  original schedule back afterward would invalidate the experiment.
- The daily evidence is captured after replaying only source repayments
  through that close, projected at the next day. The global tenant business
  date was not moved; no global or loan COB was invoked by the experiment.
  This is a historical replay/projection test, not a complete daily COB or
  future-accrual acceptance test.
- Dated payoff quotes are retained separately from the primary collectible
  schedule projection. Off-product payoff quotes can include different
  interest amounts and are not substituted for the original comparison.
- Using accounting-free products intentionally isolates loan calculations;
  this does not prove the production accounting lifecycle or periodic-accrual
  service integration. This cohort covers daily cumulative loans without
  freeze or source schedule revision, not all active loan shapes.

The original pre-repair checks are in
[`interest-recalculation-canary-checks.json`](interest-recalculation-canary-checks.json).
The helper is [`arissto_sync/loan_recalculation_canary.py`](../../arissto_sync/loan_recalculation_canary.py)
relative to the sync-engine root. It supports bounded `extract`, `plan` and
`apply` phases and refuses a nonlocal/non-sandbox target. Raw source snapshots,
immutable plans and results remain private under ignored runtime storage.

## Decision

Do not enable recalculation for canonical imports or start an insurance rewrite
on the assumption that it closes the interest gap. The tested simple-toggle
hypothesis fails: source-exact replay compatibility and source partial-interest
date allocation both remain unresolved. This does not approve an upward
opening adjustment either. Further implementation must address those
separately and retain exact handoff reconciliation.


## Repair and same-loan recovery

The processor now exposes an explicit
`handleRepaymentScheduleForInterestRecalculation` entry point. The cumulative
schedule generator uses it for its temporary schedule-prefix processing.
The Credesal processor returns only an unrepresented **principal** remainder
in that context, letting the native generator account for the early principal
and rebuild later installments. It still rejects unrepresented interest, fees
and penalties. Ordinary final posting and full reprocessing remain strict.
No mutable processor-wide or thread-local bypass flag is used.

Regression tests reproduced all four original principal remainders before the
fix. After the fix, all 39 processor tests pass, including provisional-to-final
allocation preservation and rejection of nonprincipal shortages. The interface's
default implementation delegates to existing behavior for other strategies.
The five cumulative-generator call sites now explicitly identify provisional
recalculation processing.

Recovery plan:
`9253487dd313195d4c8c94458884e7c4b74a7e02be2bbdc760d85aefa14bd1a6`.
It binds the repair source hashes, original result hash, existing four on proof
identities and their repayment baselines. Separate retry keys avoid the cached
original validation failures. It continues those same loans; no products or
loans are added, no source allocation is edited, and no target is reset.
The original plan/result files remain unchanged; the recovery's `-result.json`
records the continued histories.

| Source | Recovered on proof | Repayments now complete | Exact handoff ordinary interest |
| --- | ---: | ---: | --- |
| 2612 | 2755 | 9/9 | No; small positive residual |
| 2581 | 2759 | 10/10 | No; remaining source/native difference |
| 2597 | 2761 | 7/7 | No; small positive residual |
| 2593 | 2763 | 21/21 | Yes |

The previously completed on proof for 2647 remains unchanged and still differs
from the source. Its initial partial-interest date finding remains valid.
Those financial results are not treated as replay failures or accepted under a
cent tolerance.

Post-recovery direct API/read-only SQL reconciliation verified:

- All ten proof histories complete, with 108 repayments in total.
- Every repayment's identity, date and principal/interest components match the
  frozen source plan; there are no duplicate repayment identities.
- Every repayment's installment mapping sums match its transaction components.
- Scheduled principal totals equal disbursed principal. Paid principal and paid
  interest totals match the source, as does outstanding principal.
- Principal matches all 256 recorded daily comparisons.
- All proofs still have zero charges, zero waivers and zero linked GL entries.
- Exactly one of the five on proofs has exact handoff interest. Completing the
  histories does not authorize enabling recalculation canonically or changing
  insurance.

Non-sensitive reconciliation checks are preserved in
[`interest-recalculation-repair-checks.json`](interest-recalculation-repair-checks.json).
Financial residuals and daily numeric schedules remain in the ignored recovery
evidence. The repair addresses the integration failure identified above; the
remaining interest/date/rounding behavior still requires separate assessment.
No UI field, label or API repayment component meaning changes in this repair.
