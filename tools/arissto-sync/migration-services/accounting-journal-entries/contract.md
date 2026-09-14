# Accounting journal entries migration contract

## Contract state

This is the frozen contract for the sync engine's `accounting` category. The
G3 inspector, explicit-key G4 plan format, G5 provenance schema, and G6 atomic
target API exist. Explicit-key sync-engine apply, failed-only retry, and status
are complete in G7. Reconciliation remains G8 work, so the service remains
`planned` and `executable: false`.

The approved ownership model is an accounting cutover, not journal-by-journal
ownership classification:

- the sync engine creates every pre-cutoff business record selected for
  retention, including clients, loans, schedules, loan transactions, savings,
  deposits, shares, balances, statuses, relationships and provenance;
- the accounting service imports the final posted Arissto GL journals before
  the cutoff and is the only owner of their historical GL effect;
- native Fineract accounting generated while other migration services create
  pre-cutoff operational history must be suppressed;
- native Fineract workflows own new operational records and accounting from
  the cutoff date forward;
- each historical journal is imported intact; mixed-owner decomposition and
  native-owner comparison are not migration prerequisites;
- every import cycle carries one explicit immutable cutoff date and timezone;
  and
- the engine never deletes Fineract accounting rows or writes to Arissto.

The required Fineract cutoff guard is specified in
[`FINERACT_PRE_CUTOFF_NATIVE_ACCOUNTING_GUARD.md`](../../../../../docs/FINERACT_PRE_CUTOFF_NATIVE_ACCOUNTING_GUARD.md).
Monthly journal numbering remains specified in
[`FINERACT_MONTHLY_GL_JOURNAL_NUMBERING_REQUIREMENTS.md`](../../../../../docs/FINERACT_MONTHLY_GL_JOURNAL_NUMBERING_REQUIREMENTS.md).

## Cutover ownership rule

`cutoff_date` is mandatory in every inspect, plan, apply and reconcile cycle.
It is interpreted as an accounting date in `America/El_Salvador`, frozen into
the plan and contract hash, and must match the tenant-side Fineract cutoff
configuration. Changing it invalidates every unapplied accounting plan.

| Accounting date | Business-data owner | GL owner |
|---|---|---|
| Before `cutoff_date` | Sync engine | Arissto journals imported by the accounting service |
| On or after `cutoff_date` | Native Fineract workflows | Native Fineract accounting |

The cutoff date belongs to Fineract. If the approved cutoff is `2026-10-01`,
the accounting service imports journals through `2026-09-30`, while Fineract
owns transactions dated `2026-10-01` and later.

The cutoff limits accounting ownership, not historical data retention. Product
services may create complete pre-cutoff operational history when required, but
they must execute under an authenticated migration context that suppresses
native GL. An ordinary API command or scheduled job must never silently create
an unaccounted pre-cutoff transaction: it is rejected instead.

Post-cutoff Arissto rows are outside historical accounting import scope. A
catch-up or delayed migration that reaches the boundary must stop; it cannot
move the cutoff implicitly.

## Historical accounting scope

The accounting service imports every reviewed, posted, balanced Arissto journal
whose effective accounting date is strictly before the cutoff. `CNT_PERIODO.ANIO`
and `MES` define the intended accounting month: an in-period `FECHA_PARTIDA` is
retained, while an out-of-period value is normalized to that period's final
calendar day. Eligibility is mechanical:

- the full source header and all detail lines are present;
- the source status is `ESTADO_PARTIDA='3'`;
- total debits equal total credits at the approved precision;
- every non-zero source posting account resolves to exactly one Fineract leaf
  GL account;
- the effective accounting date is before the immutable cutoff and accepted by
  target closure rules;
- the journal has not already been imported under its complete source key; and
- annual-closing treatment follows the approved preservation policy.

The accounting service does not reconstruct Arissto product logic, infer which
product generated a journal, or compare the journal with hypothetical Fineract
product accounting. `CODIGO_SISTEMA`, staging, bank, cash, vault and product
links remain useful source provenance and exception evidence, but they do not
decide whether an otherwise eligible pre-cutoff journal is imported.

