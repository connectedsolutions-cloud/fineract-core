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
| LS-03 | Source-exact penalty allocation can fail on temporary recalculation prefixes; paid transaction copies can also lack historical charge ownership. | 72 baseline failures remain individually unverified. Loan 921 reproduced unpaid 0.26 and historical paid 0.15 cases. | **Fixed for demonstrated cases — 61 tests passed; loan 921 and its four-loan cohort recovered and officially reconciled.** | Apply the proven pattern to the remaining baseline cases without assuming a common cause or declaring portfolio recovery. |
| LS-04 | Source-exact allocation leaves principal and penalties. | 7 failures; `loan:1398`, `loan:1828`, `loan:1889`. | **Open — mixed cohort.** | Separate provisional principal handling from penalty representability. |
| LS-05 | Source-exact allocation leaves interest only. | Six baseline failures: 936, 938, 964, 971, 972, 983. New bounded-retry case: 773, first repayment `0000005349` on 2024-09-24 leaves 1.10 interest. | **Open — loan 773 reproduced; 1/54 source events represented.** Shared cause with the baseline six is unproven. | Trace the zero-principal interest-only event through temporary versus final schedule allocation; do not manufacture principal or skip the event. |
| LS-06 | First frozen repayment precedes first frozen contractual due date; strongly associated with LS-01/02. | 47/66 combined LS-01/02 cases: 25/42 and 22/24; example `loan:10`. Comparison: 4/967 recorded succeeded loans. | **Discovery — association verified, causality unproven.** Overlaps LS-01/02. | Trace actual failing event and reversals; compare temporary prefix with full schedule. Interrupted execution order limits cohort interpretation. |
| LS-07 | Refinancing creation fails; preview path can flush an installment with null `loan_id`. | 8 create failures: `loan:103`, `loan:125`, `loan:139`, `loan:159`, `loan:172`, `loan:1784`, `loan:200`, `loan:283`. Constraint confirmed for 283 and 1784; remaining six generic HTTP 500s are candidates. | **Fix committed — live payoff and schedule previews passed 8/8; persisted predecessor state unchanged. Seven original successors passed per-loan checks in the 34-loan run; 283 retains its prior four-loan acceptance but its latest cohort outcome is blocked.** Six original HTTP 500s remain individually uncorrelated. | LS-24 selection and LS-26 office-transfer planning are fixed. LS-03 recovery now reconciles 283’s native creation/disbursement/closure with the complete four-loan cohort; LS-27 now verifies its complete 34-loan closure; the 34-loan attempt now has 29 successful/recovered outcomes and five failed/blocked outcomes (LS-05/29). |
| LS-08 | EMI must exceed interest during transaction replay / schedule regeneration. | 9 failures: `loan:177`, `loan:300`, `loan:459`, `loan:516`, `loan:555`, `loan:771`, `loan:780`, `loan:781`, `loan:865`. Eight have planned terminal adjustments. | **Open — cohort identified.** Terminal-adjustment association does not establish the failing event. | Capture failing event and regenerated installment interest before changing amounts. |
| LS-09 | Fully paid, inactive historical insurance charge omitted from active charge collection causes false missing-charge refusal. | 6 failures: `loan:61`, `loan:372`, `loan:379`, `loan:651`, `loan:661`, `loan:815`. | **Fix committed; read-only verifier passed all six; workflow recovery pending.** Original process predated fix. | Load repaired code in an authorized recovery and require complete loan reconciliation. Commit/change evidence below. |
| LS-10 | Exactly one-cent terminal adjustment skipped by writer, leaving loan open. | 6 failures: `loan:1909`, `loan:2024`, `loan:2051`, `loan:2462`, `loan:2511`, `loan:2513`. | **Fix committed; regression tests reported passed; runtime recovery pending.** | Verify adjustment identity, exact amount, closed status and full reconciliation under repaired process. |
| LS-11 | Target maturity differs from frozen contractual maturity, potentially changing short-/long-term accounting classification. | 1 observed failure: `loan:999`; expected 2031-01-30 versus target 2025-12-28. | **Open — blocked by term-account guard.** | Trace schedule/creation overrides; preserve contractual dates and verify accounting class. |
| LS-12 | Loan dependencies propagate upstream failures. | 118 blocked loans; examples `loan:1014`, `loan:1017`, `loan:1038`. Failed ancestor `loan:894` has nine blocked descendants; `loan:18` has six. | **Blocked — all 118 trace to recorded failed ancestors.** Consequences, not 118 independent defects. | Link each blocked loan to causal root; verify dependency completion during authorized recovery. Descendant counts per root may overlap. |
| LS-13 | One office-transfer cohort failure blocks related loans. | 17 baseline blocked loans; the current 101/283/553 cohort had been blocked behind 921. | **Current four-loan cohort recovered and reconciled.** Broader baseline propagation remains under review. | Preserve the actual root error; source-921 LS-03 recovery resolved the current cohort, with one accepted transfer and no duplicate history. |
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
| LS-24 | Scoped retry selection can promote healthy product prerequisites into explicit fan-out roots when adding office-transfer cohort members. | Eight requested successors plus prerequisites select 17 loans initially; recomputation would select 2,735 loans. Transfer cohort includes `loan:101`, `loan:283`, `loan:553`, `loan:921`. No expanded apply ran. | **Fixed — 248 tests passed; frozen-plan audit selects 19 loans and one product instead of 2,735 loans. Latest 34-loan run remained bounded; see LS-27.** | Keep the bounded selector; LS-26 now permits complete scoped transfer cohorts. LS-27 now adds the required successors and consolidation dependencies: 34 loans and one product, with no sibling portfolio fan-out. Latest run has no portfolio fan-out; native same-client counter side effect is tracked separately in LS-30. |
| LS-25 | Frozen-plan validation detects source changes after planning; scoped loan 921 gained an October 27 repayment. | Original full-plan blocker: `loan:1613` (separate). For 921, movement `0000034318` increases 23 frozen events to 24; the prior 23 are unchanged. Before LS-28, current-source planning quarantined `loan:101`, `loan:283`, `loan:553`, `loan:921` through the refinancing cohort. | **921 diagnosed — genuine source drift; guard is correct. 280 tests passed; no runtime fix needed.** The recorded payment creation is about 79 seconds after the scoped plan observation. LS-28 now provides a verified bounded reconstruction plan for 921; four-loan replay was reconciled; exclusion also holds in the latest 34-loan retry. | Preserve Arissto through October 26 / Fineract starts October 27. Use the new LS-28 plan for the complete four-loan 921 chain; unsupported refinance histories still block. LS-27 and the separate 1613 evidence remain open. |
| LS-26 | Planner unconditionally rejects scoped loans with client office transfers, even with the full transfer cohort. | The 19-loan retry includes cohort `loan:101`, `loan:283`, `loan:553`, `loan:921`; source extraction freezes a 34-loan refinancing graph. | **Fixed — complete cohort proof, 272 tests passed, same-cycle planner accepts the cohort. LS-28 now clears the historical projection gate for the complete 921 chain. Accepted transfer remains matched after the 34-loan attempt.** | Recheck frozen cohort inventory before writes; incomplete/changed cohorts remain blocked. Current cohort outcomes are blocked by 921’s LS-29 charge recovery failure; prior transfer history and financial state remain represented. |
| LS-27 | Dependency-only retry omits successors whose disbursements create selected loans’ native refinancing payoffs. | Original eight roots select exactly 34 loans and one product; all 35 actions received outcomes. | **Selection fix runtime-verified; recovery incomplete.** Run `4b0d62a7a0034254b67cba8cfbbc5fbd`: 29 succeeded/recovered, two failed (773/921), three blocked (101/283/553). Official reconciliation is false; zero blocking mismatches among the 29 successful/recovered loans. | Resolve LS-05 (773) and LS-29 (921), then perform a reviewed bounded recovery/reconciliation. Preserve payment exclusion and investigate LS-30; do not replay the portfolio. |
| LS-28 | Historical reconstruction for 921 preserves the original snapshot and excludes the October 27 payment. | Completed recovery: `loan:101` → native 1, `loan:283` → 1144, `loan:553` → 1145, `loan:921` → 1146. | **Recovered — officially reconciled.** All source event identities and 32/32 metric targets match; October 27 payment absent. | All four retain complete events and 32/32 metric matches after the latest attempt; latest run flags them failed/blocked through LS-29. Historical reconstruction and payment exclusion remain verified. |
| LS-29 | Recovery cannot find an inactive historical penalty charge through the loan API and attempts to create it before checking the existing repayment. | Loan 921, movement `0000021121`, penalty 1.31 dated 2026-05-29; indirectly blocks 101/283/553. Persisted charge 5056 is inactive/unpaid and omitted by the API, while its repayment exists. | **Open — failure and visibility gap confirmed.** Re-creation is rejected as earlier than the latest transaction. Existing 23 events and eight final metrics still match. | Investigate historical charge ownership/alignment, then make recovery safe for this proven state. Do not reactivate, duplicate or waive the charge without proof. Analogous to LS-09 visibility, but penalty-specific. |
| LS-30 | Native historical disbursement can update a later same-client loan row outside selected writer actions. | Loan 383 / native 261, outside the 34-loan plan, changed while selected loan 125 was historically disbursed. Same client/product; 383 is later in time. | **Discovery — outside loan-row hash differs.** Native borrower/product counter update is a supported explanation, not a proven complete column diff. Outside transactions, schedules, charges, ownership, clients, products and GL hashes match. | Capture per-row preimages and trace native `updateLoanCounters` before promising strict row preservation. Keep financial replay bounded; do not add 383 to replay merely to hide the side effect. |

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

