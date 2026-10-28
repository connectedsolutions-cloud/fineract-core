# Loan sync updates and progress — October 27, 2026


## Latest: failure-pattern repair and Arissto timeout

A local follow-up corrected the native office model in
`05767a0399a944a8002695883504261ae73c6bb3` (tracker entry 51): historical terminal
credits now use the recorded repayment office, proved against client transfer
history, rather than the loan's derived current-client office. Seven focused
provider tests pass, and read-only native/frozen-plan checks confirm all 19
local repair preconditions. The Arissto connection-only recheck still timed out;
no source comparison, new sync/retry or guarded native reload followed it.

See [the pattern-repair record](loan-failure-pattern-repair-oct27.md) and
[the sanitized resumed-run result](investigations/loan-pattern-repair-resumed-result-oct27.json).
The full 2,288-history barrier and all four office transfers passed. Native
readback verifies 418 active metric baselines, zero closed/pending metric rows,
all products/loans with recalculation off, and a paused scheduler.

The last attempt is terminal with 30 finalization failures: 11 historical
closure/office-date cases, 8 selected-maturity refresh conflicts and 11 insurance
template mismatches. Local native and retry-selection repairs are committed as
`a8b32b22557804979c190016619649d874866033` (durable tracker entry 50), with
433 Python and 22 Java checks passing. They await controlled runtime validation.
The earlier shared repairs are `ad32e90e4827fcf8b7fb4069d1759c71c093e4b1`
and cashless gross verification `8c34138a5bcdf88f7c079cbbb61b57de5ea963a4`.

Arissto source-check timed out after the user's outage warning. Fresh source
comparison and further sync/retries are stopped. The 11 insurance mappings were
left unchanged. No replacement cycle, reset, new sync/retry or guarded backend
reload was started after that timeout. The migration remains unaccepted.


## Final result of the fresh/clean recalculation-off attempt

The requested diagnostic run **finished failed** on October 27 at 20:11:20
America/El_Salvador (October 28 02:11:20 UTC). All **18 selected services** have
terminal dispositions: **11 completed and reconciled, Loans failed, 6 were
blocked by dependencies**. No service was silently removed. This is a completed
clean-run test, **not an accepted full migration**. No additional reset or retry
was performed after the terminal result.

[Final machine-readable result](investigations/historical-off-clean-run-result-oct27.json)
records the actual workflow/child identities, service outcomes, native policy and
source-boundary checks. Workflow run `e942a4ece71b4833b478a265b4296159` belongs to
fresh/clean cycle `sandbox-2026-10-27-full-clean-recalc-off-a` and immutable plan
`5359676d1cd44c9a9fca6f0147981662`. **Arissto through: 2026-10-26.
Fineract starts: 2026-10-27.** Target remains local `sandbox` / `fineract_sandbox`.

| Service | Final result | Evidence / disposition |
| --- | --- | --- |
| `clients` | **completed** | Reconciliation matched 1,072. |
| `employees` | **completed** | Reconciliation matched 43. |
| `client-staff-assignments` | **completed** | Reconciliation matched 1,072. |
| `client-pep` | **completed** | Reconciliation matched 1,072. |
| `client-family-references` | **completed** | Reconciliation matched 2,058. |
| `client-personal-family-references` | **completed** | Reconciliation matched 4,287. |
| `membership-share-capital` | **completed** | Reconciliation matched 70,445. |
| `loans` | **failed** | final_metrics_due_exceeds_outstanding |
| `delinquency-history` | **blocked** | Blocked by unsuccessful dependencies: loans |
| `savings-deposits` | **completed** | Reconciliation matched 165. |
| `savings-account-parties` | **completed** | Reconciliation matched 165. |
| `native-share-capital` | **completed** | Reconciliation matched 57. |
| `aml-alerts` | **completed** | Reconciliation matched 10,222. |
| `dte-history` | **blocked** | Blocked by unsuccessful dependencies: loans |
| `mobile-collections` | **blocked** | Blocked by unsuccessful dependencies: loans |
| `accounting-journal-entries` | **blocked** | Blocked by unsuccessful dependencies: loans, mobile-collections |
| `native-share-yield` | **blocked** | Blocked by unsuccessful dependencies: accounting-journal-entries |
| `cheque-history` | **blocked** | Blocked by unsuccessful dependencies: accounting-journal-entries |

Loan apply completed with **2,249 succeeded, 9 recovered, 1 failed, 17 blocked
and 476 planned quarantines**. The recorded failed root is `loan:101`; the
verified first transfer conflict involves source-closed loans `115`, `363` and
`688`. Official loan reconciliation then aborted with
`final_metrics_due_exceeds_outstanding`, with **31 native loans** matching that
invalid observed-vector pattern and API confirmation on representative `96`.
No complete official loan reconciliation report was saved.

The actual complete-plan barrier deferred corrections for **all 2,276 eligible
loans**. Final native checks found **2 products and 2,268 loans, all recalculation
false**, and **1,220 refinance settlement rows**. Interim refinance credits,
terminal corrections, final metric alignments, and source movement transactions
on/after October 27 are all **zero**. Scheduler remains **paused**; native cutoff
is **ACTIVE at 2026-10-27 / America/El_Salvador**. Runtime source hashes are
unchanged from the start. Focused loan/workflow checks passed **372 tests** and
the guarded backend startup compiled the changed native source successfully.

The 977 workflow failure-ledger rows are **not 977 distinct runtime bugs**:
they include the 476 planned quarantines recorded again at apply, blocked
cohort/dependency records, and the reconciliation exception. The two current
runtime issue groups are recorded below. Fixing them and accepting the complete
migration remain open under durable implementation record **47**. The prior
cycle's evidence archive and the durable tracker were preserved across reset.

Historical in-progress observations below remain timestamped evidence; this
terminal result supersedes their statements that the run is still active.


## Current direction — address the shared replay design

**Implementation for the requested clean run:** historical policy `source-exact-off-v1`
is frozen in revision 10 plans. Both native flags must read back false; old plans
and enabled native contracts fail closed. Guarded source-exact disbursement now
initializes staged historical refinance relationships and uses recorded source
allocations without ordinary future-interest quote substitution or either interim
credit bridge. Final corrective writes wait for every eligible frozen-plan
history and a complete native event read pass. A failed, blocked or missing chain
prevents corrections even on successful siblings or a scoped retry. Focused
Python plus workflow/control-plane checks: **372 passed**. Full native/workflow acceptance remains pending.
The operator has authorized the guarded fresh/clean 18-service run to discover
remaining errors; no partial acceptance or post-migration activation is implied.


**Initial execution assessment, before implementation:** the [readiness assessment](recalculation-off-execution-readiness-oct27.md)
stopped before reset/planning at the handoff's unsupported historical refinance
gate. Native creation/approval/disbursement still validate ordinary prepayment
quotes, and the importer contains both prepayment and residual goodwill bridges.
The coherent off-policy implementation and complete-service correction barrier
remain open; no runtime setting, financial target or source window changed.


The [next-chat fresh/clean run plan](recalculation-off-full-sync-handoff-plan.md)
now specifies **all 18 services**, historical loan recalculation off, the
implementation prerequisites and guarded restore/new-cycle sequence. Preparation
only: no settings changed, cycle/executable plan created, reset or sync started.
The source window remains October 26 inclusive / Fineract starts October 27.


The [October 27 design decision](historical-replay-design-decision-oct27.md)
consolidates LS-01/03/05 and LS-32–35 into a shared replay/recalculation workstream.
Keep the case rows below as evidence and unresolved outcomes, not separate
proofs of a completed loan-service fix.

**Direction:** native interest recalculation off for historical replay; import
source facts, reconcile complete histories/refinance chains, then apply explicit
migration corrections at the end of the complete loan service. A future
post-migration activation must start at **Fineract starts** and preserve the
accepted historical state. The current code has no verified forward-only
activation for already-migrated loans.

**Historical design-review baseline (before `9d021d4efd`):** implementation
remained open. At that point existing code and product/loan flags were unchanged; there was no sandbox replay, write, reset, boundary change, or new
reconciliation. Additional tests/experiments and complete-lifecycle baseline
construction were stopped following the operator's instruction to decide from
existing evidence. The temporary isolated test services were stopped before any
loan replay. Earlier case counts and the unaccepted 65-loan attempt remain true.

