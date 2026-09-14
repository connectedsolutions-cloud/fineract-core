# Cutoff implementation decisions

## Accepted

- Migration `0320` owns cutoff configuration, lifecycle, and permissions.
- Historical journal header/line provenance is installed by tenant migration
  `0336`; the occupied migration number `0321` was not reused.
- The cutoff date is historical-exclusive: dates before it are historical;
  the cutoff date and later are native.
- New plans default the cutoff to their creation date in
  `America/El_Salvador`. The resolved value is frozen for apply, retry,
  reconciliation, and workflow children; `--cutoff-date` is the explicit
  override.
- Nightly testing may advance the cutoff only by creating a new sync plan
  against a newly restored disposable-tenant cycle. Existing plans and an
  `ACTIVE` tenant cutoff are immutable.
- `config/accounting.json` intentionally keeps `cutoff.date` unset so the
  plan-level explicit value or `sync_run_date` default owns resolution. The
  permanent production cutoff is approved during G12 release approval.
- Journal status eligibility is fail-closed: only populated, balanced
  `ESTADO_PARTIDA='3'` journals are import candidates. Status `1` uses
  `SOURCE_JOURNAL_NOT_MAYORIZED`, status `2` uses
  `SOURCE_JOURNAL_EXCLUDED_FROM_LEDGER`, and unexpected, empty, or unbalanced
  journals retain distinct stable quarantine reasons.
- The status-`2` decision is based on ledger effect rather than balance: both
  current status-`2` journals balance, but all 22 affected account/branch daily
  ledger groups equal status-`3` totals and exclude status `2` exactly.
- The reporting requirement is ledger reproduction, not reconstruction of
  loan/savings reversal lifecycles. Those migrations create no historical GL;
  the accounting service owns all eligible pre-cutoff journal effects.
- Every eligible source journal is imported independently, including ordinary
  opposite postings. Reversal detection, classification and pairing are not
  eligibility requirements and never produce a quarantine by themselves.
- Imported lines retain the native defaults `reversed=false` and
  `reversal_id=NULL`. The current Daily Journal Ledger Report filters out
  `reversed=true`, while Fineract's ordinary reversal creates counter-lines on
  the original transaction date; either behavior would break faithful source
  dates or report parity.
- No reversal relation table is required for report parity. Source pointers,
  module flags, catalog labels, concepts and inverse vectors may be retained as
  optional diagnostic evidence without changing the target journal.
- The reversed-loan canary supports separate storage: among 195 heuristically
  matched marked-credit pairs, 69 retained status-3 journals at both ends and
  none shared a journal ID. All 18 reversed-refinance payoff pairs and all 18
  successor disbursement/undo pairs also used separate journals; 17 of each
  cohort were exact whole-journal inverses and one was aggregated differently.
- Every journal follows the accounting month declared by `CNT_PERIODO` at the
  cutoff, without needing to know whether another journal reverses it. An
  in-period `FECHA_PARTIDA` remains exact; an out-of-period date is normalized
  to the period's final day and retained separately as source provenance.
  Pre-cutoff effective dates import; on/after-cutoff effective dates remain
  outside historical scope.
- Historical accounting begins with the first populated status-`3` journal on
  2022-11-18 in period `00028`. All 29 `CNT_MAYOR` rows in that first
  journal-bearing period have `SALDO_INICIAL=0.00`, and their closing balances
  carry exactly into `00029`. Import every otherwise eligible journal from
  that inception through the day before cutoff. Never create a synthetic
  opening or residual journal and never replay configured empty periods from
  before operations began.
- Annual liquidation is preserved as posted GL. Import every eligible
  `ID_TIPO_PARTIDA='003'` and `LIQ_ING_EGR='1'` journal intact on its December
  31 source date. Do not generate a Fineract year-end entry and do not replay
  `CNT_MAYOR` January carry-forward state as an opening or residual journal.
- Source evidence found nine closing journals, three per year for 2023-2025;
  no `PARTIDA_INICIAL` header and no duplicate closing vector. All 211 result
  account/branch rows touched by them close to zero and begin January at zero,
  while the balance-account result carries forward through `CNT_MAYOR` state.
- Fineract `acc_gl_closure` only prevents posting on or before a date; it does
  not generate annual closing entries. Its product/asset-owner annual summary
  is not a general GL closing mechanism or migration target.
- Historical income statements and pre-closing trial balances exclude imported
  transaction groups whose immutable header provenance has source journal type
  `003`. General ledger, balance sheet, and post-closing trial balance include
  them. Date, reference number, description, and `manual_entry` are forbidden
  closure classifiers.
- Annual shape validation is fail-closed: type `003`, `LIQ_ING_EGR='1'`, a
  December 31 source date, and `PARTIDA_INICIAL='0'` must agree. Any mismatch or
  newly populated opening flag requires quarantine and review rather than an
  inferred correction.
- The four legacy journal-text fields remain four separate fields. The
  provenance header stores `CNT_PARTIDAS.CONCEPTO` as `source_header_concept`
  and `CNT_PARTIDAS.DESCRIPCION` as `source_header_description`; line
  provenance stores `CNT_DETALLE_PARTIDAS.CONCEPTO` as `source_line_concept`
  and `CONCEPTO_AUX` as `source_line_aux_concept`. All use `TEXT` and retain
  decoded Unicode verbatim rather than being concatenated or truncated.
