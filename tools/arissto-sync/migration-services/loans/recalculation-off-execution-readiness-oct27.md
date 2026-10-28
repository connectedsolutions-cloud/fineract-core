# Recalculation-off execution readiness — October 27

## Requested execution and result

The operator requested execution of the prior conversation's handoff in thread
`01a17e0f-7ff3-7523-83fa-9d571fffc8f3`. The requested run remains **fresh/clean**,
`local-full-sync`, all **18 services**, local disposable `sandbox` /
`fineract_sandbox`, **Arissto through 2026-10-26 / Fineract starts 2026-10-27**.
Recalculation must stay off on both products and loans throughout this run.

**Execution did not reach reset or executable planning.** Read-only inspection
confirmed that the required shared historical refinance behavior is unsupported
by the current implementation. This meets the handoff's explicit stop condition:
“If the settlement path cannot satisfy this, report a blocker before
resetting/running.” No runtime implementation or completed acceptance is claimed.

## Concrete code evidence

All paths below are relative to `fineract-core`.

| Required behavior | Current evidence | Consequence |
| --- | --- | --- |
| Historical interest recalculation off | `tools/arissto-sync/config/loans.json:78` and `arissto_sync/loans.py:41,332,4186` still require daily recalculation on. | Changing the JSON flag alone is rejected by `LoanContract.load`; a new CLI plan from current code would have the wrong policy. |
| Create/approve refinance using recorded source settlement | `fineract-provider/src/main/java/org/apache/fineract/portfolio/loanaccount/serialization/LoanApplicationValidator.java:671,1965,1995,2160` validates against ordinary `retrieveLoanPrePaymentTemplate` amounts, including during creation/preview and approval. | Supplying exact source allocations only at disbursement does not fix earlier quote validation. The off-mode ordinary quote can include future scheduled interest. |
| Disburse refinance using source settlement semantics throughout | The same validator's `validateSourceExactRefinancingLoans` at line 2010 delegates to ordinary `validateRefinancingLoans`; `LoanWritePlatformServiceJpaRepositoryImpl.java:442` invokes it before processing the source allocation. | The source-exact disbursement command still has a native quote gate. Removing the Python bridge alone can reject a source-valid successor. |
| No interim migration credits | `arissto_sync/loans.py:6055` posts a prepayment component goodwill bridge; the refinance-disbursement path at lines 7508–7548 posts a second residual goodwill bridge before accepting closure. | Both bridge paths conflict with end-only correction. Removing only the first bridge is insufficient; the immediate full-close assertion also needs coordinated historical settlement behavior. |
| Corrections wait for complete history and all chains | `_apply_loan_lifecycle` at lines 7709–7758 can write cutover insurance and terminal adjustments during per-loan finalization. `apply_loan_plan` at line 8741 adjusts each successful loan while skipping failed/blocked outcomes. | The existing final loop is not a complete-service success barrier. Moving just that loop cannot establish the requested ordering. |
| No premature off-mode parity gate | `_apply_loan_lifecycle` at line 7782 runs `_assert_active_cutover_components` before final metric alignment for policies other than `daily-native-v1`. | The historical-off policy needs an explicit phase contract, preserving strict final reconciliation rather than requiring final parity before corrections. |

The native writer already consumes source allocation amounts for account
transfers and subtracts their total from successor cash. That is useful existing
behavior, but it does not remove the earlier ordinary quote validation or the
Python close/bridge requirements. No claim is made that every refinance fails;
the unsupported point is the shared guarantee needed for this full run.

## Operational observations

- Workflow inspection resolves the same 18 services and definition hash
  `0c61a1fdc2edcb9e8438ece259b6eab4fbf2236fc7ed2a2b81c2650edc5e7d24`.
  Its structural blockers are empty. `cheque-history` remains `testing`,
  explicitly allowed by the existing workflow policy. Structural readiness does
  not certify historical-off loan behavior.
- Preserved cycle: `sandbox-2026-10-26-full-clean-a`; recorded local fingerprint
  `b9f6834b66790744`. The preserved workflow run
  `2490d7f94fe841c196402e20bc1fa3aa` is `interrupted`, with 10 completed,
  2 failed and 6 blocked service steps. This is historical state, not a fresh
  API/database identity verification or permission to resume it.
- Storage health reports 1,075,631,240 bytes against its 1 GiB warning budget,
  with zero active workflows. No retention was manually applied.
- Existing unrelated mora/interest-pause backend changes and dirty loan notes
  were observed and preserved. No new isolated stack or exploratory replay
  campaign was started.

## Remaining prerequisite work

Implement the historical-off product/loan policy, plan revision and native
readback guards together with a historical refinance contract spanning
application/preview, approval, disbursement and full-close acceptance. Keep
ordinary operational refinance validation unchanged. Freeze and verify exact
source allocations, predecessor/successor identities, net cash, source date
boundary and the complete connected history. Remove both interim goodwill
bridge paths from historical replay without substituting synthetic payments.

Separate genuine dated source operations from migration corrections, introduce
the complete financial replay barrier, and defer final corrective writes until
that barrier passes. Keep failures and source-boundary quarantines visible.
Then complete the focused implementation checks in the
[handoff](recalculation-off-full-sync-handoff-plan.md), inspect Mifos behavior,
and commit/register the coherent implementation before returning to the guarded
restore/new-cycle/executable-plan gates.

The current execution request supplies authorization to pursue that plan; this
assessment is a recorded stop at its unsupported-behavior gate, not a request
for another reset permission. No reset, new cycle, plan, approval/start, retry,
financial target write, recalculation toggle, scheduler release or Arissto write
was performed. Baseline restoration/protected-access readiness and native target
identity were not revalidated because execution stopped before that phase.
