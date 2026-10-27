# Loan sync updates and progress — October 27, 2026

Working tracker for issue discovery, diagnosis, implementation and verified recovery. Keep observations separate from hypotheses, and preserve earlier evidence when updating a status. This document complements the [durable change tracker](change-log.md); implemented loan-sync changes must still be recorded there with commit and affected-loan evidence.

## Evidence baseline

Initial entries describe the preserved interrupted cycle `sandbox-2026-10-26-full-clean-a`, not a fresh live verification on October 27.

- Target: local `sandbox` / `fineract_sandbox`.
- **Arissto through:** 2026-10-26. **Fineract starts:** 2026-10-27.
- [Operator investigation](../../.arissto-sync/cycles/sandbox-2026-10-26-full-clean-a/operator-investigation.json), generated at 2026-10-26 20:40:16 America/El_Salvador.
- [Cycle state](../../.arissto-sync/cycles/sandbox-2026-10-26-full-clean-a/state.sqlite3): loan plan `8098f714e10b4363934545537026a714`; loan run `d48a6841f13c4c48ae6682cab2d9950a`; workflow run `2490d7f94fe841c196402e20bc1fa3aa`.
- Read-only pattern review of that state, frozen plan, backend logs, code and existing canary notes. No new runtime recovery or target reconciliation was performed for this tracker.

Counts are observations from this attempt. Representative loans use Arissto `loan:<ID>` source keys, not Fineract loan IDs. Rows can overlap; do not sum the table. Dependencies, quarantines, reporting problems and financial failures are separate categories.

## Issue groups and progress

