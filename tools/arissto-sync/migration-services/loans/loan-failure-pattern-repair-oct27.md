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
present in the source transfer balances. Proven source-closed histories receive no branch transfer transaction pair;
their original native transactions retain their recorded offices.

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
A subsequent connection-only recheck also timed out; no source comparison or
sync/retry was resumed.

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


## Local native-model audit after the source timeout

Read-only inspection confirmed that `Loan.getOfficeId()` and `Loan.getOffice()`
follow the client's current office. There is no persisted `m_loan.office_id`.
The first terminal guard therefore compared the reconstructed historical office
with the wrong native property, and its original mock allowed an impossible
loan/client office combination. The guard now resolves the office recorded on
the unreversed source terminal repayment, proves it against accepted client
transfer history, and constructs the new terminal credit using that exact office.
Conflicting terminal receipt offices are rejected. The client and its current
office are not changed. Ordinary repayments continue using the current office.

The updated native tests reproduce a current client/loan office different from
the historical repayment office and require the historical office object to be
returned; they also reject ambiguous receipt offices. The provider's seven
focused tests pass. A separate read-only local audit confirms every guard
precondition across all 11 office-date cases and confirms valid selected source
contract dates differing from the legacy schedule endpoint in all 8 maturity
cases. Its [19-case predicate evidence](investigations/loan-local-terminal-preconditions-oct27.json)
contains stable IDs and booleans, without financial amounts. This is local
precondition evidence, not completed runtime acceptance.

All 30 failed-action native IDs were enriched from exact local loan external
identities; the same known IDs were restored in durable tracker rows whose
later failure records had omitted target IDs. The insurance templates remain
unchanged, and the later Arissto connection-only recheck also timed out. No
source comparison, sync/retry, tenant reset or guarded native reload followed it.


Historical receipt-office correction:
`05767a0399a944a8002695883504261ae73c6bb3`, durable tracker entry 51.
It covers the shared terminal guard and preserves the other local repairs from
entry 50. Runtime acceptance is still pending; the local audit never writes to
Fineract or reads Arissto source data.


## October 28: source recovered and insurance basis confirmed

A fresh Arissto connection/permission check passed with the read-only login.
Read-only comparison of all 11 insurance failures confirms the same pattern:
each frozen metric target equals the October 26 daily snapshot, while every
opening-charge template equals the newer current CRD_CARTERA insurance balance.
All 11 current-header amounts differ from their dated snapshots. The
[boolean-only source comparison](investigations/insurance-source-contrast-oct28.json)
records stable source IDs and proof predicates without financial amounts.

Opening insurance now uses the dated snapshot balance and source status, just
like final metrics. A zero source-day balance does not import a later current
header charge; a positive source-day balance still gets an opening template if
the current header has since become zero. The policy is explicit in the service
contract as `cutover_insurance_balance_policy=dated-source-snapshot-v1`. Changing
that contract hash makes supported workflow recovery discard the old child
plan and generate a replacement under the same accounting boundary. Saved
financial plans are not edited. Recalculation remains false and metric alignment
remains restricted to source-active/native-active loans.

The requested final validation is a resumed sync in local sandbox, retaining
Arissto through 2026-10-26 / Fineract starts 2026-10-27. The native historical
terminal fixes also require the documented guarded backend reload before the
next attempt. Native and source read-only checks verified the exact sandbox
database, active matching cutoff, paused scheduler, 2,288 off-mode loans and
no active workflows before the recovery action.


## October 28 — preserve accepted baselines when replacing a child plan

The dated insurance contract invalidates the old child plan, so resumed planning
can revisit previously aligned active loans. Native final metric alignment
deliberately replaces historical schedule projections with a continuation
baseline. Reinstalling the original source schedule would undo that state.

A recovered source-active historical-off loan now takes a read-only recovery
path only after native alignment identity/version/continuation, all eight frozen
metrics, the complete frozen event/reversal/refinance history, selected term GLs
and dates, and any opening insurance baseline all pass. Initial unaligned loans
continue normal replay; inactive source loans never invoke metric recovery.
Drift fails closed before schedule reinstall or provisional term reset. Final
portfolio history and reconciliation gates still run after recovery.

