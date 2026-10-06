# Credesal chart-of-accounts tenant bootstrap

## Status

- Service registry: intentionally not registered
- CLI block: none
- Source: approved local Fineract `default` tenant snapshot
- Fineract tenant migration: implemented in Liquibase `0310`

The Credesal chart of accounts is tenant configuration, not Arissto business
data. It is therefore a one-time, versioned Fineract bootstrap rather than an
`inspect -> plan -> apply` synchronization service.

Migration
[`0310_bootstrap_credesal_chart_of_accounts.xml`](../../../../fineract-provider/src/main/resources/db/changelog/tenant/parts/0310_bootstrap_credesal_chart_of_accounts.xml)
loads the canonical CSV under `parts/data/0310/` during normal tenant
Liquibase startup. The snapshot contains 2,523 accounts and uses `gl_code` and
`parent_gl_code` as stable identity; database IDs and hierarchy paths are
resolved inside each destination tenant.

## Why Liquibase instead of the API

- Every new tenant receives the exact reviewed snapshot automatically with its
  schema version.
- The standard GL API creates one account per request. A full clone would need
  2,523 ordered writes plus separate planning and reconciliation.
- Fineract's bulk workbook import is asynchronous and skips existing GL codes;
  it is useful for operator uploads but is a weaker source of truth for tenant
  bootstrap and drift detection.
- The migration is atomic and keeps IDs of the 19 accounts already seeded by
  migrations `0295` and `0297`, so existing product references remain valid.

The GL read API returned HTTP 500 for both collection and individual-account
requests during the 2026-08-30 audit. That defect reinforces the bootstrap
choice but is not required for the migration to work.

## Safety and convergence policy

The migration:

1. validates the snapshot row count and parent hierarchy;
2. no-ops when a tenant already matches the approved COA;
3. fills or normalizes an empty/bootstrap-only tenant while preserving existing
   account IDs;
4. refuses to change a divergent tenant after clients, loans, savings accounts,
   or journal entries exist; and
5. checks exact metadata and parent reconciliation before completing.

Do not paste or maintain a second ad-hoc SQL copy of the COA. Deliberate future
COA changes should use a new versioned migration rather than modifying the
released `0310` snapshot.

Sandbox migration `0381` adds active Arissto expense detail `8120040800`
(`ESTUDIO DE MERCADEO`) beneath existing header `812004`. The frozen `0310`
snapshot ends at sibling `8120040700`; the missing detail blocks historical
journal `001:001:00074:0000014445`. The migration validates the existing parent
and any preexisting detail, then adds only this account to `fineract_sandbox`.

## Vault account consolidation decision

Arissto currently posts vault cash to two office-specific asset accounts:
`111001030201` (Agencia Central / Santiago de María) and `111001030202`
(Usulután). Its older generic `111001020201` also appears in historical vault
journals. These are source accounting facts, not a requirement to keep separate
vault GL accounts in Fineract.

The Fineract target is **`111001030200` — `BOVEDA GENERAL`**, one enabled
detail asset account under the existing `1110010302` (`BOVEDA`) parent, next
to the two Arissto office-specific codes in the same path structure. The
journal line's native `office_id` and matching
`dimensions.office` identify the office. Historical lines from both Arissto
office-specific codes, and applicable lines from the older generic code, must
resolve to that one target account while preserving the original source code
in journal provenance. Financial activity `101` (`Cash at Main Vault`) must map
to the same account, so native vault and teller flows use the same GL identity.

Migration `0310` remains an immutable source-derived bootstrap: it seeds all
three historical vault detail accounts. The revised accounting crosswalk
`arissto-to-fineract-coa-v4-hybrid-parent-postings` maps those source codes to
`111001030200`. The targeted `fineract_sandbox` configuration added this detail
account under `1110010302`, disabled the three source-only detail accounts for
new posting, and mapped financial activity `101` to the shared account. The
vault screen filters that shared account's journal entries by office. Sandbox
tenant migration `0365` reapplies and validates this configuration after a
disposable baseline reset during normal Liquibase startup. Do not map activity
`101` to either office-specific account while both offices use the tenant.

## Teller cash account consolidation

Arissto posts teller cash to `1110010101` (Santiago de María) and
`1110010102` (Usulután). Fineract uses the existing `1110010199` (`CAJA`)
detail asset account for both offices. It is a sibling of the two source
accounts under `111001` (`CAJA`); the posted office is carried by each journal
line's native `office_id` and `dimensions.office`. The accounting crosswalk
already maps both source codes to `1110010199`, and native share accounting
uses that same canonical cash account.

The targeted `fineract_sandbox` configuration disabled the two source-only
office accounts for new posting and mapped financial activity `102` (`Cash at
Teller`) to `1110010199`. Activity `101` (`Cash at Main Vault`) remains mapped
to `111001030200`. Sandbox tenant migration `0365` restores both activity
mappings and the source-only disabled states after a reset. It only changes
`fineract_sandbox`; other tenants retain their existing configuration.

