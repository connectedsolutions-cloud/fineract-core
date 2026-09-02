# Native savings Actual/Actual design

## Status and decision

Implemented in the local Fineract fork on 2026-08-26. Native calculation and
API support are present, focused unit tests pass, and the dedicated
`native_actual_actual_interest_basis` implementation blocker is cleared. The
separate `controlled_native_lifecycle_proof` release gate remains until a
controlled account lifecycle proves API round-trip, posting, accrual, transfer,
reversal, fixed-deposit maturity, and accounting behavior against Arissto.

Use the actual length of the calendar year containing each accrued day:

- 365 for a day in a normal year;
- 366 for a day in a leap year; and
- split a balance span at every calendar-year boundary.

This matches the verified Arissto formula. For example, its five-day 2024
catch-up on 6,280.00 at 10% reconstructs as
`6,280 × 10% × 5 / 366 = 8.58`. Source evidence remains in
[`creditos-y-depositos.md`](../../../../../../credesal-db-space/docs/learnings/creditos-y-depositos.md).

The persisted/API value for this new savings option should be `1`, matching
Fineract's existing common `DaysInYearType.ACTUAL` convention. The savings
enum remains separate because the native savings calculation pipeline uses
`SavingsInterestCalculationDaysInYearType` throughout.

## Why a per-period denominator is insufficient

The original savings calculation resolved the account setting once and passed
its numeric value through the complete posting period:

```text
SavingsAccount / fixed deposit / accrual service
  -> PostingPeriod(daysInYear)
    -> CompoundingPeriod(daysInYear)
      -> EndOfDayBalance(daysInYear)
```

That is correct for fixed 360 and fixed 365. It is not correct for an interval
that crosses 31 December. A four-day balance spanning 30 December 2023 through
2 January 2024 has the year fraction:

```text
2 / 365 + 2 / 366
```

It must not be calculated as `4 / 365` or `4 / 366`. Splitting posting periods
or creating artificial year-end interest transactions would introduce new
rounding and capitalization boundaries, so the calculation should split only
its internal day-count factors.

## Required native change

1. Add `ACTUAL(1, "savingsInterestCalculationDaysInYearType.actual")` to
   `SavingsInterestCalculationDaysInYearType`, its API enumeration, dropdown,
   validators, and supported bulk-import values.
2. Pass the day-count type, not a raw `long`, through `PostingPeriod`,
   `PostingPeriod.createFromDTO`, and every `CompoundingPeriod` implementation.
3. Add one pure savings day-count component that calculates a year fraction
   for a start date and an inclusive number of balance days. For `ACTUAL`, it
   segments the interval by calendar year and sums `segmentDays / 365|366`.
4. Use that component in `EndOfDayBalance.calculateInterestOnBalance` for
   daily-balance simple accrual, including overdraft interest.
5. For daily compounding, multiply the factors for each calendar-year segment:
   `product((1 + annualRate / yearLength)^segmentDays)`. Do not select one
   denominator for the complete balance span.
6. For average-daily-balance products, preserve the existing threshold test,
   but calculate interest from the sum of each balance-days amount weighted by
   its calendar-year denominator. A single average balance multiplied by one
   denominator is not Actual/Actual across a year boundary.
7. Keep dedicated fixed-360 and fixed-365 branches so their unrounded and
   rounded results remain byte-for-byte compatible with current behavior.

The calculation component should be independent of migration code. Future
native savings activity must use the same rule after Arissto history has been
migrated.

## Persistence and schema

No new database column is required. Both
`m_savings_product.interest_calculation_days_in_year_type_enum` and
`m_savings_account.interest_calculation_days_in_year_type_enum` are non-null
`SMALLINT` columns without a database check constraint. Value `1` therefore
fits the existing schema and is copied from product to account through the
normal native lifecycle.

This is still a persisted enum contract: once released, value `1` must always
mean calendar-day Actual/Actual for savings. Existing rows with 360 or 365 are
not rewritten.

The migration contract encodes the complete linkage in
`config/savings_deposits.json`: API parameter
`interestCalculationDaysInYearType`, enum value `1`, product column
`m_savings_product.interest_calculation_days_in_year_type_enum`, and account
column `m_savings_account.interest_calculation_days_in_year_type_enum`.
Product creation sets the API parameter; native account creation must inherit
it, and inspection/reconciliation must verify that both persisted values
remain `1`.

