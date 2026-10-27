# Historical source-day reconstruction for refinanced loans

This supplements the [loan contract](contract.md) and the ordinary-loan
[source-window acceptance](loan-flow-cob-acceptance.md). It admits a narrowly
proven historical incoming refinance before later ordinary payments, without
moving the frozen accounting boundary or importing those later payments.
Implementation: [loan_source_window.py](../../arissto_sync/loan_source_window.py).

## Eligibility and proof

All existing ordinary-loan projection checks remain required: an exact source-day
snapshot, active state currently and at that snapshot, complete after-boundary
movement counts, only ordinary/mobile payments after the boundary, no reversed
history or revisions, and retained principal/interest cash totals matching the
snapshot's paid counters. The full eligible historical stream is retained;
only later payment movements and their associated charge details are excluded.
Historical balances are restored from the dated close.

An incoming refinance additionally requires:

- Exactly one historical same-owner top-up; no outgoing successor, consolidation
  or cross-owner settlement for the projected loan. Its payoff day precedes
  `accounting_cutoff.date` (an event on the inclusive source-through day is valid).
- Both source loans and histories in the extracted dependency graph, matching
  raw client keys, and the same unique liquidation/payoff/disbursement link in
  the predecessor and successor lifecycle views.
- Exact snapshot identities for both loans. The predecessor is closed in its
  current header and the exact source-day snapshot, with zero total, interest,
  mora and recargos and fully paid principal. Its post-payoff state is closed;
  there are no later posted payments, after-boundary predecessor events,
  reversed history, revisions or omitted financial reconstruction.
- One successor disbursement on the historical payoff day. Its amount equals
  the successor's snapshot disbursed principal. The unique predecessor payoff
  movement has the declared identity/date/role and exactly matches every
  linkage amount component; the payoff is positive and no larger than the
  successor disbursement. Missing or ambiguous evidence leaves the original
  quarantine intact without partially changing the source data structures.

A positive predecessor insurance residue is accepted only by the existing
`_classify_closed_stale_insurance_residue` rule, with the exact same residue in
its current header and historical snapshot. The rule requires the complete
closed, zero-debt signature. It neither creates collectible insurance nor
changes the predecessor's amounts, charge history or replay contract. A
positive actual debt balance, negative/missing residue or unmatched header/
snapshot remains blocked. The projection reuses the canonical classifier.

The frozen `source_window` policy is
`active-historical-refinance-before-later-payments-v1`. It records both dates,
excluded movement identities/count, paid-counter corroboration, and the
`single-same-owner-historical-topup-v1` proof: predecessor key, liquidation,
payoff/disbursement identities, payoff date, snapshot identities and terminal
insurance policy. This metadata also belongs to the projected source-header
hash. Planning and apply validation run the same proof against fresh source
reads. A new immutable plan is required for newly projected evidence; old
plans and source events are never edited. Changed retained history, evidence
or excluded-event membership remains subject to the normal source/hash guards.

Multiple-predecessor consolidation, cross-owner refinancing, outgoing or
post-boundary refinancing, predecessor temporal reconstruction and revised/
reversed histories remain unsupported by this projection. Existing downstream
financial validation, exact allocation, transfer cohort, target-state and
accounting guards remain active. This extension adds no API writes during
planning and does not reprocess managed transactions or charges.

## October 27 same-cycle verification

Evidence: [LS-28 sandbox checks](investigations/ls28-historical-refinance-projection-oct27.json).

- Cycle `sandbox-2026-10-26-full-clean-a`; local `sandbox` / `fineract_sandbox`,
  fingerprint `b9f6834b66790744`.
- **Arissto through: 2026-10-26. Fineract starts: 2026-10-27.**
- Plan `46b49222cc9e488ca7a4f553f27af5f9`, requested root `loan:921`.
  Source and write selection both contain exactly **101, 283, 553, 921**, plus
  `product:00010`: one recovered loan, three creates, one unchanged product.
  All prerequisites and native-payoff successors are included. This is the
  complete four-loan recovery scope for 921; it does not select the other
  LS-07 roots or the wider 19/34-loan scope.
- Planner applicable with no blockers or quarantines; read-only
  `_loan_apply_guard` passed. Source `553 → 921` payoff remains on 2024-12-20.
  The existing closed-insurance-residue policy applies to 553.
- Payment `0000034318`, dated October 27, is frozen as excluded. The writer's
  23 events, **entire source lifecycle**, refinancing terms and all eight
  metric targets equal the original October 26 plan. No writer event is dated
  on or after October 27. The changed 921 source hash records the explicit
  projection evidence, rather than a changed historical lifecycle.
- Seven new regression methods include fail-closed cases for future/reversed/
  ambiguous links, missing predecessor evidence, paid-counter mismatch, invalid
  dates, stale insurance, boundary-day behavior, idempotency and input order.
  The positive regression fails against the pre-extension implementation.
  **287 focused tests passed.**
- Complete before/after target hashes match for loans, transactions, schedules,
  charges, transaction mappings, charge ownership, clients, transfer history
  and GL journals. Counts remain 1,143 loans, 24,850 loan transactions and zero
  GL journals. Scheduler remains paused, workflow interrupted and accounting
  boundary unchanged. No reset, replacement cycle, apply, resume or backend
  restart occurred. No Arissto or target financial records were changed.

This verifies reconstruction and plan readiness for a bounded same-cycle retry.
**Native creation/disbursement, transfer replay and financial reconciliation
remain unexecuted.** Recheck current source/target guards before using the new
plan; test evidence does not freeze future source commits. The separate LS-27
payoff-closure issue for the original eight-root/19-loan recovery remains open.
