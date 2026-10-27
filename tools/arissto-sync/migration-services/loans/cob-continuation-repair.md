# Reconciled loan continuation: COB repair — 2026-10-26

**Later normal-CLI acceptance:** [planning repairs and actual loan-sync/COB evidence](loan-flow-cob-acceptance.md) supersede the archived-lifecycle limitation. The dated evidence below is retained.

**Scoped local acceptance passed.** Fresh isolated loans for source 1572 and
1826 were created with interest recalculation enabled, their complete frozen
source histories replayed, all eight opening metrics aligned, and six native
COB days checked against an independent arithmetic oracle. This supersedes the
[earlier failed diagnostic](pause-cob-canary.md), whose evidence is retained.

## Why ordinary COB changed the aligned amounts

The daily mora insertion path reprocessed the entire repayment history. That
rebuilt native allocations after the approved final correction. The mora
calculator also compared historical cumulative mora with adjusted charges and
attempted a reduction through ordinary charge-adjustment validation; the
available transaction-backed adjustment was zero, producing the reported error.

Future contractual interest was still mixed into operational interest owed.
Simply preserving the opening summary did not establish a usable accrual
baseline: a future installment date could change the daily result, and a
materialized period amount alone did not make the new interest postable.
These were continuation defects after reconciliation; they do not require
attributing every historical Arissto/Fineract difference before alignment.

## Implemented behavior

- Final alignment establishes a source-day baseline even when the eight amounts
  already match. Read-back exposes `continuationReady`; an unchanged monetary
  comparison cannot skip initialization.
- Future projected interest is preserved separately as `interestForecast`.
  It is displayed as forecast in Mifos and excluded from earned interest owed.
  The definitive nullable schedule column is versioned in
  [Liquibase 0437](../../../../fineract-provider/src/main/resources/db/changelog/tenant/parts/0437_loan_metric_interest_forecast.xml).
- Ordinary accrual starts after the baseline source day. Whole-loan freeze
  intervals exclude freeze day through the day before resume. Only eligible
  new days accrue, including across a future installment date. Previously
  materialized new interest is deducted rather than earned twice.
- Native periodic accrual receives the new interest in both the amount and
  accruable fields, dated on the native COB day. Only native accruals after
  source day offset that new recognition. Source opening interest is not
  recognized again. Native arrears projection is refreshed afterward.
- Aligned-loan mora adds only the new daily delta, using source terms and a
  source-day clock floor. Stable day-specific external IDs prevent duplicate
  charges. Adding it refreshes native projections without replaying imported
  cash transactions or reducing historical charges.

The final migration correction remains GL-free. Normal post-handoff COB
accruals make normal native accounting entries. No guarantee is added for
arbitrary later historical reversal/recalculation; rerun final alignment after
repeating earlier migration steps, as already required.

## Controlled live proof

Target: disposable local `sandbox`, fingerprint `b9f6834b66790744`.
**Arissto through 2026-10-19; Fineract starts 2026-10-20.**
Namespace `cob-fixed-oct26-d`; native loans **2771 / 2772**; both have
recalculation enabled and periodic accrual accounting (rule 3).

The actual lifecycle writer, source freeze-history importer and final metric
alignment helper replayed source-bounded histories from accepted archived plan
`bddc742688a7439096e9b23fed3d24c3`: 22 events for 1572 and five for 1826.
The current rejected canonical plan was not applied or bypassed. A fresh
isolated product and loans were used; this is not certification of a composed
workflow, production deployment, or the unrelated current product-drift guard.
No tenant reset, new cycle, or Arissto write occurred.

| COB date | 1572 interest | 1572 mora | 1826 interest | 1826 mora |
| --- | ---: | ---: | ---: | ---: |
| Opening | 5.60 | 0.00 | 54.04 | 0.34 |
| October 20 | 6.03 | 0.01 | 54.04 | 0.34 |
| October 21 | 6.46 | 0.02 | 54.04 | 0.34 |
| October 22 | 6.89 | 0.02 | 54.04 | 0.34 |
| October 23 | 7.32 | 0.03 | 54.04 | 0.34 |
| October 24 | 7.75 | 0.04 | 54.04 | 0.34 |
| October 25 | 8.19 | 0.06 | 54.04 | 0.34 |

1572: new interest = currency-rounded `262.15 × 60% × 6 / 365 = 2.59`;
its native ordinary-income accruals independently sum to 2.59. The older
12.35 opening figure included future projected interest; actual accrued
opening interest was 5.60. 1572 is not past final maturity in this window.
Mora was independently calculated from eligible installment principal, new
eligible days and the source monthly rate 0.42%, with per-installment rounding
and cumulative daily differences. No pre-handoff day entered the new clock.

1826 remains frozen from May 30 with no source resume through the snapshot;
zero new interest, mora and ordinary-income accrual was the expected result.
1572 had already resumed on April 22. This live October window does not test
that historical April boundary or invent a resume for 1826. Domain regression
tests cover a joint freeze October 21–23, resume October 24, and a future
installment boundary: both interest and mora exclude the paused days without
catch-up.

All 36 daily balance/accounting checks passed. Original imported cash
transaction IDs, dates, components and reversal flags were unchanged. Replay
and opening corrections left the global GL fingerprint unchanged; neither
loan has a native historical GL posting before Fineract starts. Repeating the
final COB added no transactions or GL entries. The original business-date
configuration and saved date state were restored.

## Evidence and regression coverage

[Sanitized checks](cob-continuation-checks.json) include the complete daily
observations and preservation checks. Frozen local artifacts are retained under
`.arissto-sync/pause-cob-proofs/`:

- `cob-fixed-oct26-d-plan.json`, SHA-256
  `e4406313b509e1f51b9bfe19e91ae9f4ded3653c6e80fe130e8e4b04abe2c0b7`;
- `cob-fixed-oct26-d-result.json`, opening state, transactions and daily native read-back;
- `cob-fixed-oct26-d-checks.json`, independent persisted-state oracle;
- `cob-fixed-oct26-d-runner.py` and `cob-fixed-oct26-d-oracle.py`, executed harness snapshots.

Focused Gradle regressions passed (59 tests in the final combined invocation,
including native continuation and posting coverage). The final-metric Python
regressions passed (245 tests), and the Mifos final-metric/forecast read-back
suite passed (three tests). Representative native regressions:
`MigrationAccrualContinuationTest`, `FinalLoanMetricsTest`,
`ReconciledLoanAccrualTest`, `CredesalDailyMoraFreezeTest`, and
`CredesalDailyMoraCalculatorTest`. The test-only oracle independently reads
persisted native balances, posted accruals, terms and schedule; a successful COB
HTTP response alone is not acceptance evidence.
