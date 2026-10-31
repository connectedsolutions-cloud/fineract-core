# Refinancing surplus: local default end-to-end verification

Tested October 30, 2026 through the live local Fineract API, with independent read-only PostgreSQL journal checks. This is API-to-database verification; no browser interaction was exercised. Scope: `https://127.0.0.1:8443`, tenant `default`, database `fineract_default`. The tenant's existing Fineract-owned accounting begins September 3, 2026. All test disbursements and postings are October 29–30, after that boundary. The local server was restarted to load the feature with startup Liquibase migrations disabled; the startup log confirmed that no databases were upgraded. No production or Arissto connection was used for this test.

[Requirement and implementation](../../docs/REFINANCING_SURPLUS_REPAYMENT.md) · [Machine-readable evidence](refinancing-surplus-e2e-2026-10-30.json)

## Synthetic fixture and retained records

Created synthetic client **1044**, external ID `REFISURPLUS-E2E-20261030-A`, using existing loan product **4**, `Arissto 00010 M-MICROCREDITO MULTIDESTINO`. Its maximum principal is 6,800; tests use 4,000 predecessor loans and 6,000 successors without changing the product. The product uses USD, periodic accrual accounting, the Credesal accrued-interest-first allocation strategy, and no interest recalculation. Predecessors were disbursed October 29 and refinances October 30, with a 1% monthly contractual rate and 12 monthly installments. A dedicated fixed 100 upfront charge was created for the fee cases; its ID is in the evidence JSON. Existing clients' loans and accounting mappings were not edited.

The date-specific native payoff was **4,264.78**, comprising 4,000 principal and 264.78 interest. This no-interest-recalculation product's payoff included contractual schedule interest; it was not a one-day accrued-interest-only payoff. The test used the native quoted and settled amount rather than assuming a payoff formula.

Test records remain in `default` for inspection. Closed predecessors, active successors, the payout control, and the failed case are intentional synthetic artifacts, not business borrowers.

## Verified outcomes

| Case | Old → new loan | Payoff | Upfront fee | New-loan repayment | Net borrower payout | New principal paid | New principal outstanding |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Retain proceeds | 510 → 511 | 4,264.78 | 0.00 | 1,735.22 | 0.00 | 1,568.07 | 4,431.93 |
| Option omitted: payout control | 512 → 513 | 4,264.78 | 0.00 | 0.00 | 1,735.22 | 0.00 | 6,000.00 |
| Retain proceeds with fee | 514 → 515 | 4,264.78 | 100.00 | 1,635.22 | 0.00 | 1,468.07 | 4,531.93 |
| Separate undo guard check | 516 → 517 | 4,264.78 | 100.00 | 1,635.22 | 0.00 | 1,468.07 | 4,531.93 |

All successful predecessors closed with obligations met and zero outstanding balance. The retained repayments were dated October 30. The product allocated 167.15 to interest in each retained case; the rest went to principal. The full remaining amount was paid, but the payment was not principal-only. API command results reported the exact retained amount and repayment transaction ID. Native same-loan transfer rows link all three retained disbursement/repayment pairs. Independent sums of completed principal and interest in the persisted repayment schedules match the repayment allocations and API summaries. Exact debit/credit account-and-amount assertions passed for each retained disbursement and repayment, in addition to journal balance checks.

For the primary retained case, successor disbursement transactions are **20484** (4,264.78 predecessor payoff) and **20487** (1,735.22 retained proceeds). Automatic repayment **20488** is 1,735.22, with 1,568.07 principal and 167.15 interest. The fee-case automatic repayment is **20501**, amount 1,635.22.

## Accounting verification

Every disbursement and repayment transaction in the successful cases has journal entries. Each journal group balances individually, and each refinance's combined debit and credit totals balance. Fineract journal enum values are **1 = credit, 2 = debit**.

The two primary retained-proceeds transactions posted:

| Transaction | Debit | Credit |
| --- | --- | --- |
| 20487: retained disbursement | 1,735.22 to `1141030101` OTORGAMIENTOS ORIGINALES | 1,735.22 to `111001` CAJA |
| 20488: automatic repayment | 1,735.22 to `111001` CAJA | 1,568.07 to `1141030101`; 167.15 to `1520` interest receivable |

**Configuration finding:** the existing local `default` financial activity **100 / ASSET_TRANSFER** maps to **`111001` CAJA**, account ID 5. Native loan-to-loan accounting uses this activity, including the existing predecessor payoff path and the new retained-proceeds path. The product's transfers-in-suspense account `1510` is not selected by that native path. Thus the operation creates equal cash-account debit and credit legs rather than using a dedicated non-cash clearing ledger. The net CAJA movement is zero. This is the configured local routing, not evidence that a dedicated clearing account is configured. The test did not change this global mapping, because doing so would affect other transfers.

For the fee case, transaction **20499** disburses 100 of charge-funded principal (debit portfolio, credit product fund source `14`), and **20500** records the 100 fee payment (debit `14`, credit fee income `6110010800`). Those source-account legs also net to zero. All retained refinance cases have **zero combined net movement on CAJA and product fund source**. The payout control has the expected **1,735.22 cash outflow**, with no successor repayment.

The JSON includes all loan-linked journal rows for the test date, their exact ledger accounts, totals, and net amounts by account. It verifies native postings and configured routing; it does not change or approve the product's interest recognition policy or the tenant's global transfer mapping.

## Failure atomicity and reversal restriction

The insufficient-remainder case uses predecessor **518** and successor **519**, with a 3,000 upfront fee exceeding the 1,735.22 remainder. Disbursement failed with `error.msg.loan.refinancing.surplus.insufficient.for.charges`. The predecessor remained active with 4,000 principal outstanding and zero principal paid. The successor remained approved and awaiting disbursement with no transactions. There were **zero refinance-date journal entries** on either loan. This verifies that predecessor payoff preparation rolled back with the failed disbursement.

Undo-disbursement of the separate successful successor **517** was rejected with `error.msg.loan.undo.disbursal.not.allowed.on.topup.loan`. The predecessor remained closed and the successor's repayment and balance were unchanged. This is enforced by [LoanDownPaymentTransactionValidator](../fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/serialization/LoanDownPaymentTransactionValidator.java). Earlier implementation notes incorrectly implied that the normal undo path was available for this feature; this live verification corrects that claim. The persisted transfer links do not bypass the existing top-up undo restriction. Enabling safe refinancing undo requires separately reviewed behavior.


## Subsequent source verification

The [Arissto final-journal investigation](../../../credesal-db-space/docs/learnings/refinanciamientos-contabilizacion-y-caja.md) confirms that the offsetting CAJA legs observed in this local test do not reproduce Arissto's refinance posting route. Arissto uses a combined successor/predecessor journal and a separate payout payable. Treat this E2E result as proof of payment allocation and configured native journal balance, not proof of source-account parity. See the global requirement for the cross-stack comparison; the source investigation did not change mappings.