The code audit identifies two central gaps beyond the flag: historical refinance
currently depends on interim native-quote bridges, and final metric adjustments
can run on successful outcomes while other chains remain failed/blocked. Both
must be addressed as part of the shared service design, with source payoff/net
cash preserved and a global completion barrier before corrections. No new issue
row is added for each manifestation.


Working tracker for issue discovery, diagnosis, implementation and verified recovery. Keep observations separate from hypotheses, and preserve earlier evidence when updating a status. This document complements the [durable change tracker](change-log.md); implemented loan-sync changes must still be recorded there with commit and affected-loan evidence.

## Fresh/clean recalculation-off attempt

Implementation `9d021d4efd` and test/documentation follow-up `ea1321dafe` preceded
the guarded restore. Cycle `sandbox-2026-10-27-full-clean-recalc-off-a` uses the
verified captured baseline and a new target lifetime. Immutable workflow plan
`5359676d1cd44c9a9fca6f0147981662` selects all 18 services; workflow run
`e942a4ece71b4833b478a265b4296159` retains **Arissto through 2026-10-26 /
Fineract starts 2026-10-27**.

The first runner attempt failed before any service step because the restored
baseline scheduler was active. Supported `workflow resume --reload-local-fineract`
paused and verified it, then continued the same run/cycle. Native API readback
confirmed `active=false` and accounting cutoff `ACTIVE` at October 27. All seven
services preceding Loans completed and reconciled. Loan child plan
`d0c58102d06d4c5f8a897971f3828132` freezes revision 10 / `source-exact-off-v1`:
2,752 source identities, 2,276 eligible create actions and 476 explicit
quarantines. No eligible event is on/after October 27. Loan child run
`a16c564d59804e2bb2426599e41bf026` finished apply with errors; the final result above governs acceptance.

The [in-progress native observation](investigations/historical-off-clean-run-in-progress-oct27.json)
records 2 native products and 186 native loans, all with recalculation false,
13 native refinance settlements, and zero interim refinance credits, terminal
corrections or final metric alignments. These are timestamped intermediate
observations, not final portfolio counts or complete-chain acceptance.

| Current clean-run observation | Affected loans | Status / next verification |
| --- | --- | --- |
| Historical office-transfer active-loan inventory mismatches after historical-off replay. | Recorded root `loan:101`; 17 related actions blocked in the transfer cohort. Source/native inventories for the four transfer clients are preserved in the observation. | **Verified phase conflict; replay continues elsewhere.** The frozen plan shows loans `115`, `363`, `688` source-closed before the November 27, 2024 transfer, while native readback leaves them Active because corrections are deferred. This includes an ordinary terminal repayment as well as refinance payoffs. Python and native transfer guards independently require the exact active-loan inventory. Do not weaken inventory validation or post interim credits to force it through; review an explicit source-state transfer proof/ownership contract after this attempt finishes. |
| Final-metric reconciliation aborts on an observed native vector with due principal above summary outstanding. | 31 native loans in a read-only SQL screen matching `FinalLoanMetrics.read`; API confirmed representative `loan:96` (native 103). Other representative IDs: `113`, `182`, `253`, `314`. | **New clean-run reconciliation failure:** `final_metrics_due_exceeds_outstanding`; no complete reconciliation report was recorded. The same invariant is used for targets and observations. Record invalid observations as blocking per-loan mismatches and review expected-state validation for guarded correction; do not relax valid-final-target requirements or mark the native state reconciled. Runtime writer unchanged while the workflow continues. |
| Historical recalculation-off and source-exact refinance execution. | All native products/loans observed so far; 13 recorded native settlements. | **Runtime exercised, full acceptance pending.** Native flags are false and both interim bridge counts remain zero. The complete-plan correction barrier and strict final reconciliation remain enforced. |

Loan apply has now finished **completed-with-errors**: 2,249 loans succeeded,
9 recovered, 1 failed (`loan:101`, the recorded transfer-cohort root), 17 blocked,
and 476 planned quarantines. The actual complete-plan gate recorded
`final_corrections_deferred=2276`. Native readback at apply completion found
2,268 loans, all recalculation false; 1,220 refinance settlement rows; zero
interim refinance credits, terminal corrections, final metric alignments, or
source movement transactions dated on/after October 27. Partially replayed
blocked-cohort loans explain why native loan count exceeds successful outcomes.
Official loan reconciliation then failed with `final_metrics_due_exceeds_outstanding`; no complete loan report was recorded. Delinquency is dependency-blocked and the independent Savings Deposits step is running. These results do not accept the loan service or the complete migration.

