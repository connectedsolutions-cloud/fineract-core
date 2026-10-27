# Source-exact penalty recalculation recovery — October 27

**Recovered and reconciled:** source loans 101, 283, 553 and 921 in the preserved
sandbox cycle. This fixes the two demonstrated temporary-schedule LS-03 cases;
it does not establish recovery of the wider baseline penalty cohort.

[Execution and regression evidence](investigations/ls03-penalty-recalculation-recovery-oct27.json).
Implementation: [source-exact processor](../../../../fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/domain/transactionprocessor/impl/CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor.java).

## Cause and change

Repayment `0000012748` dated 2025-08-25 had a real, active, unpaid 0.26 penalty
charge (native charge 5040), due on that date. The full schedule placed it in
installment 9, due September 23. Native recalculation processed an August
schedule prefix without installment 9 and rejected the penalty as
unrepresentable. The failure occurred in
`handleRepaymentScheduleForInterestRecalculation`, before strict final posting.
It was not a missing source charge, rounding adjustment or October 27 payment.

Temporary source-exact processing now defers an unrepresented penalty only
when same-loan, dated, eligible charge evidence covers the **whole declared
penalty**. It returns only the unprocessed principal to the native early-payment
calculation; a penalty never becomes early principal. It does not synthesize
penalty amounts on temporary installments, pay a charge, create a paid-by row,
attach managed ownership rows to a copy, or modify the frozen source allocation.
Final posting still requires full schedule representability and normal native
charge settlement.

The first corrected retry passed the 0.26 payment and eight following events,
reaching 19/23 source events. It exposed the second case: recalculation replayed
a previously paid 0.15 penalty from source payment `0000018697` (2026-03-31)
while processing the May 29 payment. A property-only transaction copy omits
paid-by links, and the historical charge has zero outstanding balance.

For this case, the processor reads the unique persisted, unreversed source-exact
transaction with the same nonempty external ID, date and declared penalty.
Only that original transaction's own paid-by amounts can back its copy. Charge
loan ownership, penalty type, due date, waived status and simple dated-charge
eligibility are still checked. No other payment's ownership is borrowed;
ambiguous originals, insufficient amounts and altered ownership fail closed.
The original managed transaction, charge and paid-by links remain untouched.

## Tests

The original positive regression failed with the exact allocation exception
before the repair (2 expected failures among 11 new invocations). The added
paid-copy regression then failed before its ownership extension (1 expected
failure among 17 invocations). The final **61 focused tests passed**:
17 penalty-prefix/ownership cases, 39 existing source-exact processor cases,
and 5 ORM preview-isolation tests. Formatting checks passed for the two changed
Java files. Missing, future, inactive/unowned, waived, foreign, insufficient and
installment-charge evidence remain rejected. Final posting against a schedule
missing the penalty still fails even with a real charge.

The Mifos transaction grid already displays `penaltyChargesPortion`, and its
summary displays `penaltyChargesPaid`. Read-only source inspection confirms the
existing API fields remain compatible; no UI or API payload changes were
introduced. Browser acceptance was not performed.

## Same-cycle recovery

- Cycle: `sandbox-2026-10-26-full-clean-a`; local `sandbox` /
  `fineract_sandbox`, fingerprint `b9f6834b66790744`.
- **Arissto through: 2026-10-26. Fineract starts: 2026-10-27.** Unchanged.
- Original immutable plan: `46b49222cc9e488ca7a4f553f27af5f9`.
- Intermediate run: `af75dd61e08d48d687a94b484ae81b4b`; partial progress kept.
- Successful retry: `a352b996b7ce4fd295270bac38568108`.
  Run **completed**; all four loans recovered, product unchanged;
  **official reconciliation `ok: true`**, zero blocking mismatches and no
  failed/quarantined entities. The 28 native recalculated-schedule comparisons
  are existing nonblocking variances, not source allocation or metric failures.

| Source loan | Native ID | Native state | Source events represented | Metric targets matched |
|---|---:|---|---|---|
| 101 | 1 | Closed (600) | 6/6 | 8/8 |
| 283 | 1144 | Closed (600) | 8/8 | 8/8 |
| 553 | 1145 | Closed (600) | 9/9 | 8/8 |
| 921 | 1146 | Active (300) | 23/23 | 8/8 |

All four metric read-backs report a ready continuation baseline. Final metric
alignment ran only after complete historical replay. It was not used to mask
the earlier failed allocation or four missing source events.

Independent read-back confirms repayment `0000012748` has penalty portion
**0.26**; that charge and the historical 0.15 charge are fully paid, with zero
outstanding and exactly one correct **cash repayment** owner each. Each also
has a separate native type-10 accrual-recognition link, which is not a duplicate
cash payment. Full target row hashes are unchanged by diagnostic GETs.

The client office transfer still has exactly one proposal and one acceptance;
loan 921 retains one type-12/type-13 pair dated 2025-04-01. No duplicate loan or
transfer was created. Native loan count stayed **1,146** throughout this task;
loan transaction count progressed **24,888 → 24,897 → 24,918**, including the
remaining repayments and native accrual catchup. GL journals remain **zero**.

October 27 payment **0000034318 remains excluded** from the frozen writer
stream and absent from all target external-ID namespaces. No scoped target
transaction is dated October 27 or later. Compared outside-scope loan,
transaction, schedule, charge, client, product and GL hashes remain unchanged.

Both backend reloads used the original frozen, guarded lifecycle command;
whole-row hashes, counts and the 2,103-entry Liquibase history were unchanged
across each reload. No reset, new cycle, Arissto write, tenant migration or
broader workflow resume occurred. The scheduler remains paused and the parent
workflow interrupted. This is complete acceptance of the four-loan recovery,
not completion of LS-27 or the full migration workflow.