Unbalanced, empty, unsupported-status, unresolved-account or structurally
invalid journals are quarantined. Quarantine is an integrity outcome, not an
ownership category.

Status selection is fail-closed. Status `1` represents a journal that has not
yet reached the materialized daily ledger and quarantines as
`SOURCE_JOURNAL_NOT_MAYORIZED`. The two observed status-`2` journals are
balanced but excluded from every affected `CNT_MAYOR_DIARIO` amount, so status
`2` quarantines as `SOURCE_JOURNAL_EXCLUDED_FROM_LEDGER`. Any new status uses
`SOURCE_JOURNAL_STATUS_UNSUPPORTED` until independently reviewed. Empty and
unbalanced status-`3` headers remain quarantined rather than becoming monetary
postings.

## Historical bank, vault and cash boundary

The imported GL is the durable historical representation of bank, vault and
cash activity. Their Arissto operational records may be read for source
evidence but are not independently recreated in Fineract teller, cashier,
vault or bank-reconciliation tables unless a separate migration contract is
approved.

From the cutoff date forward, Credesal may use native Fineract teller, cashier,
vault and future bank-reconciliation workflows. Those workflows must obey the
same accounting cutoff guard.

## Source identity and scope

The authoritative journal identity is:

```text
(CNT_PARTIDAS.ID_EMPRESA,
 CNT_PARTIDAS.ID_SUCURSAL,
 CNT_PARTIDAS.ID_PERIODO,
 CNT_PARTIDAS.ID_PARTIDA)
```

Each line extends that identity with
`CNT_DETALLE_PARTIDAS.ID_DETALLE_PARTIDA`. Neither `ID_PARTIDA` nor
`NUMERO_PARTIDA` may be used alone for idempotency.

| Source | Role |
|---|---|
| `CNT_PARTIDAS` | Journal header, number, date, type, status, system and provenance |
| `CNT_DETALLE_PARTIDAS` | Posting accounts, debit/credit amounts and line provenance |
| `CNT_PERIODO` | Accounting period and close context |
| `CNT_CATALOGO_CUENTAS` | Source account code used for reviewed Fineract COA resolution |
| `CNT_TIPO_PARTIDA` | Journal-type labels, including annual liquidation |
| `CIERRE_DIARIO` | Operating-date and close evidence; not a target sequence generator |

`CNT_MAYOR`, `CNT_MAYOR_DIARIO`, and `CNT_MAYOR_ANUAL` are reconciliation
evidence. They are not independent transaction sources and are never replayed
as additional journals.

Some Arissto accounts have a hybrid shape: they have real children and also
receive direct journal lines. The reconciler discovers that shape from actual
parent links rather than trusting `ULTIMO_NIVEL`. A raw direct-journal versus
`CNT_MAYOR` mismatch is accepted as a materialized parent rollup only when all
of these conditions hold at the account/agency grain:

- every direct line belongs to a type-`003`, `LIQ_ING_EGR='1'` annual
  liquidation journal;
- the cumulative direct signed movement is exactly zero;
- every immediate child has a row in the control-period mayor; and
- the parent `SALDO_FINAL` equals the exact sum of those child balances.

The accepted parent variance is reported separately and never becomes an
opening, residual, or balancing journal. Any hybrid account that fails one of
the conditions remains a reconciliation blocker with
`SOURCE_HYBRID_ACCOUNT_ROLLUP_UNSAFE`. Account `314002` is the verified control:
its two agency variances total `37,880.08` and are fully reproduced by children
`3140020100` and `3140020200`.

## Historical origin and opening balance

For company `001`, historical accounting begins with the first populated,
balanced status-`3` journal on 2022-11-18 in period `00028`. Earlier configured
periods contain no populated posted journals. Every one of the 29
`CNT_MAYOR` rows in `00028` has `SALDO_INICIAL=0.00`, and its closing balance
carries exactly into period `00029`. Cumulative eligible journal activity
reproduces every compared account/branch closing balance through the first
annual liquidation.

The importer therefore imports every otherwise eligible journal dated on or
after 2022-11-18 and strictly before the frozen cutoff. It never creates a
synthetic opening journal, residual journal, or transaction from a configured
empty period or `CNT_MAYOR*` carry-forward state. If future source evidence
contradicts the demonstrated zero origin, planning must fail closed for a new
contract decision; it must not infer an adjustment.