| ID | Observed issue / pattern | Impact and representative loans | Status | Next evidence or completion check |
|---|---|---|---|---|
| LS-01 | Source-exact allocation leaves principal and interest unrepresented. | 42 failures; `loan:10`, `loan:1036`, `loan:1040`. | **Open — cohort identified.** Temporary schedule availability is a hypothesis requiring per-event tracing. | Reproduce first failing event; identify provisional recalculation versus final posting and available installments. |
| LS-02 | Source-exact allocation leaves principal, interest and fees unrepresented. | 24 failures; `loan:1024`, `loan:1117`, `loan:1180`. | **Open — cohort identified.** | Trace schedule availability and named fee-charge materialization independently. |
| LS-03 | Source-exact allocation leaves penalties only. | 72 failures; `loan:100`, `loan:1011`, `loan:102`. | **Open — separate penalty cohort.** Cause not yet established; not automatically rounding. | Verify penalty charge identity, charged/paid amounts, active visibility and recalculation behavior. |
| LS-04 | Source-exact allocation leaves principal and penalties. | 7 failures; `loan:1398`, `loan:1828`, `loan:1889`. | **Open — mixed cohort.** | Separate provisional principal handling from penalty representability. |
| LS-05 | Source-exact allocation leaves interest only. | 6 failures: `loan:936`, `loan:938`, `loan:964`, `loan:971`, `loan:972`, `loan:983`. | **Open — separate interest cohort.** These are not the six terminal-closure cases. | Capture interest availability and exact transaction/schedule chronology. |
| LS-06 | First frozen repayment precedes first frozen contractual due date; strongly associated with LS-01/02. | 47/66 combined LS-01/02 cases: 25/42 and 22/24; example `loan:10`. Comparison: 4/967 recorded succeeded loans. | **Discovery — association verified, causality unproven.** Overlaps LS-01/02. | Trace actual failing event and reversals; compare temporary prefix with full schedule. Interrupted execution order limits cohort interpretation. |
| LS-07 | Refinancing creation fails; preview path can flush an installment with null `loan_id`. | 8 create failures: `loan:103`, `loan:125`, `loan:139`, `loan:159`, `loan:172`, `loan:1784`, `loan:200`, `loan:283`. Constraint confirmed for 283 and 1784; remaining six generic HTTP 500s are candidates. | **Fix committed — isolated off/on reproduction and 55 focused tests passed; portfolio recovery pending.** Six generic HTTP 500s still need individual correlation. | Load repaired backend in a separately reviewed sandbox recovery; verify original application/disbursement flows and reconcile all eight successor loans. |
| LS-08 | EMI must exceed interest during transaction replay / schedule regeneration. | 9 failures: `loan:177`, `loan:300`, `loan:459`, `loan:516`, `loan:555`, `loan:771`, `loan:780`, `loan:781`, `loan:865`. Eight have planned terminal adjustments. | **Open — cohort identified.** Terminal-adjustment association does not establish the failing event. | Capture failing event and regenerated installment interest before changing amounts. |
| LS-09 | Fully paid, inactive historical insurance charge omitted from active charge collection causes false missing-charge refusal. | 6 failures: `loan:61`, `loan:372`, `loan:379`, `loan:651`, `loan:661`, `loan:815`. | **Fix committed; read-only verifier passed all six; workflow recovery pending.** Original process predated fix. | Load repaired code in an authorized recovery and require complete loan reconciliation. Commit/change evidence below. |
| LS-10 | Exactly one-cent terminal adjustment skipped by writer, leaving loan open. | 6 failures: `loan:1909`, `loan:2024`, `loan:2051`, `loan:2462`, `loan:2511`, `loan:2513`. | **Fix committed; regression tests reported passed; runtime recovery pending.** | Verify adjustment identity, exact amount, closed status and full reconciliation under repaired process. |
| LS-11 | Target maturity differs from frozen contractual maturity, potentially changing short-/long-term accounting classification. | 1 observed failure: `loan:999`; expected 2031-01-30 versus target 2025-12-28. | **Open — blocked by term-account guard.** | Trace schedule/creation overrides; preserve contractual dates and verify accounting class. |
| LS-12 | Loan dependencies propagate upstream failures. | 118 blocked loans; examples `loan:1014`, `loan:1017`, `loan:1038`. Failed ancestor `loan:894` has nine blocked descendants; `loan:18` has six. | **Blocked — all 118 trace to recorded failed ancestors.** Consequences, not 118 independent defects. | Link each blocked loan to causal root; verify dependency completion during authorized recovery. Descendant counts per root may overlap. |
| LS-13 | One office-transfer cohort failure blocks related loans. | 17 blocked loans; `loan:101`, `loan:115`, `loan:1274`. | **Blocked — cohort-level propagation identified.** | Retain actual root failure and verify the complete office-transfer timeline. |
| LS-14 | Partial refinancing-component failure blocks sibling component members. | 8 blocked loans; `loan:1178`, `loan:1482`, `loan:1897`. | **Blocked — component-level propagation identified.** | Repair root and reconcile the entire refinancing component. |
| LS-15 | Final-metric snapshot exists but insurance and surcharge targets are null. | 13 quarantined loans; `loan:5`, `loan:7`, `loan:21`, `loan:1262`, `loan:1562`. | **Quarantined — incomplete source evidence.** Missing values were not replaced with zero. | Establish complete, approved source targets; preserve quarantine until evidence is sufficient. |
| LS-16 | Other frozen quarantine reasons include historical freeze/terminal support, mora/schedule mismatch, remaining-schedule signature mismatch and reviewed omissions; refinancing propagates quarantine. | 165 quarantined loans total, including LS-15; 115 have chain-propagation reasons, 50 do not. Examples of named roots: `loan:1513`, `loan:26`, `loan:2427`. | **Quarantined / reviewed no-write policy — classify each reason separately.** Not every quarantine is an implementation bug. | Distinguish unsupported behavior, source errors and intentional reviewed omissions. There are 200 reason occurrences across 165 loans; counts overlap. |
| LS-17 | Apply guard reconstructed quarantine reasons differently from planner and aborted apply. | First observed on `loan:5`; guard failure affected the loan apply phase. | **Fixed — recovery passed guard.** Does not resolve incomplete source targets in LS-15. | Preserve planner/apply symmetry and frozen quarantine regression coverage. |
| LS-18 | Family-reference readiness rejected unmapped label `CUÑANA`. | One label among 2,056 reference rows; loan-level impact not established. Related prerequisite service. | **Recovered — 2,056 rows reconciled.** | Retain reviewed alias and tests; no outstanding recovery indicated by baseline evidence. |
| LS-19 | SIGTERM does not promptly stop queued loan workers because executor context exit waits for submitted futures. | Workflow-wide; representative loan count not established. | **Open — diagnosed; exact runner force-stopped in preserved attempt.** | Stop submission, cancel queued work, define active-write boundaries and persist/reconcile final outcomes. |
| LS-20 | DTE batch writer uses the same executor shutdown pattern. | Potential downstream DTE exposure; no observed affected-loan count in this cycle. | **Discovery — code-level analogous risk, not reproduced runtime failure.** | Include DTE batches in cooperative cancellation verification. |
| LS-21 | Parent and child status/summary disagree after interruption and earlier recovery. | One workflow: 11 latest completed services, one interrupted loan step, six blocked services; parent summary still says 10 completed / two failed. Loan child remains stored as `running`. | **Open — reporting inconsistency verified in preserved state.** | Recompute effective latest-attempt summary and consistently expose interrupted children. |
| LS-22 | Planned actions lack recorded outcomes; target creation differs from completed replay. | 1,293 of 2,752 planned actions have no item record. 970 succeeded items include three setup actions, leaving 967 succeeded loans; supplied target check reports 1,143 created loans. | **Open — incomplete outcome evidence.** Missing record does not prove no target write. | Reconcile stable target identities, transaction prefixes and mappings before retry; preserve original evidence. |
| LS-23 | Final metric alignment and first native COB cannot establish a complete handoff while replay/downstream financial services are incomplete. | Cycle-wide; final alignment not reached, six downstream services blocked, no first native COB recorded. | **Blocked — awaiting complete financial replay and reconciliation.** | Complete required services and opening metric reconciliation before first native COB. Do not mask incomplete replay with corrections. |

