# Fineract native accounting table map

## Outcome

The migrated ledger must make `acc_gl_journal_entry` plus `acc_gl_account` the
authoritative native Fineract basis for trial balance, balance sheet, income
statement, general ledger, and agency/consolidated reporting. Derived summary
tables and report definitions are consumers or caches; they are not alternate
sources of accounting truth and are not migration write targets.

## Authoritative posting spine

| Fineract table | Role | Migration rule |
|---|---|---|
| `acc_gl_account` | Hierarchical chart of accounts | Resolve every Arissto posting account to one enabled Fineract detail account. Migration `0310` preserves code, name, parent/hierarchy, classification, usage, and levels; the reviewed crosswalk owns non-identical mappings. |
| `acc_gl_journal_entry` | One debit or credit line; rows sharing `transaction_id` form one journal | The historical writer creates all lines atomically. This is the only native financial table that receives imported Arissto journal amounts. |
| `m_office` | Required native office on each journal row | Resolve each line from its posted destination branch: `001 -> 1`, `002 -> 2`. One transaction may contain both offices. |
| `m_currency` | Currency master referenced by `currency_code` | Version 1 is USD-only. Preflight requires enabled target USD with `decimal_places=2` and fails closed if source company/base-currency evidence or target configuration differs. |
| `credesal_gl_account_presentation` | Versioned source reporting metadata keyed to `acc_gl_account` | Create through Liquibase and seed from a reviewed snapshot. Preserve source code/name, parent, classifier, order, `TIPO_SALDO`, `BC`, and `BG`. This table drives presentation only and never creates or changes journal amounts. |
| `credesal_gl_correction` | Immutable approval and linkage for native cross-office corrections | Stores correction ID, approval/evidence hash, economic window, actual posting date, wrong/correct offices, linked imported transactions, and the native correction transaction ID. It never replaces imported provenance. |
| `credesal_arissto_gl_journal` / `credesal_arissto_gl_journal_line` | Complete source keys, lossless legacy fields, hashes, mappings, retry evidence, and annual-report classification | Tenant migration `0336` creates the versioned schema. The header stores source journal type, liquidation flag, opening flag, header concept, and header description. Each line stores its concept and auxiliary concept. Every legacy text field remains independent and has its own hash. The target `transaction_id` plus source type is indexed for report filtering. Reversal pairing is not required. |
| `acc_accounting_cutoff_configuration` | Tenant-wide accounting ownership boundary | Must match the frozen plan cutoff; historical import is allowed only while ACTIVE and strictly before the cutoff. |

## `acc_gl_journal_entry` field contract