The old cycle's SQLite snapshot is compressed under the new run's ignored
`.arissto-sync/evidence/` directory, outside automatic cycle retention. Durable
change record **47** owns this implementation and pending verification across
all 2,752 planned source loan identities. The attempt ran through the existing control plane; runtime writer files were
not changed during replay.

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
| LS-01 | Mixed principal/interest allocation failures contain empty pre-first-due and nonempty first-due cases; completing the first payment does not guarantee the remaining lifecycle. | 42 baseline failures. Prior 3 + current 24 have full event/metric checks; 15 histories remain unresolved. Existing fix passed all 28 eligible original empty-prefix payments in this attempt; two more such roots are source-quarantined. | **Partially recovered — 194 tests passed; current 65-loan attempt is NOT accepted (49 successful/recovered, 8 failed, 8 blocked).** | Per-loan classification below: LS-32 first-due guards, LS-33 source drift, LS-34 later insurance-fee allocation, LS-35 reversal chronology; preserve existing strict guards. |
| LS-02 | Source-exact allocation leaves principal, interest and fees unrepresented. | 24 failures; `loan:1024`, `loan:1117`, `loan:1180`. | **Open — cohort identified.** | Trace schedule availability and named fee-charge materialization independently. |
| LS-03 | Source-exact penalty allocation can fail on temporary recalculation prefixes; paid transaction copies can also lack historical charge ownership. | 72 baseline failures remain individually unverified. Loan 921 reproduced unpaid 0.26 and historical paid 0.15 cases; dependency 565 now stops on a separate 0.48 penalty remainder with a real unpaid named charge. | **Fixed for demonstrated cases — 61 tests passed; loan 921 and its four-loan cohort recovered and officially reconciled.** | Trace 565’s actual temporary/final schedule path and charge ownership before changing anything; the 921 canary does not establish portfolio recovery. |
| LS-04 | Source-exact allocation leaves principal and penalties. | 7 failures; `loan:1398`, `loan:1828`, `loan:1889`. | **Open — mixed cohort.** | Separate provisional principal handling from penalty representability. |
| LS-05 | Source-exact allocation leaves interest only; 773 fails before the first contractual due date on an empty recalculation prefix. | Loan 773: September 24, 2024 interest-only payment 1.10, first contractual due October 20. Six baseline cases (936, 938, 964, 971, 972, 983) remain individually unverified. | **Fixed for 773 — 77 Java tests passed; 54/54 events, 8/8 metrics and continuation readiness verified.** | Bounded 34-loan attempt recovered 31; three separate cutover-insurance refusals are now LS-31. Do not declare the six baseline cases recovered. |
| LS-06 | First frozen repayment precedes first frozen contractual due date; strongly associated with LS-01/02. | Initial heuristic: 47/66 combined LS-01/02 cases: 25/42 and 22/24; example `loan:10`. Comparison: 4/967 recorded succeeded loans. | **Discovery — now traced across LS-01.** Original mixed payments pass for all 28 eligible pre-first-due roots in the remaining batch; nine first-due cases differ. Other groups remain unverified. | Trace actual failing event and reversals; compare temporary prefix with full schedule. Interrupted execution order limits cohort interpretation. |
| LS-07 | Refinancing creation fails; preview path can flush an installment with null `loan_id`. | 8 create failures: `loan:103`, `loan:125`, `loan:139`, `loan:159`, `loan:172`, `loan:1784`, `loan:200`, `loan:283`. Constraint confirmed for 283 and 1784; remaining six generic HTTP 500s are candidates. | **Fix committed — live payoff and schedule previews passed 8/8; persisted predecessor state unchanged. All eight original successors are recovered and officially reconciled in the LS-31 34-loan follow-up.** Six original HTTP 500s remain individually uncorrelated. | LS-24 selection and LS-26 office-transfer planning are fixed. LS-03 recovery now reconciles 283’s native creation/disbursement/closure with the complete four-loan cohort; LS-27 now verifies its complete 34-loan closure; the LS-31 follow-up now accepts the complete 34-loan group. Historical failures and the six original generic-500 attribution caveats remain; whole-workflow recovery is separate. |
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
| LS-24 | Scoped retry selection can promote healthy product prerequisites into explicit fan-out roots when adding office-transfer cohort members. | Eight requested successors plus prerequisites select 17 loans initially; recomputation would select 2,735 loans. Transfer cohort includes `loan:101`, `loan:283`, `loan:553`, `loan:921`. No expanded apply ran. | **Fixed — 248 tests passed; frozen-plan audit selects 19 loans and one product instead of 2,735 loans. Latest 34-loan run remained bounded; see LS-27.** | Keep the bounded selector; LS-26 now permits complete scoped transfer cohorts. LS-27 now adds the required successors and consolidation dependencies: 34 loans and one product, with no sibling portfolio fan-out. LS-31 now officially reconciles all 34 selected loans without portfolio fan-out. LS-30 now confirms the separate native product-counter resequencing as expected behavior. |
| LS-25 | Frozen-plan validation detects source changes after planning; scoped loan 921 gained an October 27 repayment. | Original full-plan blocker: `loan:1613` (separate). For 921, movement `0000034318` increases 23 frozen events to 24; the prior 23 are unchanged. Before LS-28, current-source planning quarantined `loan:101`, `loan:283`, `loan:553`, `loan:921` through the refinancing cohort. | **921 diagnosed — genuine source drift; guard is correct. 280 tests passed; no runtime fix needed.** The recorded payment creation is about 79 seconds after the scoped plan observation. LS-28 now provides a verified bounded reconstruction plan for 921; four-loan replay was reconciled; exclusion also holds in the latest 34-loan retry. | Preserve Arissto through October 26 / Fineract starts October 27. Use the new LS-28 plan for the complete four-loan 921 chain; unsupported refinance histories still block. LS-27 and the separate 1613 evidence remain open. |
| LS-26 | Planner unconditionally rejects scoped loans with client office transfers, even with the full transfer cohort. | The 19-loan retry includes cohort `loan:101`, `loan:283`, `loan:553`, `loan:921`; source extraction freezes a 34-loan refinancing graph. | **Fixed — complete cohort proof, 272 tests passed, same-cycle planner accepts the cohort. LS-28 now clears the historical projection gate for the complete 921 chain. Accepted transfer remains matched after the 34-loan attempt.** | Recheck frozen cohort inventory before writes; incomplete/changed cohorts remain blocked. LS-29 follow-up recovers/reconciles the complete four-loan cohort again, with the existing transfer matched and no duplicate history. |
| LS-27 | Dependency-only retry omits successors whose disbursements create selected loans’ native refinancing payoffs. | Original eight roots select exactly 34 loans and one product; all 35 actions received outcomes. | **Recovered — officially reconciled.** LS-31 follow-up run `68b2c701797546849a349bdda2cf52ac`: all 34 recovered, zero failed/blocked, 336/336 events and 272/272 metric targets match. | Preserve this bounded acceptance and October 27 exclusion. Prior failed attempts remain historical; full portfolio/workflow readiness remains separate. LS-30’s counter effect is now classified as expected native behavior. |
| LS-28 | Historical reconstruction for 921 preserves the original snapshot and excludes the October 27 payment. | Completed recovery: `loan:101` → native 1, `loan:283` → 1144, `loan:553` → 1145, `loan:921` → 1146. | **Recovered — officially reconciled.** All source event identities and 32/32 metric targets match; October 27 payment absent. | LS-29 follow-up again recovers/reconciles all four: 46/46 events, 32/32 metric targets and continuation readiness; historical reconstruction and payment exclusion remain verified. |
| LS-29 | Existing repayment recovery tries to provision historical penalty/insurance charges omitted from the active loan charge collection. | Loan 921, May 29 movement `0000021121`: inactive penalty 5056 (1.31) and fully paid inactive insurance 5057 (0.32). Blocks 101/283/553 as one transfer cohort. | **Fixed — 310 tests passed; all four loans recovered and officially reconciled.** Existing repayments are checked without charge provisioning; strict insurance settlement checks remain. | Run `0837cac1d1b4496fac6f22e06c90035a`: 46/46 events and 32/32 metrics match, no duplicate or post-boundary transactions. Historical charges/repayment and outside-scope hashes unchanged. Details below. |
| LS-30 | Historical disbursement updates a later same-client/product loan’s native sequence counter outside selected financial writer actions. | Loan 125 inserted between 43 and 383: current product counters 1/2/3; 383 / native 261 is the expected later neighbor. Overall borrower cycles are disabled and `loan_counter` stays null.  Latest bounded retry: 2026 counter 2→3 after historical loan 1999; all noncounter fields match. | **Expected native behavior confirmed — no runtime fix needed.** 15 Java tests passed; command 40939 starts 19.57 ms before 383’s change, with no direct command/replay on 383. | Keep counter 3. Future audits must capture per-row preimages and verify only predicted counter/audit deltas; original complete column diff remains unavailable. Current accepted cohort still reconciles read-only. |
| LS-31 | Recovery expects the original cutover insurance charge to retain an obligation already moved to the approved final-metric baseline. | 172 (12.54), 360 (7.82), 515 (6.45); original charge is zero and canonical INS baseline carries the balance. | **Fixed — 325 tests passed; complete 34-loan cohort recovered and officially reconciled.** Prior alignment, full metrics and charge identity/balance proof permit read-only recovery. | Run `68b2c701797546849a349bdda2cf52ac`: zero metric adjustments, unchanged charge/transaction rows and counts. Drift or missing proof remains blocking; no insurance obligation recreated. |
| LS-32 | Nonempty first-due recalculation prefixes leave source interest unrepresented; the empty-prefix fix does not cover this path. | 331, 901, 903, 904, 907, 916, 924, 928, 939. Eight frozen-calendar refusals reproduced; 331’s native prefix leaves principal 3.25 / interest 5.43. | **Open — nine root histories unresolved.** Eight were excluded from replay; 331 was retried and retained its original failure despite sufficient frozen-calendar interest capacity. | Characterize native first-due recalculation, not just source-calendar capacity; retain strict final allocation and managed-charge isolation. |
| LS-33 | Current source refinance/payment history crosses the frozen accounting boundary or lacks a complete source-through metric snapshot. | Root 18’s chain through 2541; root 2435 and new successor 2763. October 27 movements 34336, 34340, 34341 and 34394 stay excluded. | **Blocked by source history — existing quarantines retained; no target replay of these chains.** | Require approved historical reconstruction/snapshot proof; preserve Arissto through October 26 and Fineract starts October 27. |
| LS-34 | A later pre-first-due repayment includes insurance fees that the schedule cannot represent, although the exact named source charge exists. | Roots 575 (0.11), 1330 (0.14), 1743 (1.19); dependencies 1187 (0.44), 1883 (0.59). All five named charges remain unpaid with zero paid-by links. | **Open — original empty-prefix P/I payments passed; later fee-bearing events refused.** | Trace the actual provisional/final fee representation and prove safe charge coverage; do not waive charges, forge ownership or relax the fee guard. |
| LS-35 | Historical reversal of an earlier repayment hits the native last-transaction-date guard after later repayments have been posted. | Root 2519: September 9/11/12 payments posted; the first September 17 reversal targets September 9 and fails against last user transaction September 12. | **Open — original LS-01 payment now represented; reversal batch incomplete.** | Test safe same-day reversal ordering and later-target-activity protection. Native validation uses the original transaction date; no date shift or blanket bypass. |

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

## LS-29 repair and four-loan recovery — October 27

**Recovered and officially reconciled:** 101, 283, 553 and 921 in the same
`sandbox-2026-10-26-full-clean-a` cycle, local `sandbox` / `fineract_sandbox`,
fingerprint `b9f6834b66790744`. **Arissto through: 2026-10-26. Fineract starts:
2026-10-27.** Reused immutable four-loan plan
`46b49222cc9e488ca7a4f553f27af5f9`; final run
`0837cac1d1b4496fac6f22e06c90035a` completed with four recovered loans and an
unchanged product. Official persisted reconciliation is **`ok=true`**, with
zero blocking mismatches and 28 nonblocking native schedule variances.