## Annual liquidation and report views

Arissto annual liquidation is ordinary posted GL with a specialized reporting
view. The current source has nine eligible type-`003` journals: three balanced
stages on December 31 of each year from 2023 through 2025. They close income and
expense accounts through `RESULTADOS DEL PRESENTE EJERCICIO` and transfer the
net result to a balance account. No source header is flagged as an opening
journal, no annual vector is duplicated by another posted journal, and January
opening values are `CNT_MAYOR` carry-forward state rather than transactions.

The importer therefore:

- imports every otherwise eligible `ID_TIPO_PARTIDA='003'` and
  `LIQ_ING_EGR='1'` journal intact on its effective accounting date;
- never generates a second Fineract annual-closing transaction;
- never imports `CNT_MAYOR*` state or creates an opening/residual journal from
  it; and
- persists `source_journal_type`, `source_liquidation_flag`, and
  `source_opening_flag` in immutable header provenance.

Classification is fail-closed. Type `003`, liquidation flag `1`, a December 31
source date, and opening flag `0` must agree. A mismatch quarantines as
`SOURCE_ANNUAL_LIQUIDATION_SHAPE_UNSUPPORTED`; any nonzero opening flag
quarantines as `SOURCE_OPENING_JOURNAL_REQUIRES_REVIEW` until separately
approved. The policy is structural and does not require exactly three journals
per future year.

Fineract does not supply an equivalent general year-end process.
`acc_gl_closure` only rejects posting or reversal on and before its office/date;
it creates no journals. `acc_gl_journal_entry_annual_summary` supports a narrow
loan-product/asset-owner report and is neither a complete GL close nor a
migration target.

Because Fineract's standard income-statement SQL sums all income/expense lines
between `startDate` and `endDate`, including a December 31 closing would reduce
the annual result accounts to zero. Report behavior is therefore explicit:

| View | Annual type-`003` transaction groups |
|---|---|
| General ledger | Include |
| Balance sheet through the report date | Include |
| Post-closing trial balance | Include |
| Income statement | Exclude by immutable source header provenance |
| Pre-closing trial balance | Exclude by immutable source header provenance |

The exclusion joins the journal's `transaction_id` to the provenance header
and selects `source_journal_type='003'`. It must never infer closure from
December 31, `ref_num`, description text, or `manual_entry`; all imported
journals are manual in the native representation and ordinary transactions also
occur on December 31. This filter changes presentation only and never removes
the journal from `acc_gl_journal_entry` or reconciliation.

## Journal number and target mapping

`CNT_PARTIDAS.NUMERO_PARTIDA` generally follows the verified `YYYYMM####`
monthly pattern, but isolated month-prefix errors exist. The engine preserves
`RTRIM(NUMERO_PARTIDA)` exactly, records a non-blocking mismatch observation,
and never regenerates it or derives the effective date from it.

| Arissto source | Fineract target | Rule |
|---|---|---|
| Complete journal key | Durable provenance plus one `transaction_id` | Idempotency authority |
| `NUMERO_PARTIDA` | `acc_gl_journal_entry.ref_num` | Exact trimmed value on every line |
| `CNT_PERIODO.ANIO/MES` plus `FECHA_PARTIDA` | Transaction/entry date | Preserve `FECHA_PARTIDA` when it lies in the period; otherwise use the period's final calendar day. Preserve the original source date separately in provenance. |
| Detail `ID_CUENTA` | `acc_gl_journal_entry.account_id` | Reviewed source-code-to-target-account resolution |
| Detail `ID_SUCURSAL_DESTINO` | Per-line `acc_gl_journal_entry.office_id` and `dimensions.office` | Resolve both native office ID and stable dimension tag from the frozen crosswalk; never replace the posted destination with one journal-wide office |
| Detail `DEBE`/`HABER` | Entry type and amount | Preserve one non-zero side per normalized line |
| Header/detail concepts | Dedicated header/line provenance columns plus `description` display projection | Preserve all four fields independently; never concatenate them into the native 500-character column |

### Agency dimension crosswalk

