# Recalculation-off servicing acceptance — October 28, 2026

> **Repair follow-up:** the subsequent [fresh API/COB rerun](recalculation-off-servicing-repair-oct28.md)
> passes after the payment materialization and migrated-pause fixes. This document
> preserves the original failed observations; do not treat them as current acceptance.

**Acceptance failed. Keep this as a diagnosis, not approval to release servicing
or enable standard recalculation.** The operator requested live API and COB
checks for early/late principal repayment, interest/mora pause-resume and
interest/mora waivers. Exact Arissto behavior is explicitly not the goal.

## Scope and safeguards

- Disposable local `sandbox` / `fineract_sandbox`, fingerprint `b9f6834b66790744`.
- **Arissto through October 26; Fineract starts October 27.** Boundary unchanged.
- Namespace `servicing-off-oct28`; fresh proof products 3/4, loans 2727–2734.
- Two cumulative, daily declining-balance, periodic-accrual products, standard
  interest recalculation false throughout, Credesal accrued-interest strategy.
- Synthetic $1,000 principal, $10 opening collectible interest, 36.5% annual
  interest; contractual installments October 30 and November 6. Opening metrics
  installed through the same migration-metrics API, with genuine marked native
  baseline rows. No real source history or borrower financial samples copied.
- Mora variants use the existing 0.42% monthly product charge and $200 opening
  due principal. They use the proof identity/product fallback, not a full imported
  source-mora-terms extraction. This test does not certify portfolio mora pricing.
- 146 successful individual loan/day inline COB closes, plus eight repeated
  final closes. HTTP success alone was not treated as acceptance.
- Scheduler remained paused. Non-proof `m_loan` row count/hash unchanged.
  This is a table-specific preservation check, not a hash of every target table.
- Business-date configuration was restored disabled with its original empty
  date state. APIs have no date-row deletion operation; only the two exact
  temporary configuration rows created by this test were removed under a
  sandbox/date-value guard. All financial mutations used APIs.
- No canonical loan replay, reset, cycle, workflow, target-boundary change,
  production operation, source write or application repair was performed.
- Proof records and their legitimate post-boundary native GL remain for review.

Plan SHA-256: `8cad139b0773e139b7e14233761cad90aa036bebf0209b8659015f4f34e32bad`.
The local checkout contained pre-existing uncommitted changes. Results describe
what the running local API actually did; checkout HEAD alone does not identify
its complete deployed build.

## Repayment results — failed

Pay $500 principal plus independently computed interest due. The first-day COB
control confirms $1/day on $1,000. With opening interest $10 and source day
October 26, interest due at the three repayment dates is $12/$14/$16.

| Case / loan | Payment date | Total paid | Expected principal paid / interest paid | Actual principal paid / interest paid | Principal left |
| --- | --- | ---: | --- | --- | ---: |
| Early / 2727 | Oct 28 | 512.00 | 500.00 / 12.00 | 499.00 / 13.00 | 501.00 |
| On time / 2728 | Oct 30 | 514.00 | 500.00 / 14.00 | 497.00 / 17.00 | 503.00 |
| Late / 2729 | Nov 1 | 516.00 | 500.00 / 16.00 | 495.00 / 21.00 | 505.00 |

The excess is exactly the $1/$3/$5 already materialized by prior daily COB.
This supports a duplicate-materialization diagnosis: payment-time
`PostDueAccruedInterestCalculator.calculateAndApply` accrues from the source-day
or prior-payment anchor without subtracting interest materialized by COB.
`calculateUnmaterializedAccruableThrough` handles that subtraction on the COB
side, but the payment-side calculation does not. A repair still needs native
regression and acceptance; this observation does not authorize changing code.

Subsequent COB uses actual remaining principal, but the wrong allocation has
already left excess principal and interest collected too early. Therefore
observing that early repayment lowers later daily accrual is insufficient to
approve this path. The unpaid control correctly accrues $1/day, including beyond
maturity; by November 17 it carries $32 ($10 opening plus $22 new interest).

## Pause/resume results — partial

**Interest, across an unpaid future installment: failed.** Loan 2731, submitted
October 27 for an October 29–31 pause, returned 403
`interest.pause.changes.historical.schedule`. It rolled back. An eligible
prospective control was therefore unusable on this aligned schedule.

**Interest, after final contractual due date: passed in this scope.** On the same
loan, a November 9–10 inclusive pause was accepted on November 8. Interest
outstanding was $23 on November 8, remained $23 on November 9–10, then became
$24/$25 on November 11/12. Posted new ordinary-interest income was $15 through
November 12: 17 elapsed days less two paused days, excluding $10 source opening
interest. This verifies finite-range expiration/resume, not arbitrary early
termination or an open-ended interest-pause API.

**Mora-only pause/resume: passed in this scope.** Loan 2732 accepted both
freeze/unfreeze commands. The stronger repeat starts with positive mora $1.01:
freeze November 13, resume November 16. Mora remains $1.01 on November 13–15,
then $1.12/$1.23 on November 16/17. Ordinary interest continues $28/$29/$30/$31/$32
on those same days. The observed new-day mora returns without charging the
three skipped days. Existing mora is preserved, not forgiven by freezing.

## Waivers and later servicing — persistence passed, full path failed

**Interest waiver, loan 2733:** $5 waived October 30. It remained waived through
later COB and a $1 repayment on November 9. Before that repayment, ordinary
interest behaved correctly: $18 outstanding on November 8 equals $10 opening
plus $13 newly earned less $5 waived. After the repayment and November 9 COB,
outstanding interest is **$31 instead of $18**. The waiver counter remains $5;
it is new duplicate interest, not restoration of the waived amount. By November
12 outstanding is still $31 despite only $17 total new native income recognized.

**Mora waiver, loan 2734:** eight positive daily charges totaling $0.51 were
waived through charge-waiver APIs on November 8. Outstanding mora immediately
became zero; waived mora stayed $0.51 through later payment and COB. New eligible
mora accrued separately. On November 9, its $1 repayment also exposed the ordinary
interest duplication: **$36 outstanding instead of $23**. Neither waiver path
can therefore be called complete servicing acceptance even though the waived
amounts themselves persisted.

## Evidence and next repair boundary

The independent oracle checks 216 bounded expectations; **nine fail**: six
repayment-allocation expectations, two later-payment interest balances and the
rejected prospective pause. Persisted loan/transaction reads confirm the wrong
allocations. All eight stored loan flags remain false; no linked GL entry is
dated before Fineract starts. Native control income is $22, paused-loan income
$15, and source opening interest is not posted again. Repeating the final COB
changes neither proof snapshots nor proof GL.

- [Sanitized oracle and persisted totals](investigations/recalculation-off-servicing-oct28-checks.json).
- [API/COB runner](investigations/recalculation-off-servicing-oct28-runner.py).
- [Independent arithmetic oracle](investigations/recalculation-off-servicing-oct28-oracle.py).
- Complete synthetic API snapshots, frozen plan and supplementary runners remain
  under ignored `.arissto-sync/servicing-off-oct28/`.
- [Earlier source investigation](../../../../../../credesal-db-space/docs/learnings/loan-variable-repayment-interest.md)
  is comparison evidence, not the target servicing specification.

Repair payment-versus-COB interest materialization and the pause guard's treatment
of aligned schedules, then rerun this matrix before declaring recalculation-off
servicing accepted. Enabling standard recalculation has not been tested here as
an alternative repair and must not be assumed to solve either failure.