### Confirmed cause and safe repair

The wider LS-27 retry correctly selected the complete transfer cohort, including
already-posted loan 921. Its recovery path tried to ensure each penalty charge
and historical insurance charge **before** branching on an existing repayment.
Native loan responses omit inactive charge rows. May 29 source repayment
`0000021121` already exists as native transaction 24898, dated 2026-05-29,
amount 40.00, allocated to principal 22.70, interest 15.67, insurance 0.32 and
penalty 1.31. Exact date, amount and all components match the frozen event.

Two corresponding persisted charges are absent from the active loan response:
penalty 5056 is inactive (amount/outstanding 1.31, paid zero, no paid-by rows),
and insurance 5057 is inactive but fully paid (0.32, outstanding zero). The
insurance charge can be retrieved by its exact external ID and verified. The
writer mistook API omission for a need to create a charge; Fineract correctly
rejected the backdated creation. This reproduces without a new source payment
or staff edit. The exact historical cause of penalty 5056’s inactive/unpaid
state is not established by this repair, and no ownership row was invented.

The writer now provisions event penalty and insurance charges only when the
source repayment still needs posting. Existing repayments continue through
exact amount, date and component validation; duplicate identities still fail.
Declared fee-charge identity and amount are still checked, and final insurance
settlement verification still uses its existing direct-lookup fallback for
hidden charges. Missing, unpaid or mismatched historical insurance still
blocks recovery. New payments still require their charges before posting.
No charge is reactivated, duplicated, waived or reassigned to make recovery pass.

The first penalty-only attempt (`4c66b2d8fc934078af7be038ab94e0c3`) stopped at
the same defect for the hidden insurance charge and officially reconciled
`ok=false`; three cohort members were blocked. That failed attempt is retained.
After inspecting the fully paid insurance evidence and testing the same safe
recovery rule for it, the second attempt completed successfully. Writer code
was changed between finished attempts, with preflight and immutable-plan guards
rechecked before execution. No running attempt was modified.

### Verification and limits

**310 focused Python tests passed**, including 14 new regression methods.
Before the respective repairs, nine penalty subcases and eight insurance
subcases reproduced unwanted creation. New coverage exercises all three payment
roles, charge/transaction immutability, invalid existing payments, strict
historical insurance settlement and mandatory charge provisioning for new
payments. The older test that expected charge restoration for an already-posted
repayment now requires read-only verification of its hidden paid charge.

| Source loan | Native loan | Status | Event identities | Final metric targets | Continuation ready |
|---|---:|---|---:|---:|---|
| 101 | 1 | Recovered / closed (600) | 6/6 | 8/8 | Yes |
| 283 | 1144 | Recovered / closed (600) | 8/8 | 8/8 | Yes |
| 553 | 1145 | Recovered / closed (600) | 9/9 | 8/8 | Yes |
| 921 | 1146 | Recovered / active (300) | 23/23 | 8/8 | Yes |

Final metric alignment made **zero adjustments**. Historical charges 5040,
5055, 5056 and 5057 and native repayment 24898 have identical before/after row
fingerprints. The inactive penalty’s physical 1.31 outstanding field was not
converted into a collectible obligation or silently marked paid. The accepted
active metrics and existing transaction allocation remain unchanged.

Payment `0000034318` remains excluded from the frozen 921 source window and
absent across target transaction namespaces. There are zero scoped transactions
dated on/after 2026-10-27 and no duplicate scoped Arissto transaction identities.
The accepted transfer pair remains exactly two transactions; client transfer
history remains two rows. Global counts are unchanged: **1,167 loans, 25,273
loan transactions, zero GL entries**. Outside-scope loan, transaction, schedule,
charge, ownership, client, product and GL hashes all match, including loan 383
and loan 773. Read-only final verification also preserved all target table hashes.

The same active accounting boundary, immutable plan and parent interrupted
workflow remain in place, with the scheduler paused. **No reset, new cycle,
backend reload, COB, source write or broader workflow resume occurred.**
The original 34-loan failed run is not rewritten; its loan-773 interest failure
(LS-05) and prior outside-row finding (LS-30) remain separate work. This
acceptance closes LS-29 for the demonstrated four-loan recovery.

Machine-readable evidence: [LS-29 inactive-charge recovery](investigations/ls29-inactive-charge-recovery-oct27.json).
Regression suite: [`test_penalty_repayment_recovery.py`](../../tests/test_penalty_repayment_recovery.py).

## LS-05 loan 773 — interest allocation repair and bounded recovery

Loan 773’s first source repayment (`0000005349`, 2024-09-24) is **1.10 interest
and zero principal, fees or penalties**. It follows actual disbursement on
September 19 and precedes the first contractual due date, October 20, whose
frozen interest is 130.82. The pending native loan had only the source funding
event represented; its full first repayment installment already had that
interest capacity. The failed 1.10 is not missing from the source or too large
for the full schedule.

### Cause, reproduction and repair

Credesal inherits the non-interest-first recalculation route. Before the first
due date, `AbstractCumulativeLoanScheduleGenerator` asks the transaction
processor for early-paid amounts while the generated installment prefix is
empty. `materializeSourceExactPostDueInterest` correctly has no installment to
mutate, but the source-exact allocation guard then rejects the remaining
interest as if this were final posting. Static native routing, source/native
chronology and a focused domain reproduction identify the failure path; the
controlled live recovery below confirms the repair on the actual event.

Temporary source-exact recalculation now defers that interest only when:

- the temporary installment list is empty;
- a full loan schedule exists, with every due date strictly after the payment;
- actual disbursement exists and is not later than the payment; and
- full-schedule charged interest covers the entire declared source interest.

This is a read-only proof against the full schedule. It does not reset payments
or change installments/charges. Paid contractual interest still supplies
historical capacity; today’s outstanding counters are not used to rewrite
history. Only declared unallocated **principal** is returned to the native
early-payment calculation. Interest never becomes principal. Final posting
must represent the complete allocation; nonempty-prefix, same-day first-due,
fee, penalty and final-empty-schedule guards remain intact.

The valid before-fix suite ran 15 tests with exactly three expected failures:
interest-only empty prefix, mixed principal/interest early-payment return, and
final posting following that prefix. After the fix, **77 Java tests passed**:
16 new interest regressions, 17 penalty regressions, 39 existing processor
cases and five real-ORM preview isolation tests. Coverage includes invalid or
missing contractual evidence, insufficient interest, pre-disbursement payment,
preserved paid state, strict final posting and no interest-to-principal
conversion. Scoped Spotless formatting checks passed. Unrelated pending source
changes were preserved.

### Same-cycle execution and result

Mode: **bounded resumed loan-block recovery**, existing cycle
`sandbox-2026-10-26-full-clean-a`, local `sandbox` / `fineract_sandbox`,
fingerprint `b9f6834b66790744`. **Arissto through: 2026-10-26. Fineract starts:
2026-10-27.** Reused reviewed immutable 34-loan plan
`ced78c4c83cd4d44bbcba748c4093d49`, original eight roots and one product.
Preflight and source, schema, resource, transfer-cohort and accounting guards
passed. The Java fix was loaded through the original workflow’s frozen guarded
restart policy. All captured financial table hashes and Liquibase’s 2,103
changesets were unchanged across reload; no parent workflow was queued.

Execution run: `0f2000b00c2245ed81e4eb318e67f971`.