| Target column | Source or value | Rule |
|---|---|---|
| `transaction_id` | Generated target group ID | One value for the complete source journal, including journals whose lines carry different agency tags. Durable provenance, not this generated value, is the idempotency authority. |
| `account_id` | `CNT_DETALLE_PARTIDAS.ID_CUENTA` through the frozen COA crosswalk | Must resolve to exactly one enabled detail account with manual/historical import allowed. |
| `office_id` | `CNT_DETALLE_PARTIDAS.ID_SUCURSAL_DESTINO` through the frozen office crosswalk | Set each line independently: `001 -> 1`, `002 -> 2`. Do not use the header branch or one fixed import office. Validate user access and the exact latest closure for every distinct office before the atomic write. |
| `currency_code` | Reviewed company/tenant currency | `USD` for the first version; never infer currency from the amount or account. |
| `entry_date` | `CAST(CNT_PARTIDAS.FECHA_PARTIDA AS date)` | Authoritative accounting/effective date. It must be before the cutoff and after any applicable target closure unless the dedicated import policy explicitly handles historical closures. |
| `type_enum` | `DEBE > 0` -> `2` (debit); `HABER > 0` -> `1` (credit) | Source rows with both sides or neither side quarantine. Current audit found neither shape. |
| `amount` | Non-zero source `NUMERIC(18,2)` `DEBE` or `HABER` | Preserve a two-decimal canonical value exactly in Fineract `DECIMAL(19,6)`, yielding four trailing zeroes. Binary float, sub-cent values, rounding, conversion, plugs, and recomputation are forbidden. Pre-quarantine target-range overflow. |
| `ref_num` | `RTRIM(CNT_PARTIDAS.NUMERO_PARTIDA)` | Copy exactly on every line. It is searchable business evidence, not unique identity. |
| `manual_entry` | `true` | Imported journals use the historical manual-journal representation, even when the Arissto source type was automatic. Source type is provenance, not this boolean. |
| `description` | Deterministic display projection only | It is not the preservation store. Choose the first nonblank value from line concept, header description, and header concept; normalize the display form and cap it at 500 characters. Preserve all four unmodified legacy fields in separate provenance columns, including the auxiliary line concept, and never use free text as identity. |
| `dimensions` | Deterministic per-line JSON dimensions | For source company `001`, translate destination `001` to JSON string `office: "1"` and `002` to `office: "2"`. Values come from the uniquely matched `m_office.external_id`; names and numeric primary keys are not tag authorities. Unknown or drifted mappings quarantine without fallback. Also preserve non-core metadata such as source company, header branch, period, journal type, module, close IDs, and known anomaly flags. Never store account, date, side, or amount only inside JSON. |
| `reversed` / `reversal_id` | Native defaults: `false` / `NULL` | Never invoke native reversal semantics during historical import. Every eligible source journal, including an opposite posting, remains an ordinary independent journal for report reconstruction. |
| product/entity/payment FKs | `NULL` for historical direct GL import | Historical GL must not pretend to be native product-generated accounting. Product provenance belongs in the dedicated mapping and optional dimensions. |
| `submitted_on_date` | Fineract business date at import | Audit/entry timestamp, not the accounting date. Reports and reconciliation must use `entry_date`. |
| running-balance columns | Native Fineract calculation | Do not import Arissto running balances into journal rows. Recalculate from the imported journal after the atomic load. |
| `transaction_date` | `NULL` | The schema marks this column unfinished/not maintained. It must not drive migration reconciliation or reports. |

## Source-to-target journal identity

The source header identity remains:

```text
(ID_EMPRESA, ID_SUCURSAL, ID_PERIODO, ID_PARTIDA)
```

The source line identity adds `ID_DETALLE_PARTIDA`. One header maps to one
target `transaction_id`, while every source line maps to exactly one
`acc_gl_journal_entry.id`. A target journal is balanced across the complete
transaction, not necessarily inside each `dimensions.office` tag. This is
required because inter-agency entries can leave each individual agency
dimension unbalanced while the organization is balanced.

## Office anomalies and transferred loans

The 2026-09-05 source audit found 1,697 populated journals with more than one
`ID_SUCURSAL_DESTINO`, 1,777 journals with at least one destination different
from the header, and 8,647 such lines. The business also confirmed a known
Arissto defect: some accruals for transferred loans were posted to the wrong
office.

Historical fidelity wins during import. Translate the actually posted
destination branch into both per-line native `office_id` and the matching
`dimensions.office` tag, preserve the header and current operational office
only as provenance, and flag known transferred-loan accrual mismatches. Do not
rewrite history to the loan's current office.

Policy `explicit-cross-office-reclassification-v1` requires an immutable
accounting-approved manifest before any correction. Loan `838` proves a
mismatch but cannot be physically allocated to exact GL lines, so it is not an
automatic correction. A dedicated native command posts the correction on or
after cutoff: it removes each approved account/amount from the wrong office and
posts the same side to the correct one. The atomic transaction and linked
`credesal_gl_correction` provenance must leave every consolidated GL account at
net change `0.00`. Imported history and product subledgers remain untouched.

## Native supporting and derived tables

| Table/family | Native purpose | Historical-import treatment |
|---|---|---|
| `acc_gl_closure` | Prevents posting/reversal on or before an office closing date | Preflight input and policy gate; never migrated from `CIERRE_DIARIO` one-for-one. |
| `acc_product_mapping` | Product/payment/charge roles used by native accounting processors | Configured by product services; does not receive historical journal lines. |
| `acc_gl_financial_activity_account` | Organization-wide financial-activity account roles | Native configuration only. |
| `acc_accounting_rule`, `acc_rule_tags` | Reusable manual accounting rules | Not needed to represent imported journals; account lines are explicit. |
| `m_trial_balance` | Job-maintained summary/cache | Rebuild after import if retained. Do not insert source `CNT_MAYOR` rows here. Its current job depends on unfinished `acc_gl_journal_entry.transaction_date`, so it is not the migration acceptance source until separately validated. |
| `acc_gl_journal_entry_annual_summary` | Year-end/product/asset-owner reporting optimization | Derived optimization, not a replacement for annual liquidation journals and not an import target. |
| provisioning tables | Loan-loss provisioning configuration/history | Native post-cutoff producer. Arissto journal effects are imported only through the GL journal; source provisioning operational state follows its own service contract. |
| `stretchy_report` accounting definitions | SQL report projections | Validate after import, but do not treat definitions or results as ledger facts. |

