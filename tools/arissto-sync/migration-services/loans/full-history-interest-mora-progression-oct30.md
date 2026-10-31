# Full-history handoff progression: ordinary interest and mora

October 30, 2026. Separate experiment in local **`default`**, with standard
interest recalculation **off** throughout.

**Execution and native accrual/accounting checks pass, but exact Arissto
progression does not.** All retained source repayments through October 29 are
represented. Loan 2647's post-handoff payment allocations materially differ
from Arissto; mora progression also differs. Do not interpret successful native
arithmetic or balanced journals as source servicing parity.

## Source cohort and adjustment audit

| Source loan | New proof loan | Complete source repayments | Historical through Oct 13 | Ordinary native cash events after handoff |
| --- | ---: | ---: | ---: | ---: |
| 2430 | 523 | 2 | 2 | 0 |
| 2612 | 524 | 9 | 9 | 0 |
| 2647 | 525 | 10 | 5 | 5 |
| Total | | 21 | 16 | 5 |

The [source narrative](../../../../../../credesal-db-space/docs/learnings/loan-variable-repayment-interest.md#full-histories-and-a-clean-progression-window-october-30-follow-up)
owns the audit and its limitations. **759 source assertions pass** across
524 master audit rows, 42 payment before/after rows and 141 formula-audited
daily closes. The three lives have no recorded restructuring or reversal,
stable ordinary/mora rates and no observed freeze. All observed last-interest-
date changes accompany interest-bearing payments; no unexplained critical
noninitial audit edit was found. Available evidence cannot exclude unlogged or
same-day offsetting manual edits.

2430's actual disbursement movement precedes its initialized portfolio anchor
by two days. Both dates and all repayment intervals are retained, rather than
silently choosing the header date for disbursement. 2647's partial-interest
covered-day behavior is a payment-side source rule, not an identified manual
adjustment.

## Handoff simulation and frozen scope

Source comparison calendar:

- **Arissto through: October 13, 2026**, inclusive.
- **Fineract starts: October 14, 2026**.
- Daily comparison through October 29: **16 days / 48 loan-day observations**.

The existing local default tenant has **Arissto through September 2** and
**Fineract starts September 3**. That boundary was not changed. Every canary
date is shifted backward by **41 calendar days**, including origination,
disbursement, all installment dates, all repayments, mora anchors and the
comparison window. Thus source October 13/14 maps to native September 2/3,
and source October 29 maps to native September 18. All intervals remain intact
and in 2026; no rate, cash or installment component is rescaled.

Plan SHA-256:
`a82de2eca836f5e119fb37da0e8c03597d16ae8155446cf61122eab175915172`.
Target: local `localhost:8443`, tenant `default`, database `fineract_default`,
fingerprint `264d304e2927f694`. Namespace `PROOF:hist-prog-oct30:` uses client
1046, products 9/10 and daily mora definition 14. This is an isolated canary in
the existing target lifetime, not a reset or composed sync workflow.

All **134 source contractual installments** are installed exactly before
historical servicing. Historical disbursements and the 16 pre-handoff
repayments use the supported source-exact APIs; source component allocations,
dates, amounts and identities are verified. Historical insurance cash and its
charge owner are retained, including 2430's fee component. No pre-handoff GL
is posted. The actual migration-metrics API establishes all eight opening
operational metrics from the October 13 source state. This is one handoff
baseline, not daily source alignment.

After handoff the five unchanged source cash amounts use the **ordinary
repayment API**, with no declared component overrides. Native daily interest
and daily mora then operate with explicit source mora terms. No waiver,
manual interest/date edit, balance correction or source-exact future repayment
is injected. New recurring insurance assessments are excluded from this
ordinary-interest/mora experiment; historical insurance cash remains included.

## Results: native behavior versus source parity

**969 native API/ledger/arithmetic/protection assertions pass; zero fail.**
**78 additional persisted accounting assertions pass; zero fail.** Those
**1,047 native-contract checks** establish full cash-event coverage, unchanged
imported history, actual-principal interest arithmetic, daily mora assessment,
accrual recognition and controlled execution. They are separate from source
parity: of **144 exact daily source comparisons** (three metrics per loan/day),
**74 match and 70 differ**.

| Source loan | Principal matches | Exact ordinary-interest matches | Ordinary interest within one cent | Mora matches | Source / native positive-mora days |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2430 | 16/16 | 12/16 | 16/16 | 16/16 | 0 / 0 |
| 2612 | 16/16 | 8/16 | 16/16 | 2/16 | 14 / 11 |
| 2647 | 0/16 | 0/16 | 0/16 | 4/16 | 6 / 11 |

### Ordinary interest and allocations

The independent interest oracle sums actual-principal calendar-day intervals
after the source anchor, rounds cumulative native earned interest once, adds
the frozen opening interest, and subtracts native interest actually collected.
Its inputs are the handoff principal/rate and dated repayment ledger principal
components, not the server's outstanding-interest summary. Thus it validates
accrual on the principal the native allocator actually repaid; it does not
declare those allocations equivalent to source allocations.

2430 and 2612 have no cash event after handoff in this window. Their exact
ordinary-interest differences are at most one cent, explained by carrying a
rounded opening balance and separately rounding native subsequent cumulative
accrual, versus the source's rounded full interest-date interval.

2647 diverges on its first native cash event, source October 14. The persisted
repayment mappings show the entire payment going to **older overdue principal**,
on contractual rows dated before the migration baseline. No interest is paid
by that first native transaction, while the source transaction has both
principal and ordinary-interest components. This changes subsequent principal
exposure and therefore later ordinary interest and mora.

The mechanism is consistent with the inspected strategy:
`CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor` inherits
`DuePenFeeIntPriInAdvancePriPenFeeIntLoanRepaymentScheduleTransactionProcessor`.
Its due-payment order is penalty/fee/interest/principal **within each
installment**. That is not a global interest-first rule across the whole loan.
The handoff's collectible interest is on the additional baseline dated after
older principal arrears; those older rows can consume cash first. The first
post-handoff persisted mapping confirms this mechanism directly.

### Mora

The independent mora check uses the persisted handoff contractual principal
rows, actual native principal, source monthly rate and mora payment anchors.
It computes rounded installment amounts and each positive daily difference,
then subtracts actual native mora collections. All daily assessments,
outstanding amounts and mora accrual transactions agree with that native rule.

They do not reproduce source mora progression. 2612 has source positive mora
on October 16–29, while the native canary has 11 positive days. 2647 has six
positive source closes but 11 positive native closes, with native repayment
allocations also changing the exposure and mora-payment anchor behavior.
2430 remains the zero-mora control.

The native implementation clamps the mora calculation anchor to the migration
baseline and assesses differences of rounded cumulative installment amounts.
It also uses the aligned native schedule. These are verified native mechanics,
not proof of the unavailable source application's complete mora eligibility
and timing path. The [existing source mora investigation](../../../../../../credesal-db-space/docs/learnings/mora-y-cargos-de-creditos.md)
and [ordinary-interest source comparison](../../../../../../credesal-db-space/docs/learnings/loan-interest-basis-2612.md)
already identify incomplete historical reproducibility of that source path.
The complete cause of every source mora difference remains unresolved. Do not
invent a grace period or change the rate to make this experiment match.

## Accounting and preservation

Read-only PostgreSQL confirms loan/product flags off, all 21 cash repayments,
one handoff baseline per proof, persisted principal/interest/mora totals and
the first native allocation mapping. All **152 linked journal rows** balance
per transaction and are dated on or after native Fineract starts. Ordinary and
mora income equal their respective native accrual amounts; imported opening
interest is not recognized again. The 16 imported repayments keep their IDs,
dates, cash and component allocations throughout progression.

Repeated final COB changes neither proof loan snapshots nor linked GL
count/hash. Loan-local simulation remains enabled on the new proofs. The
scheduler was temporarily paused during mutations and restored to its original
active state. Tenant business dates remain empty, business-date configuration
disabled, and accounting-cutoff metadata unchanged. Protected counts/hashes of
pre-existing loans, loan transactions, schedules, loan charges, GL, clients,
products and mora-term rows remain unchanged, including previous canaries.
This is protection of the stated tables, not every table in the tenant.

No backend repair, runtime configuration change, production operation or
source write was made. Setup, all progression days and repeat completed with
no execution errors.

## Evidence and implications

[Sanitized checks and daily parity results](investigations/history-progression-oct30-checks.json)
keep native assertions separate from failing source comparisons. Private full
source extraction, audit/payment traces, immutable plan, API snapshots,
independent oracle, persisted accounting audit and runners are retained under
ignored `.arissto-sync/history-progression-oct30/`; no source financial samples
or borrower identities are copied into this report.

This completes the requested separate full-history progression experiment.
Dynamic accrual with the flag off is demonstrated, but the earlier
[adapted three-event canary](source-event-recalculation-off-canary-oct30.md)
does not establish source-equivalent servicing after a real handoff. Payment
priority across the migration baseline and overdue rows needs an explicit
business decision and a new acceptance proof. Mora parity needs further source
execution research. Neither mismatch justifies toggling standard interest
recalculation or silently altering historical allocations.