## LS-07 investigation — why this appeared after recent changes

### Conclusion and confidence

The recent change most strongly supported as the activation trigger is commit
`312edcb8129881722cc50529d6947615d2355f60` (**2026-10-26 13:09:58
America/El_Salvador**), which enabled daily interest recalculation for every
newly imported product/loan. Before that commit, product payload construction
explicitly set `isInterestRecalculationEnabled` to `false`.

This exposes an existing unsafe prepayment-preview path inside a loan-creation
write transaction. Git history, branch conditions and the captured failure
stack support this explanation. The follow-up below reproduced the defect with
recalculation off/on and a real EclipseLink flush on synthetic records, then
verified the repair. This is not a complete Git/runtime bisect or individual
correlation of all six generic HTTP 500 cases.

### Failure mechanism

1. Refinancing application validation calculates the predecessor loan's payoff
   using `retrieveLoanPrePaymentTemplate`.
2. With recalculation disabled, `fetchPrepaymentDetail` uses stored outstanding
   amounts. With recalculation enabled, it calls `calculatePrepaymentAmount`.
3. That calculator generates temporary installments, including installments
   constructed with a null loan reference, then retrieves persistent predecessor
   transactions from the repository and calls the normal mutating
   `reprocessLoanTransactions` method against the generated schedule.
4. The reprocessor does create a transaction copy for calculation, but when its
   component amounts match, it updates the **original persistent transaction's**
   repayment-schedule mappings from that copy. Thus copying the transaction at
   this step does not isolate the preview. Reprocessing can also reset the
   active charge paid state; safe preview isolation must cover charges too.
5. Transaction mappings cascade persistence to installments. A persistent
   transaction can consequently reference a new temporary installment whose
   `loan_id` is null.
6. After calculation, the read service fetches payment types. In the enclosing
   write transaction, that query triggers the ORM flush seen in the stack.
   PostgreSQL rejects the attempted schedule insert with a null `loan_id`.

The reported failure is on **creating the successor**, but the persistent state
at risk belongs to its **predecessor's preview**. This is not evidence that the
successor application omitted a required loan ID. Assigning a loan to temporary
preview installments would risk persisting preview state rather than repairing
calculation isolation. The existing read service already has
`@Transactional(readOnly = true)`; that annotation has not prevented the flush
observed inside this calling context.

### Affected relationships in the frozen plan

