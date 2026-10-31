# Three source-event canaries with recalculation off — October 30, 2026

**Passed in local `default` / `fineract_default`.** Three source-evidenced
repayment-timing scenarios were adapted into fresh synthetic loans. Ordinary
interest follows actual principal and repayment dates with the standard
interest-recalculation flag **false**. This confirms the bounded servicing
claim; it does not enable native schedule recalculation or certify the portfolio.

## Cohort and source evidence

| Arissto loan | Movement | Source due | Source paid | Timing | Synthetic Fineract loan |
| --- | --- | --- | --- | --- | ---: |
| 2430 | `0000032966` | 2026-10-15 | 2026-10-12 | 3 days early | 520 |
| 2612 | `0000031887` | 2026-09-27 | 2026-09-29 | 2 days late | 521 |
| 2647 | `0000032865` | 2026-10-01 | 2026-10-09 | 8 days late | 522 |

The [source investigation](../../../../../../credesal-db-space/docs/learnings/loan-variable-repayment-interest.md#three-evidenced-repayment-events-october-30-follow-up)
owns event selection, SELECT queries and interpretation. Timing is based on a
payment crossing cumulative scheduled principal, not a source movement-to-
installment allocation FK. Before/on/after completed source closes demonstrate
the corresponding principal reduction and actual-principal daily provision.
All three have no recorded restructuring, no reversal, stable ordinary rates
and no frozen state over those observed closes. This is not proof of source
contractual schedule regeneration.

## Frozen experiment and adaptation

- Target: local API `localhost:8443`, tenant `default`, database
  `fineract_default`, fingerprint `264d304e2927f694`, explicitly requested by
  the operator. No composed workflow or sandbox reset was run.
- Existing ownership boundary: **Arissto through September 2, 2026**;
  **Fineract starts September 3, 2026**, America/El_Salvador. These are the
  existing default-tenant dates, not a new source snapshot for canonical loans.
- Frozen plan SHA-256:
  `104d36a07cc1a221000fb0f459113aa96c03233c76d506856e6e538ead28ae4b`.
- Namespace: `PROOF:source-off-oct30:`. One synthetic client (1045), two new
  products (7 monthly / 8 daily), exactly three new synthetic loans.
- Product and loan flags remain false in both API and PostgreSQL. Products
  use the Credesal strategy, daily declining-balance interest, periodic
  accrual accounting and API-installed migration metric baselines.
- Preserve each source event's annual rate, actual principal immediately before
  payment, principal reduction and early/late day offset. Opening interest is
  synthetic **10.00**, not the source interest balance. Dates and two-installment
  native schedules are synthetic. All three first due dates are September 8;
  payments are September 5, 10 and 16 respectively. Observation dates run
  September 3–19.
- Ordinary repayment cash covers independently calculated native collectible
  interest plus the preserved source principal reduction. No source-exact
  allocation is injected for these repayments. This is deliberately not a replay
  of source cash amounts, the full source history or the source schedule.
- Mora, insurance, fees, pauses, waivers and historical reversals are excluded.
  A namespaced historical disbursement uses `sourceExactDisburse`; the opening
  baseline uses the real migration-metrics API. Financial writes use APIs only.

## Independent results

**414 source/API/arithmetic assertions passed; zero failed.** This includes
24 source assertions, daily comparisons over **51 loan-day observations**, the
three ordinary repayment allocations, unchanged contractual forecasts,
protection checks and repeated-COB checks. **53 additional read-only persisted
accounting assertions passed; zero failed**: **467 final assertions total**.

The oracle does not derive expected interest from the server's schedule or
summary. It uses Decimal arithmetic over principal/date intervals:

```text
new interest = round(sum(actual principal in interval × annual rate / 100
                         × calendar days in interval / 365), 2)
collectible interest = synthetic opening interest + new interest - interest paid
```

For a payment at date `p`, the original principal applies from source anchor
`S` to `p`, and the reduced principal applies after `p`. Dates are evaluated at
the loan's simulated business date; do not relabel them as Arissto's inclusive
end-of-day snapshots. On-time and unpaid controls are independent mathematical
comparisons, not additional runtime loan copies.

All observed principal, interest-paid and interest-outstanding amounts match.
Early repayment produces less total earned interest than the on-time
counterfactual, and both late repayments produce more. A due date alone does
not reduce principal. After each actual payment, subsequent interest uses the
reduced principal, including for the daily loans after contractual maturity.
Prior COB interest is not collected twice by the subsequent ordinary repayment.

The contractual future principal/interest forecasts remain unchanged. Thus the
tested response is dynamic earned/collectible ordinary interest, not native
future schedule regeneration. Enabling the standard flag would be a separate
capability with separate preservation requirements; see the
[handoff investigation](interest-recalculation-handoff-investigation.md).

Persisted loan totals and flags agree with the API. Each proof has one opening
baseline, one disbursement, one ordinary repayment and 17 native accruals.
All **111 proof GL rows** balance per linked loan transaction. Native ordinary
income equals only post-boundary earned interest; opening interest is not
recognized again. No proof GL row predates Fineract starts. Repeating final
loan-scoped COB changes neither proof snapshots nor linked GL count/hash.

## Preservation and execution record

The scheduler was paused/restored around each mutation phase and is restored
to its original active state. Tenant business dates remain empty and business-
date configuration remains disabled. The active accounting boundary is
unchanged. Loan-local simulation remains enabled on the three proofs so regular
scheduled COB excludes them. No global business date was moved.

Counts/hashes of all pre-existing loan rows, loan transactions, repayment
schedule rows, loan charges, journal rows, clients and products remain unchanged.
These are the specified protected tables, not a hash of every target table.

Setup validation refusals (required client legal form, product numbering,
simulation HTTP verb and daily loan term) were corrected without duplicate
proof creation. The retained result records them. All three final setups and
servicing runs complete successfully. An initial accounting-check script used
the wrong debit/credit enum assumption; the rejected check is retained, and
the final check uses the verified `JournalEntryType` mapping credit=1/debit=2.
No backend or migration runtime repair was made for this experiment.

[Sanitized final checks](investigations/source-event-off-oct30-checks.json)
contain identities, assertions and outcomes without source financial samples.
Complete private source extraction, frozen plan, API snapshots, execution
runner, independent oracle and persisted audit are retained under ignored
`.arissto-sync/source-event-off-oct30/`. Treat that evidence as private; it is
not a reusable service or authorization to replay any target.

The [earlier repaired servicing proof](recalculation-off-servicing-repair-oct28.md)
owns pause/waiver and mora coverage outside this experiment. These three
adapted events do not establish exact Arissto allocation parity, full historical
replay acceptance, arbitrary backdated correction, native flag activation or
production readiness. The existing synced portfolio was not changed.

## Full-history progression follow-up

The separate [October 30 full-history handoff canary](full-history-interest-mora-progression-oct30.md)
represents all 21 retained source repayments and 16 daily progression dates.
Native accrual/accounting checks pass, but exact source progression fails:
2647 changes cash allocation after handoff, and mora differs on both delinquent
loans. Earlier adapted-event acceptance is not source-equivalent servicing
acceptance. Historical allocations remain preserved; no runtime repair or
recalculation activation was made.