For source company `001`, every detail line uses this versioned crosswalk:

| `CNT_DETALLE_PARTIDAS.ID_SUCURSAL_DESTINO` | Source catalog label | Required target office | `dimensions.office` |
|---|---|---|---|
| `001` | `AGENCIA CENTRAL` | `m_office.id=1`, `external_id='1'` | JSON string `"1"` |
| `002` | `USULUTAN` | `m_office.id=2`, `external_id='2'` | JSON string `"2"` |

The dimension value authority is the unique, contract-frozen target
`m_office.external_id`, not its name and not the generated numeric primary key.
Preflight must resolve each configured ID/external-ID pair uniquely. Every plan
freezes mapping version `fineract-office-external-id-v1`, the mapping hash, and
the resolved string on every line. Target drift invalidates an unapplied plan.

A null, blank, unknown, foreign-company, duplicate, or target-unresolved value
quarantines as `SOURCE_DESTINATION_BRANCH_UNMAPPED`. The importer never falls
back to the header branch, a fixed journal-wide office, or an office name.
The source audit found only `001` and `002` across current detail rows and zero
catalog-unresolved values. Destination-`002` accounting predates the target
office's formal opening. Neither the historical dimension tag nor journal
persistence is constrained by `m_office.opening_date`.

Native accounting on and after cutoff must use the same canonical namespace:
its journal `dimensions.office` is derived from the posting office's
`m_office.external_id`. This makes one agency filter valid across imported and
native periods.

Each imported line also uses the crosswalk's `target_office_id` as its native
`acc_gl_journal_entry.office_id`: destination `001` becomes office ID 1 and
destination `002` becomes office ID 2. All lines retain one shared
`transaction_id`, and balance is enforced across the complete source journal,
not independently per office. Inter-office journals may therefore be
intentionally unbalanced within each office while balancing organization-wide.
There is no database constraint requiring all rows in one transaction group to
share an office.

Before the atomic write, the dedicated API must load every distinct mapped
office, verify that the authenticated historical-import user has access to all
of them, and evaluate the journal date against each office's exact latest
`acc_gl_closure`. The journal is rejected before any row is written if its date
is on or before any involved office's closure. Closure bypass is forbidden.
Fineract's existing manual-journal endpoint accepts only one top-level office
and therefore cannot implement this contract; the dedicated historical API
must accept and persist office ID on every line. Source attribution can predate
an office's configured opening date because Fineract journal persistence does
not apply `m_office.opening_date` as a posting constraint.

### Currency and amount precision

The first accounting-import contract is USD-only. Arissto company `001` has
`MULTIMONEDA='0'`; its `MONEDA_EMPRESA` type-`1` base currency resolves to
`MONEDA.ISO='USD'`. Other catalog currencies are type `2` and do not make the
journal currency ambiguous under the non-multicurrency company setting.

Both source posting columns, `CNT_DETALLE_PARTIDAS.DEBE` and `HABER`, are
`NUMERIC(18,2)`. Plans preserve each non-zero side as a plain decimal string
with exactly two fractional digits. The extractor, planner, hashes, API client,
and writer must never pass amounts through a binary floating-point type. No
currency conversion, rounding, allocation, plug, or recomputation is allowed.

Fineract stores journal amounts in `DECIMAL(19,6)`. This wider fractional scale
is storage only: source `10.50` persists numerically as `10.500000`, and every
imported target amount must equal its value rounded to two decimals. The target
type has only 13 integer digits versus the source type's theoretical 16. Any
amount outside the target range quarantines as `SOURCE_AMOUNT_TARGET_OVERFLOW`
before apply; any unexpected source scale quarantines as
`SOURCE_AMOUNT_SCALE_UNSUPPORTED`. The current source audit found zero such
rows and at most six integer digits on either posting side.

Preflight must verify that target USD is enabled with two decimal places. A
changed source multicurrency/base-currency configuration, non-USD journal
evidence, missing/disabled target USD, or target decimal-place mismatch
quarantines as `SOURCE_OR_TARGET_CURRENCY_UNSUPPORTED`. Every plan freezes
policy version `usd-numeric-18-2-v1` and its hash.

## Report-presentation contract

