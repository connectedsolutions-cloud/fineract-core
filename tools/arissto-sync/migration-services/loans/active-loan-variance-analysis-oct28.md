# Active-loan schedule/reference variance analysis — October 28, 2026

The requested scope is **active loans and the eight identified financial
metrics**. At **Arissto through October26 / Fineract starts October27**, no
active-loan metric correction is indicated by the56,520 variance records.
Fresh read-only native checks match **4,168/4,168 metric values across521 active
loans**, and all521 continuation checks pass their recorded contracts.

This analysis uses accepted immutable source targets from loan plan
`f0da9e74973e4923a4866dc8eb3cef2e` and reconciliation
`d4b9a7330b3a45098a60bc564c6bdf8e`, followed by current local sandbox API/SQL
readback. It does not claim comparison with new Arissto activity after S.
There was no sync, reset, metric adjustment, source write or target financial
write. Detailed source IDs, native IDs and predicate outcomes are in the
[sanitized analysis evidence](investigations/active-loan-variance-analysis-oct28.json).

## Population and patterns

Of56,520 records, **55,188 belong to521 active loans**, and **1,332 belong to
inactive loans**. The latter are outside this review's priority. All521 active
loans have at least one schedule/reference difference; each record is a
field/installment comparison, so the large count is not a count of bad loans.

| Pattern | Active variance records | Explanation | Action for the requested metrics |
| --- | ---: | --- | --- |
| Installment counts, numbers and positional dates | 26,854 | Final alignment consolidates paid/accrued settlement into an explicit S-dated baseline, redistributes remaining principal, and renumbers rows. The generic comparator filters zero-economic rows and then pairs source/native rows by position. Position shifts create repeated number/date differences. | Expected under the accepted continuation contract; no balance correction. |
| Principal by installment and whole-schedule principal totals | 13,201 | 13,193 row differences reflect the final principal distribution. Eight whole-schedule totals concern reviewed replacement/reference schedules. All eight native totals equal frozen paid principal plus outstanding principal. | No identified-metric mismatch. Preserve the correct paid/outstanding/due principal targets. |
| Interest by installment and whole-schedule interest totals | 14,955 | 14,434 row differences plus521 total differences compare the source reference plan with a native settlement baseline and separately preserved future interest forecast. Full schedule interest is not the accrued-interest metric at S. | Expected; paid and accrued interest both match on every active loan. |
| Fee balance and generic total outstanding | 178 on89 loans | Each loan contributes two records for the exact same future-insurance difference. The generic native fields include scheduled insurance after S. | Expected future-charge difference; identified insurance owed at S matches. |
| Inactive-loan differences | 1,332 | 409 reviewed manual schedule rows,917 historical-reference rows and6 repaid mora-running-balance references. | Exclude from the default active-metric review. |

The first three active groups total **55,010** records classified as
`verified_final_continuation_schedule_variance`. The remaining178 active rows
are89 `native_schedule_component_variance` fee records and89
`full_native_schedule_not_cutover_comparable` total records.

## Direct metric verification

Each metric was read through the native `GET /loans/{id}/migration-metrics`
projection with the frozen T and identified insurance definitions, and compared
at exact currency precision with its immutable source target.

| Identified metric | Matching active loans | Mismatches |
| --- | ---: | ---: |
| Paid principal | 521 | 0 |
| Outstanding principal | 521 | 0 |
| Paid ordinary interest | 521 | 0 |
| Outstanding accrued ordinary interest through S | 521 | 0 |
| Due principal through S | 521 | 0 |
| Outstanding accrued mora | 521 | 0 |
| Insurance paid | 521 | 0 |
| Insurance outstanding through S | 521 | 0 |

All521 current native continuation representations also pass
`loan_continuation_schedule.verify`, including the active identity, baseline,
metric/audit, paid/remaining/due principal and settlement invariants. Their
recorded schedule policies are494 exact source schedules,8 historical-reference
schedules,8 reviewed manual schedules and11 unordered-source-date schedules.
The strict source calendar/future-interest-forecast comparison applies to the494
exact schedules; the27 reviewed policies retain their explicit reference
exceptions. Passing a reviewed policy does not assert row-for-row calendar or
forecast equality for that loan. This does not introduce a current metric gap.

## The89 fee/total cases are fully explained

Independent charge/installment reads prove all five predicates on **89/89**:

1. Generic fee gap equals the generic total-outstanding gap.
2. The entire gap equals identified insurance scheduled after S.
3. Source insurance owed equals native identified insurance due through S.
4. There are no other-fee or undated-charge residuals in these89 cases.
5. The generic native fee outstanding equals the complete native fee-charge total.

The same economic difference is therefore logged twice for each loan. Reducing
those future premiums to force equality with S would change the future charge
plan despite an already correct insurance metric. No such change is warranted
by this analysis.

## Eight principal-total references

Source IDs1117,1743,1748,1761,2254,2535,2613,945 account for all eight
`schedule_principal_total` records. Five have reviewed manual schedule policy;
three have unordered-source-date policy. Their source reference totals differ
from origination principal. In every case the native schedule total equals the
frozen paid-plus-outstanding principal, and all eight identified metrics match.
These total-reference records are not outstanding-principal errors.

## Recommended changes

**No migration amount repair is needed for the identified active metrics in
this accepted snapshot.** Improve signal and presentation instead:

- Make the default reconciliation summary report521 active loans,4,168 metric
  checks,0 metric mismatches, and521 passing continuation checks. Exclude
  inactive loans from that default result.
- Move the55,010 expected original-versus-final schedule comparisons into
  collapsed reference detail. Retain strict continuation invariant failures as
  blocking findings; do not remove those checks.
- Group the178 fee/total rows into89 future-insurance explanations. Use the
  identified due insurance projection for the requested insurance metric;
  retain full scheduled charges as a separately labelled value.
- Avoid showing the56,520 reference records as unresolved financial errors.
  Keep a searchable audit appendix and links to each affected source/native ID.

Mifos inspection confirms that the general summary's Fees/Outstanding cell
reads `summary.feeChargesOutstanding`, and its header reads
`summary.totalOutstanding` under Remaining Scheduled Repayment. Existing
English/Spanish help text explains future interest but does not explicitly name
future insurance. A consumer using Fees/Outstanding as insurance owed today
needs a mapping/label clarification: expose due identified insurance separately
and explain future premiums. The underlying eight metric values do not need
adjustment. The summary component's existing readback test uses a case without
this future-insurance distinction, so a later UI/reporting implementation should
cover the89-loan pattern explicitly.

## Primary implementation references

- [Eight metrics and exact target comparison](../../arissto_sync/loan_metric_alignment.py).
- [Native metric definitions and due-only insurance](../../../../fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/domain/FinalLoanMetrics.java): `read`, `dueOutstanding`, `apply`.
- [Strict continuation proof and reviewed reference policies](../../arissto_sync/loan_continuation_schedule.py).
- [Variance emission and positional schedule comparator](../../arissto_sync/loans.py): `reconcile_loans`, `_loan_schedule_differences`.
- [Metric contract](loan-metric-final-alignment.md) and [accepted import](loan-quarantine-recovery-oct28.md).
