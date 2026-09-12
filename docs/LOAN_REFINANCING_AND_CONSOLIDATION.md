# Loan refinancing and consolidation

## Decision

Credesal exposes one financing workflow with two explicit modes:

- **Refinancing** closes exactly one predecessor loan.
- **Consolidation** settles two or more predecessor loans. Each settlement is
  either a full close or a partial paydown.

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
accepted for a single fully closed predecessor. These application fields contain
only `FULL_CLOSE` predecessors; `PARTIAL_PAYDOWN` predecessors are supplied only
to the permission-gated source-exact disbursement command. The operation type is
derived, never trusted from the client:

- one unique predecessor: `SINGLE_REFINANCE`;
- two or more unique predecessors: `CONSOLIDATION`.

For ordinary operational refinancing, all predecessors must exist, belong to
the successor client, be active, use the same currency, and be eligible for
payoff on the effective disbursement date.
The combined full-close and partial-paydown amounts cannot exceed the successor
disbursement.

That ownership boundary remains intentional for every ordinary application and
disbursement command. The permission-gated Arissto source-exact migration
command has one narrower exception for completed legacy history: it may attach
and settle a cross-client predecessor only when the payload carries the
definitive source liquidation, payoff movement, payoff date, and original
operator. A finalized liquidation connected to the persisted predecessor and
successor lifecycles is the authorization basis; a guarantor row is supporting
context, not a prerequisite. Missing or inconsistent evidence fails closed.

## Persistence and atomicity

`m_loan_topup` remains the one-to-one refinancing header. Tenant migration
`0317_add_loan_refinancing_settlements.xml` adds its derived `operation_type`
and creates `m_loan_refinancing_settlement`, one row per predecessor. Existing
single-loan rows are backfilled.

Tenant migration `0329_add_partial_refinancing_settlements.xml` adds the
`settlement_type` discriminator. Existing rows default to `FULL_CLOSE`.
`PARTIAL_PAYDOWN` records the exact source amount and allocation but does not
make that predecessor part of the native application close set.

Tenant migration `0327_add_legacy_cross_client_refinancing_audit.xml` adds the
migration-only audit fields to each settlement: authorization basis, source
system, liquidation and payoff identities, source operator and date, plus both
client IDs. These fields make the historical relationship reviewable without
creating an operational cross-client refinancing option.

The disbursement transaction locks all predecessor loans in deterministic ID
order, validates the complete set, creates one native loan-to-loan transfer per
predecessor, records each exact allocation and transfer identity, then disburses
only the remaining net cash. A `FULL_CLOSE` predecessor must end closed with no
material balance. A `PARTIAL_PAYDOWN` predecessor must retain active status and
a positive residual after the exact source payment. The command is
transactional: any failure rolls back every predecessor settlement and the
successor disbursement. A consolidation whose settlements consume the full
principal creates no redundant zero-value cash leg.

Migration-only source-exact execution uses
`sourceExactRefinancingDisburse` and a `refinancingSettlements` array. Each row
contains the predecessor loan, exact principal/interest/fee/penalty allocation,
deterministic repayment and transfer external IDs, and `settlementType`.
Ordinary operational refinancing continues to use Fineract's calculated payoff
quote and cannot create partial-paydown refinancing relationships.

## UI

The loan terms step offers Standard loan, Refinancing, and Consolidation.
Refinancing requires one predecessor; consolidation requires at least two. All
ordinary successor terms remain editable through the existing controls. Loan
details display the derived operation type and every predecessor settlement.
Full closures and partial paydowns have distinct English and Spanish labels.
Legacy cross-client settlements also
show their source liquidation, payoff movement, operator, and date read-only;
none of these fields is exposed in the loan creation form.

## Mixed full/partial consolidation evidence

Arissto loan `2402` is the defining mixed case. Its 2026-08-07 definitive
liquidation fully settled predecessor `1784`, while applying `$393.80` to
predecessor `2265`. Loan `2265` remained active, retained a positive balance,
and accepted a later `$15.00` payment on 2026-08-12. Therefore the later
transaction is not a Fineract date-rule exception and must not be moved or
discarded: `1784` is `FULL_CLOSE`, `2265` is `PARTIAL_PAYDOWN`, and both belong
to the same atomic consolidation that creates `2402`.

Local proof namespace `grf003-20260903-a` verified this contract end to end.
Plan `5fd1b9ac0292496f9a04a6d614bec503`, successful run
`0b17c12ffbe64b92bac7e7b3cf1d15ea`, and unchanged replay
`cdf43c654c484160a235ce3343230379` reconciled with no failures, quarantines, or
mismatches. The target contains exactly two settlement rows: `$566.65` against
closed loan `1784` and `$393.80` against still-active loan `2265`, whose exact
allocation includes `$0.11` of penalty. Its later `$15.00` payment remains
unreversed, and replay did not duplicate the settlements or source movements.

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

Credesal has approved the migration-only policy for completed historical
cross-client refinancing. The implementation preserves ordinary same-client
validation and accepts a legacy edge only through
`sourceExactRefinancingDisburse` with complete source evidence. The nine
cross-client consolidations and five cross-client single-refinance cases are
now admitted by full plan `0065dc7d540f42c89b5cbe0fe18ec568`. This removes
all 75 graph-propagated cross-client quarantines. Cross-client canary plan
`3aa9523256434f1eaf4d974b946b205a`, successful run
`726183dce4cf4e50ae77b6be219feaf4`, and unchanged replay
`709cd5eda5bb463caf5e62ab299847ad` reconciled with no failed/quarantined items
and no mismatches.