## Paths that must agree

The same implementation must cover all native entry points:

- ordinary savings calculation in `SavingsAccount`;
- fixed-deposit maturity and premature-closure calculation;
- recurring-deposit calculation;
- `SavingsAccountInterestPostingServiceImpl`, including its DTO posting path;
- `SavingsAccrualWritePlatformServiceImpl`; and
- positive-balance and overdraft calculations.

The accrual service previously wired its enum fields incorrectly: it constructed
the posting-period type from `getInterestCalculationType()` and the compounding
type from `getInterestPostingPeriodType()`. The implementation now resolves
both values from their matching account fields, with a focused regression test.

## Acceptance tests

The implementation is not complete until the following cases pass:

1. API/product/account create, read, and update round-trip value `1` as
   `Actual`.
2. Existing fixed-360 and fixed-365 golden calculations are unchanged.
3. Normal-year daily balance uses 365.
4. Leap-year daily balance uses 366, including the verified Arissto
   6,280.00/10%/five-day case.
5. One unchanged balance crossing 31 December splits its year fraction.
6. A transaction on each side of 31 December splits every resulting balance
   interval correctly.
7. Monthly, quarterly, annual, and daily compounding cross a year boundary
   without creating an artificial posting event.
8. Average-daily-balance and overdraft calculations use the same day-count
   convention.
9. Fixed and recurring deposits produce correct projected maturity interest
   when the term crosses a normal/leap-year boundary.
10. Direct account calculation, read-platform interest posting, and the
    accrual job return the same unrounded amount for the same account history.
11. Posting, reversal, recalculation after a backdated transaction, cutoff
    accrual, and journal amounts remain internally consistent.
12. A controlled Arissto account replay reconciles calculated, posted, accrued,
    transferred, and rounded amounts before savings products are created.

## Delivery sequence

1. Add focused unit tests for the day-count component and preserve fixed-basis
   golden outputs.
2. Add enum/API/dropdown/import support.
3. Replace raw-denominator propagation with the typed day-count contract.
4. Correct accrual-service enum wiring and add path-equivalence tests.
5. Add savings/fixed-deposit integration cases, especially calendar-year
   boundaries and backdated recalculation.
6. Clear the dedicated `native_actual_actual_interest_basis` implementation
   blocker after focused native verification, while retaining the separate
   `controlled_native_lifecycle_proof` release gate for the account replay.

## Implementation result

Completed:

- savings enum/API value `1`, code
  `savingsInterestCalculationDaysInYearType.actual`, dropdown, validation, and
  bulk-import support;
- deposit-product validation accepts value `1` alongside fixed `360` and `365`,
  closing the fixed/recurring-deposit creation path as well as ordinary
  savings;
- typed day-count propagation through posting and every compounding period;
- calendar-year segmentation for simple, average-daily-balance, daily
  compounding, positive-balance, and overdraft calculations;
- ordinary savings, fixed-deposit, recurring-deposit, DTO posting, and accrual
  entry paths;
- correction of the accrual service's posting/compounding field wiring; and
- focused tests for enum/API exposure, normal/leap years, a year boundary,
  the verified Arissto example, fixed-365 compatibility, average daily
  balance, daily compounding, every native compounding-period path, the real
  posting-period calculation path, and accrual configuration resolution.

Verification completed with 9 focused core calculation tests, 3 provider
configuration tests, compilation of core/savings/provider modules, formatter
checks scoped to every changed Java file, and all 128 sync-engine unit tests.

The `native_actual_actual_interest_basis` blocker is cleared. Still required
before clearing `controlled_native_lifecycle_proof`:

- **Completed 2026-08-27 for VISTA:** controlled API product/account readback
  with value `1` and a lifecycle replay crossing the 2025/2026 boundary. Exact
  source type/date/amount/running balance and native journals reconciled for 25
  events.
- Still required: fixed-deposit lifecycle across a calendar-year boundary and
  exact cutoff-accrual, linked-transfer, maturity, cancellation, reversal, and
  joint-account reconciliation.