The enforced GET-only audit passed **418/418** existing baselines (19 generated,
380 variable, 12 active exact and 7 remaining-schedule writers). Focused engine
regressions passed **311 tests**, including 9 new read-only recovery tests.
The broader 961-test suite reports 14 failures and 12 errors in penalty replay,
remaining-schedule fixtures and the savings minimum-balance expectation. All
26 outcomes reproduce against the committed pre-change runtime in memory; they
are not accepted as a passing broad suite. Runtime acceptance remains pending
the resumed workflow. See [read-only evidence](investigations/aligned-historical-recovery-readonly-oct28.json).


## October 28 — final apply accepted; continuation reconciliation correction

Loan child plan `7d8308469e774c8db104850ece10d9b8`, run
`a0fce5b52e544fad901318f4b98fd0cc`, recovered all 2,288 eligible loans with
zero failed items and 464 planned quarantines. All 429 active metric vectors
and accrual controls reconciled; 1,859 inactive loans skipped metrics. Nine
metric writes were needed. The 11 insurance cases and 19 terminal cases all
passed independent GET-only history, selected-term and native-state checks.
Native evidence: 429 active baselines, zero inactive metric rows, 1,718 terminal
adjustments, zero interim refinance credits, zero on/after-boundary source
movements, recalculation off on both products and all 2,288 loans, scheduler
paused. Dates stay **Arissto through 2026-10-26 / Fineract starts 2026-10-27**.

The workflow nevertheless stopped in loan reconciliation: 33,219 original
settlement-schedule comparisons treated the approved final continuation
projection as an exact copy of the pre-alignment source schedule. No other
blocking mismatch kind was present. The source calendar and future forecasts
remain strict requirements where the frozen policy requires exact schedules.

The corrected read-only validator separately checks one additional baseline
at S, native active/off flags, matching metric identity/version/continuation,
latest persisted source-day and target/after audit, all final principal
projections, paid baseline amounts, absence of unearned collectible interest,
nonnegative components, chronological contiguous installment numbers, absence
of additional future rows, exact contractual calendars and future forecasts.
The existing 19 reviewed reference-policy exceptions remain disclosed; they
do not exempt native structural or monetary invariants. Historical supplementary
rows are distinguished by their persisted additional flag and must be pre-T.

Only after that full proof are original schedule differences classified as
`verified_final_continuation_schedule_variance`. A missing or corrupt baseline,
calendar, forecast, audit or metric remains blocking. Other repayment, reversal,
refinance, ownership, term, collateral, staff, accrual and accounting checks
remain unchanged. No target financial state is changed by this validator.

Read-only structural acceptance passed 429/429 native schedules. This structural
audit reused frozen metric targets as inputs and does not claim to replace the
official native metrics API checks. Focused regressions passed 329 tests, with
18 continuation tests and corruption controls. Official reconciliation must be
rerun before the workflow or these changes are accepted.

Evidence: [insurance/terminal native proof](investigations/insurance-terminal-native-recovery-oct28.json),
[continuation structure](investigations/continuation-schedule-structure-oct28.json).


## October 28 — official loan reconciliation accepted

Workflow attempt 5 reused completed child run `a0fce5b52e544fad901318f4b98fd0cc`
without another loan replay or backend reload. Official reconciliation passed
**zero blocking mismatches**, all 2,288 eligible loans and 429 continuation
schedules. It retained 38,644 disclosed schedule/reference variances, including
37,315 differences validated as final continuation projections; this acceptance
is not exact parity with the original settlement schedule. All 429 active
accrual controls, four office transfers, 259 guarantor relationships, 34
collateral assets and 2,288 staff/mora assignments passed. The 464 quarantines
remain explicit, and 1,859 inactive loans skip metric methods.

Durable change records 48–54 are resolved for the loan recovery scope. The
whole 18-service workflow is still pending; downstream services proceed only
after this accepted loan gate. See [accepted reconciliation summary](investigations/loan-recovery-reconciliation-accepted-oct28.json).