Report presentation is metadata over the journal ledger; it must never change,
supplement, or net imported entries. Version `arissto-coa-presentation-v1`
creates a Liquibase-owned `credesal_gl_account_presentation` snapshot keyed to
the target GL account. It retains the source account code and label, parent,
classifier, order, `TIPO_SALDO`, `BC`, and `BG`. The actual parent graph is
authoritative when `ULTIMO_NIVEL` disagrees with it.

Amounts are calculated directly from `acc_gl_journal_entry`:

- `TIPO_SALDO='D'` presents debits minus credits;
- `TIPO_SALDO='A'` presents credits minus debits; and
- negative results remain negative. In particular, a provision, accumulated
  depreciation, or accumulated amortization under assets is not moved to the
  creditor section or converted to an absolute value. Its negative balance is
  the contra-asset reduction.

The source flags identify presentation rows, not posting destinations. Target
journals remain on leaf/posting accounts. Each selected row recursively sums
its posting descendants through the target hierarchy, with each posting account
counted once in a report section. The canonical reports are:

| Report | Rows and formula |
|---|---|
| Trial balance | The 101 audited `BC=1` rows. Classifiers 001/004/007 form the debtor side and 002/003/005/006 the creditor side, ordered by `CNT_CLASIFICADOR_CUENTAS`. Return opening balance, debits, credits, and closing balance. The post-closing view includes all eligible journals; the named pre-closing view excludes source type `003` using immutable transaction provenance. |
| Balance sheet | The 64 `BG=1` rows in classifiers 001 assets, 002 liabilities, and 003 equity. Present `assets = liabilities + equity + current result`, where current result is classifier 005 income minus classifier 004 expense. Include annual-closing journals. The 11 `BG=1` memorandum rows in classifiers 006/007 are a separate disclosure and never enter the balance-sheet equation. |
| Income statement | The 26 `BC=1 AND BG=0` rows in classifiers 004/005, from fiscal-year start through the report date. Net result is income minus expense. Exclude imported source type-`003` transaction groups by immutable provenance so December remains a pre-closing performance view. |
| General ledger | All mapped posting accounts and every eligible journal. `BC`, `BG`, and `TIPO_SALDO` never filter ledger entries. |

Machine output retains all selected rows, including zeros. The ordinary display
may suppress a row only when every requested measure is zero and must offer an
include-zero option. Labels come from the frozen source account label plus
explicit versioned section/total labels. Subtotals come from the classifier and
selector formulas above, never from a mutable report label. Comparatives rerun
the same selector and formula independently for every requested date column.
Agency reports filter each journal line by `dimensions.office`; consolidated
reports sum all office values without elimination. A single agency may be
unbalanced because source journals can span offices, while consolidated trial
balance sides must agree exactly.

### Why `CNT_REPORTES*` is not replayed

Rows in `CNT_REPORTES` are populated for `00009`, `00010`, and `00014`, but
population is not proof of an active or internally valid template. The stored
procedures define row type 1 as data, 2 as a non-calculated label, and 3 as a
subtotal; subtotal `LISTA_GRUPOS` values multiply member rows by `SIGNO`.
Those mechanics are retained in a hashed read-only audit export only.

The current mappings fail the authority test:

- `00009` does not reproduce the supplied current trial balance and has two
  account IDs that no longer resolve;
- `00010` has one unresolved mapping and the other 28 all resolve to asset
  accounts, including rows labeled as liabilities and capital; and
- all 19 mappings of income-statement template `00014` resolve to balance
  accounts—18 assets and one liability—not result accounts.

This is internal-ID reuse/drift, not a rounding issue. The importer must not use
those IDs, `SIGNO`, labels, or group totals to select or transform journal
amounts. Any drift in the frozen COA presentation snapshot blocks report-parity
readiness as `SOURCE_REPORT_PRESENTATION_DRIFT`. Acceptance requires zero-cent
variance from direct journals, equal consolidated trial-balance sides, and a
zero balance-sheet equation.

## Transferred-loan accrual correction policy

