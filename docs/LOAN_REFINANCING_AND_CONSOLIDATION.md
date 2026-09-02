# Loan refinancing and consolidation

## Decision

Credesal exposes one financing workflow with two explicit modes:

- **Refinancing** closes exactly one predecessor loan.
- **Consolidation** closes two or more predecessor loans.

Neither mode is named "top-up" in the public UI. Fineract's existing
`m_loan_topup` aggregate and `isTopup` application flag remain compatibility
details because they already own the native loan-to-loan transfer lifecycle.

## Contract

The successor is an ordinary Fineract loan and continues to own its normal
product terms: principal, nominal interest rate, repayment frequency, repayment
amount or amortization method, installment count, dates, charges, and accounting
configuration. Refinancing adds only the predecessor-settlement relationship.
This keeps the controls observed in Arissto consolidated loans independent: a
consolidation can change rate, payment amount, installment count, and net cash
without inventing a separate schedule model.

Applications accept `loanIdsToClose`. The legacy `loanIdToClose` field remains
accepted for a single predecessor. The operation type is derived, never trusted
from the client:

- one unique predecessor: `SINGLE_REFINANCE`;
- two or more unique predecessors: `CONSOLIDATION`.

All predecessors must exist, belong to the successor client, be active, use the
same currency, and be eligible for payoff on the effective disbursement date.
The combined payoff cannot exceed the successor disbursement.

That ownership boundary is intentional. A consolidation must not close a loan
owned by another client merely because its ID was submitted. Cross-client debt
settlement needs a separate participant/authorization model, explicit API and
UI permissions, auditable consent, and reconciliation rules before it can use
this financial engine.

## Persistence and atomicity

`m_loan_topup` remains the one-to-one refinancing header. Tenant migration
`0317_add_loan_refinancing_settlements.xml` adds its derived `operation_type`
and creates `m_loan_refinancing_settlement`, one row per predecessor. Existing
single-loan rows are backfilled.

The disbursement transaction locks all predecessor loans in deterministic ID
order, validates the complete set, creates one native loan-to-loan transfer per
predecessor, records each payoff allocation and transfer identity, then
disburses only the remaining net cash. The command is transactional: any
failure rolls back every predecessor settlement and the successor disbursement.
A consolidation whose payoffs consume the full principal creates no redundant
zero-value cash leg.

Migration-only source-exact execution uses
`sourceExactRefinancingDisburse` and a `refinancingSettlements` array. Each row
contains the predecessor loan, exact principal/interest/fee/penalty allocation,
and deterministic repayment and transfer external IDs. Ordinary operational
refinancing continues to use Fineract's calculated payoff quote.

## UI

The loan terms step offers Standard loan, Refinancing, and Consolidation.
Refinancing requires one predecessor; consolidation requires at least two. All
ordinary successor terms remain editable through the existing controls. Loan
details display the derived operation type and every predecessor settlement.
English and Spanish labels are provided.

## G5-GRF-002 evidence and remaining boundary

The source cohort contains two ownership shapes. Three successors (`2252`,
`2402`, and `2406`) consolidate two loans owned by the successor client. The
other nine each settle one loan owned by the successor client and one loan
owned by a different client.

The same-client path is proved by namespaced local plan
`fe97d37686904e1bbc75e1904ca1e3fa` for `2042 + 2205 -> 2406`. Initial run
`3b2e253daee3432dafd03e66a178957e` and unchanged replay
`4f8cb9a347a645b98ebc0814d717f891` both reconciled with `ok=true`, no failed or
quarantined items, and no blocking mismatches. The proof established:

1. both predecessors close through their exact frozen payoff movements;
2. the successor disbursement equals both settlements plus exact net cash;
3. principal, interest, fees, and penalties reconcile for each predecessor;
4. both loan-to-loan transfers and their external identities are unique;
5. successor rate, installment count, repayment dates, and amounts match the
   frozen plan and resulting native schedule contract;
6. balances, terminal states, accounting entries, and journals reconcile with
   no blocking mismatch; and
7. replay creates no additional loans, transactions, transfers, or journals.

The nine cross-client cases remain outside this contract. `G5-GRF-002` cannot
be marked complete for the full 12-successor cohort until Credesal chooses and
implements an explicit cross-client authorization/participant design, or
classifies those nine cases under a separately approved migration-only policy.
Audit plan `922175c4a44740b18cd9b75fb9bc564d` verifies the fail-closed behavior:
successor `2472` is planned as `quarantine-loan` with
`cross_client_refinance_requires_authorization` before any target write.
