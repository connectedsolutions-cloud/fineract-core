# Sandbox loan cutoff canary results

## 2026-09-02 — expanded loan-lifecycle canary

The local `sandbox` tenant contained four active seeded clients. Matching those
external identities to the read-only Arissto source produced thirteen candidate
loans. Candidate selection avoided customer names and other sampled PII.

The first fresh candidates were not applied:

- loan `2` planned as quarantine because its first-accrual-day signature was
  ambiguous;
- loan `687` was not standalone because its refinance chain continues into
  loan `805`; and
- loans `805` and `2319` planned as quarantine because required assigned-staff
  mappings were absent from the sandbox.

The executed proof used the isolated namespace `cutoff-canary-0902` for the
seeded-client refinance chain `183 -> 301 -> 569`. This prevented collisions
with the chain's existing sandbox identities while exercising ordinary
disbursements, source-exact repayments, historical charges, one repayment
reversal, and two refinance payoffs. Every frozen financial event was dated
between `2023-08-18` and `2024-07-24`, strictly before the active cutoff of
`2026-09-02` in `America/El_Salvador`.

### Immutable identifiers

- plan: `9c15fc0e277c4004bbde8258383811f8`
- initial run: `66bcb6a0a837439f887628e53361c959`
- replay run: `773caa3039e04735a6654b66156c42f7`
- target fingerprint: `b9f6834b66790744`

### Results

- Initial apply: three loan lifecycles succeeded and the existing product was
  unchanged.
- Initial reconciliation: `ok=true`; three loans, one product, and three staff
  assignments checked; zero mismatches and zero failed or quarantined items.
- Database assertion: three namespaced loans contained 28 total loan
  transactions, including 19 source-exact allocation transactions and one
  reversed transaction. Their linked `acc_gl_journal_entry` count was zero.
- Frozen-plan replay: all three loans were recovered rather than recreated.
- Replay reconciliation: `ok=true`, with the same counts and zero mismatches.
- Post-replay database assertion remained exactly three loans, 28
  transactions, 19 source-exact transactions, and zero linked GL entries.

This canary proves the expanded synced-loan lifecycle can cross the active
historical cutoff without native journal leakage and can be replayed without
duplicate loan or transaction effects. It does not replace the separate
acceptance proofs for native commands exactly on the cutoff, ordinary native
pre-cutoff rejection, undo-disbursement, terminal adjustment, taxed
disbursement charges, scheduled jobs, or savings/transfer fan-out.