The historical import is immutable and source-faithful even when Arissto's
office attribution is known or suspected to be wrong. It preserves every
source account, debit/credit side, amount, and `ID_SUCURSAL_DESTINO` in the
native office and dimension mappings. Candidate detection records an anomaly;
it never changes a plan and never authorizes a correction.

That distinction is required by the source evidence. Loan `838` proves an
office mismatch at the operational/account-group level, but the daily journal
aggregates multiple loans and carries no physical loan key on each GL line.
Its `327.62` mismatch-window accrual therefore cannot be assigned automatically
to exact original GL lines. The broader 166-loan candidate population is still
less conclusive. All candidates remain uncorrected unless accounting supplies
an immutable approved correction manifest.

The manifest must identify a unique correction ID, approval reference,
approver/time, actual posting date, economic-period range, wrong and correct
offices, exact imported source transaction and provenance-line IDs,
account/side/amount lines, rationale, and a supporting-evidence SHA-256.
Amounts are exact two-decimal USD
strings. Any missing approval, ambiguous allocation, changed source/target
provenance, or unbalanced request rejects the complete correction.

Corrections are native accounting, not migration. A dedicated cross-office
command with permission `CREATE_CREDESAL_GL_CORRECTION` creates one atomic
`manual_entry=true` journal and a linked `credesal_gl_correction` provenance
record. Its posting date must be on or after the active cutoff and strictly
after every involved office's latest closure. It cannot use migration origin,
backdate across the cutoff, bypass closure, or insert core GL rows directly.
The correction ID is the immutable idempotency key.

This operation reassigns office only:

| Approved original side | Correction lines |
|---|---|
| Debit in wrong office | Credit the same account and amount in the wrong office; debit the same account and amount in the correct office |
| Credit in wrong office | Debit the same account and amount in the wrong office; credit the same account and amount in the correct office |

For a two-account accrual, that normally produces four correction lines. No
account substitution, amount recomputation, currency conversion, plug, or
suspense line is allowed. The journal must balance as a whole and must produce
`0.00` consolidated net change for every GL account. Consequently consolidated
financial statements remain unchanged; only office distribution changes. The
workflow does not modify a loan/customer subledger, imported journal, or
historical provenance.

The ordinary chronological ledger displays the original and linked correction
as separate transactions, with the correction appearing only on its actual
post-cutover posting date. A distinct corrected-agency analytical view may use
the provenance economic-period range to restate attribution, but it must not
rewrite or backdate the statutory ledger.

`ref_num` is searchable business evidence, not a unique target identity. The
engine must durably map the complete source key to the returned Fineract
transaction ID and recover when a response is lost after commit.

## Provenance and write boundary

The preferred target design remains a Credesal-owned journal provenance header
and line model created atomically with the manual journal. The dedicated API
must accept native office and dimensions on every line while assigning one
shared transaction ID to the complete source journal. At minimum the
provenance model stores:

- complete source journal and line keys;
- exact source journal number and date;
- source journal type, liquidation flag, and opening flag;
- cutoff date, source hash, mapping version, plan and run;
- source account code and resolved Fineract account ID;
- source debit/credit values and target line identity;
- `source_header_concept` and `source_header_description` as independent
  unrestricted-length text columns on the provenance header;
- `source_line_concept` and `source_line_aux_concept` as independent
  unrestricted-length text columns on each provenance line;
- one SHA-256 column for each of those four values, using a serialization that
  distinguishes null, empty, and whitespace-only values;
- the display-description policy version, display hash, and truncation flag;
- `IMPORTED`, `QUARANTINED`, or `UNCHANGED` result and stable reason.

The four legacy values are preserved as decoded Unicode with no normalization,
trimming, concatenation, or truncation before provenance storage. Native
`acc_gl_journal_entry.description` is not a preservation field. It is a
deterministic display projection for each line: nonblank detail concept, then
nonblank header description, then nonblank header concept. The auxiliary line
concept is retained but is not displayed by default. The projection applies
NFC, removes unsupported controls, collapses whitespace, and is limited to 500
characters using the first 499 characters plus a Unicode ellipsis when needed.
The dedicated API must validate every projected line description against the
500-character limit before persistence, including per-line comment overrides.