| Check | Observed result |
|---|---|
| Loan 773 | Native 1167, active; **54/54 event identities**, **8/8 metrics**, continuation ready. Per-loan reconciliation has no blocking mismatch. |
| Repaired payment | Native transaction **25274**, September 24, 2024: amount 1.10, interest 1.10, principal/fees/penalties zero. |
| Bounded apply | **31 recovered, three failed, zero blocked**, one product unchanged. |
| Official persisted reconciliation | **`ok=false`**, because 172/360/515 fail LS-31; zero blocking mismatches on the 31 recovered loans and 343 nonblocking native schedule variances. |
| Current target state | All 34 loans physically retain **336/336 events and 272/272 metric matches**. This readback does not override the three failed writer outcomes. |
| Metric alignment | 31 reconciled, one adjusted (773); three active accrual controls reconciled. |
| Excluded payment | October 27 movement `0000034318` remains outside the frozen 921 writer history and absent across target transaction namespaces. Zero scoped transactions dated on/after October 27. |
| Scope and identity | Exactly 35 action outcomes; no portfolio expansion, no duplicate scoped Arissto transaction external IDs. Existing transfer pair/history remains two transactions/two rows. |
| Preservation | Outside-scope loan/transaction/schedule/charge/ownership/client/product/GL hashes match, including prior loan-383 state. Final read-only verification also preserves all target table hashes. |
| Global counts | Loans remain 1,167; loan transactions 25,273 → 25,352; GL entries remain zero. |

The scheduler remains paused; the parent workflow remains interrupted; the
immutable plan and active accounting boundary are unchanged. **No reset, new
cycle, COB, source write or broader workflow resume occurred.** One guarded
backend reload was required for the tested Java change.

### Separate discovery: LS-31 cutover insurance recovery

The three current refusals are `existing_insurance_charge_outstanding_mismatch`
on loans 172, 360 and 515. Read-only inspection shows the approved final-metric
alignment has placed their insurance outstanding balances (12.54, 7.82 and 6.45)
on `ARISSTO:CRD-METRICS:INS:<native-id>`, while the original
`ARISSTO:CRD-INS-CUTOVER:<source-id>` charge is now zero. All three still have
eight matching target metrics and continuation readiness. The recovery guard
examines the older charge representation. These are separate from the 1.10
interest defect. No charge was restored, duplicated, waived or manually
reassigned, and no failure was changed to success to pass reconciliation.

LS-05 is verified for **loan 773**. The six baseline interest-only failures
remain individually unverified. The 34-loan group still requires LS-31 recovery;
the earlier LS-30 outside-row observation remains separate. Previous failed
runs and the current `ok=false` result are preserved.

Static Mifos review confirms transaction rows bind `interestPortion` separately
from `principalPortion`, and the repayment form displays the same native
components. Existing Interest/Interés labels remain applicable; the API shape
and submit contract are unchanged. No UI code was changed or browser test run.

Machine-readable results, affected native IDs and LS-31 evidence:
[LS-05 loan 773 recovery](investigations/ls05-loan-773-interest-recovery-oct27.json).
Regression suite:
[`SourceExactInterestRecalculationTest`](../../../../fineract-loan/src/test/java/org/apache/fineract/portfolio/loanaccount/domain/SourceExactInterestRecalculationTest.java).

## LS-31 repair — preserve the approved insurance baseline on recovery

**All 34 bounded loans recovered and officially reconciled** in run
`68b2c701797546849a349bdda2cf52ac`, same cycle
`sandbox-2026-10-26-full-clean-a`, local `sandbox` / `fineract_sandbox`,
fingerprint `b9f6834b66790744`. Reused immutable plan
`ced78c4c83cd4d44bbcba748c4093d49` and original eight roots.
**Arissto through: 2026-10-26. Fineract starts: 2026-10-27.**

### Confirmed cause

Final metric alignment intentionally consolidates insurance outstanding onto
`ARISSTO:CRD-METRICS:INS:<native-id>` and reduces the old cutover charge to
zero. The resumed writer nevertheless checked the original
`ARISSTO:CRD-INS-CUTOVER:<source-id>` against the frozen opening balance.
That is a representation mismatch after successful alignment, not missing debt.

| Source / native loan | Original cutover charge | Canonical baseline | Outstanding | Paid on baseline | Prior alignment version |
|---|---:|---:|---:|---:|---:|
| 172 / 1158 | 5101, zero | 5194 | 12.54 | 0.00 | 15 |
| 360 / 1161 | 5125, zero | 5199 | 7.82 | 0.00 | 18 |
| 515 / 1164 | 5149, zero | 5206 | 6.45 | 0.96 | 21 |

All three had matching frozen eight-metric vectors and continuation readiness
before the repair. Restoring the original charge would duplicate the obligation.

### Repair and safety checks

Finalization now uses a dedicated cutover recovery proof when the plan includes
final metric alignment. A previously aligned loan must have a positive alignment
version, the exact native loan and cutoff identity, continuation readiness and
all eight current metrics equal to the frozen targets. The canonical charge
must be in the active loan response and match its exact identity, owner,
insurance definition, currency, flat specified-date type and source-through
(the day before Fineract starts) due date. Its outstanding equals the frozen
insurance target; paid plus outstanding equals amount, with no waiver or
writeoff. The original cutover charge must still have the frozen identity,
owner and due date and all monetary values zero; a hidden zero original can be
retrieved by exact external ID.

Only that proven representation is accepted read-only. Missing, duplicate,
malformed, foreign or drifted evidence fails instead of creating or adjusting
debt. A changed paid/outstanding metric cannot be treated as permission to
reset staff activity. Existing native expected-state and accounting-boundary
guards remain in force. A never-aligned initial loan (version zero, no
continuation state or canonical baseline) still provisions its original opening
charge normally. Legacy plans without final metrics retain their existing
path; full re-sync handling is unchanged.

**325 focused Python tests passed**, including 15 new regression methods.
Coverage includes the three demonstrated amounts, the paid portion on 515,
full metric drift, metadata/identity/date/definition/currency failures,
malformed money, hidden original lookup, actual initial charge creation and
native lifecycle integration. The positive regression reproduced
`existing_insurance_charge_outstanding_mismatch` before the proof was added.
A live GET-only proof then passed all three loans in six reads; full financial
table hashes were unchanged during that proof.

### Same-cycle retry and acceptance

Preflight, source/resource/schema, full transfer-cohort and active accounting
boundary guards passed before the retry. The original two-worker, 30-second
transient pause and three-attempt policy was retained. No running attempt was
modified.

| Check | Verified result |
|---|---|
| Apply | **34 recovered**, zero failed/blocked/quarantined; one product unchanged. Exactly 35 selected action outcomes. |
| Official persisted reconciliation | **`ok=true`**, zero blocking mismatches; 448 nonblocking native schedule variances remain visible. |
| Source identities / metrics | **336/336 event identities**, **272/272 target metrics**, continuation ready for every loan. |
| Final metric pass | All 34 reconciled, **zero adjustments**; six active accrual controls reconciled. |
| Insurance debt | Charge rows unchanged across the retry, including zero original charges and the three canonical balances above. No restored, duplicated, waived or reassigned charge. |
| Native counts | Unchanged: **1,167 loans, 25,352 loan transactions, zero GL entries**. |
| Row preservation | Transaction, schedule, charge, paid-by/mapping, client, transfer-history and GL hashes match. Outside-scope loan/product hashes match. Loan rows changed within the authorized cohort and their state reconciles; exact column preimages were not captured. |
| October 27 payment | Movement `0000034318` remains excluded from the frozen 921 writer history and absent across target namespaces. Zero scoped transactions dated on/after October 27. |
| Duplicate/transfer checks | No duplicate scoped Arissto transaction IDs; accepted 921 transfer pair remains two transactions and client transfer history remains two rows. |
| Control plane | Same immutable plan, cycle, fingerprint and active boundary; scheduler paused, parent workflow interrupted. |

This Python-only repair needed **no backend reload, reset, new cycle, COB,
source write or broader workflow resume**. Original failed attempts keep their
recorded outcomes and `ok=false` reports. This acceptance completes the original
eight-root refinancing group’s bounded 34-loan recovery, including LS-07,
LS-24, LS-27, LS-29 and the demonstrated LS-05 loan 773. It does not declare
all baseline issue cohorts or the full workflow recovered. The earlier LS-30
outside-row forensic question remains separate; no outside-row change recurred
in this attempt.

Machine-readable evidence:
[LS-31 cutover insurance recovery](investigations/ls31-cutover-insurance-recovery-oct27.json).
Regression suite:
[`test_cutover_insurance_baseline_recovery.py`](../../tests/test_cutover_insurance_baseline_recovery.py).

## LS-30 investigation — loan 383’s expected native product-counter update

