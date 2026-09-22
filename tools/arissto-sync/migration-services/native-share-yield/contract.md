# Native share-yield contract

## Source authority

`FNC_PROVISIONES` rows with `ID_TIPO_PRODUCTO=4`, joined to current preferred
certificates (`AFI_CERTIFICADO.ID_TIPO_ACCION=2`), are the authoritative daily
events. `AFI_CERTIFICADO_HISTORICO_DIARIO` is an independent state check, not a
second transaction source.

The accepted formula is:

```text
INT_PROV = round_8(SALDO_CUENTA × TASA_INTERES / (100 × days_in_year))
INT_PROV_CNT = round_2(INT_PROV)
```

No inferred payment, capitalization, redemption, or reversal is created.

## Native target ownership

- Product configuration: `m_share_product_yield_config`.
- Financial event: `m_share_account_transactions`, type `YIELD_ACCRUAL`.
- Exact subledger: `m_share_account_yield_accrual`.
- Future settlement audit: `m_share_account_yield_settlement`.
- Expense mapping: share mapping type `YIELD_EXPENSE` → `7110040100`.
- Payable mapping: share mapping type `YIELD_PAYABLE` → target liability
  `222099910101`. The reviewed accounting crosswalk maps Arissto source account
  `222099940101` to this target GL code.

Multiple source certificates may belong to one native share account. Historical
imports therefore allow multiple certificate events for the same account and
date, while the COB job creates at most one new account-level event per date.

## Settlement

Settlement is explicit and never scheduled automatically. The command
`settleYield` validates the unpaid balance and credits the share account's
linked savings account using Fineract's native dividend-payout transaction.
The configured payable must equal financial activity `PAYABLE_DIVIDENDS` so
the settlement journal debits the same liability that daily accrual credits.

## Fail-closed rules

- unknown or duplicate source reference;
- formula or rounding mismatch;
- missing certificate/native account mapping;
- inactive or drifted preferred product configuration;
- wrong GL classification or disabled account;
- source hash change after planning; or
- target financial values that differ from the frozen source event.
