# Native savings product contracts

## Product boundary

Create one native product for each migratable Arissto line. The durable
identity is `AHO_LINEA_AHORRO|ID_EMPRESA|ID_LINEA_AHORRO` in
`credesal_savings_product_map`; Fineract product names are display values, not
idempotency keys.

| Source line | Native type | Proposed name | Short name | Numbering code | Default rate | Term |
|---|---|---|---|---|---:|---|
| `00001` | Savings | Credesal Ahorro a la Vista | `AVST` | `4V1` | 3.00% | none |
| `00003` | Fixed deposit | Credesal DPF 30 días | `D030` | `5D1` | 3.00% | 30 days |
| `00004` | Fixed deposit | Credesal DPF 60 días | `D060` | `5D2` | 4.00% | 60 days |
| `00005` | Fixed deposit | Credesal DPF 90 días | `D090` | `5D3` | 4.00% | 90 days |
| `00006` | Fixed deposit | Credesal DPF 120 días | `D120` | not approved | 4.00% | 120 days |
| `00007` | Fixed deposit | Credesal DPF 150 días | `D150` | not approved | 5.00% | 150 days |
| `00008` | Fixed deposit | Credesal DPF 180 días | `D180` | `5D6` | 6.00% | 180 days |
| `00009` | Fixed deposit | Credesal DPF 210–330 días | `D330` | `5D7` | 6.50% | 210–330 days |
| `00010` | Fixed deposit | Credesal DPF 360 días | `D360` | `5D8` | 7.25% | 360 days |
| `00011` | Fixed deposit | Credesal DPF 390–1080 días | `D390` | `5D9` | 7.50% | 390–1080 days |

`00002 PROGRAMADO` remains inspect-only because there are no source accounts.
Lines `00006` and `00007` currently have no accounts and their inferred `5D4`
and `5D5` codes are explicitly disabled by Credesal numbering validation; the
engine must not create those products until a code is approved.

## Per-account behavior

- Preserve `AHO_CUENTA_AHORRO.PORCENTAJE_INTERES` as the native account rate.
  It is negotiated state and may differ from or exceed the line default.
- Calculate on daily balance. `VISTA` has a 50.00 opening/interest threshold;
  DPF lines use 100.00.
- Arissto uses simple daily accrual until capitalization/payment; it does not
  compound the unposted provision every day. Do not configure these products
  with Fineract daily compounding.
- Configure `VISTA` with quarterly compounding and quarterly posting to the
  same account. The posted interest then becomes principal for the next
  quarter, matching the source lifecycle.
- Transfer normal DPF interest to its linked, active, same-client `VISTA`.
  Preserve account-level at-maturity exceptions rather than forcing the line's
  normal monthly-on-opening-day schedule.
- Fineract's standard monthly schedule is calendar-month based, while 116
  Arissto DPF accounts are configured monthly on their opening day. Actual/Actual
  solves the denominator but not that schedule difference. The reviewed design
  is a distinct native activation-anchored monthly posting/compounding option,
  using the month's last day when the original anchor does not exist and then
  returning to that original anchor. See
  [`opening-day-interest-schedule.md`](opening-day-interest-schedule.md).
- Do not enable product-wide ISR withholding for historical replay. Taxability
  is event-specific in Arissto. Link the native 10% ISR tax group to the VISTA
  product/account but keep `withHoldTax=false`; the explicit type-18 command
  uses that configuration only for events whose `APLICA_RENTA=1` contract has
  already passed inspection.

## Interest-basis gap

Arissto uses the actual number of days in the calendar year: 365 normally and
366 in leap years. This is verified by reconstructed daily and catch-up
interest. Fixed 365 would therefore misstate leap-year accruals.

The local Fineract fork now implements a native Actual/Actual savings basis
that selects the denominator for each accrued day, including posting periods
crossing a year boundary. A migration-only balance adjustment is not used;
future native accruals follow the same calendar-day rule.
The reviewed native design and acceptance matrix are in
[`actual-actual-design.md`](actual-actual-design.md).

The sync contract now pins the native linkage explicitly:

- product/API field: `interestCalculationDaysInYearType = 1`;
- persisted product field:
  `m_savings_product.interest_calculation_days_in_year_type_enum = 1`;
- persisted account field:
  `m_savings_account.interest_calculation_days_in_year_type_enum = 1`; and
- enum identity: `savingsInterestCalculationDaysInYearType.actual`.

Fineract's normal product-to-account lifecycle copies this setting. The
inspector reports product and account value counts, and the eventual writer
must reject a created account whose effective basis differs from its mapped
product. These mappings define the required configuration. The enum and
calculator now support value `1`; the dedicated implementation blocker is
cleared. The separate release gate remains until a controlled native
product/account lifecycle and financial reconciliation pass.

## Accounting roles

Every one of the 19 distinct line-specific source GL codes exists and is
enabled in the local target.

- `savingsControlAccountId` (`financial_account_type=2`) ← line principal GL.
- `interestOnSavingsAccountId` (`financial_account_type=3`) ← line interest
  expense GL.
- `interestPayableAccountId` (`financial_account_type=17`) ← line accrued
  interest liability GL.
- ISR tax component credit account ← line tax GL, subject to the event-level
  tax design.

The shared roles use the convention already common to both local target deposit
products: savings reference `1110040202`, transfer suspense `213005`,
fee/penalty income `6420`/`6430`, and fee/penalty receivables `1530`/`1540`.
The sync contract stores these as GL codes and resolves their target IDs at run
time; inspection rejects missing, disabled, or misclassified accounts.

## Release gate

Actual/Actual is implemented and is no longer an implementation blocker.
The native linked-VISTA ISR command and explicit historical type-3 interest
command are implemented. The dedicated VISTA proof product passed locally, but
production migration products remain uncreated until migrations 0292, 0296,
and 0299 are applied and the remaining DPF controlled lifecycle is complete.
Product creation must use native APIs; only the durable crosswalk is written
with controlled SQL.