**Conclusion: expected native counter resequencing; no runtime correction.**
The bounded writer did not import or replay loan 383. Disbursing the selected
historical loan 125 made an existing later loan the third disbursed account on
the same product, so native Fineract updated its `loan_product_counter`.
Restoring counter 2 or suppressing the native update would leave the sequence
inconsistent with the actual disbursement history.

| Same client / product 2 | Native loan | Actual disbursement | Current product counter | Overall borrower counter |
|---|---:|---|---:|---|
| Source 43 | 40 | 2023-05-19 | 1 | null |
| Source 125 | 1154 | 2023-07-24 | 2 | null |
| Source 383 | 261 | 2023-12-16 | 3 | null |

Product 2 has both `include_in_borrower_cycle=false` and
`use_borrower_cycle=false`. These do not turn off the separate product sequence
counter. Native code gates the overall borrower counter on the include flag,
while incrementing the product counter whenever the two loans share a product.
Cycle-based product rules are disabled here; no repricing follows this update.

### Evidence and causal path

- Original bounded run: `4b0d62a7a0034254b67cba8cfbbc5fbd`, immutable plan
  `ced78c4c83cd4d44bbcba748c4093d49`; 383 was not one of its 34 selected loans.
- Audit command **40939**, `SOURCEEXACTREFINANCINGDISBURSE`, targets native
  1154 / source 125, uses actual disbursement 2023-07-24 and completed HTTP 200.
  It started **2026-10-27 19:52:43.636043 UTC**; loan 383’s row modification is
  **19:52:43.655613 UTC**, **19.57 ms later**. No direct command on 383 occurred
  during that bounded retry.
- The handler calls `disburseSourceExactTopupLoan`, then
  `disburseLoanInternal`. That method invokes native `updateLoanCounters`.
  `FIND_CLIENT_OR_JLG_LOANS_DISBURSED_AFTER` loads the same client’s loans with
  actual disbursement strictly later than the inserted date. The equivalent
  read-only query selects **383 only** in this case.
- `updateLoanCounter` increments the later same-product loan and assigns the
  inserted loan its proper position, then saves the related loan entities.
  Real `Loan` setters change counter fields; JPA versioning and the auditable
  base class explain accompanying version/last-modified bookkeeping.
- The original retry’s outside-scope transaction, schedule, charge, ownership,
  client, product and GL hashes all matched. Only the aggregate outside
  `m_loan` hash changed. Its postimage hash still exactly matches the current
  **1,133 outside loan rows**. Loan 383 remains product counter **3**, version
  **20**, with the same original modification timestamp across later retries.
- The native API returns `loanProductCounter=3`, `loanCounter=null`; an
  independent chronological ranking of current disbursed same-product loans
  gives 1, 2 and 3. Existing disbursement recovery has not repeatedly shifted
  the counter.

This confirms the counter effect and excludes a selected-action expansion or
normal out-of-scope payment replay as the explanation. **The original complete
per-row before-image was not captured.** We cannot reconstruct an exhaustive
historical column diff or independently certify every original noncounter
`m_loan` value. The inferred prior counter 2 is reproduced from the chronology
and native algorithm; it is not presented as a separately retained old row.

### Testing and operating-guidance correction

**15 Java tests passed**: five new native counter characterizations and ten
existing disbursement-service cases. The new tests use the real native counter
stage and real `Loan` entities, with repository selection/persistence mocked.
They verify insertion of 125 before 383 (new ordinal 2, later ordinal 3), shifts
of multiple later same-product loans, unchanged other-product counters, no
change to previous loans when appending, and the separate enabled-borrower-cycle
case. Domain and embedded summary comparisons, with nonzero principal and paid/
outstanding fixtures, show only the expected counter changes;
EclipseLink’s non-persistent lazy holders are excluded. This is not a full
historical ORM before-image reconstruction. Scoped Spotless checks passed.

No runtime bug was found in this case, so no counter, transaction or financial
writer behavior was patched. The operating guide now distinguishes bounded
**source financial actions** from native related-loan **counter metadata**.
Future audit captures must include potential later-client-loan neighbors before
historical disbursement and retain per-row counter/audit values plus full and
noncounter hashes. Only a proven predicted counter delta with corresponding
version/audit changes may be classified as expected; other row changes still
require investigation. Do not add 383 to financial replay or globally ignore
outside loan-row mismatches.

### Preserved sandbox and accepted cohort

This was a **read-only same-cycle investigation** in
`sandbox-2026-10-26-full-clean-a`, local `sandbox` / `fineract_sandbox`,
fingerprint `b9f6834b66790744`. **Arissto through: 2026-10-26. Fineract starts:
2026-10-27.** A read-only recheck of accepted run
`68b2c701797546849a349bdda2cf52ac` still returns **`ok=true`**, zero blocking
mismatches and the same 448 nonblocking schedule variances. Its stored
reconciliation record was not replaced and no new financial run was started.

All captured target financial-table hashes, including loan rows, match before
and after this investigation. October 27 movement `0000034318` remains absent
across namespaces; there are zero post-boundary transactions in the accepted
34-loan scope. The scheduler stays paused, parent workflow interrupted and
active accounting boundary unchanged. **No replay, reset, new cycle, backend
reload, source write or broader workflow resume occurred.**

Machine-readable evidence:
[LS-30 loan 383 counter behavior](investigations/ls30-loan-383-counter-behavior-oct27.json).
Regression suite:
[`HistoricalDisbursementLoanCounterTest`](../../../../fineract-provider/src/test/java/org/apache/fineract/portfolio/loanaccount/service/HistoricalDisbursementLoanCounterTest.java).


## LS-01 loan 10 — mixed allocation recovery, October 27

Loan 10 failed on movement `0000000061`, **May 13, 2023**, one day before
its first contractual due date. The frozen payment is **126.00: principal
27.37, interest 98.63, fees and penalties zero**. Its first two contractual
installments provide sufficient capacity: principal 18.95 + 19.92 and interest
101.92 + 100.95. The new scoped lifecycle matches the original full plan;
this case is a recalculation defect rather than source drift.

The temporary pre-first-due recalculation prefix is empty. Principal 27.37 may
return for native early-principal handling, but the previous guard rejected the
98.63 interest remainder. The LS-05 fix in `d07e76ea0ca326c471c8a152cd1e9eafd04115cd`
already resolves this case by proving future charged-interest coverage read-only.
No additional runtime patch, backend restart, or charge-state workaround was
needed. Final posting retains strict component checks.

Three new regression cases exercise the exact mixed payment: provisional
principal-only return followed by final 18.95/8.42 principal and 98.63 interest
allocation; rejection without contractual coverage; and final rejection with
insufficient principal capacity. The relevant Java suites passed **80 tests**
(19 interest, 17 penalty, 39 processor and 5 managed-state isolation); scoped
Spotless passed. These tests isolate allocation behavior; the live retry below
validates the complete loan lifecycle.

| Recovery control/result | Observed evidence |
| --- | --- |
| Mode and cycle | Bounded resumed loan-block recovery; `sandbox-2026-10-26-full-clean-a`; no reset or new cycle. |
| Target and dates | Local `sandbox` / `fineract_sandbox`, fingerprint `b9f6834b66790744`; **Arissto through 2026-10-26; Fineract starts 2026-10-27**. |
| Immutable plan | `d7ed6dfa193f4980bffb3b6ab81c8750`; root `loan:10`, closure only `loan:10` + unchanged `product:00010`. Planning preserved all financial table hashes; preflight and apply guard passed. |
| Completed run | `2a0f07b8b7af41239551968bf3723e56`; one recovered loan, unchanged product, no failed/quarantined entities. Native loan remains ID 10 and closes as repaid (600). |
| First payment | Native transaction 25353, May 13, 2023, exact 126.00 split: principal 27.37 / interest 98.63 / fee 0 / penalty 0. |
| Event and metric reconciliation | All 35 non-reversal events represented plus one repayment reversal in the 36-event lifecycle; 37 native transactions including the explicit adjustment, one reversed. All 8 frozen metrics match; continuation ready; official reconciliation `ok=true`, zero blocking mismatches. |
| Explicit adjustment and limits | Existing planned cutover adjustment `ARISSTO:CRD-CUTOVER:10`, dated January 14, 2026, applies 91.70 interest. Six native recalculated schedule variances remain nonblocking. Metric agreement includes this explicit adjustment; it is not evidence of exact replay-only schedule parity. |
| Preservation | All 1,166 outside-scope loan rows and their transactions, schedules, charges and ownership mappings unchanged; all clients, products and GL unchanged. Accepted 34-loan cohort is included in those preserved rows. |
| Exclusions and controls | October 27 payment `0000034318` absent across all transaction namespaces; no scoped transaction on/after October 27. GL stays empty, scheduler stays paused, parent workflow stays interrupted, cutoff and immutable plan unchanged. No portfolio-wide replay, reset, or boundary advance. |

