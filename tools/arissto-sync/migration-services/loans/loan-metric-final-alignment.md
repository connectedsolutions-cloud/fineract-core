# Final loan metric reconciliation

**Live COB follow-up — 2026-10-26:** [the two-loan canary](pause-cob-canary.md)
passed six frozen days on source 1826 but found a post-baseline interest jump
and a mora adjustment failure on source 1572. Resume-boundary/no-catch-up
acceptance and a fresh recalculation-enabled replay remain unverified. The
point-in-time and unit checks below do not establish safe continued operation.

## Approved use — 2026-10-26

Implemented in the local working tree and verified against the disposable local
`sandbox` tenant. The final step is part of the existing loans service, not a
separate registry service. No composed sync cycle or production deployment was
launched for this change.

The loans service runs the final step as follows: For each loan, finish all
existing applicable steps first, compare the loan metrics with the frozen
Arissto values, and invoke the appropriate migration-only metric adjustment
for every difference. Read the metrics again and finish only when they match.
Interest-recalculation activation remains independent of this work.

The [source metric inventory](../../../../../../credesal-db-space/docs/learnings/loan-historical-adjustment-events.md#loan-metrics)
owns definitions and source evidence. The
[project-global decision](../../../../../docs/ARISSTO_LOAN_ALIGNMENT.md#final-loan-metric-reconciliation--approved-2026-10-26)
owns the scope. This document owns the service step and method requirements. Versioned
Liquibase and backend sources own definitive schema and persistence behavior.

The accompanying [accrual-control contract](loan-accrual-controls.md) covers
ordinary-interest and mora pause/resume state. The final pass verifies those
controls before correcting monetary targets; monetary equality does not prove
correct accrual state.

## Execution sequence

1. Complete the current loan creation, source schedule installation, historical
   replay, reversals, refinancing/settlement, charges, freeze/control history,
   accrual catch-up, term/account selection and any other existing applicable
   steps. Include dependency operations that can still mutate this loan: a
   successor's refinance must not change a predecessor after final alignment.
2. Load the frozen source metric targets for that same loan and boundary.
   Display **Arissto through** inclusive day `S` and **Fineract starts**
   `T = S + 1 calendar day`. Compare target state at that boundary; do not compare
   source accrued interest with native unearned future schedule interest.
3. Read the current Fineract metrics. Equal values require no adjustment.
   Differences covered by this step are inputs to correction, rather than
   reasons to reject the loan before this final step can run. Existing unrelated
   identity, history-integrity and accounting guards remain applicable.
4. Select the corresponding method for each difference. Apply the necessary
   methods in dependency order; a grouped method is acceptable for coupled
   metrics. Commit the loan's alignment atomically so a failed method cannot
   leave only part of its metric set adjusted.
5. Read all metrics back through the normal native read/calculation paths.
   Require equality at currency precision, including any metrics affected
   indirectly by another adjustment. Record source, before, target, after and
   method outcome. Unmatched values, missing source observations or unsupported
   adjustments make final reconciliation incomplete; never substitute zero.
6. Mark the loan's final metric reconciliation complete. Do not schedule another
   historical replay, schedule replacement, reversal, recalculation or other
   existing sync mutation after this final pass for that loan. If one is later
   required, repeat the final comparison/adjustment step after it finishes.

A failed earlier step must finish before metric alignment; final corrections
must not disguise an incomplete loan import. There is no new requirement to
reconstruct the precise historical manual event responsible for every residual
metric difference before applying a final migration-state correction.

## Required adjustment coverage

Each method must accept an absolute target amount and support both increase
and decrease, including zero, within the metric's valid domain. The writer
computes and records the difference; repeated execution against an already
matching target is a no-op. Validate the observed pre-adjustment state so a
stale request does not overwrite an intervening change.

| Metric | Required final adjustment effect |
| --- | --- |
| Paid principal | Align the final cumulative paid-principal value without creating a fictitious collection. |
| Outstanding principal | Align remaining collectible principal. Coordinate changes with due principal and the applicable principal baseline. |
| Paid ordinary interest | Align the cumulative paid ordinary-interest value, separately from accrued interest and mora. |
| Outstanding accrued ordinary interest | Align collectible accrued interest through `S`, upward or downward; exclude unearned future interest. |
| Due principal | Align the principal already due through `S`, with a valid remaining-principal distribution; keep `0 <= due principal <= outstanding principal`. |
| Outstanding accrued mora | Align the carried unpaid mora obligation, separately from ordinary interest and insurance. |
| Insurance paid | Align cumulative insurance settled/paid, separately from the outstanding insurance obligation. |
| Outstanding insurance | Align insurance owed at `S`; exclude unissued future recurring insurance. |

These are coverage requirements, not a requirement for eight public endpoints.
A shared service may group related updates. Existing methods can be reused
where they satisfy this contract; missing capabilities need sync-only methods.
Current public repayment, waiver, goodwill or write-off semantics must not
force a final migration-state correction to masquerade as one of those events.
Represent any required opening/settlement baseline correction explicitly as
migration state, with an audit record distinct from imported cash movements.
The storage choice must serve the native metric reads and calculation inputs;
a separate comparison-only number or temporary API response override is not
sufficient. Paid totals are permitted alignment targets in this final step;
independent paid-counter setters being absent today does not remove that need.

<a id="method-readiness"></a>

## Implemented adjustment methods — 2026-10-26

All eight metrics use one atomic migration-only operation:
`POST /v1/loans/{loanId}/migration-metrics`. A companion `GET` reads the native
metric vector for `cutoffDate=T` and the two selected insurance definition IDs.
The previous readiness assessment is superseded by the implementation below.

| Metrics | Native correction used for increase/decrease/zero |
| --- | --- |
| Paid, outstanding and due principal | Native installment completed/outstanding amounts and a separately marked additional migration baseline row. A credited-principal baseline reconciles original principal, paid and remaining principal without a cash transaction. Due principal retains existing past installment weights; remaining non-due principal retains future installment weights and dates. |
| Paid and outstanding accrued ordinary interest | Native paid interest and an opening accrued-interest amount on the migration baseline row. The boundary-spanning installment retains only its unearned remainder from `T`; future ordinary interest stays in the native schedule. |
| Insurance paid and outstanding insurance | Identified insurance charge/installment amounts, coordinated with a dated flat migration baseline charge. Future installment charges retain their not-yet-due outstanding state. |
| Outstanding mora | Native penalty charge amounts and a separate dated migration baseline penalty, preserving paid penalty amounts. |

These corrections change the final native settlement projections. Imported loan
transaction identities, amounts and allocations remain untouched. The baseline
row is explicitly additional and `migration_metric_baseline=true`; it is not a
customer repayment. All normal native summaries and charge/schedule reads use
the corrected state. Native arrears aging is refreshed at `S` as part of the
same transaction. Paid insurance uses selected insurance charge identities,
not total fees paid.

### API guards and audit

The POST requires exact fields: `sourceSystem=ARISSTO`, `sourceLoanExternalId`,
`cutoffDate`, `sourceObservedAt` (ISO offset timestamp), `requestId`,
`insuranceChargeId`, `recurringInsuranceChargeId`, `penaltyChargeId`, and full
`expected` and `targets` vectors. The eight keys are `paidPrincipal`,
`outstandingPrincipal`, `paidInterest`, `accruedInterest`, `duePrincipal`,
`mora`, `insurancePaid`, `insuranceOutstanding`.

It requires `USE_ARISSTO_OPERATIONAL_MIGRATION`, the exact active accounting
boundary, matching imported loan identity, compatible active charge definitions
and currency, and an eligible originated lifecycle. It locks the loan and
boundary, rejects stale expected values, rejects native disbursement/repayment
activity on or after `T`, validates nonnegative currency amounts and
`duePrincipal <= outstandingPrincipal`, and rejects a collectible balance on
a non-active loan. Non-due principal requires an existing future contractual
due date; the method does not invent an extension to represent an invalid
schedule. Existing unrelated import guards continue to apply.

`credesal_loan_metric_alignment` stores before/target/after vectors, source day,
observation timestamp, request hash and actor. The `(loan_id, request_id)`
identity is unique. An identical repeated request returns `alreadyApplied`;
changed payload or drift under the same identity is rejected. The GET returns
`alignmentVersion` from the latest audit row; the sync client includes it in
request identity derivation, allowing a later final pass to repeat an earlier
transition after intervening adjustments. Native linked
journal rows are compared before/after inside the transaction; any change
rolls the operation back. The method invokes no accounting writer, transaction
processor, loan transaction creator or business-event notifier.

### Sync integration and source completeness

Loan plans now carry `component_alignment_plan_revision=9`,
`final_metric_alignment_revision=1`, `accrual_control_revision=1`, a plan-level `source_observed_at`, and a
per-loan frozen target/definition descriptor. Older plans must be regenerated.
Preflight requires the versioned alignment table and native schedule marker.

The source reader freezes the latest committed dated snapshot: an active loan needs
an exact `S` snapshot; a terminal historical loan may use its latest
prior snapshot. COB closure status is observation evidence, never an eligibility gate; saved
snapshots reflect source commits visible at the recorded observation time.
Missing required counters are quarantined as
`missing_final_metric_source_snapshot`, never converted to zero. Outstanding
principal uses dated disbursement less dated paid principal. Ordinary interest
uses `SALDO_INTERES` without adding pending interest again. Existing approved
mora/recargo and closed-insurance classification policies remain applicable.

Insurance paid prefers `SALDO_PAGADO_SEGURO`. When it is null, a legacy
`SALDO_PAGADO_OTROS` fallback is accepted only if it equals this loan's net
identified insurance allocations after reversal handling. A differing or
missing counter needs source evidence; the five zero-valued source observations
do not establish that every legacy other-paid amount is insurance.

The final coordinator runs after all loan workers, client transfers and refinance
components finish. It processes only successful loans, including retained or
unchanged loans, so retry can repair a failed final pass without replaying
successful history. Existing standalone balance-only mora opening and insurance
rebase are bypassed when the grouped final correction owns those targets.
Errors are recorded as `final_metrics:` failures and prevent run success.
`reconcile_loans` independently reads and compares the eight frozen metrics.
An earlier mutation must finish before the final pass is repeated.

### Implementation evidence

- [Native metric reader and correction](../../../../fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/domain/FinalLoanMetrics.java).
- [Transactional migration service](../../../../fineract-provider/src/main/java/org/apache/fineract/portfolio/loanaccount/service/FinalLoanMetricAlignmentService.java) and [API](../../../../fineract-provider/src/main/java/org/apache/fineract/portfolio/loanaccount/api/FinalLoanMetricAlignmentApiResource.java).
- [Versioned schema](../../../../fineract-provider/src/main/resources/db/changelog/tenant/parts/0436_final_loan_metric_alignment.xml).
- [Sync vector/transport](../../arissto_sync/loan_metric_alignment.py) and [final coordinator](../../arissto_sync/loans.py).
- [Domain tests](../../../../fineract-loan/src/test/java/org/apache/fineract/portfolio/loanaccount/domain/FinalLoanMetricsTest.java), [service tests](../../../../fineract-provider/src/test/java/org/apache/fineract/portfolio/loanaccount/service/FinalLoanMetricAlignmentServiceTest.java) and [sync tests](../../tests/test_loan_metric_alignment.py).

### Verification performed

Local target fingerprint `b9f6834b66790744`, disposable `sandbox` tenant:
**Arissto through 2026-10-19; Fineract starts 2026-10-20**.

- Source loans `2612`, `2647`, `2581`, `2597`, `2593` on native proof loans
  `2755`, `2757`, `2759`, `2761`, `2763`: all 40 frozen source metrics matched.
  Normal native API principal, paid interest, accrued-interest schedule and due
  principal reads agreed. Repeated sync calls made no further correction.
  Entire global GL and selected transaction-row fingerprints were unchanged.
  These five proof products have accounting disabled; this evidence alone does
  not establish behavior with accounting enabled.
- Separate native proof loan `2766`, periodic accrual accounting (`accountingRule=3`)
  and interest recalculation enabled: all eight targets increased, decreased
  and reached zero. All 24 comparisons passed; repeated calls were no-ops;
  entire global GL and that loan's transaction-row fingerprints stayed unchanged.
  Synthetic targets test capability and are not source parity evidence. Direct
  repeated POSTs returned `alreadyApplied`; stale expected-state requests were
  rejected without mutation; repeating an earlier transition after intervening
  adjustments also succeeded.
- 62 selected Java tests passed (54 domain/replay/insurance-validation tests,
  eight provider alignment/insurance-rebase tests). The focused Python loan
  suite passed (236 tests); a focused staged version excluding unrelated local
  mora/freeze edits independently passed 220 tests; the full suite ran 849 tests with four unrelated existing
  failures (native override inventory, Vista minimum balance, workflow service
  count, and share-selection employee dependency).
- Two Mifos read-back tests passed: normal general-tab native metrics and
  repayment-schedule correction rows used for display/export. Existing fee,
  penalty and principal/interest fields retain their normal English/Spanish
  labels, search/list semantics and forms. The migration setter has no ordinary
  user edit form. No new UI amount field or separate comparison-only balance
  was introduced.

Immutable local manifests/results are under
`.arissto-sync/final-loan-metric-proofs/`: source proof
`3eb1362bfab0eddd38fddf67ebdfed7c6a1736d6d7b7472ef0eda083c6883599.json`
and its result; `accounting-enabled-edge-plan.json` (SHA-256
`320b9864d3df2dfbcb719b72a9d964da762c560f0cf8827fd3fdb56e59e07634`)
and its result. They remain local operational evidence, outside Git.

## Accounting and execution boundary

All adjustment methods are restricted to the sync/migration flow and reuse the
permission-controlled operational migration context. They must create **zero
GL postings**, reverse no existing GL postings and change no existing journal
entries. Arissto historical GL remains owned by the separate accounting import.
The audit of a metric correction is operational evidence, not a journal entry.
Future normal Fineract accounting retains its usual ownership from `T`.

Inputs include loan/source identity, frozen source observation and boundary,
expected current state, requested target amounts, and a stable request identity.
Keep a durable, non-sensitive audit of each actual change. No ordinary user
balance-edit control or production enablement is implied by these requirements.

## Deliberately limited persistence requirement

The methods run **at the very end**, after all current sync work affecting the
loan. They are not required to preserve their changes through a later schedule
recalculation, transaction reprocessing, reversal or replay. Do not add generic
replay-resistant adjustments, reconstruction of every manual historical edit,
or post-adjustment reversal/recalculation canaries as prerequisites for this
version. A later history-changing operation invalidates the final reconciliation
checkpoint and requires another final pass; it need not preserve the earlier
correction automatically.

This does not remove the purpose of handoff: the persisted final state must be
readable by native operations and usable as the starting state for continued
loan operation. It does not require durable preservation through arbitrary
future recalculation or reversal. Normal operations remain enabled; operational
calculation inputs such as rates, dates and freeze state retain the existing
loan setup and are not new amount targets in this first version.

## Acceptance evidence for implementation

- For each metric, test target above current, below current, zero where valid,
  and already equal. Use the native read path for the final check.
- Test a loan with multiple differences: all final targets must match together,
  without an unrelated metric silently drifting.
- Repeat the same final request: no duplicate adjustment, cash movement or GL.
- A failed/stale/invalid request leaves the loan unchanged; a resumed final step
  can complete without replaying successful earlier loan steps.
- Compare the relevant GL entries before and after every adjustment: zero added,
  updated or reversed entries. Preserve imported payment identities and amounts.
- Verify ordering places final alignment after the existing mutations and all
  dependency operations that can change the loan. After deliberately rerunning
  an earlier mutation, the final step must be eligible to run again.

Tests of surviving later recalculation/reversal are explicitly outside this
acceptance scope. No composed sync cycle was launched for this implementation verification.