The initial isolated repair phase did not connect to Arissto or the tenant or
reload the backend. The following same-cycle verification is the subsequent
live evidence; it supersedes that phase's pending-live-check statement.

### Live same-cycle verification — October 27

Evidence: [eight-loan sandbox verification](investigations/ls07-sandbox-verification-oct27.json).
The guarded orchestrator restart loaded the repaired backend using the original
workflow plan's frozen restart command. It did not queue the workflow, restore
a baseline or create a replacement cycle. The scheduler remains paused and the
active accounting cutoff retains its date, revision and configuration hash.

| Original failing successor | Predecessor source / Fineract ID | Live payoff preview | Application-schedule validation | Persisted predecessor state |
|---|---|---|---|---|
| `loan:103` | `loan:25` / 23 | Passed | Passed | Unchanged |
| `loan:125` | `loan:43` / 40 | Passed | Passed | Unchanged |
| `loan:139` | `loan:30` / 27 | Passed | Passed | Unchanged |
| `loan:159` | `loan:29` / 26 | Passed | Passed | Unchanged |
| `loan:172` | `loan:34` / 31 | Passed | Passed | Unchanged |
| `loan:1784` | `loan:1482` / 3 | Passed | Passed | Unchanged |
| `loan:200` | `loan:14` / 14 | Passed | Passed | Unchanged |
| `loan:283` | `loan:101` / 1 | Passed | Passed | Unchanged |

All eight predecessor loans report recalculation enabled. Requests used the
original frozen application terms and historical expected-disbursement dates,
resolving only current native predecessor/product IDs. The application check
used the non-posting `calculateLoanSchedule` route, which invokes refinancing
application validation; it did **not** create a pending application or test
actual approval/disbursement.

Before/after hashes match for the complete predecessor loan rows, transactions,
repayment installments, transaction mappings, charges, charge ownership and
installment charges. Global counts remain **1,143 loans**, **24,850 loan
transactions**, **zero GL journal rows**, and **2,103 Liquibase changes** across
reload and live checks. No successor was created or financially replayed.

The source inspection built immutable scoped plan
`6fa82232f72748a5833e2d28bc3c0d5a` in the same cycle. Its graph contains 34
related loans; **all 34 source hashes match the original plan**. It remains
non-applicable with `scoped_loan_plan_cannot_replay_client_office_transfers`.
The original full-plan guard independently stops on newly inapplicable source
evidence for `loan:1613` (LS-25). A read-only selection check also exposed the
2,735-loan retry expansion (LS-24). Neither blocked/expanded path was executed.