- Each raw legacy text column has its own SHA-256 and preserves null, empty and
  whitespace as distinct values. The native journal `description` is a display
  projection only, with deterministic line/header fallback, NFC and whitespace
  normalization, unsupported-control removal, and fixed truncation to 500
  characters. `CONCEPTO_AUX` is not shown by default.
- The complete four legacy fields are excluded from standard journal APIs and
  all sync plan/status/error/reconciliation output. Their derived 500-character
  display projection remains the standard journal description. Reading the
  complete values requires a dedicated, restricted provenance permission. This
  controls exposure without discarding the historical fields.
- The agency-dimension crosswalk uses target office external IDs as canonical
  JSON string tags: source-company `001` branch `001` maps to
  `dimensions.office="1"`, and branch `002` maps to
  `dimensions.office="2"`. Target office names and internal numeric IDs are not
  tag authorities. Preflight verifies the configured ID/external-ID pairs;
  plans freeze mapping version `fineract-office-external-id-v1`, its hash, and
  every resolved line value.
- Missing, blank, foreign-company, unknown, duplicate, and target-drifted
  destination branches quarantine as `SOURCE_DESTINATION_BRANCH_UNMAPPED`.
  There is no fallback to header branch or a fixed journal-wide office.
  Historical tag dates may precede target office opening, while post-cutoff
  native journals derive the same tag from their actual posting office
  external ID.
- Native `office_id` is also line-specific: source destination `001` maps to
  office ID 1 and `002` maps to office ID 2. Mixed-office lines keep one shared
  transaction ID; only the complete journal must balance. Before any write,
  the dedicated API checks its historical-import permission, user access to
  every distinct office, and the journal date against every involved office's
  exact latest closure. A blocked office rejects the whole journal, and closure
  bypass is forbidden.
- Accounting import version 1 is USD-only. Arissto company `001` is configured
  as non-multicurrency and its type-`1` base currency is USD. Target preflight
  requires enabled USD with two decimal places; a source or target mismatch
  quarantines as `SOURCE_OR_TARGET_CURRENCY_UNSUPPORTED`.
- Source `DEBE` and `HABER` are `NUMERIC(18,2)`. Canonical plan amounts retain
  exactly two fractional digits and never pass through binary floating point.
  Fineract `DECIMAL(19,6)` stores those exact cents with four trailing zeroes;
  it does not permit the importer to create sub-cent values, round, convert, or
  recompute. Unsupported scale and target-range overflow quarantine before
  apply under policy `usd-numeric-18-2-v1`.
- Report presentation uses policy `arissto-coa-presentation-v1`. A dedicated,
  versioned `credesal_gl_account_presentation` snapshot retains source
  account code/name, parent, classifier, order, `TIPO_SALDO`, `BC`, and `BG`;
  these fields never mutate journal amounts.
- `TIPO_SALDO D` renders debit minus credit and `A` credit minus debit.
  Negative contra balances remain negative in their natural statement section;
  reports never take an absolute value.
- Trial balance selects 101 `BC=1` rollups. Balance sheet selects 64 `BG=1`
  asset/liability/equity rollups, adds current income minus expense, and keeps
  11 memorandum rollups outside the equation. Income statement selects the 26
  `BC=1/BG=0` result rollups and excludes annual closing groups by immutable
  provenance.
- Populated `CNT_REPORTES*` definitions `00009`, `00010`, and `00014` are not
  target authorities. Their account IDs are missing or semantically reused;
  notably all 19 income-statement mappings now resolve to balance accounts.
  Keep a hashed audit export, but derive target labels, sections, and subtotals
  from the frozen COA presentation contract.
- Transferred-loan accrual candidate detection never authorizes a correction.
  Historical import preserves source accounts, sides, amounts, and posted
  office. Loan `838` is a verified office mismatch but still lacks a physical
  loan-to-exact-GL-line allocation.
- A correction requires an immutable accounting-approved manifest with exact
  imported transaction IDs, accounts, sides, amounts, wrong/correct offices,
  economic window, actual posting date, rationale, approver, and evidence hash.
- The dedicated native cross-office command posts on or after cutoff. It
  reverses each approved account/amount out of the wrong office and posts the
  same side into the correct office. Every GL account must have consolidated
  net change `0.00`; only office distribution may change.
- Corrections never mutate imported journals/provenance or product subledgers,
  substitute accounts, recompute amounts, convert currency, use suspense/plugs,
  bypass closures, use migration origin, or backdate before cutoff.
- `DRAFT` never enables suppression or historical import.
- `SEALED` disables both operational suppression and historical GL import.
- Native activity remains the default origin.
- No request field or HTTP header may select an accounting origin.
- Final journal persistence rejects both policy rejections and any suppressed
  transaction that escaped its generation guard.

Source reversal measurements are documented in
[`reversos-contables.md`](../../../../../../credesal-db-space/docs/learnings/reversos-contables.md).
Annual-closing evidence is documented in
[`contabilidad-libro-mayor-y-partidas.md`](../../../../../../credesal-db-space/docs/learnings/contabilidad-libro-mayor-y-partidas.md#liquidación-anual-no-existe-una-segunda-partida-de-apertura).

## Still open

- The exact set of migration-only product commands and their narrow
  permissions.
- Atomic historical-journal request and provenance payload shape.
- Job-specific behavior when calculation spans dates on both sides of cutoff.
