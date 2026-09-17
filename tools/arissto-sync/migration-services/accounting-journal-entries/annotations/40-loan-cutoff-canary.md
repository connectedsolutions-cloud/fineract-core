# Loan cutoff canary

## Supported slice

The loan sync now uses the permission-gated `sourceExactDisburse` command for
ordinary source disbursements. Existing source-exact repayment, component
reallocation, goodwill-credit, top-up disbursement, and refinancing
disbursement handlers also establish the operational-migration origin for only
the duration of their command execution.

At the loan accounting bridge, the complete batch is evaluated before any
journal processor runs:

- all transactions before an active cutoff under migration origin suppress the
  complete native accounting batch;
- all eligible transactions post the complete batch; and
- a batch spanning both sides of the cutoff is rejected rather than partially
  accounted.

## Local canary procedure

Use a restored disposable tenant and one reviewed source loan whose frozen
lifecycle contains an ordinary disbursement and source-exact repayments, with
no reversal, refinance, top-up, or terminal adjustment.

1. Start Fineract so Liquibase applies migration `0320`.
2. Grant both `SOURCEEXACTDISBURSE_LOAN` and
   `USE_ARISSTO_OPERATIONAL_MIGRATION` to the local sync principal.
3. Create the scoped loan plan. Its inclusive source-through date defaults to
   the current sync date in `America/El_Salvador`; use
   `--source-through-date YYYY-MM-DD` when the canary requires an explicit
   source boundary. The internal cutoff is the following day.
4. Configure Fineract with that frozen plan date and read it back in `DRAFT`;
   record its date, timezone, revision, and hash.
5. Pause accounting-producing jobs, then activate the cutoff.
6. Confirm the one-loan plan's financial event dates are all strictly before
   its frozen cutoff.
7. Apply and reconcile the plan.
8. Prove the native loan, schedule, and transactions exist while the loan has
   zero native journal lines for the migrated pre-cutoff events.
9. Prove an ordinary pre-cutoff financial command is rejected.
10. In a separate native fixture, prove a transaction dated exactly on the
   cutoff creates its complete balanced journal.
11. Restore the tenant baseline after the canary; do not seal the exploratory
    configuration.

## Superseded exclusions

Loan repayment reversal, undo-disbursement, native terminal goodwill-credit,
cross-cutoff refinancing, and accounting side effects that fan out into
savings accounting were deliberately excluded when this first canary was
written. They are now covered by the next implementation slice documented in
[`50-loan-lifecycle-coverage.md`](50-loan-lifecycle-coverage.md). Keep this
procedure bounded to its original fixture so its expected evidence remains
stable.