| Failing successor | Predecessor | Predecessor planned repayment events | Planned recalculation policy |
|---|---|---:|---|
| `loan:103` | `loan:25` | 3 | `daily-native-v1` |
| `loan:125` | `loan:43` | 2 | `daily-native-v1` |
| `loan:139` | `loan:30` | 3 | `daily-native-v1` |
| `loan:159` | `loan:29` | 7 | `daily-native-v1` |
| `loan:172` | `loan:34` | 3 | `daily-native-v1` |
| `loan:1784` | `loan:1482` | 10 | `daily-native-v1` |
| `loan:200` | `loan:14` | 4 | `daily-native-v1` |
| `loan:283` | `loan:101` | 4 | `daily-native-v1` |

These are counts of frozen `repayment` events, not independently verified target
transaction counts. The supplied investigation confirms the schedule constraint
for successors 283 and 1784. All eight failures are POST `/loans` and their
frozen actions contain refinancing data.

### Recent changes versus pre-existing behavior

| Change / evidence | Interpretation |
|---|---|
| `312edcb8129881722cc50529d6947615d2355f60`: products switch from recalculation disabled to enabled. | Strongly supported trigger: switches prepayment from stored totals to schedule generation and reprocessing. |
| `3c8efdfdab02c7d23eeba57aa4411732df5b83bd`: earlier October 26 provisional-principal repair. | Related enabling work, but did not introduce the prepayment method's repository read or final reprocessing call. Those are present in its parent revision. It does not establish preview isolation. |
| Git blame dates the prepayment repository read / temporary installment construction to older upstream history, and the matching-amount update of persistent transaction mappings to 2020. | Unsafe mechanism predates the recent feature activation; evidence favors newly exposed behavior over a newly added null-installment constructor. |
| First retained matching constraint in `logs/fineract-devrun.log`: October 26 at 19:59:35. Later rollover log repeats it from 20:27:30. | Consistent with the recalculation-enabled full attempt. Log retention does not prove this is the first occurrence ever. The later insurance verifier and one-cent writer commits cannot explain the 19:59 occurrence. |
| Recalculation activation proofs covered source loans 2612/2647; official two-loan replay/COB acceptance covered 1572/1826 and explicitly excluded refinancing from its dated source-window admission. | Bounded acceptance did not demonstrate refinance-preview persistence safety. Earlier successful non-recalculating refinancing does not cover the newly enabled branch. |
| Current `LoanTransactionProcessingServiceImplTest` prepayment tests explicitly stub recalculation as false. | Those tests do not exercise this branch or detect query-triggered ORM writes. |

### Evidence references and next proof

Code paths are relative to the `fineract-core` root:

- `tools/arissto-sync/arissto_sync/loans.py`: product payload construction; compare commit `312edcb812` with its parent.
- `fineract-provider/src/main/java/org/apache/fineract/portfolio/loanaccount/serialization/LoanApplicationValidator.java`: `validateRefinancingApplicationLoans` and `validateRefinancingLoans`; the latter uses the same preview during disbursement validation.
- `fineract-provider/src/main/java/org/apache/fineract/portfolio/loanaccount/service/LoanTransactionProcessingServiceImpl.java`: `fetchPrepaymentDetail` recalculation branch.
- `fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/loanschedule/domain/AbstractCumulativeLoanScheduleGenerator.java`: `calculatePrepaymentAmount` and `addLoanRepaymentScheduleInstallment`.
- `fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/domain/transactionprocessor/AbstractLoanRepaymentScheduleTransactionProcessor.java`: matching-amount branch in `reprocessLoanTransactions`.
- `fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/domain/LoanTransaction.java`: `updateLoanTransactionToRepaymentScheduleMappings` and `updateMappingDetail`.
- `fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/domain/LoanTransactionToRepaymentScheduleMapping.java`: cascading persistence of installment references.
- `fineract-provider/src/main/java/org/apache/fineract/portfolio/loanaccount/service/LoanReadPlatformServiceImpl.java`: `retrieveLoanPrePaymentTemplate`, including payment-type read after calculation.
- Backend stack anchors: `logs/fineract-devrun.log:72401`, `:72427`, `:72443`, `:72454`; rollover evidence in `logs/fineract-devrun.log.2:218530`.
- Acceptance scope: [recalculation activation](interest-recalculation-default.md) and [actual CLI/COB acceptance](loan-flow-cob-acceptance.md).

