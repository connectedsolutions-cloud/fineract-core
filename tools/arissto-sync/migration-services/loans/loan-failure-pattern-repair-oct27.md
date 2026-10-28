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

390 focused Python tests pass, including active/closed metric scope, raw-versus-
target validation, final barrier ordering, closed-source transfer proofs and
unowned active inventory rejection. Native FinalLoanMetrics,
FinalLoanMetricAlignmentService and deferred-closure transfer tests pass.
Native provider compilation also passes. Complete workflow acceptance remains
pending the controlled resumed run; these checks do not establish migration
acceptance or authorize scheduler release.