## Report reconstruction rules

All acceptance reports must be reproducible directly from journal entries and
the account hierarchy:

- Trial balance: opening balance before the interval, interval debits, interval
  credits, and closing balance by leaf account and `dimensions.office`, then rolled up via
  `acc_gl_account.parent_id`/`hierarchy`.
- Balance sheet: cumulative closing balances through the report date for asset,
  liability, and equity classifications, with account nature/contra-account
  presentation supplied by the reviewed COA contract.
- Income statement: net activity for income and expense classifications over
  the selected interval, excluding only imported transaction groups whose
  immutable provenance identifies Arissto source journal type `003`. Annual
  liquidation remains real GL and is not deleted or moved to another date.
- General ledger: ordered journal lines by `entry_date`, `transaction_id`, and
  stable line provenance, with `ref_num`, account, agency tag, side, amount, and
  description.
- Consolidated reports: sum all agency-dimension tags and eliminate nothing
  unless an explicit consolidation rule exists. Agency reports may be individually
  unbalanced because Arissto contains cross-office postings.

Existing Fineract stretchy reports aggregate `acc_gl_journal_entry` by
`entry_date`, `type_enum`, `account_id`, and native `office_id`. They must be
adapted to filter and group by the canonical `dimensions.office` tag before
they are accepted as Credesal agency reports. The migration reconciler must
calculate the same primitives independently.

The annual filter is also provenance-driven. Balance sheet, general ledger, and
post-closing trial balance include type-`003` transaction groups. Income
statement and pre-closing trial balance exclude them through the provenance
header's target transaction ID and `source_journal_type`; they must not use a
December 31 condition, reference-number pattern, description match, or
`manual_entry`. `acc_gl_closure` is not an annual-close producer, and
`acc_gl_journal_entry_annual_summary` is not populated from source journals.

### Report-presentation boundary

Migration `0310` does not preserve Arissto's `TIPO_SALDO`, `BC`, or `BG`.
Policy `arissto-coa-presentation-v1` therefore adds a Credesal-owned,
Liquibase-seeded metadata row keyed to each target account. `D` presents debit
minus credit and `A` credit minus debit; negative contra balances remain
negative. `BC` selects the 101 trial-balance rollups, `BG` plus classifiers
001/002/003 selects the 64 balance-sheet rollups, and `BC=1/BG=0` plus
classifiers 004/005 selects the 26 income-statement rollups. Resolve them from
posting descendants through the parent graph; never post to report rollups.

The 11 `BG` memorandum rows display separately from the balance-sheet equation.
Current result is income minus expense. Income statement and pre-closing trial
balance exclude imported type-`003` groups by immutable provenance; balance
sheet and post-closing reports include them. Agency scope comes from each
line's `dimensions.office` and may be unbalanced; consolidated scope must tie.

Do not copy `CNT_MAYOR` into target amounts. The populated `CNT_REPORTES*`
templates are also excluded: `00009` fails the verified current trial balance,
`00010` has 28 asset mappings plus one unresolved mapping despite liability and
capital labels, and all 19 `00014` mappings resolve to balance accounts. Retain
only a hashed audit export of those definitions. Canonical labels and subtotals
come from the frozen account names, classifiers, and explicit report formulas.

## Gaps before an executable sync-engine service

1. Build G8 direct-journal identity, line, amount, office, dimension, and
   cutoff reconciliation against provenance and native GL rows.
2. Build direct-journal trial-balance, balance-sheet, income-statement, and
   general-ledger reconciliation queries for a closed month, the day before
   cutoff, and the first native cutoff-date transaction.
3. Implement and reconcile the approved `arissto-coa-presentation-v1` metadata
   snapshot and report formulas that migration `0310` does not retain.