Resolution applies to **loan 10 only**. The other 41 baseline LS-01 cases
remain individually unverified; LS-06 causality is now demonstrated for this
case, not for the entire associated cohort. Durable change tracking records
this regression coverage and verified recovery separately from the LS-05 fix.

Evidence: [loan 10 mixed allocation recovery](investigations/ls01-loan-10-mixed-allocation-recovery-oct27.json).


## LS-01 loans 1036 and 1040 — same-fix verification and bounded recovery

Both failures are the same empty temporary pre-first-due recalculation prefix
confirmed on loan 10. All four newly planned lifecycles match the original full
plan; no source drift is needed to explain either failure.

| Root loan / native ID | First failing frozen payment | First contractual due | Allocation capacity and cause |
| --- | --- | --- | --- |
| 1036 / 557 | `0000008218`, February 28, 2025: 100.00 = principal 88.25 + interest 11.75; mobile collection; no fee/penalty. | March 15, 2025 | First principal 69.73 + second 18.52 represent 88.25; first charged interest 25.32 covers 11.75. Empty provisional prefix previously left both components in the error. |
| 1040 / 558 | `0000008170`, February 28, 2025: 90.00 = principal 30.33 + interest 59.67; no fee/penalty. | March 17, 2025 | Principal spans three installments: 22.44 + 7.31 + 0.58; first charged interest 151.89 covers 59.67. The same provisional-prefix guard previously rejected the accompanying interest. |

The existing LS-05 runtime fix (`d07e76ea0ca326c471c8a152cd1e9eafd04115cd`)
applies unchanged. Six new parameterized regression invocations cover both
payments: principal-only provisional return without changing full-calendar paid
state, exact final allocation across two/three installments, rejection without
future contractual coverage, and strict final rejection with insufficient
principal capacity. The relevant Java suites passed **86 tests**: 25 interest,
17 penalty, 39 processor, 5 managed-state isolation. Scoped Spotless passed.
No new runtime patch, backend reload, managed-charge workaround, or source write
was performed.

Loan 1036 has a native payoff funded by successor 1253, which itself has a payoff
funded by 1544. The required closure is therefore exactly **1036, 1040, 1253,
1544**, with two existing products and existing collateral setup. Healthy product
prerequisites were not promoted into portfolio-wide retry roots.

| Recovery control/result | Observed evidence |
| --- | --- |
| Mode and cycle | Bounded resumed loan-block recovery in `sandbox-2026-10-26-full-clean-a`; no reset or new cycle. |
| Target and dates | Local `sandbox` / `fineract_sandbox`, fingerprint `b9f6834b66790744`; **Arissto through 2026-10-26; Fineract starts 2026-10-27**. |
| Immutable plan | `fd84f6cee84f40f5bd126d353e5a6534`; explicit retry roots 1036/1040; four-loan closure plus `product:00001`, `product:00010`, `collateral-product:arissto`. Preflight/apply guard passed. Planning changed no financial table hashes. |
| Completed run | `d92de4980bf3466cab646f1b2f7d4034`; 1036/1040 recovered; 1253/1544 created as native IDs 1168/1169. All three setup actions unchanged; no failed/quarantined entities. |
| Exact first payments | Native transaction 25389: principal 88.25 / interest 11.75; transaction 25391: principal 30.33 / interest 59.67. Both dated February 28, 2025; no fee/penalty. |
| Event and metric checks | 40 frozen events: **38/38 non-reversal events represented and both reversals reconciled**. **32/32 frozen metrics match**; all four continuation checks ready; one active-loan accrual control reconciled. |
| Final native states | 1036/557, 1253/1168 and 1544/1169 repaid (600); 1040/558 active (300). |
| Official reconciliation | `ok=true`, zero blocking mismatches; 258 nonblocking variances retained: 256 native schedule variances plus fee-balance and full-native-total comparisons for 1040. |
| Explicit financial adjustments | Native refinance component bridges: 30.74 for 1036→1253 and 3.22 for 1253→1544; post-topup residuals both zero. Separate 65.03 interest cutover adjustment on 1544. Existing metric alignment ran on all four loans; exact handoff metrics include these approved operations. |
| Outside scope and counters | All **1,165 outside-scope loan rows**, transactions, schedules, charges and ownership mappings unchanged; all clients, products and GL unchanged. The only outside same-client neighbor, 840/456, predates the new disbursements; its captured counters, version, timestamps, full-row and noncounter hashes stayed identical. Prior accepted loan 10 and 34-loan cohort are included in preserved rows. |
| Boundary and controls | October 27 payment `0000034318` absent across all transaction namespaces; no scoped transaction dated on/after October 27. Scheduler paused, parent workflow interrupted, cutoff and plan unchanged. No reset, portfolio replay or boundary advance. |

The two loan-1040 comparison variances are retained explicitly: source fee
balance 19.80 versus full native schedule fee balance 75.14, and source total
outstanding 4815.40 versus full native 4870.74. Both differ by 55.34. These
full-schedule comparisons are nonblocking under the existing reconciliation
contract; all eight cutoff metrics still match. This recovery does **not** claim
exact native/source schedule or full-future-schedule parity.

LS-01 resolution is now demonstrated for **10, 1036 and 1040**; the other **39
baseline failures** remain individually unverified. Successors 1253 and 1544
completed only as required dependencies. The parent portfolio workflow remains
incomplete.

Evidence: [1036/1040 bounded recovery](investigations/ls01-loans-1036-1040-recovery-oct27.json).


## Remaining 39 LS-01 roots — investigation and partial bounded retry

The existing LS-05 fix remains unchanged. Direct tracing against the original
frozen plan identifies **30 mixed payments before the first frozen contractual
due**, and **nine first-due capacity cases**. This compares the matched failing
payment and native prefix, rather than treating the earlier LS-06 population
heuristic as proof of a shared cause. The first-due source/native distinction
matters: loan 331’s frozen first interest row is 32.55, while its native prefix
has 27.12; source-calendar capacity alone did not fix actual replay.

The new frozen-data regression class exercises **108 cases**: 30 empty-prefix
successes with missing-proof and strict-final negative controls (90), nine exact
native first-due remainders, eight frozen-calendar first-due refusals, and one
isolated 331 frozen-calendar capacity comparison. Together with the existing
allocation and managed-state suites, **194 unique tests passed**; scoped
Spotless passed. First-due unit fixtures omit fees to isolate the P/I guard;
actual replay retains full fee/penalty ownership checks. No production code,
charge-coverage policy or backend runtime was changed or reloaded.

The original 39-root closure contained 97 loans. Fresh source extraction also
found required successor 2763 after the boundary and unselected reviewed voided
attempt 2723, yielding a **99-loan plan inventory**, not 99 authorized writes.
The eight diagnosed first-due roots have a separate 24-loan dependency closure.
The initially eligible 31-root/73-loan group lost two complete chains to current
source quarantines: 18→…→2541 and 2435→2763. The executed selection was therefore
**29 roots plus 36 required dependencies = 65 loans**. Every selected lifecycle
matches the original frozen plan. Quarantines, new source topology and excluded
roots were reviewed before execution; no dependency or date guard was bypassed.