Complete legacy text columns are omitted from ordinary journal responses and
from sync plan, status, error, and reconciliation output. A dedicated,
restricted provenance permission may return them for authorized historical
inspection. This access boundary does not alter or redact their stored values.

Reversal reconstruction is outside this service's reporting requirement.
Every eligible posted journal—including an opposite counter-posting—is imported
independently using its own `FECHA_PARTIDA`, accounts, sides and amounts. The
writer never calls Fineract's reversal operation and leaves core `reversed=false`
and `reversal_id=NULL`. Pairing and classification are optional audit metadata;
they are not prerequisites for planning, apply, reconciliation, or report
parity. The ordinary cutoff rule is applied independently to every journal.

The writer must use a narrowly scoped Fineract journal API extension that is
authorized specifically for historical migration. It must atomically reserve
the source key, create the complete balanced journal and persist provenance.
The ordinary manual-journal API is not a cutoff bypass, and the sync engine
must not insert directly into `acc_gl_journal_entry`.

One journal is the atomic retry boundary. A run must never commit only one side
of a journal. An unchanged source key and hash is idempotent. A reused key with
a changed hash is quarantined and never edits posted accounting silently.

## Cross-service preconditions

Accounting apply is blocked until all pre-cutoff migration services use the
same cutoff contract:

1. Pre-cutoff business data is created only under authenticated migration
   execution context.
2. Native GL generation is suppressed for that context and date range.
3. Ordinary users, integrations and scheduled jobs are rejected if they try to
   create pre-cutoff accounting after the guard is active.
4. Native jobs remain paused while historical operational data and GL are
   loaded.
5. On activation, Fineract owns the cutoff date and every later accounting
   date.
6. No service can override the cutoff with a request parameter or local config.

The sync engine must preflight the tenant cutoff value, activation state,
timezone and migration authorization before planning or applying any financial
service.

## Inspection and planning

Inspection reports, without exposing free-text PII:

- header and line counts strictly before the cutoff;
- duplicate complete keys and line keys;
- balanced, unbalanced, empty and unsupported-status populations;
- unresolved or ambiguous target-account mappings;
- journal-number null, blank, duplicate and pattern statistics;
- reversal and annual-liquidation populations;
- unsupported annual-liquidation shapes and unexpected opening-journal flags;
- counts before, on and after the cutoff;
- target closure conflicts;
- target provenance/hash drift; and
- verification that the Fineract cutoff configuration exactly matches the
  requested plan.

Initial plans require explicit source keys. A planned journal stores its source
hash, exact number/date, resolved target accounts, line totals, cutoff/config
hash and every readiness failure. Quarantined journals never become apply
items.

## Reconciliation and acceptance

For every imported journal, reconciliation verifies:

1. one complete source key resolves to exactly one Fineract transaction group;
2. every line carries the expected `ref_num`, date, currency, account, side,
   amount, and translated agency dimension tag;
3. source and target debit/credit totals agree exactly;
4. no source key or target group is duplicated; and
5. no native, non-manual journal exists with an accounting date before the
   cutoff.

The independent source-ledger control compares ordinary posting accounts
directly and evaluates hybrid parent/direct accounts with the guarded rollup
rule above. This keeps exact journal preservation separate from report
hierarchy reconstruction and prevents double-posting a materialized parent
balance.

Cutover acceptance additionally requires:

- all retained operational populations reconcile at the cutoff;
- imported historical GL agrees with the Arissto trial balance immediately
  before the cutoff;
- product subledger balances agree with their migrated operational state;
- zero native pre-cutoff journal entries;
- zero imported journals on or after the cutoff;
- a first native transaction on the cutoff date posts exactly once; and
- unchanged replays create no records.

Full test cycles restore a disposable tenant baseline. The sync engine contains
no accounting wipe command, and production exposes no reset path.

## Open decisions

1. Approve the concrete cutoff date.
2. Implement tenant-side cutoff configuration and authenticated migration
   execution context.
3. Implement the atomic journal/provenance API and final Liquibase schema.
4. Confirm how each product service creates full historical operational state
   while its native GL is suppressed.
5. Implement the approved exception workflow for legitimate post-go-live
   corrections; silent suppression is never allowed outside migration.
6. Complete Mifos display and filtering of imported `ref_num`.
