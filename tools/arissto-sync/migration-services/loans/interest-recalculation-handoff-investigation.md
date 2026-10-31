# Existing synced loans: interest recalculation at handoff

Investigation: October 30, 2026. Read-only inspection of the local Fineract,
Mifos and sync-engine working trees. Fineract HEAD was
`e5d928f7c55e0f469975a9baac510a0461ab50e8`, with uncommitted changes present;
findings describe inspected source, not a verified deployed build. No loan,
product, workflow, accounting date or database was changed. No activation API
experiment was run.

## Finding

**There is no supported existing API operation in this checkout to switch an
already disbursed synced loan from recalculation off to on.** A custom
post-handoff activation capability appears technically feasible because the
loan model stores these settings, but preservation of historical allocations,
balances and accounting has not been demonstrated. It is not a bulk Boolean
update or an already accepted feature.

The requested behavior is: import with recalculation off, then activate native
recalculation on eligible outstanding loans when Fineract takes ownership.
Keep closed, refinanced-away, written-off and otherwise terminal loans outside
automatic activation unless a separate reviewed contract explicitly includes
them. Historical replay remains off.

## Code evidence

Paths below are relative to `fineract-core/` unless stated otherwise.

- `fineract-provider/src/main/java/org/apache/fineract/portfolio/loanaccount/serialization/LoanApplicationValidator.java`:
  `SUPPORTED_PARAMETERS` does not accept `isInterestRecalculationEnabled` as a
  loan application parameter. `validateForModify(command, loan)` (around line
  854) also rejects any loan not submitted and pending approval. Sending
  `PUT /loans/{id}` with this flag therefore does not provide an active-loan
  conversion path.
- `fineract-provider/src/main/java/org/apache/fineract/portfolio/loanaccount/service/LoanAssemblerImpl.java`:
  `updateFrom` copies the product recalculation flag only when the application
  changes product (around line 607). That is inside the pending-application
  modification flow; it is not an active-loan workaround.
- `fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/domain/Loan.java`:
  loan construction copies product settings into a loan-specific
  `LoanInterestRecalculationDetails` only when enabled (around line 695).
  `isInterestRecalculationEnabled()` reads the loan's own repayment detail,
  not the current product flag. Changing a product does not propagate the flag
  to its existing loans through these paths.
- `fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/domain/LoanInterestRecalculationDetails.java`:
  the `m_loan_recalculation_details` entity holds rest frequency, rescheduling,
  compounding and preclosure settings. A flag-only SQL update would leave
  disabled-originated loans without the supporting details created by normal
  enabled origination.
- `fineract-provider/src/main/java/org/apache/fineract/portfolio/loanaccount/service/LoanApplicationWritePlatformServiceJpaRepositoryImpl.java`:
  origination/modification also persists recalculation calendars and calendar
  instances. An activation implementation needs equivalent initialization for
  its selected configuration, as well as product/loan compatibility validation.
- `Loan.java#fetchInterestRecalculateFromDate` (around line 1540) falls back to
  disbursement when `interestRecalculatedOn` is absent. There is no handoff-date
  preservation guarantee in that method. Setting this marker alone would not
  prove that every subsequent repayment, reversal or COB respects the boundary.
- `fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/service/LoanScheduleService.java`:
  `recalculateScheduleFromLastTransaction` regenerates schedules and reprocesses
  transactions; its recalculation branch also revisits charges.
  `LoanWritePlatformServiceJpaRepositoryImpl#recalculateInterest` additionally
  reprocesses existing accruals. Activation must account for all these effects.
- `tools/arissto-sync/arissto_sync/loans.py`:
  current historical plans require recalculation false, reject product
  enablement, and treat an enabled historical loan as a conflict. A future
  activation needs an explicit recorded servicing phase so retries/resumes do
  not treat the intentional transition as drift or replay history afterward.
- Mifos `src/app/loans/loans-account-stepper/loans-account-terms-step/loans-account-terms-step.component.html`
  displays the recalculation flag and inherited settings. Inspection of the
  edit flow found no existing active-loan activation control. Any operator
  activation UI would be a separate implementation.

## Existing servicing alternative

[October 28 repaired servicing acceptance](recalculation-off-servicing-repair-oct28.md)
records scoped local API/COB evidence that migrated loans already earn future
ordinary interest on actual principal, with early/on-time/late payments,
interest pauses and waivers, while the standard flag remains false. That is
custom Credesal servicing, not native schedule recalculation enablement.
It does not prove portfolio-wide readiness or arbitrary historical reprocessing.

Thus a changing daily interest amount does not itself require this standard
flag. If the requirement explicitly includes native future schedule
regeneration, the existing custom servicing acceptance does not satisfy it.

## Proposed implementation boundary, not an approved operating procedure

Create a dedicated audited, idempotent backend activation command and a
separate reviewed sync handoff phase. Preserve loan IDs and imported history.
Initialize the loan configuration and necessary calendars atomically; define
how native recalculation and the existing migrated-loan interest baseline
interact, so ordinary interest is not generated twice. Product settings must
remain compatible without invalidating historical import contracts.

Use both accounting dates explicitly: **Arissto through** is inclusive `S`;
**Fineract starts** is `T = S + 1 calendar day`, America/El_Salvador. No actual
date is selected by this investigation. Activation needs an explicit effective
boundary and opening state, preserving source-owned history through `S` and
allowing only the agreed prospective effects from `T`. Merely backdating a
recalculation calendar is insufficient evidence of that isolation.

The smallest useful proof is a disposable namespaced loan imported with the
flag off, reconciled, then activated through the proposed command. Compare
historical transactions, component allocations, schedules, charges, balances
and GL before/after activation and after the first repayment and COB. Cover a
mid-installment boundary, early/late/partial payments, arrears, debt insurance,
pauses, waivers and repeated activation. Define explicit handling or rejection
of reversals/backdated transactions crossing the boundary. Closed loans should
remain untouched. Expand to a representative migrated cohort before any bulk
operation; no full-portfolio feasibility claim follows from static inspection.

The [historical activation record](interest-recalculation-default.md) explicitly
marks post-handoff activation as a separate future capability. This note
investigates that capability and does not supersede the migration contract.

For upstream context, see Apache's
[interest recalculation design](https://cwiki.apache.org/confluence/spaces/FINERACT/pages/66852838/Interest+Amount+Recalculation+for+Loan+Accounts).
The local checkout remains authoritative for the conclusions above.

## Subsequent servicing proof

The [October 30 three-source-event canary](source-event-recalculation-off-canary-oct30.md)
passes in local `default` with the standard flag off: early/late principal
repayments change earned interest while future contractual forecasts remain
unchanged. It is a bounded synthetic servicing test, not an existing-loan
activation implementation or full source-history replay.

## Full-history progression follow-up

The separate [October 30 full-history handoff canary](full-history-interest-mora-progression-oct30.md)
represents all 21 retained source repayments and 16 daily progression dates.
Native accrual/accounting checks pass, but exact source progression fails:
2647 changes cash allocation after handoff, and mora differs on both delinquent
loans. Earlier adapted-event acceptance is not source-equivalent servicing
acceptance. Historical allocations remain preserved; no runtime repair or
recalculation activation was made.