| Control/result | Evidence |
| --- | --- |
| Mode/target | Bounded resumed loan-block recovery in existing cycle `sandbox-2026-10-26-full-clean-a`; local `sandbox` / `fineract_sandbox`, fingerprint `b9f6834b66790744`. No reset, new cycle or parent-workflow resume. |
| Accounting dates | **Arissto through 2026-10-26; Fineract starts 2026-10-27**. Both remain unchanged. |
| Immutable plan and selection | `6d9e4c03eb714e7ea590e75b72789c80`; explicit 29-root selector closes to exactly 65 loans and three unchanged setup actions. Standard full source/target apply guard passed before writes. |
| Completed attempt | `2a77b6166a764a4299045875b0b63c5a`; **completed-with-errors**: 24 recovered roots, 25 created dependencies, 8 failed loans, 8 blocked dependencies. |
| Official reconciliation | **`ok=false` — cohort NOT accepted.** Failed/blocked count 16, zero blocking mismatch entries among compared successes, 1,543 nonblocking variances. Zero mismatch entries alone do not establish acceptance. |
| Successful loan checks | All 49 successful/recovered loans have full event/metric checks: **550/550 non-reversal events + 8 reversals**, **392/392 metrics**, continuation ready; 15 active-loan accrual controls reconciled. |
| Remaining event coverage | Entire selected plan freezes 756 events (744 non-reversal, 12 reversals); 587 non-reversal events are currently represented across successful and partial loans. Failed/blocked histories are incomplete. |
| Alignment/adjustment qualifications | Writer reports 49 metric reconciliations and 44 metric-adjustment operations. Official report retains 30 applied adjustment annotations out of 62 adjustment records, including explicit refinance/cutover bridges. This is not replay-only or full-future-schedule parity. |
| Outside financial preservation | All 1,140 outside loan IDs and every captured noncounter business field preserved; outside transactions, schedules, charges, paid-by/mapping rows, clients, products and GL hashes match. |
| Expected counter metadata | Source 2026/native 933 product counter **2→3** after inserting historical source 1999/native 1178, dated May 26, 2026. Exact before/after row hashes and unchanged noncounter hashes prove only permitted counter/audit metadata changed; native borrower-cycle flags remain false. No counter restore or financial replay of 2026. |
| Payment exclusion | Movement **0000034318** remains absent across namespaces; newly observed October 27 movements **34336, 34340, 34341 and 34394** are also absent. Globally zero native transactions dated on/after October 27. |
| Final controls | Scheduler paused, parent workflow interrupted, plan/cutoff unchanged. Read-only verification/failure tracing changed no captured core table hashes. Global totals: 1,197 loans, 26,821 loan transactions, zero GL entries. |

The outside-counter row above is LS-30 behavior, not an unexplained outside
financial mutation. Its exhaustive noncounter hashes were captured before this
attempt. The preserved outside rows include earlier accepted loan 10, the
1036/1040 cohort, the 34-loan cohort, and all excluded first-due/source-quarantined
loans.

### Root outcomes — all 39 investigated

**24 root histories now have full event/metric checks.** Four more original
LS-01 payments passed before later failures; nine first-due cases and two source
chains remain unresolved. Thus the original 42-loan group has 27 histories with
full checks (three earlier, 24 here) and **15 unresolved histories**. The current
65-loan attempt remains unaccepted as a whole.

| Root loan | Existing empty-prefix fix / observed outcome | Progress status |
| --- | --- | --- |
| 1059 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 1084 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 1270 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 1330 | Original mixed payment represented; later early insurance-fee allocation refused. | Partial; LS-34 open. |
| 1458 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 15 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 1671 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 1743 | Original mixed payment represented; later early insurance-fee allocation refused. | Partial; LS-34 open. |
| 1781 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 18 | Same-fix unit case, but required chain contains after-boundary source history. | Not retried; LS-33 quarantine retained. |
| 1942 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 1957 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 2396 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 2430 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 2435 | Same-fix unit case, but required chain contains after-boundary source history. | Not retried; LS-33 quarantine retained. |
| 2519 | Original mixed payment represented; September 17 reversal of the September 9 payment refused. | Partial; LS-35 open. |
| 2586 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 2588 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 2653 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 2704 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 2705 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 2706 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 3 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 331 | Native first-due prefix still leaves principal 3.25 / interest 5.43; source calendar capacity was insufficient as an integration proof. | Retried; LS-32 open. |
| 400 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 575 | Original mixed payment represented; later early insurance-fee allocation refused. | Partial; LS-34 open. |
| 653 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 677 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 680 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 894 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 9 | Original mixed payment represented; all source events and 8/8 metrics verified. | Full loan checks verified; cohort run still unaccepted. |
| 901 | Distinct nonempty first-due prefix; frozen-calendar guard refusal reproduced. | Not retried; LS-32 open. |
| 903 | Distinct nonempty first-due prefix; frozen-calendar guard refusal reproduced. | Not retried; LS-32 open. |
| 904 | Distinct nonempty first-due prefix; frozen-calendar guard refusal reproduced. | Not retried; LS-32 open. |
| 907 | Distinct nonempty first-due prefix; frozen-calendar guard refusal reproduced. | Not retried; LS-32 open. |
| 916 | Distinct nonempty first-due prefix; frozen-calendar guard refusal reproduced. | Not retried; LS-32 open. |
| 924 | Distinct nonempty first-due prefix; frozen-calendar guard refusal reproduced. | Not retried; LS-32 open. |
| 928 | Distinct nonempty first-due prefix; frozen-calendar guard refusal reproduced. | Not retried; LS-32 open. |
| 939 | Distinct nonempty first-due prefix; frozen-calendar guard refusal reproduced. | Not retried; LS-32 open. |


### Follow-up blockers and retained partial state

- **LS-32:** 331 reproduces its original principal 3.25 / interest 5.43 remainder;
  901, 903, 904, 907, 916, 924, 928 and 939 were not retried because tests show
  the same first-due guard remains. The 331 positive capacity test intentionally
  does not claim native replay success.
- **LS-33:** 18 is held by its quarantined chain through 2541 (October 27 payment
  34394 and missing complete metric snapshot). Loan 2435 has October 27 payment
  34336 and payoff 34340 into successor 2763, disbursed via 34341; remaining
  schedule signature and source-through snapshot proofs fail. These chains were
  left untouched; no historical reconstruction was invented.
- **LS-34:** 575 stops May 16, 2024 on fee **0.11** before first due May 18;
  1330 stops August 4, 2025 on fee **0.14** before August 7; 1743 stops March 16,
  2026 on fee **1.19** before September 27. Dependencies 1187 (**0.44**) and 1883
  (**0.59**) stop at analogous early fee-bearing payments. Their exact named
  charges exist, remain unpaid, and have zero paid-by ownership rows. This
  identifies fee representability as the next investigation; no broad fee
  deferral or managed-charge mutation was added.
- **LS-03 follow-up:** dependency 565 stops October 17, 2024 with **0.48 penalty**
  remaining. Named charge 5467 exists, outstanding 0.48 and zero paid-by rows.
  The proven 921 canary does not establish the cause/stage of this separate
  refusal; temporary versus final schedule and charge ownership need tracing.
- **LS-35:** loan 2519’s September 9, 11 and 12 payments are represented, but the
  first September 17 reversal targets September 9 while later repayments remain.
  `LoanAdjustmentServiceImpl` validates **the original transaction date** against
  the last user transaction date; the native refusal names September 12.
  Safe same-day reversal ordering and later-target-activity guards require a
  separate test/repair; source reversal dates were not shifted.

The eight attempt failures are **331, 565, 575, 1187, 1330, 1743, 1883, 2519**.
The eight dependency blocks are **601, 622, 708, 818, 1014, 1416, 1780, 2540**.
Successfully posted source events remain in place. Failed loans retain partial
histories and their provisioned unpaid charges, including 331’s prior 0.33
insurance charge; all seven inspected failed-event charges have **zero paid-by
links**. No manual charge waiver, reactivation, ownership fabrication or reset was used
to force acceptance. Do not treat these partial loans or the
parent portfolio as ready for handoff.

Evidence: [remaining LS-01 investigation and retry](investigations/ls01-remaining-cohort-investigation-retry-oct27.json).


## October 28 recovery checkpoint

The dated insurance fix and native terminal corrections passed full loan apply:
2,288 recovered, zero failed, 464 quarantined; 429 active metrics/accrual controls
reconciled and 1,859 inactive metric skips. Independent readback passed all 11
insurance and 19 terminal cases. The workflow remains incomplete because final
reconciliation compared the transformed continuation schedule with original
settlement rows. The strict continuation validator and 329 focused tests are
recorded in [the repair investigation](loan-failure-pattern-repair-oct27.md#october-28--final-apply-accepted-continuation-reconciliation-correction).
Reconciliation acceptance and the remaining workflow services are pending.