### Reproduction and repair results — October 27

Repair commit: `349ca8ad3f2ad6b7c513efb96252e7b4712e7ebd`. Durable change ID: **29**
(status `open`, because original portfolio recovery is not yet reconciled).
Sanitized machine-readable evidence:
[LS-07 preview isolation checks](investigations/ls07-preview-isolation-oct27.json).
Regression test:
[`CumulativePrepaymentIsolationTest`](../../../../fineract-provider/src/test/java/org/apache/fineract/portfolio/loanaccount/service/CumulativePrepaymentIsolationTest.java).

| Case | Before repair | After repair |
|---|---|---|
| Recalculation off; quote then flush | Passed. | Passed; repeated quotes preserve original mappings, installments and charges. |
| Recalculation on; quote then flush | Failed: attempted temporary installment insert with null `LOAN_ID`, SQLSTATE `23502`. | Passed with expected principal/interest; original mappings, installments and charges unchanged. |
| Rejected schedule preview | Not part of the initial two-case reproduction. | Exception remains visible; original installment and charge state unchanged. |
| Charge-paid-by cross-reference | Not part of the initial two-case reproduction. | Calculation ownership links point to snapshot transaction/charge objects. |
| Caller already has a pending payment-related charge update | Not part of the initial two-case reproduction. | Update survives quote and commits with the supplied values; preview does not clear or restore caller state. |
| Unrepresentable final source-exact penalty allocation | Existing domain rule retained. | Still rejected; no preview state leaks into the managed originals. |

The new suite executes **five tests** (including two off/on parameter cases).
Together with existing repayment, quote-date, historical target-guard and
refinancing-command tests, **55 tests passed** (14 provider, 41 loan). Formatting
of the new test and scoped whitespace checks passed.

The fixture uses actual Fineract domain entities, payoff-service branch dispatch,
transaction processor and EclipseLink persistence/flush with an isolated H2
schema. Schedule generation is deliberately stubbed to expose the persistence
boundary; this does not prove full amortization, HTTP endpoint, production
PostgreSQL, portfolio reconciliation or performance acceptance.

The cumulative payoff calculator now copies the loan's privately owned mutable
state and the selected replay transactions into a shared calculation snapshot
before schedule generation or reprocessing. A second reference pass keeps
internal charge/transaction ownership links inside that snapshot regardless of
copy order. Normal posting is unchanged. The repair does not disable
recalculation, relax exact allocation, assign persistent loan IDs to temporary
installments, or suppress normal transaction flush.

### Staff payment changes and frozen-plan safety

The synthetic reproduction has **no staff activity or changing source data**.
It proves that this preview defect can produce the constraint by itself. It
does **not** prove staff did not enter an Arissto payment during the original
run, or establish why each of the six generic HTTP 500 responses occurred.

Source drift is a separate check against the frozen plan and source observation
window. The existing apply guard's source hash/readiness checks were not
changed. A pre-apply check is not a source lock or an approved watermark for
later staff commits. No source snapshot was refreshed or substituted, and no
mid-run plan was rewritten for this fix.

No Arissto or tenant connection, backend restart/deployment, workflow resume,
retry, COB or target-loan repair was performed. All 16 successor/predecessor
identifiers are recorded against the durable change; known Fineract IDs come
only from the preserved cycle ledger. Existing unrelated working-tree changes
were preserved and excluded from the repair commit.

Remaining acceptance: separately load/verify the repaired backend, correlate the
remaining six generic HTTP 500s, exercise the original application/disbursement
paths under a reviewed local recovery and reconcile all eight original loans.
Keep the existing cycle, target lifetime, **Arissto through 2026-10-26** and
**Fineract starts 2026-10-27** boundaries for that continuation.

## Existing fix evidence

These are baseline observations from the operator investigation, not new test executions for this document.