### Cash-disbursement payable

The loan/committee cash flow also requires financial activity `202`
(`Disbursements Payable`). Arissto's office-specific liability accounts
`222099940102` and `222099940103` already resolve through the historical GL
crosswalk to the single Fineract detail liability `222099910201`
(`DESEMBOLSO DE CREDITOS EN EFECTIVO`). The sandbox maps activity `202` to
that same target account; migration `0365` restores it after a reset. The
journal line's office dimensions distinguish Santiago de María and Usulután.

### Native teller–vault posting rule

| Operation | Debit | Credit |
|---|---|---|
| Allocate cash from vault to teller | `1110010199` — `CAJA` (activity `102`) | `111001030200` — `BOVEDA GENERAL` (activity `101`) |
| Settle cash from teller back to vault | `111001030200` — `BOVEDA GENERAL` (activity `101`) | `1110010199` — `CAJA` (activity `102`) |

Both offices post to these same two detail accounts. The actual posting office
belongs on each journal line as native `office_id` and the matching
`dimensions.office` value; neither the vault nor teller GL code encodes an
office. This rule covers teller–vault transfers. Opening cash balances and
bank-to-vault funding require their own reconciled source and counter-account
decisions.

## Posting-account review across financial sync services

The historical GL crosswalk now sends alternate loan portfolio source codes
`1142030101` and `1142040101` to the same target detail accounts used by their
native loan products, `1141030101` and `1141040101`. The ledger planner rejects
target headers with `TARGET_ACCOUNT_NOT_DETAIL`. The source hybrid/control
codes `2220050501` and `314002` now have reviewed detail destinations;
their historical journals remain quarantined until those details exist in the
target.

### Hybrid source parent accounts with direct postings

Arissto directly posted to two accounts that also have children. Fineract keeps
each original code as a reporting header and adds one dedicated posting detail:

| Arissto direct posting | Fineract posting detail | Existing reporting header |
|---|---|---|
| `2220050501` OTROS ACREEDORES | `222005050199` OTROS ACREEDORES - MOVIMIENTOS DIRECTOS | `2220050501` with its creditor-specific children |
| `314002` RESULTADOS DEL PRESENTE EJERCICIO | `3140020000` RESULTADOS DEL PRESENTE EJERCICIO - CIERRE TRANSITORIO | `314002` with `3140020100` UTILIDADES and `3140020200` PERDIDAS |

The accounting crosswalk maps direct source journal lines to the new details.
Source codes and offices remain in provenance and dimensions. Reports roll
detail balances up through the unchanged headers. The `314002` direct closing
postings net to zero by year and office; no parent balance is copied as a
journal. The separate two-cent `2220050501` mayor presentation difference
does not authorize an adjustment.

Sandbox tenant migration `0367` adds the two details after the immutable `0310`
COA bootstrap. It does not rewrite already imported journals. Workflows that
select ledger sync also verify both parents and idempotently create missing
details through the Fineract GL API as a frozen, target-specific prerequisite
before any service step. This applies to fresh/clean, local full re-sync, and
the production full re-sync definition. An existing target must still verify
that previously imported journal lines match their frozen account mapping;
changed mappings are not a source delta and must not silently replay or
overwrite those journals. A production workflow requires its normal versioned
release, accepted checkpoints, exact fingerprint, and reviewed immutable plan.

### Accounting report impact

The `fineract-reports/reports/report-page-inventory.md` file is a registry and
page snapshot; it does not encode account IDs or COA hierarchy. Its report
registrations and category counts do not change when these two details are
added. Balance de Comprobación uses a frozen source presentation set and
descendant traversal: its selected rows remain the same, while detail movements
roll into the existing `2220050501` and `314002` parents. Estado de Resultados
Consolidado selects income and expense accounts, so these liability and equity
details do not enter its rows. Informe Auxiliar de Mayor,
Comprobante Contable por Sucursal, and Balance de Saldos Detallado use the
historical source account code from provenance for legacy display, so those
lines continue to show the Arissto parent code. Native-target account reports
such as Balance de Saldos may expose the two new detail rows. After a fresh
clean import, compare the affected parent totals and direct journal counts in
both office scopes and the consolidated scope before declaring report parity.

Native share capital uses `1110010199` for cash/cheque and the configured bank
detail accounts for bank payments. Share yield's expense and payable GLs are
enabled details. Savings fee and penalty roles use details `6423` and `6433`;
sandbox migration `0366` corrects existing product mappings after a reset.

Two native-posting decisions remain open. Several savings principal and
interest-payable product roles still reference GL headers, each with multiple
possible children; they require a product/office detail-account rule. Loan
products still use generic fund source `14` for cash and bank channels except
the reviewed Cobro Móvil override. The native cash-disbursement and
bank-to-vault posting paths must be reconciled before assigning channel-specific
fund sources, to avoid double posting cash movements.
