# DPF monthly-on-opening-day interest schedule

## Outcome

Preserve Arissto's customer-facing DPF schedule natively in Fineract: monthly
interest is posted and transferred on the account activation/opening
day-of-month. If that day does not exist in a shorter month, use the last
calendar day of that month, then return to the original anchor in the next
month.

Source evidence is maintained in
[`creditos-y-depositos.md`](../../../../../../credesal-db-space/docs/learnings/creditos-y-depositos.md).

The same calendar rule is also verified in Arissto's monthly loan schedules;
see [`prestamos.md`](../../../../../../credesal-db-space/docs/learnings/prestamos.md).
The domains use different source anchors, but must use the same native date
calculation.

## Verified source rule

- The current anchor is `AHO_CUENTA_AHORRO.FECHA_APERTURA` for the current DPF
  cycle.
- All 119 reviewed posted-interest movements across 23 currently active DPFs
  with current-cycle history match that opening day-of-month.
- Retained short-month cases show 29/30/31 → February 28 and then a return to
  the original anchor in March.
- Historical renewals may have earlier anchors. Replay their linked movement
  dates exactly; do not recalculate historical dates from the current master.
- A maturity or closure before the next regular anchor creates a shortened
  final period and takes precedence over the recurring schedule.

## Options

### 1. New native activation-anchored monthly enums — recommended

Add a distinct persisted option to both savings posting and compounding enums,
for example value `9`:

```text
savingsPostingInterestPeriodType.monthlyOnActivationDate
savingsCompoundingInterestPeriodType.monthlyOnActivationDate
```

The schedule derives its immutable anchor from the account activation date.
For each successive month it calculates:

```text
day = min(originalActivationDay, lastDayOfTargetMonth)
```

It must always retain the original activation day, so January 31 → February 28
→ March 31 does not drift permanently to the 28th.

This needs no schema migration: the existing product/account enum columns are
`SMALLINT`, and the normal product-to-account lifecycle persists the new value.
It does require enum/API/dropdown/import support and native schedule tests.

This is the smallest durable extension because Arissto's anchor is already the
activation date; another account field would duplicate that fact.

## Shared Fineract calendar primitive

Do not implement the short-month rule independently inside savings. Define one
dependency-light anchored-month function and have both loan and savings paths
consume it. Its inputs are an immutable anchor date and a target month (or
month offset); its result is:

```text
day = min(dayOfMonth(anchor), lastDayOf(targetMonth))
```

Every occurrence must be calculated from the immutable anchor, never from the
previous occurrence. This preserves January 31 -> February 28/29 -> March 31.

Fineract's native loan schedule generator already implements this behavior. It
advances by month and then restores the day from
`LoanApplicationTerms.seedDate`; the seed is normally the disbursement date or
an explicitly configured schedule seed. The implementation work is therefore:

1. extract or expose the dependency-light anchored-month calculation as the
   common primitive;
2. retain the existing loan behavior and add regression coverage around the
   shared primitive;
3. make the new savings posting/compounding option call that same primitive,
   using account activation as its anchor.

This does **not** mean that savings and loans use the same source field. DPF
uses the current cycle's activation/opening date. A loan uses its contractual
schedule seed, while its stored first/last irregular dates and explicit term
variations remain authoritative. Daily, weekly, and fortnightly loan
frequencies continue using their native day/week arithmetic.

### 2. Add an explicit account posting-day field

Add `interest_posting_day_of_month` to product/account persistence and APIs.
This supports an anchor unrelated to activation and future user selection, but
requires a Liquibase migration, inheritance/update rules, and conflict rules
between activation date and the explicit day. No current Arissto evidence needs
that flexibility, so it is unnecessary for the first version.

### 3. Generate manual future post-as-on dates

Precomputing dates can imitate the source schedule without changing enums, but
it creates an external calendar that must be extended forever and complicates
backdated recalculation, renewals, maturity, and auditability. Do not use this
as the production contract.

### 4. Map to standard calendar-month posting

This is operationally simple but changes the customer promise and the amount
of interest in partial first/last periods. It is not an acceptable migration
mapping.

## Recommended native behavior

- Use the new activation-anchored option only for Arissto period `06
  MENSUAL(DIA APERTURA)`.
- Keep existing Fineract `MONTHLY(4)` semantics unchanged.
- Build posting periods from the immutable activation-day anchor.
- Use the same anchored boundary for compounding. Because migrated DPF interest
  is transferred to linked VISTA accounts, posted interest must not remain in
  DPF principal for the following period.
- Let maturity, premature closure, and explicit historical posted transactions
  truncate or override the next regular boundary through existing native
  lifecycle rules.
- Keep the three Arissto at-maturity exceptions outside this monthly option.

## First version

Implementation completed on 2026-08-26 for items 1–5 below, with focused core
and provider tests. Item 6 remains part of the controlled lifecycle gate.

1. Add the new posting and compounding enum identities and API rendering.
2. Extract the existing loan-compatible anchored-month calculation into a
   shared dependency-light primitive and add cross-domain regression tests.
3. Extend `SavingsHelper.determineInterestPostingPeriods` to retain the
   original activation day across every generated month through that primitive.
4. Reuse the existing monthly calculation component for each anchored period,
   with the new compounding enum accepted explicitly.
5. Configure migratable monthly DPF products/accounts with the new values and
   `interestCalculationDaysInYearType = 1` (Actual/Actual).
6. Verify transfer-to-VISTA and accrual accounting in the controlled lifecycle.

## Acceptance matrix

- 15th: January 15 → February 15 → March 15.
- 29th in a normal year: January 29 → February 28 → March 29.
- 29th in a leap year: January 29 → February 29 → March 29.
- 30th: January 30 → February 28/29 → March 30.
- 31st: January 31 → February 28/29 → March 31 → April 30 → May 31.
- A term maturing before the next anchor ends at maturity without an extra
  posting.
- A transferred posting credits the linked VISTA and does not compound into
  the DPF's next period.
- Actual/Actual splits a period crossing 31 December correctly.
- Backdated transactions recalculate the same anchored periods.
- Existing standard monthly products keep their calendar-month behavior.
- Product/account API create, read, and update round-trip the new enum values.
- Loan regression: a May 31 seed produces June 30 and then July 31.
- Loan regression: an irregular first or final installment remains explicit
  without changing the immutable seed for regular intermediate installments.
