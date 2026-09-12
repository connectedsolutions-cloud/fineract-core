# Remaining loan lifecycle cutoff coverage

## Source-exact command boundary

The sync engine no longer invokes native command identities for these migrated
loan events:

| Migrated event | Fineract command | Required command permission |
| --- | --- | --- |
| repayment reversal | `sourceExactReversal` | `SOURCEEXACTADJUST_LOAN` |
| disbursement reversal | `sourceExactUndoDisbursal` | `SOURCEEXACTDISBURSALUNDO_LOAN` |
| terminal closeout | `sourceExactTerminalAdjustment` | `SOURCEEXACTTERMINALADJUSTMENT_LOAN` |
| source charge creation | `sourceExactAddCharge` | `SOURCEEXACTCREATE_LOANCHARGE` |

Each handler also requires `USE_ARISSTO_OPERATIONAL_MIGRATION`, limits the
migration posting origin to the underlying write call, and restores native
origin afterward. The existing native adjustment, undo-disbursement,
goodwill-credit, and charge commands retain native cutoff behavior.

## Accounting fan-out

- Loan accounting batches remain all-or-nothing. A mixed pre/post-cutoff batch
  rejects before a processor runs.
- Savings accounting batches now use the same all-or-nothing policy. This
  covers the savings side of loan top-up/refinance account transfers without
  filtering individual transaction rows.
- Due-at-disbursement tax journals are evaluated before their dedicated tax
  journal group is generated. Historical migration disbursement taxes suppress
  as a complete group; native historical attempts reject.
- Final journal persistence remains the defensive boundary for any producer
  that reaches storage without an earlier generation check.

## Canary extension

For a disposable-tenant lifecycle test, grant the event-specific permissions
above plus `USE_ARISSTO_OPERATIONAL_MIGRATION`. Exercise one fixture for each
event and reconcile both sides of the boundary:

1. A source-exact event strictly before the active cutoff changes loan state
   but creates no native GL rows for that event.
2. The equivalent native command strictly before cutoff is rejected.
3. A native event on the cutoff date creates a complete balanced journal.
4. A repayment reversal and undo-disbursement preserve their source external
   identity/idempotency behavior on retry.
5. A refinance/top-up that creates savings transactions suppresses the entire
   pre-cutoff savings accounting batch; no partial loan-only or savings-only
   journal is accepted.
6. A taxed disbursement produces either its complete eligible tax journal group
   or none under historical migration origin.

COB accrual/reprocessing jobs and provisioning/external-owner accounting are
not claimed by this loan lifecycle slice and require separate producer-level
coverage before they can be included in a cutoff canary.