**Result:** the LS-07 payoff/preview repair is verified against all eight live
pairs without observed persistence mutation. **Original successor creation,
disbursement, repayment replay and financial reconciliation remain unverified.**
The parent workflow remains `interrupted`; durable change 29 remains `open`.
No loan item was falsely marked recovered or reconciled. Full recovery requires
an explicitly bounded eligible plan and resolution of the separate scope/source
issues. This verification does not relax frozen-source, accounting or allocation
guards and does not establish that historical staff activity was absent.

## LS-24 repair and scope verification — October 27

The retry selector now retains its original explicit roots and computes one
closure over dependencies and mandatory office-transfer cohorts. A product or
collateral product added as a prerequisite never becomes a new fan-out root.
Cohort members can introduce new predecessors or another transfer cohort; the
same closure continues until all required members are present. Results retain
the original plan order and action objects, without modifying the plan or caller
selection. An explicitly selected failed product still includes its dependent
loans, preserving the existing product-retry contract.

`apply_loan_plan` invokes that selector once with the frozen transfer events.
It no longer feeds the expanded prerequisite set back into the selector as
explicit roots. Its preflight/source/target apply guard and subsequent transfer
source/balance checks remain in place.

| Preserved eight-loan selection | Before | After |
|---|---:|---:|
| Requested successor loans | 8 | 8 |
| Selected loans after dependency/cohort closure | 2,735 | **19** |
| Setup actions included | 2 | **1** (`product:00010`) |
| Total selected actions | 2,737 | **20** |

The corrected 19 comprise the original eight successors, **nine required
ancestors**, and two additional mandatory transfer-cohort members
(`loan:553`, `loan:921`). Unrelated borrowers sharing the product are excluded;
the collateral product is also excluded because this bounded set does not
require it. The original full plan remains unchanged.

Verification evidence:
[read-only frozen-plan scope checks](investigations/ls24-retry-scope-oct27.json).
The audit reads existing plan `8098f714e10b4363934545537026a714` in cycle
`sandbox-2026-10-26-full-clean-a`; it neither rebuilds that plan nor connects to
Arissto or Fineract. Its selected keys exactly reconcile to the expected 19-loan
set, every prerequisite is included, and plan ordering is preserved.

The original apply-path regression fails against the pre-fix functions because
it selects unrelated product siblings. It passes after the repair. Eight new
scope tests cover the actual apply selection entry path, healthy product and
collateral prerequisites, explicitly failed product roots, nested transfer
cohorts, deep dependencies, input/order preservation, and empty/full/unknown
selections. Together with the existing loan and final-metric suites,
**248 tests passed**:

```bash
.venv/bin/python -m unittest tests.test_loan_retry_scope tests.test_loans tests.test_loan_metric_alignment -v
```

Implementation: [retry selector and apply entry point](../../arissto_sync/loans.py).
Tests: [scope regressions](../../tests/test_loan_retry_scope.py).
The repair commit and all affected selection identities are indexed in the
[durable change tracker](change-log.md), with selected loans distinguished from
unrelated loans excluded by the repair. These are selection outcomes, not
financial migration outcomes.

No reset, backend reload, resume, loan creation, financial replay or accounting
boundary change was performed for LS-24. The scoped office-transfer planning
restriction and LS-25 source-drift gate are separate and remain unchanged.
LS-07's actual creation/disbursement/replay acceptance is still pending.

## LS-26 scoped office-transfer planning — October 27

