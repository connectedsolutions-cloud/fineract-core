# Actual loan sync and COB acceptance — 2026-10-26

**Passed for source loans 1572 and 1826 through the normal loan sync CLI.**
This closes the product-configuration and source-window planning blockers
identified in the [earlier COB diagnostic](pause-cob-canary.md) and replaces the
archived-lifecycle limitation of the [first repair proof](cob-continuation-repair.md).
The actual planner extracted Arissto, the apply coordinator performed all loan
steps and final reconciliation, and the official reconciler accepted the run.
No archived lifecycle was injected or manually aligned after apply.

## Execution scope

- Local disposable `sandbox`, fingerprint `b9f6834b66790744`.
- **Arissto through 2026-10-19; Fineract starts 2026-10-20**. The active tenant
  boundary was preserved; no reset, new cycle, production write, or Arissto write.
- This is an explicitly scoped initial proof-loan block execution within the
  current target lifetime, using the supported `--proof-namespace` option. It
  is not a fresh/clean whole-tenant workflow, resumed workflow, or full re-sync.
- Namespace `loan-flow-oct26`; isolated tracking state
  `.arissto-sync/pause-cob-proofs/loan-flow-oct26/state.sqlite3` protects canonical
  cycle mappings. The real existing line `00010` product was updated by the
  normal product writer. Loan creation used that product, rather than a cloned
  product prepared outside the planner.
- Plan `b8431e4ce9fc4b12922d2c8674a38c30`, no blockers or quarantines. Saved CLI
  plan JSON SHA-256:
  `3501e63e65fce02e6d4e27a2d47f3bf08ddc246ab502fca6b2fe820344be7978`.
- Apply run `91f7b1ef8b23403399ab82759daa9a0c`: one product action succeeded,
  two loans succeeded, two metric sets adjusted/reconciled and two shared
  accrual-control sets reconciled. Source 1572 → native **2774**;
  source 1826 → native **2773**. Both loans have recalculation enabled.

## Planning repairs

The existing product had recalculation disabled. An `update-product` plan now
permits only the approved false-to-true enablement and its fixed daily,
non-compounding settings, alongside already-reviewed migration capabilities.
An already-enabled product with different recalculation settings still conflicts.
The frozen pre-update contract hash detects target drift; a completed update
can be recovered on retry without another PUT. Existing loan contracts are
separately persisted; enabling product defaults is not a bulk loan-conversion
operation. Normal fresh product creation already enables recalculation.

1572 had a later ordinary repayment on October 26 (principal 21.81, interest
8.19), beyond the fixed source window. The planner previously combined that
current history with an October 19 close and quarantined the loan. Planning
and apply guard now share a conservative source-window projection:

1. Require an exact source-day close and active status both then and now.
2. Admit later ordinary/mobile payments only, with complete movement counts,
   no reversals, no refinance relationships and no schedule revisions.
3. Independently corroborate all retained principal and interest payments
   against the dated close's paid counters.
4. Bound movements and associated charge details through the inclusive source
   day, restore historical balance fields from that close, and freeze explicit
   excluded-event metadata in the plan. The later repayment was not replayed.

Missing evidence, changed status, reversals, revisions, refinance, unsupported
later events or inconsistent paid counters keep the original quarantine. This
is not general temporal reconstruction and does not remove portfolio-wide
source-quality guards. The same projection is re-read during apply validation.

## Reconciliation and COB results

Official `reconcile --run` returned `ok: true`, no blocking mismatches, no failed
or quarantined entities. All eight opening metrics matched the source close,
`continuationReady` was true, and dated shared freeze controls matched. There
were 103 explicitly nonblocking native recalculated-schedule comparisons;
source schedule identity is not an activation gate. No GL entries were linked
to either proof loan before COB, including the final metric adjustments.

| COB date | 1572 accrued interest | 1572 mora | 1826 accrued interest | 1826 mora |
| --- | ---: | ---: | ---: | ---: |
| Opening | 5.60 | 0.00 | 54.04 | 0.34 |
| October 20 | 6.03 | 0.01 | 54.04 | 0.34 |
| October 21 | 6.46 | 0.02 | 54.04 | 0.34 |
| October 22 | 6.89 | 0.02 | 54.04 | 0.34 |
| October 23 | 7.32 | 0.03 | 54.04 | 0.34 |
| October 24 | 7.75 | 0.04 | 54.04 | 0.34 |
| October 25 | 8.19 | 0.06 | 54.04 | 0.34 |

The independent oracle passed **36 daily balance/accrual checks**, plus **24
actual GL account checks**: ordinary interest-income credits and receivable
debits equal the independently expected new interest on every day. All native
journal entries balance. Original imported cash transactions remain unchanged;
no native historical journal predates Fineract starts. Repeating the final COB
added no transaction or GL entry. Original scheduler and date controls were
restored; the temporary native runtime was stopped afterward.

1572 earned `262.15 × 60% × 6 / 365`, currency-rounded to **2.59**. Mora uses
eligible installment principal, only new eligible days, source monthly rate
0.42%, per-installment rounding and daily differences. 1826 remains frozen,
with zero new interest or mora. The live October window covers 1572 after its
April 22 resume and 1826's ongoing May 30 freeze. Exact joint freeze/resume
crossing without catch-up remains covered by the native continuation regression
from the repair, rather than an invented source resume for 1826.

## Reproduction and evidence

The commands used the supported loan CLI, with `ARISSTO_SYNC_STATE` pointing to
the isolated proof state above:

```bash
./arissto-sync plan --block loans --target local \
  --source-key 1572 --source-key 1826 \
  --source-through-date 2026-10-19 --proof-namespace loan-flow-oct26
./arissto-sync apply --plan b8431e4ce9fc4b12922d2c8674a38c30 --target local
./arissto-sync reconcile --run 91f7b1ef8b23403399ab82759daa9a0c --target local
```

Do not repeat the historical migration/final alignment after native activity
unless intentionally restoring the opening handoff state. The original final
reconciliation contract still applies: finish migration mutations first, align
last, and only then begin Fineract-owned COB.

[Sanitized persisted checks](loan-flow-cob-checks.json) are versioned. The
ignored private proof directory retains `plan.json`, `apply.json`,
`reconcile.json`, `opening.json`, `cob-plan.json`, `cob-result.json`, `checks.json`,
and executed `cob-runner.py`, `oracle.py`, `gl-oracle.py`. No credentials or
borrower names are included in the committed checks.

Regression coverage: **295 loan tests plus 15 remaining-schedule tests passed**.
The new source-window tests cover inclusive source-day/exclusive native-day
selection and eleven unsupported/inconsistent-history cases; product tests
cover enablement, persisted-update retry and intervening target drift. An old
exact-list test was corrected to include the already-versioned, entity-scoped
2482 override; no financial override was added by this repair.

These results establish the next-cycle loan path for the two tested loans.
They do not certify every portfolio shape, a future source snapshot, or an
entire dependency-complete workflow execution. Existing client/employee
prerequisites were reused; composed workflows still own their normal lifecycle
and prerequisite gates.
