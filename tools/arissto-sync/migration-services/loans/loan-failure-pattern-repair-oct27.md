# Loan failure pattern repair — October 27

The failed historical-off full workflow exposed two shared integration problems.
Interest recalculation remains explicitly false for products and loans.

## Final metric scope and observation validation

Final metric alignment applies only to loans whose frozen Arissto state is `1`
(active). Source-closed (`3`) and pending (`2`) loans skip metric target freezing,
metric snapshot completeness quarantine, and migration-metrics reads and writes
in both apply and reconcile. Native status alone cannot establish eligibility:
a source-closed loan can temporarily remain native Active during replay.
An eligible loan must also be native Active before adjustment; other statuses
fail rather than silently skipping an active source account. Closure, complete
source history, amounts, identity and accounting-boundary reconciliation remain
required for every eligible imported history.

`final_metric_alignment_policy=source-active-only-v1` changes the service
contract hash, and final-metric plan revision 2 rejects previous immutable child
plans. Supported workflow resume can discard an old child plan when the contract
hash changes and generate a new one under the same source/accounting boundary.

The old reconciliation parsed raw native observations as valid target vectors.
That aborted the entire service when derived due principal exceeded outstanding
principal. Read-only inspection of the failed cycle found all 31 instances on
source-closed loans. Raw observations now require a complete finite currency
vector; targets still require nonnegative amounts and due principal no greater
than outstanding principal. The exact observed vector remains the optimistic
concurrency token in Python and native alignment. Readback and continuation
baseline checks remain strict; malformed observations become blocking per-loan
reconciliation findings without abandoning the rest of the report.

## Historical office-transfer phase

A fully repaid source-closed account can retain native future schedule interest
until the complete-plan final-correction barrier. Previously the client transfer
required native active inventory to equal source active inventory, and the
historical-off path correctly refused the old early finalization workaround.
This produced one failed cohort root and seventeen dependency-blocked actions.

The guarded source-exact transfer now accepts explicit `deferredClosedLoans`
proofs generated from the frozen loan actions. Python requires source state 3,
zero source principal, a dated terminal repayment matching the planned closure,
every source event before the transfer boundary, complete native history
readback, same native client and paid native principal. Native Fineract separately
validates the Arissto identities, recalculation-off flag, paid principal, an
unreversed native terminal repayment on the exact date, and absence of later
native activity at/after transfer. Missing, duplicate, cross-client or overlapping
proofs fail the exact inventory check. Every other native active loan must be
present in the source transfer balances. Proven source-closed loans keep their
historical office and receive no branch transfer transaction pair.

This changes no loan balance and posts no early credit, waiver or terminal
correction. The global replay/readback barrier still precedes final closure
corrections. Ordinary operational client transfers keep their existing behavior.

## Evidence and remaining acceptance

The previous run and its evidence are linked from
[the progress tracker](loan-sync-updates-progress-oct27.md).
Read-only checks against that failed sandbox verified the three closure proofs
at its first failing office transfer. Later incomplete cohorts still fail the
proof readback, as required, until their source history is replayed.

430 focused Python tests pass, including active/closed metric scope, raw-versus-
target validation, final barrier ordering, closed-source transfer proofs and
unowned active inventory rejection. Eight native FinalLoanMetrics,
FinalLoanMetricAlignmentService and deferred-closure transfer tests pass.
Native provider compilation also passes. Complete workflow acceptance remains
pending the controlled resumed run; these checks do not establish migration
acceptance or authorize scheduler release.


Implementation commit: `ad32e90e4827fcf8b7fb4069d1759c71c093e4b1`.
Durable change-tracker entry 48 includes all 2,752 source loan identities and
existing native IDs where known. The pre-resume cycle database was backed up
under the cycle evidence directory before the guarded backend reload.
The supported resume targets the same workflow run
`e942a4ece71b4833b478a265b4296159`, local `sandbox:fineract_sandbox`, retaining
**Arissto through 2026-10-26 / Fineract starts 2026-10-27**. The changed contract
hash requires a fresh immutable child loan plan; the old child is not replayable.
The scheduler remains subject to the guarded pause verification on reload.

Mifos account details still read `loanDetails.isInterestRecalculationEnabled`
and conditionally display recalculation fields; this repair introduces no new
frontend field or activation flow.

## Resumed full-run evidence and cashless-refinance barrier repair

The resumed plan `75aa8b92014c4995ab88a2b30bc4239f` is applicable. Its executable
scope is 2,288 loans: 429 source-active, 1,850 source-closed and 9 pending.
It retains 464 quarantines. Twelve closed histories previously quarantined only
for a missing metric snapshot became eligible; their financial history guards
remain. The plan also retains 77 quarantined active metric snapshots as evidence,
so counting all 506 frozen target vectors overstates executable metric scope.

All four historical office transfers completed and matched native proposal and
acceptance records. Eleven source-closed histories were excluded with validated
proofs, and none received loan transfer postings. All 2,288 eligible histories
replayed without action failures. The subsequent complete readback rejected one
fully cashless refinancing representation and deferred all 2,288 final corrections.
No terminal correction or metric-alignment rows were posted.

