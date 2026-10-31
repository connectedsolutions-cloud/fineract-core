# Credesal mora freeze and unfreeze

## Scope

These controls suspend **Credesal daily mora (charge time 19) only**, on one active
loan. Ordinary interest, other fees, repayments, repayment allocation, contractual
due dates and delinquency classification continue normally. They do not waive
mora already owed or change the loan lifecycle status.

The existing `command=freeze` is a separate whole-loan control. A mora-only
unfreeze cannot lift it. The public whole-loan unfreeze remains unimplemented;
use neither command as a substitute for the other.

## API

Use the normal Fineract tenant header and authentication. Grant `FREEZEMORA_LOAN`
and/or `UNFREEZEMORA_LOAN` to the operator's role. Tenant migration
`0432_add_mora_freeze_permissions.xml` creates these permissions; it does not
automatically grant them to ordinary roles.

Freeze:

```http
POST /loans/123?command=freezeMora
Content-Type: application/json

{
  "effectiveDate": "2026-09-01",
  "dateFormat": "yyyy-MM-dd",
  "locale": "en",
  "reason": "Temporary agreement"
}
```

Unfreeze:

```http
POST /loans/123?command=unfreezeMora
Content-Type: application/json

{
  "effectiveDate": "2026-09-15",
  "dateFormat": "yyyy-MM-dd",
  "locale": "en",
  "reason": "Resume mora"
}
```

Read state and history with `GET /loans/123/mora-freeze` (`READ_LOAN`). The response
has `moraFrozen` (the mora-only control), `wholeLoanFrozen` (the separate general
freeze) and `history`, ordered by effective date then event ID. Each history row
includes action, effective date and optional reason. Effective dates follow the
normal API date serialization. `GET /loans/123/freezehistory` also exposes the
underlying combined freeze history with distinct action names.

Mora remains suspended if **either** control is frozen. `moraFrozen=false` alone
does not mean the whole-loan freeze has been lifted.

## Dates and validation

- A freeze date is inclusive. An unfreeze date is the first day mora runs again.
  The example excludes September 1 through 14; September 15 is chargeable.
- Past effective dates and today's business date are accepted, even before the
  loan's last closed business date. Future dates and dates before actual loan
  disbursement are rejected.
- Events are appended in effective-date order. An effective date cannot precede
  the last mora-only event. This permits recording a complete past interval by
  first freezing and then unfreezing, both in the past.
- A freeze requires mora-only state to be running; an unfreeze requires mora-only
  state to be frozen. Duplicate transitions are rejected. Both require an active
  loan. An unfreeze cannot precede its freeze. Same-day freeze/unfreeze is valid
  and excludes zero days.
- `effectiveDate` is required; `reason` is optional and limited to 500 characters.
  The loan row is locked while transitions are validated and persisted.
- To record multiple past intervals, enter the oldest first. This API does not
  insert, edit or delete events in the middle of an existing history.

## Calculation and past postings

The command saves history only. It does **not** immediately run COB, change
charges, reprocess repayments, reverse transactions or rewrite GL postings.
Existing mora remains payable while frozen.

On subsequent daily mora processing, a frozen loan is skipped. Once unfrozen,
the cumulative calculator counts only chargeable days after the installment due
date or latest mora payment date, excluding every stored frozen interval.
Overlapping whole-loan and mora-only intervals are subtracted only once, and
later repayment dates clip the calculation window. Grace-day eligibility and
rates remain unchanged. Frozen days never become a catch-up mora charge.

Backdating does not automatically repair historical accounting. The existing
COB balance reconciliation still compares the recalculated amount with assessed
outstanding mora, and may create its normal charge increase or adjustment at the
processing date. In particular, a past freeze can lower the next calculated
balance; a past unfreeze can include chargeable days since its effective date.
These controls are not a historical journal reversal or accounting repair tool.

## Storage and Mifos

The existing `m_loan_freeze_history` stores `MORA_FREEZE` and `MORA_UNFREEZE`
events, including the existing audit metadata. Whole-loan `FREEZE`/`UNFREEZE`
events remain independent; mora-only commands never change `m_loan.is_frozen`,
`frozen_on` or `freeze_reason`. The mora calculator unions both kinds of frozen
intervals. Ordinary interest pauses are separate and do not pause mora.

In Mifos, open the loan's **Overdue Charges** tab. The mora control shows its
state and any separate whole-loan freeze. Authorized users can submit an
effective date and optional reason, including past dates. History displays
chronologically with exact action filtering and English/Spanish labels. This
change does not add a portfolio-wide freeze search or change report/export
schemas; the read endpoint provides the ordered history for consumers.

## Verification and rollout

Focused tests cover backdated transitions, future/disbursement bounds, inactive
loans, duplicate/inverted events, inclusive boundaries, multiple intervals,
overlapping whole-loan controls, same-day events and mora-payment clipping.
Frontend tests cover exact past-date payloads and invalid dates/state. Build and
template compilation verify the API and Mifos integration.

Deploy backend and frontend together, apply the permission migration through
normal Fineract startup, and assign role permissions. Before live use, verify
one dated interval and the following daily COB on an isolated tenant. Unit tests
and compilation do not establish deployed availability or live balance parity.
