# Dated principal revision-chain projection

Implemented 2026-10-30. This is a migration-only admission policy in the loans
service. Offline regression proof is complete; a disposable-target import,
native readback and future-servicing acceptance have **not** been performed.
No sync, reset, plan approval or target mutation is authorized by this note.

## Scope and proof

The reason-based classifier accepts a complete sequence of at least two source
revisions containing multiple distinct remaining-principal stages. It requires:

- unique revision IDs and strictly ordered creation timestamps;
- a complete initial full-principal archive;
- every later superseded archive's principal equal to the preceding revision's
  derived replacement principal;
- replacement principal at every revision equal to original principal less net
  valid principal allocations recorded before that revision;
- a final current plan equal to the latest derived replacement principal;
- current installments numbered consecutively, nonnegative and strictly dated,
  starting after the latest revision day;
- a unique historical/later payment split, matching the source principal balance
  after all payments under the existing remaining-schedule classifier.

Missing payment creation times, a payment tied to a revision timestamp, mixed
naive/offset clock representations, duplicate revisions, missing archives and
unexplained principal transitions fail admission. Creation times establish the
split only; original financial event dates still govern replay. No timezone is
inferred for Arissto's stored timestamps. Existing simpler classifiers retain
their scope; their payment/revision timestamp ties also fail closed.

The archived rows represent superseded plans. They need not equal their
replacements row for row. Historical anomalous dates and negative interest stay
unchanged in frozen evidence with an `archived_schedule_anomaly` warning. Stale
`MONTO_REESTRUCTURADO` headers are retained with reported/derived values and a
`stale_revision_header_amount` warning. Neither warning changes operative rows.
The frozen source hash includes complete revision/archive evidence and the
payment creation times, so changing that evidence invalidates the source proof.

## Refinance identity and dates

Reviewed refinance overrides use `reviewed-date-or-proven-revision-v1` in both
`config/loans.json` and its strict validator. The saved reviewed origin remains
valid. A later origin is admitted only if it equals the latest proven revision
creation day. Predecessor, successor, actual payoff/disbursement date, linked
successor disbursement identity and amount, principal and payoff remain guarded;
a later posted predecessor payment is not accepted by this reviewed path.
This is not another unconditional loan-ID bypass.

The compatibility descriptor preserves original application and actual
refinance dates, reviewed and current origin, current maturity, approved/source/
projected installment counts, refinance links, and the accounting boundary.
The original approved count comes from the application before the mutable
portfolio header; the current header count is retained separately.
Immutable plans separately record when the source was observed. The descriptor,
revision proof, warnings and raw archives are part of the plan and source hash.

## Selected writer and retry behavior

`fineract-source-exact-remaining-schedule-v1` uses
`sourceExactResyncSchedule` to install the frozen schedule after disbursement
and before servicing, with expected non-disbursement transaction count zero and
current/replacement schedule hashes. This API replaces the installment
collection and supports a different row count. It does not use the separate
same-cardinality `sourceExactActiveSchedule` command.

The native application carries the projected repayment count and frequency
term. The original approved count stays in provenance; expected maturity stays
under the existing source-term contract. The planner and writer validate the
projected count, principal conservation, contiguous dates, nonnegative monetary
components and frozen replacement hash. Apply validates the descriptor before
accessing the target. The replacement creates neither cash nor a disbursement.

An identical installed schedule is a no-op, including retries after partial
payment replay. A mismatching progressed schedule is rejected rather than
reinstalled as unserviced. After final metric alignment, the existing aligned
recovery path verifies native identity, boundary, continuation readiness, all
eight metrics, complete dated history and refinance settlement, and selected
term/account contract before returning without writes. A metric match alone
cannot bypass an incomplete import. No new full re-sync/reprocessing authority
is introduced.

## Regression case and acceptance still required

For the reviewed 2499 case, **Arissto through: 2026-10-29**;
**Fineract starts: 2026-10-30**. These are the evidence/test boundary, not a
change to an active tenant. The projection has a 73.91 principal / 50.04 interest
historical bridge followed by 15 current rows totaling 98.09 principal. Native
row count is 16; original approved count is 30. The later 4.33 principal / 0.67
interest payment is replayed once. The 22 source payments retain their external
identities and financial dates; cash is 129.29 including 0.34 historical mora.
The current balance is not deducted a second time from the replacement plan.

Final eight-metric targets, including 0.64 accrued ordinary interest and 1.90
due principal, use the existing frozen snapshot and
[final alignment contract](loan-metric-final-alignment.md). Insurance is never
inferred from undifferentiated fees. Existing accounting ownership, no fictitious
GL, source drift, borrower identity and component closure guards still apply.
The source narrative remains in
[the loan research note](../../../../../../credesal-db-space/docs/learnings/prestamos.md).
The supplied October 30 investigation/policy/timeline in the local
`fineract-reports/reports/loan-2499-*-2026-10-30.md` files are planning evidence.

Offline tests: `tests/test_dated_principal_revision_chain.py`, plus existing
remaining-schedule, aligned-recovery, source-window, refinance, metric-alignment
and loan tests. Before declaring the component imported, regenerate and review
the immutable plan at the selected target boundary using the supported workflow
mode; execute only when authorized. Require native 16-row readback, exactly-once
22-payment history, all eight native metric reads, complete-component
reconciliation and separate next collection/accrual smoke tests. No backend
change was needed for the offline representation; target compatibility remains
to be demonstrated by that controlled execution.