The readback bug was generic: `_find_reconciliation_transaction` can return a
refinance transfer as an alias for a disbursement when there is no cash remainder.
The barrier then added that same transfer again. It now resolves the exact cash
external ID for refinances, permits its absence only when the independently
verified settlement sum represents the complete source gross, and counts every
transfer once. Positive cash, multiple predecessors, missing cash and excess
cash are covered by regression tests. No native transaction needed changing.
Read-only verification of the actual cashless native representation now passes.

The failed child run `9e234c07a4f94980b715a0bb9568ef66` saved an official full
reconciliation rather than aborting on the old metric invariant. It records
1,858 inactive metric skips (the failed cashless closed action is excluded from
that loop) and 429 active comparisons. Its financial/status/term differences
remain blocking because final corrections were intentionally deferred. These
are not accepted variances. The runner is terminal before the verifier change.

The expanded Python suite passes 432 tests. The next supported same-cycle resume
can retry the failed refinance dependency scope under the same immutable child
plan, then revalidate the entire 2,288-history barrier before any final correction.


## Final attempt and source-outage boundary

The cashless repair passed the entire 2,288-history native barrier. Final
correction run `84feecf5f7574b9c9b89e48fd5d15e37` finished with 30 failures in
three shared patterns: 11 historical closure adjustments rejected before the
client's later office transfer, 8 expected-maturity/selected-account conflicts,
and 11 insurance-template identity mismatches. Its guarded alignment reconciled
418 active loans (384 changed); native alignment rows for closed/pending loans
are zero. Native readback still shows 2 off products and 2,288 off loans, zero
interim refinance credits, zero imported source movements on/after October 27,
and a paused scheduler. The full migration is not accepted. The
[sanitized run report](investigations/loan-pattern-repair-resumed-result-oct27.json)
records counts, exact source IDs and target IDs without financial amounts.

After the user reported possible Arissto downtime, one read-only `source-check`
failed with an OperationalError timeout. Fresh source comparison stopped. No
new sync/retry or guarded backend reload was launched after that observation.
The already-running attempt completed its target-only finalization and exited.
Current source availability has not been rechecked since the timeout.

### Local-only repairs, not runtime acceptance

The terminal-adjustment handler now establishes a scoped context under the
existing authenticated operational-migration permission. The native guard
requires exact source loan/adjustment identities and an ACTIVE accounting cutoff
with the adjustment strictly before Fineract ownership. An earlier office date
is permitted only for an off-mode, source-exact goodwill terminal adjustment on
a paid-principal loan, with an unreversed source repayment on that exact day,
no later unreversed native activity, and an unambiguous chain of accepted native
client transfers reconstructing the loan's historical office. Ordinary repayment
and office-date validation remains in effect outside that proof.

During this guarded off-mode balance refresh, a valid selected contractual
expected maturity remains unchanged. The legacy schedule endpoint must not
silently replace the already selected source contract and trigger the entity's
366-day-account reclassification invariant. The original invariant still rejects
ordinary expected-date revisions; it is not disabled, cleared or reclassified.
Mifos general/account details display the native expectedMaturityDate directly;
its field meaning and labels are preserved and no frontend input was introduced.

The local retry adapter previously used sticky replay successes: all 30 later
correction failures disappeared from its retry roots. It now uses the latest
attempted outcomes. A blocked, unattempted row cannot erase a failed root;
blocked dependants remain visible for dependency closure. The complete replay
barrier keeps its actual-latest view and cannot treat a blocked loan as complete.

433 Python and 22 Java tests pass. The native test set exercises guarded office
history, source-date and identity rejection, unchanged ordinary reclassification,
contract date preservation, and scope cleanup. A stale reversal-handler test
stub was updated to the existing source-exact reversal method; reversal runtime
behavior was not changed. These repairs were made after the writer exited and
remain pending controlled runtime validation. No source-dependent insurance
mapping change was made.

### Remaining work after Arissto becomes reachable

Compare the 11 frozen insurance templates against dated source insurance
snapshots before changing their basis. Preserve **Arissto through 2026-10-26 /
Fineract starts 2026-10-27**, immutable plans, native transaction ownership and
the same disposable sandbox lifetime. Do not edit a saved financial plan in
SQLite. If a financial template changes, generate the supported replacement
child plan through the workflow control plane. Then use a reviewed same-cycle
resume with guarded native reload to validate the local terminal repairs and
finish strict loan reconciliation. Do not release the scheduler or mark this
migration accepted from unit tests or partial correction counts.


Local-only implementation commit:
`a8b32b22557804979c190016619649d874866033`; durable tracker entry 50 covers
all 2,752 source identities and existing native IDs. Read-only inspection of the
preserved retry chain now exposes all 30 failed roots, where the earlier sticky
view exposed zero. No recovery execution was performed to verify that selection
against the target while source comparison is unavailable.