The blanket `scoped_loan_plan_cannot_replay_client_office_transfers` restriction
was introduced in `15c5e2c3f8fe00cb3ede322b66679480e95c65db` on October 19.
It rejected every explicit loan scope containing a transfer. The existing
[transfer contract](contract.md#historical-client-office-transfer-replay)
requires complete cohorts, so a complete scoped cohort should be eligible.
This was a planner restriction, not a new target transfer failure.

The planner now reads the complete `AFI_SOCIO → CRD_CARTERA` loan inventory for
each touched transferring client and freezes it as
`client_office_transfer_cohorts`, separate from the existing frozen event
payload. Every source loan must be represented by an action belonging to that
client, including loans closed or with zero balance on the transfer day.
Positive pre-transfer balances alone cannot establish completeness. An empty
inventory, missing loan, wrong owner or uninventoried active loan blocks the
plan. This conservative proof does not automatically add unrelated loans.

Before apply, the guard rereads that inventory and compares it to the frozen
proof, then verifies action coverage again. Changed inventories and legacy
scoped transfer plans without proof fail before API construction or a new run.
Existing full-block plans retain their event shape and validation behavior.
The chronology, opening-date, quarantine, multiple-transfer, savings,
future-target-activity, mixed retention/replay, source drift, native active-loan
and exact amount checks remain active. Planning does not replay transactions
or mutate charges while source or target evidence is being inspected.

[Verification evidence](investigations/ls26-scoped-office-transfer-planning-oct27.json):

- The complete-cohort planning regression fails against the pre-fix function
  and passes after repair. Ten new tests cover cohort inventory and completeness,
  planning acceptance/rejection, preservation of existing guards, drift before
  writes, and compatibility with historical full-block plans.
- **272 tests passed** across scoped planning, office chronology/native replay,
  bounded retry selection, loans, and final-metric suites.
- Existing cycle: `sandbox-2026-10-26-full-clean-a`, local `sandbox` /
  `fineract_sandbox`, fingerprint `b9f6834b66790744`.
  **Arissto through: 2026-10-26. Fineract starts: 2026-10-27.**
- New immutable loan plan: `3e9d8024d1504f3eabfe8498f5a049fb`.
  Its frozen planning result is **applicable with no readiness blockers**.
  The read-only `_loan_apply_guard` passes the new cohort proof, then fails
  closed on `loan:921:source_events_after_fineract_accounting_boundary`.
  This plan must **not** be applied while that guard is failing.
  It contains 34 refinancing-connected source loan actions (10 recover, 24 create) and one unchanged product. All 34 source hashes
  match the original loan plan. `loan:1613` is outside this scoped plan; the
  original full-plan LS-25 guard is not bypassed or relaxed.
- The transferring client's source inventory is exactly **101, 283, 553, 921**.
  The transfer date is **2025-04-01**, with **921** active in the frozen source
  snapshot. The original eight retry roots still select exactly **19 loans plus
  `product:00010`** through the LS-24 selector.
- Before/after complete-row hashes and counts match for loans, transactions,
  schedules, charges, transaction mappings, charge ownership, clients, transfer
  history and GL journals. The workflow remains interrupted, the scheduler
  paused, and the accounting boundary unchanged. The original plan is intact.
  No reset, replacement cycle, backend restart, apply, resume or financial
  replay occurred. Only the new local immutable plan and documentation were saved.

### LS-27 discovery: 19 selected actions do not complete native payoffs

The new plan's 34-loan source graph and the selector's 19-loan write selection
serve different purposes. Code inspection of `native-refinance-payoff` confirms
that the predecessor action deliberately skips posting that event: the
successor's top-up disbursement must create the repayment atomically.

| Selected predecessor | Omitted successor | Successor present in sandbox | Required payoff present |
|---|---|---|---|
| `loan:103` | `loan:308` | No | No |
| `loan:139` | `loan:515` | No | No |
| `loan:159` | `loan:360` | No | No |
| `loan:200` | `loan:433` | No | No |
| `loan:1784` | `loan:2402` | No | No |

All five omitted successors are `create-loan` actions in the new scoped plan.
Their absence and the missing unreversed payoff external IDs were verified
with read-only target queries. Therefore **passing LS-26 does not establish a
safe, fully reconcilable 19-loan recovery**. The separate LS-25 boundary guard
on 921 also remains blocking. Before running a recovery, review complete
successor/payoff closure (including further descendants) inside the
bounded 34-loan graph and test the resulting write selection. This turn does
not change LS-24 selection or authorize silently applying all 34 loans.
At the LS-26 verification, the timing of the 921 source-boundary observation
was unresolved. The LS-25 follow-up below confirms an added source repayment
after the planning read; the actor and transaction commit time remain unknown.
LS-07 creation/disbursement and financial reconciliation remain pending.

## LS-25 loan 921 boundary investigation — October 27

**Conclusion: genuine source drift, not inconsistent planning logic. No runtime
fix is warranted.** The accounting-boundary guard prevents importing a later
source payment under an earlier frozen plan.

[Read-only source and sandbox evidence](investigations/ls25-loan-921-source-drift-oct27.json).

| Observation | Evidence |
|---|---|
| Frozen ownership boundary | **Arissto through 2026-10-26; Fineract starts 2026-10-27.** Unchanged throughout the investigation. |
| Original and LS-26 scoped snapshots | Both freeze 23 events for `loan:921` and source hash `16ad13f2167132d726cc421dd55b0ed5fd3369652e16bb072a783522b8b715a7`. |
| Added source record | `CRD_MOVIMIENTOS_CARTERA.ID_MOVIMIENTO_CARTERA=0000034318`, ordinary repayment (`4:00001`), not marked reversed; `FECHA_OPERACION=2026-10-27`. |
| Recorded timing | Scoped plan observed at `2026-10-27T17:33:57.166901Z`; movement `DT_CREO=2026-10-27 17:35:16.500000`. SQL Server's clock reports UTC; the reported creation is about **79 seconds later**. `DT_CREO` is not a transaction commit watermark. |
| Prior source history | Current 24 events comprise the exact same 23 pre-boundary events plus the one October 27 repayment. The pre-boundary event-stream hashes match. |
| Scope of source change | Only `loan:921` has a changed source hash among the same 34 source loan actions. Current hash: `a74187dcae4aa7ba5dc4dc19edc8af1460456047551d9bdb9359f1c38bf1d0ae`. |

The preserved original loan plan and scoped plan
`3e9d8024d1504f3eabfe8498f5a049fb` describe the earlier source read. Their
clean 921 disposition was correct for that evidence. The later apply guard
reread Arissto and found the additional event. Recorded creation timing is
consistent with a payment entered between planning and validation; no source
actor identity or exact commit time was established. This does not identify
whether staff or an automatic process entered it.

### Why the existing source-day projection cannot admit this loan

The loan is active both currently and in its exact October 26 daily snapshot,
but its historical incoming refinance link is **553 → 921**, dated
**2024-12-20**. The conservative projection in
[loan_source_window.py](../../arissto_sync/loan_source_window.py) requires no
incoming or outgoing refinancing relationships. That exclusion alone prevents
using the ordinary-payment projection for 921. Its source counts remain
`{movements: 1}` after the projection step, and
`_guard_unmapped_loan_events` correctly adds
`source_events_after_fineract_accounting_boundary`.

The same source snapshot was traced through attachment of cutoff evidence,
source-window projection, target resolution and lifecycle rebuilding. None
of those stages removes the count or changes the source header/history.
The original 23 events do not permit silently dropping the later event:
temporal reconstruction for refinancing is outside the approved projection.
The lifecycle-only post-boundary hash fallback also returns **false** for the
actual old/new pair; it does not establish equivalence for this drift.
Eligibility failures are checked before that fallback and cannot be overridden
by it. The existing [source-window contract](loan-flow-cob-acceptance.md)
remains unchanged.

### Planner/apply consistency and tests

A new immutable loan plan, `52571d0c0209402ab20d7cde2a24950e`, was saved in the
same preserved cycle `sandbox-2026-10-26-full-clean-a` against local `sandbox` /
`fineract_sandbox` (fingerprint `b9f6834b66790744`). The original eight roots
still extract the bounded 34-loan graph and select 19 loans plus one product.
With current source evidence, the planner now:

- Quarantines 921 for the post-boundary repayment and propagates the refinancing
  quarantine to **101, 283 and 553**.
- Retains the complete transfer cohort proof and declares the plan
  **non-applicable**, with `transfer_client_has_quarantined_loan`.
- Freezes 9 recover, 21 create and 4 quarantine loan actions, plus one unchanged
  product. No action was executed.

The read-only apply guard rejects that new plan as non-applicable. Thus fresh
planning and apply validation agree on the current evidence. The difference
from the prior plan is the source payment, not divergent planner behavior.

Four regression tests cover unchanged refinancing evidence, rejection of a new
boundary-day repayment before API construction/run creation, rejection of a
pre-boundary edit, and the distinction between ordinary-loan projection and
unsupported incoming/outgoing refinance history. They use a single synthetic
source snapshot and exercise the real projection, eligibility and hash guards.
**280 focused tests passed**, including existing source-window, office-transfer,
retry-scope, loan and final-metric suites. No runtime code was changed.

Complete before/after target row hashes match for loans, transactions,
schedules, charges, transaction mappings, charge ownership, clients, transfer
history and GL journals. Counts remain **1,143 loans**, **24,850 loan
transactions**, and **zero GL journals**. The workflow remains interrupted,
the scheduler paused and the active accounting boundary unchanged. No Arissto
writes, target writes, reset, replacement cycle, apply, resume, backend restart
or financial replay occurred. Only the diagnostic local plan, tests and
investigation/tracker artifacts were added.

**At this diagnosis stage, recovery was blocked.** Keeping this cycle and its
boundary required explicitly reviewed temporal reconstruction for refinanced
source loans;
rebuilding a plan alone did not resolve the unsupported history. The subsequent
LS-28 section records the narrowly approved extension and verified four-loan
plan; the source-drift finding remains valid. Keep 921 in
its mandatory transfer cohort and preserve the source payment. LS-27 successor/
payoff closure and the separate full-plan 1613 evidence remain unresolved.

## LS-28 historical refinance reconstruction — October 27

The user-approved extension adds a narrow historical incoming-top-up projection;
it does not reinterpret LS-25's observed source drift as a bug. Policy and
proof requirements are in the
[historical refinance contract](historical-refinance-source-window.md).
Evidence: [same-cycle planning verification](investigations/ls28-historical-refinance-projection-oct27.json).

The projection now accepts a single same-owner refinance already completed
before the boundary when the source loan histories, unique liquidation and
payoff/disbursement identities agree, the predecessor is closed and paid in its
exact source-day snapshot, and retained principal/interest payments corroborate
the successor snapshot counters. Later ordinary/mobile payments and their
charge details are excluded; historical refinance events remain intact.
Missing/reversed/revised/ambiguous/future refinance evidence, outgoing links,
consolidation and cross-owner settlements remain blocked. The existing closed
stale-insurance classifier is reused for 553 only when historical and current
residue evidence agree. No charge state is changed during planning.

| Check | Result |
|---|---|
| Preserved cycle/target | `sandbox-2026-10-26-full-clean-a`, local `sandbox` / `fineract_sandbox` |
| Boundary | **Arissto through 2026-10-26; Fineract starts 2026-10-27**, unchanged |
| New immutable loan plan | `46b49222cc9e488ca7a4f553f27af5f9` — applicable, no blockers/quarantines |
| Requested/selected scope | Root 921 → **101, 283, 553, 921** plus `product:00010`; all prerequisites and native-payoff successors included |
| Read-only apply validation | Passed; no apply/run was started |
| Excluded payment | `0000034318` on October 27; frozen as excluded and absent from writer events |
| Historical 921 lifecycle | Exact match to the original source lifecycle, 23 events, refinance terms and all eight metric targets |
| Regression tests | Positive pre-fix failure reproduced; seven new methods; **287 focused tests passed** |
| Target state | All compared row hashes/counts unchanged: 1,143 loans, 24,850 loan transactions, zero GL journals |

The 921-only recovery has a complete four-loan financial chain and does not
need the other eight-root request's 19-loan selection or 34-loan source graph.
This removes the historical-reconstruction planning blocker for that bounded
retry. **Financial creation/disbursement, transfer replay and reconciliation
remain pending.** LS-27 for the original eight-root recovery is unchanged.
The original plans were not edited. No reset, replacement cycle, backend
restart, apply, resume, Arissto writes or target financial writes occurred.

## LS-28 bounded retry execution and reconciliation — October 27

**Partial native recovery; reconciliation did not pass.** The authorized
four-loan plan was executed once in the same cycle. Source reconstruction and
exclusion of the later payment worked; an independent historical penalty
allocation failure stopped the remaining replay. The allocation guard remains
intact and the rejected request was not blindly retried.

Evidence: [bounded retry results](investigations/ls28-bounded-retry-results-oct27.json).

- Mode: bounded loan-block recovery of the interrupted migration, preserving
  cycle `sandbox-2026-10-26-full-clean-a` and target lifetime.
- Target: local `sandbox` / `fineract_sandbox`, fingerprint `b9f6834b66790744`.
- **Arissto through: 2026-10-26. Fineract starts: 2026-10-27.** Unchanged.
- Immutable plan: `46b49222cc9e488ca7a4f553f27af5f9`.
  Apply run: `bac2eee7a4744cc8ba3f7c0a12d895f4`.
- Scope: only 101, 283, 553 and 921, plus unchanged `product:00010`.
  Parent-frozen controls retained: two workers, 30-second pause, three attempts
  for transient failures. The domain-rule HTTP 403 is not transient.
- Official result: **completed-with-errors**, one loan failed and three cohort
  members blocked; product unchanged. The official reconciler ran and its
  **`ok: false`** result is persisted in the same cycle.

| Source loan | Native ID | Persisted native state | Apply journal | Read-only event identity check | Read-only metric matches |
|---|---:|---|---|---|---|
| 101 | 1 | Closed (600) | Blocked by cohort failure | 6/6 represented | 7/8; paid interest differs |
| 283 | 1144 | Created, disbursed, then closed (600) | Blocked by cohort failure | 8/8 represented | 7/8; paid interest differs |
| 553 | 1145 | Created, disbursed, then closed (600) | Blocked by cohort failure | 9/9 represented | 7/8; paid interest differs |
| 921 | 1146 | Created and active (300); replay incomplete | Failed | 10/23 represented; 13 missing | 1/8; financial completion pending |

These independent identity/metric observations are **not successful financial
reconciliations**. The cohort failure prevents final metric alignment and
successful loan journal dispositions. The official compact report has zero
blocking mismatch groups because failed/blocked loans are excluded from full
comparison; its four failed/blocked entities keep the result unsuccessful.
No loan was manually marked recovered, mapped or reconciled to override that.

### Root failure and next investigation

The first missing source event is ordinary repayment **0000012748**, dated
**2025-08-25**, on native loan **1146**. Fineract rejected its source-exact
repayment request with HTTP 403 and
`error.msg.loan.source.exact.allocation.not.representable`:
remaining principal, interest and fees are zero; **0.26 penalty** remains.
The frozen penalty charge identity is
`ARISSTO:CRD-MOV:0000012748:PENALTY`. This is LS-03's penalty-only pattern;
its representability cause has not been established by this execution.
Do not attribute it to rounding or the excluded October payment.

The first three loans have their historical event identities represented, but
remain cohort-blocked. Native final metrics were read only after the failure:
paid interest differs on each closed predecessor, and 921 is still incomplete.
Final corrections were not forced over unfinished replay. The next fix must
trace this historical penalty's charge identity, active/due state and native
allocation/reprocessing behavior, then use guarded recovery in the same cycle.

### Transfer, payment exclusion and scope verification

The client office transfer **matched official reconciliation**. Exactly one
proposal and one acceptance are stored. Native loan 921 has one type-12 and one
type-13 transaction, both dated **2025-04-01**, and the four-loan client's
current office is 2. Predecessor loans were closed before transfer; no reset
was used to obtain that state.

October 27 payment **0000034318 was not imported**:

- Its canonical transaction external ID is absent before and after apply.
- A post-run lookup across **all external-ID namespaces** also returns zero.
- None of the four target loans has a transaction dated October 27 or later.
- The frozen plan retains its explicit excluded-event metadata and is unchanged.

Native loan count increased **1,143 → 1,146** and loan transaction count
**24,850 → 24,888**; GL journals remain **zero**. Complete before/after row
hashes match for loans, transactions, schedules and charges outside the four
loans, clients outside their client, all loan products and GL journals.
Subsequent diagnostic GETs did not change the target snapshot.
The scheduler remains paused, the active accounting cutoff is unchanged,
and the broader parent workflow remains interrupted. No reset, new cycle,
backend restart, broader workflow resume, Arissto write or runtime-code change
occurred. The partial target state is preserved for the next bounded recovery.

## LS-03 fix and completed four-loan recovery — October 27

**Recovered and officially reconciled:** 101, 283, 553 and 921. The initial
0.26 failure and the paid 0.15 replay case were both temporary-schedule
representability defects, not changes to the source amounts.

Implementation and policy: [penalty recalculation recovery](penalty-recalculation-recovery.md).
Evidence: [regression, reload and reconciliation results](investigations/ls03-penalty-recalculation-recovery-oct27.json).

A temporary schedule can end before the real charge's installment exists.
Only source-exact penalties backed by eligible same-loan due charges, or by
that same persisted payment's historical paid ownership, may wait for the
full schedule. Penalties never become early principal. The helper reads
ownership without modifying the original transaction/charge rows or attaching
them to its property-only copy. Final posting still requires and settles the
complete declared penalty. Missing, future, foreign, waived, ambiguous or
insufficient backing remains blocked. **61 focused Java tests and scoped
formatting checks passed**, including strict final-posting and ORM-isolation
regressions. Existing Mifos penalty field bindings remain compatible.

| Recovery check | Verified result |
|---|---|
| Preserved scope | Exactly 101, 283, 553, 921 plus unchanged `product:00010`; failed root 921 expands only to this dependency/transfer cohort |
| Preserved cycle | `sandbox-2026-10-26-full-clean-a`, local `sandbox` / `fineract_sandbox` |
| Boundary | **Arissto through 2026-10-26; Fineract starts 2026-10-27**, unchanged |
| Immutable plan | `46b49222cc9e488ca7a4f553f27af5f9`, unchanged |
| Successful retry | `a352b996b7ce4fd295270bac38568108` — completed; four recovered loans, no failed/quarantined loans |
| Official reconciliation | `ok: true`, zero blocking mismatches; 28 existing nonblocking native schedule variances |
| Source event identities | 101: 6/6; 283: 8/8; 553: 9/9; 921: **23/23** |
| Final metrics | **32/32** match; each loan reports `continuationReady=true` |
| Target states | 101/1, 283/1144 and 553/1145 closed (600); 921/1146 active (300) |
| Penalty ownership | 0.26 and 0.15 charges fully paid, zero outstanding, one correct cash-repayment owner each; separate native accrual links are not duplicate cash |
| Excluded payment | `0000034318` absent in all namespaces; no scoped transaction dated October 27 or later |
| Transfer | Existing proposal/acceptance and 921 type-12/type-13 pair reused; no duplicates |

The first tested fix advanced 921 to 19/23 events in intermediate run
`af75dd61e08d48d687a94b484ae81b4b`. Its 0.15 remainder exposed a property-only
copy of an already-paid March 31 payment (`0000018697`). The final extension
requires the unique persisted unreversed original's external ID, date,
declared penalty and own paid-by links; another transaction's ownership cannot
be used. The intermediate failure and earlier failed run are retained as
historical evidence. No failed run was rewritten as successful.

The guarded backend reloads preserved all compared rows and Liquibase counts.
The final retry reused the three previously created loans: total loans remain
**1,146**, transactions progressed 24,888 → 24,897 → **24,918**, and GL journals
remain **zero**. Outside-scope row hashes match throughout, and independent
read-back did not modify target rows. Scheduler stays paused; parent workflow
stays interrupted. There was **no reset, replacement cycle, tenant migration,
Arissto write or broader workflow resume**. LS-27 and untested baseline LS-03
loans remain open. This resolves the requested four-loan recovery only.

## Existing fix evidence

These are baseline observations from the operator investigation, not new test executions for this document.

| Related groups | Commit | Durable change ID | Evidence and remaining gate |
|---|---|---:|---|
| LS-17, LS-18 | `7868ef043ef97c686df4f3cdf94db4d18a4b8a93` | 26 | Final-metric completeness repeated during apply validation; reviewed family-reference alias added. Guard passed recovery; references reconciled. |
| LS-09 | `327f7c09b503ea81fec8b177fc98b17b9bcd5dc6` | 27 | Exact-identity lookup for omitted inactive insurance charges; six read-only verifications passed. Full workflow recovery pending. |
| LS-10 | `65037a62583c83b0a8ce84a56a65b4ab4445809e` | 28 | Positive currency-precision terminal adjustment includes exactly one cent. Regression tests reported passed; runtime recovery pending. |
| LS-07 | `349ca8ad3f2ad6b7c513efb96252e7b4712e7ebd` | 29 | Synthetic off/on ORM reproduction and 55 tests pass; live payoff/schedule previews pass all eight with unchanged predecessor hashes. Actual replay/reconciliation still blocked. |

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
| 2026-10-27 | LS-07, LS-24, LS-25 | Guarded backend reload and 16 non-posting live checks passed across all eight pairs; target hashes/counts unchanged. Scoped recovery remains non-applicable; broad retry would expand to 2,735 loans and full-plan guard detects loan:1613 source changes. | [Live sandbox evidence](investigations/ls07-sandbox-verification-oct27.json); scoped plan `6fa82232f72748a5833e2d28bc3c0d5a`; durable change 29. | Live preview verification complete; original successor creation/disbursement/replay and reconciliation pending. |
| 2026-10-27 | LS-24 | Preserved explicit retry roots through joint dependency/transfer-cohort closure; removed the second selector invocation that promoted healthy product prerequisites. | [Scope checks](investigations/ls24-retry-scope-oct27.json); pre-fix mocked apply regression reproduced; 248 tests passed; frozen plan selects exactly 19 loans plus one product. | Selection fixed and verified without reset or replay; office-transfer planning restriction and LS-25 source-drift gate unchanged. |

| 2026-10-27 | LS-26, LS-27 | Replaced blanket scoped-transfer ban with frozen full-client loan inventory and apply-time completeness/drift checks. 272 tests passed; same-cycle planner accepts the cohort; read-only apply guard then blocks loan:921 on source boundary evidence; target hashes unchanged. Five absent successor/payoff links discovered outside the 19-loan selection. | [Planning and target evidence](investigations/ls26-scoped-office-transfer-planning-oct27.json); new loan plan `3e9d8024d1504f3eabfe8498f5a049fb`; commit indexed in the durable change tracker. | Office-transfer planning fixed; source boundary guard (LS-25, 921) and complete financial scope (LS-27) remain blocking. No reset or replay. |

| 2026-10-27 | LS-25 (921) | Confirmed added October 27 repayment `0000034318`; recorded creation follows scoped planning by about 79 seconds. Prior 23 events unchanged; only 921 source hash changes. Current-source planning and validation both block the unsupported refinanced-loan history. | [Drift evidence](investigations/ls25-loan-921-source-drift-oct27.json); non-applicable plan `52571d0c0209402ab20d7cde2a24950e`; 280 tests passed; diagnosis/test commit indexed in durable tracker. | No planning bug or runtime change; no reset/replay. Review temporal refinance reconstruction before recovery; LS-27 remains open. |

| 2026-10-27 | LS-28, LS-25 (921) | Added source-proven historical same-owner refinance projection. Original 921 lifecycle and eight metrics preserved; October 27 payment excluded. Four-loan scoped plan/apply guard pass; 287 tests passed; target hashes unchanged. | [Projection evidence](investigations/ls28-historical-refinance-projection-oct27.json); plan `46b49222cc9e488ca7a4f553f27af5f9`; commit indexed in durable tracker. | Reconstruction and bounded planning verified; native replay/reconciliation pending. No reset. |

| 2026-10-27 | LS-28, LS-03, LS-13 | Executed exact four-loan plan once. Created 283/553/921, closed predecessors and matched office transfer; stopped on 921 movement `0000012748` with 0.26 penalty unrepresented. Official reconciliation unsuccessful. | [Live retry evidence](investigations/ls28-bounded-retry-results-oct27.json); run `bac2eee7a4744cc8ba3f7c0a12d895f4`; native IDs 1/1144/1145/1146. | Partial state retained; October 27 payment absent; outside-scope hashes unchanged. Investigate LS-03 before another recovery. No reset. |

| 2026-10-27 | LS-03, LS-13, LS-28 | Fixed temporary penalty prefixes using real due-charge coverage and exact historical paid ownership. 61 tests passed; four-loan retry completed and official reconciliation passed; 921 has 23/23 events, all 32 metric targets match. | [Complete recovery evidence](investigations/ls03-penalty-recalculation-recovery-oct27.json); run `a352b996b7ce4fd295270bac38568108`; commit indexed in durable tracker. | Current cohort recovered; October 27 payment excluded; no reset, duplicate loan/transfer, outside-scope change or broader workflow resume. Other baseline cases remain unverified. |

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

## LS-27 repair — complete bounded native-payoff closure

The selector previously followed `depends_on` from a successor to its
predecessors. A selected predecessor can also contain a frozen
`native-refinance-payoff` event which only its successor’s disbursement can
create. Omitting that successor leaves the selected loan’s lifecycle incomplete.
This is separate from LS-24’s healthy-product fan-out defect.

The selector now reaches a joint fixed point over prerequisites, those typed
payoff-successor events, and mandatory client office-transfer cohorts. Each
successor must be an existing loan action with a reciprocal predecessor
`depends_on` link. Missing prerequisites or invalid/missing successor actions
fail before API construction or run creation. Generic reverse dependencies and
ordinary events do not select successors. Discovered product prerequisites do
not become explicit retry roots. Original action order and frozen objects are
preserved; full-plan selection semantics are unchanged.

| Scope / evidence | Result |
|---|---|
| Explicit roots | 103, 125, 139, 159, 172, 1784, 200, 283 |
| Frozen original-plan audit | 19 → **34 loans**, one `product:00010`; 26 native-payoff links complete. Original portfolio has 2,749 loan actions. |
| Five directly missing successors | 308, 360, 433, 515, 2402 |
| Further payoff successors | 580, 711, 773 |
| Required consolidation ancestors | 407, 644, 1897, 1962, 2055, 2165, 2265 |
| Complete loan set | 14, 25, 29, 30, 34, 43, 101, 103, 125, 139, 159, 172, 200, 283, 308, 360, 407, 433, 515, 553, 580, 644, 711, 773, 921, 1178, 1482, 1784, 1897, 1962, 2055, 2165, 2265, 2402 |
| Current immutable bounded plan | `ced78c4c83cd4d44bbcba748c4093d49`: applicable, zero readiness blockers; 13 recover, 21 create, one unchanged product. Read-only apply guard passed. |
| Tests | **296 Python tests passed**, including nine new regression methods; two targeted closure cases failed before the repair. |
| Already accepted 921 cohort | Selecting 921 still closes to exactly 101/283/553/921. Its frozen lifecycle matches the reconciled plan, with 23 events. |
| Excluded payment | `0000034318` remains excluded; no writer event reaches October 27, and no matching target transaction exists in any namespace. |
| Preserved sandbox | Full financial row hashes unchanged; 1,146 loans, 24,918 loan transactions, zero GL entries. Parent workflow remains interrupted and scheduler paused. |

Validation used **resumed-sync recovery planning in the same target lifetime**,
cycle `sandbox-2026-10-26-full-clean-a`, local `sandbox` / `fineract_sandbox`,
fingerprint `b9f6834b66790744`. **Arissto through: 2026-10-26. Fineract starts:
2026-10-27.** No financial apply, parent resume, backend reload, cutoff advance,
new cycle or reset occurred. The accepted four-loan recovery was preserved.

The original full plan was used only for the selection audit and remains
unchanged. Its unrelated loan-1613 global source guard remains in force; the
new bounded plan does not bypass that guard or authorize replay of the full
portfolio. Wider financial recovery is still pending, so the durable change
entry remains `open` until reconciliation verifies that recovery.

Machine-readable evidence: [LS-27 bounded payoff closure](investigations/ls27-payoff-retry-scope-oct27.json).
Regression suite: [`test_loan_retry_payoff_scope.py`](../../tests/test_loan_retry_payoff_scope.py).

## LS-27 bounded execution and reconciliation — October 27

Executed the user-authorized **bounded resumed loan-block recovery** in the same
cycle `sandbox-2026-10-26-full-clean-a`, local `sandbox` / `fineract_sandbox`,
fingerprint `b9f6834b66790744`. **Arissto through: 2026-10-26. Fineract starts:
2026-10-27.** The reviewed immutable plan is
`ced78c4c83cd4d44bbcba748c4093d49`; execution run is
`4b0d62a7a0034254b67cba8cfbbc5fbd`. It ran from 19:51:40 to 19:53:14 UTC
(13:51:40–13:53:14 America/El_Salvador), with two workers, a 30-second transient
pause and three maximum transient attempts. Preflight and the unmodified source,
cohort, schema, resource and accounting guards passed before writes.

| Observation | Result / status |
|---|---|
| Scope | Exactly 34 loan outcomes and one unchanged product, from the original eight roots. No portfolio expansion. |
| Apply | `completed-with-errors`: 13 succeeded, 16 recovered, two failed, three blocked. |
| Official persisted reconciliation | `ok=false`; the 29 successful/recovered loans have **zero blocking mismatches**. There are 353 nonblocking native schedule variances. Failed/blocked items keep overall acceptance false. |
| Successful-loan verification | **236/236** planned event identities represented, **232/232** final metric targets match. Four active accrual controls reconcile. |
| Loan 773 / LS-05 | Native 1167 exists and is active; only its disbursement is represented (1/54 events). First repayment `0000005349`, 2024-09-24, is interest-only 1.10 and fails the source-exact allocation guard. 2/8 metrics match; continuation is not ready. |
| Loan 921 / LS-29 | Native 1146 retains 23/23 events, 8/8 metrics and continuation readiness. Recovery nevertheless attempts to recreate inactive penalty charge 5056 for May 29 movement `0000021121` (1.31), and the backdated-charge guard refuses it. No manual charge change was made. |
| Dependent outcomes | 101, 283 and 553 are blocked by the transfer-cohort failure; all still retain their complete events, 8/8 metric matches each and continuation readiness. The prior successful four-loan reconciliation remains historical evidence, not the latest run’s status. |
| Original eight successors | 103, 125, 139, 159, 172, 1784 and 200 succeeded/recovered with clean per-loan reconciliation. 283 is blocked in this attempt, with prior accepted financial state preserved. |
| October 27 payment | `0000034318` remains excluded from the frozen 921 writer history and absent across target transaction namespaces. **Zero** scoped transactions dated on/after 2026-10-27. |
| Native transaction identity | No duplicate scoped Arissto transaction external IDs. Transfer history remains two rows; the accepted 921 transfer pair remains exactly two transactions. |
| Global counts | Loans 1,146 → 1,167; loan transactions 24,918 → 25,273; GL entries remain zero. |
| Preservation limit / LS-30 | Outside-scope transactions, schedules, charges, paid-by/mapping ownership, clients, products and GL hashes match. **Outside loan-row hash differs**; loan 383/native 261 was modified during the run and now has product counter 3. |
| Cycle/lifecycle controls | Same immutable plan, cycle, fingerprint and active accounting boundary; scheduler paused and parent workflow interrupted. No reset, new cycle, backend reload, COB or broader workflow resume. |

For LS-30, selected loan 125 is disbursed on 2023-07-24; existing loan 383 for
the same client/product is disbursed on 2023-12-16. Native
`LoanWritePlatformServiceJpaRepositoryImpl.updateLoanCounters` loads later
disbursed loans for that client, increments same-product counters and saves
those loan entities. This explains the observed counter value and timing, but
we did not capture a per-row preimage, so we cannot prove an exhaustive changed
column list or claim total outside-row preservation. The selector itself still
produced exactly the reviewed 35 actions. No additional loan was replayed to
absorb the discrepancy.

For LS-29, the database contains inactive charge 5056 with amount/outstanding
1.31 and paid amount zero, no paid-by rows; the loan API omits it while the
source repayment already exists. `_ensure_source_penalty_charge` uses the
API-visible charge collection and attempts creation before the existing
repayment branch. The historical ownership/alignment reason for this inactive
row remains unproven. It needs a separate fix and cannot be repaired by
blindly activating, duplicating or waiving the charge during execution.

No source or writer code was changed during this attempt. The selection repair
is verified at runtime, while complete 34-loan recovery remains **open** pending
LS-05/29 and preservation follow-up LS-30. The run’s failed/blocked outcomes and
official `ok=false` reconciliation are retained as evidence.

Machine-readable results and all affected-loan/native IDs:
[LS-27 bounded retry results](investigations/ls27-bounded-retry-results-oct27.json).