| Related groups | Commit | Durable change ID | Evidence and remaining gate |
|---|---|---:|---|
| LS-17, LS-18 | `7868ef043ef97c686df4f3cdf94db4d18a4b8a93` | 26 | Final-metric completeness repeated during apply validation; reviewed family-reference alias added. Guard passed recovery; references reconciled. |
| LS-09 | `327f7c09b503ea81fec8b177fc98b17b9bcd5dc6` | 27 | Exact-identity lookup for omitted inactive insurance charges; six read-only verifications passed. Full workflow recovery pending. |
| LS-10 | `65037a62583c83b0a8ce84a56a65b4ab4445809e` | 28 | Positive currency-precision terminal adjustment includes exactly one cent. Regression tests reported passed; runtime recovery pending. |
| LS-07 | `349ca8ad3f2ad6b7c513efb96252e7b4712e7ebd` | 29 | Synthetic off/on ORM reproduction confirms preview mutation; snapshot repair passes 55 focused tests. Original eight-loan recovery pending. |

For the earlier analogous provisional-principal issue and its repair limits, see [interest recalculation canary](interest-recalculation-canary.md). Its successful scoped recovery does not establish resolution of LS-01–05 or exact handoff interest across the present population.

## Discovery and annotation log

Append findings with their issue ID. Record a new cycle/run explicitly rather than replacing this baseline's counts with incomparable results.

| Date | Issue IDs | Observation / decision | Evidence | Result / next step |
|---|---|---|---|---|
| 2026-10-27 | LS-01–06 | Split all 151 allocation failures by nonzero error components; identified early-repayment association. | Frozen plan and structured errors in baseline loan run. | Five cohorts retained; per-event causes still open. |
| 2026-10-27 | LS-07 | All eight create failures have refinancing data; shared preview also used during disbursement validation. | Frozen actions; `LoanApplicationValidator` and prepayment calculation/read-service code; supplied backend stack evidence. | Confirm individual generic HTTP 500 causes and test preview isolation. |
| 2026-10-27 | LS-19–22 | Identified analogous DTE cancellation exposure and incomplete/inconsistent interruption reporting. | Loan and DTE executor code; orchestration SIGTERM handler; cycle state. | Cancellation and outcome reconciliation remain open. |
| 2026-10-27 | LS-07 | Traced newly enabled recalculation branch to persistent transaction remapping onto temporary installments; identified activation commit and acceptance coverage gap. | Git diff/blame, frozen successor/predecessor relationships and retained ORM flush stack; detailed LS-07 investigation above. | Mechanism diagnosed; isolated off/on reproduction, per-case HTTP 500 correlation and repair remain pending. |
| 2026-10-27 | LS-07 | Reproduced off-pass/on-null-loan-ID failure with real EclipseLink flush; isolated preview state and preserved pending caller changes. | Repair `349ca8ad3f2ad6b7c513efb96252e7b4712e7ebd`; durable change 29; [sanitized checks](investigations/ls07-preview-isolation-oct27.json); 55 tests passed. | Fixed in code and verified on synthetic records; original portfolio recovery and separate staff/source-drift evidence remain pending. |

### Template for the next annotation

- Date and issue ID:
- New observation or hypothesis (label which):
- Affected Arissto loan keys / count and selection scope:
- Evidence: cycle, plan, run, reconciliation, test, commit or PR:
- Change or decision and rationale:
- Verification result and remaining acceptance check:
- Updated group status:

## Update rules

- Use **Open**, **Discovery**, **Quarantined**, **Blocked**, **Fix committed — recovery pending**, or **Recovered — reconciled** with a short qualification.
- A committed fix or passing unit test is not a recovered migration. Record runtime and reconciliation evidence before marking recovered.
- Preserve exact source allocations, contractual dates and accounting ownership boundaries. A similarity or correlation is not approval to relax a guard.
- Keep borrower data, credentials and transaction payloads out of this tracker. Use opaque source keys and evidence references.
- Keep executable behavior and policy authoritative in the [loan contract](contract.md), [reconciliation guide](loan-reconciliation.md), and [orchestration contract](../orchestration.md). Record implemented changes in the durable SQLite tracker as required by [change-log.md](change-log.md).
- Continuing this interrupted attempt means a reviewed **resumed sync** in the same cycle and target lifetime. Updating this document does not authorize a reset, resume, retry, COB or target change.
