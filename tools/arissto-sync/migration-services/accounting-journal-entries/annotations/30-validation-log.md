# Cutoff validation log

Record each validation cycle with date, commit/worktree identity, commands,
results, and unresolved failures. Never include credentials or sampled customer
or financial descriptions.

## 2026-09-17 — inclusive source-through terminology correction

- Supersedes the operator-facing date wording in the September 2 and September
  6 entries below without changing their historical test evidence.
- Operators now select inclusive `source_through_date=S`, defaulting to the
  plan-creation date in `America/El_Salvador`; the engine derives the internal
  Fineract cutoff as `T=S+1 day`.
- `--source-through-date` is the normal input. `--cutoff-date` remains an
  advanced direct override for `T`, the first native Fineract accounting date.
- Example: September 17 is imported with `S=2026-09-17`; native accruals begin
  on `T=2026-09-18`.
- The complete sync-engine suite passed 593 tests, and a live read-only
  September 17 inspection resolved the latest closed `CNT_MAYOR` control period
  to August 31 without blocking the open September journal scope.

## 2026-09-07 — G6 atomic historical-journal API

- Worktree: `credesal-sistema/fineract-core`, uncommitted G6 implementation on
  commit `30258943a496bd8d882297eb3bfb9083384d0ff6` in the shared dirty
  `local-development` worktree.
- Added dedicated `POST /v1/arisstohistoricaljournals`; the ordinary manual
  journal API is unchanged and cannot select historical-import origin.
- The authenticated caller requires `IMPORT_ARISSTO_HISTORICAL_GL` and access
  to every resolved line office. Lossless text reads use the separate
  `READ_ARISSTO_GL_PROVENANCE` permission added by migration `0336-3`.
- One transaction locks the ACTIVE cutoff row, validates the complete frozen
  binding and all journal lines before writing, reserves the full Arissto key,
  persists one shared native transaction group plus header/line provenance,
  and freezes the successful provenance state.
- Identical completed retries and lost-response replays return the existing
  transaction and line IDs. Changed hashes, incomplete reservations, partial
  payloads, duplicates, post-cutoff dates, closure conflicts, mapping drift,
  invalid dimensions, unsupported precision/currency, unbalanced journals, and
  unauthorized requests fail closed.
- The writer preserves exact `ref_num`, entry date, USD cents, per-line native
  office and canonical string dimension. It creates manual journal rows with
  no product/entity/payment foreign keys.
- Focused and module verification passed:

  ```text
  ./gradlew :fineract-accounting:test --tests '*HistoricalJournalImportServiceImplTest'
  11 tests passed

  ./gradlew :fineract-accounting:test
  20 tests passed

  ./gradlew :fineract-provider:compileJava :fineract-provider:processResources
  BUILD SUCCESSFUL

  ./gradlew :fineract-provider:test --tests '*ApiVerificationTest'
  2 tests passed
  ```

- Scoped formatting and migration/sync regression checks passed:

  ```text
  ./gradlew :fineract-accounting:spotlessJavaCheck -Pgate6Format
  BUILD SUCCESSFUL

  xmllint --noout 0336_add_arissto_gl_journal_provenance.xml changelog-tenant.xml
  .venv/bin/python -B -m unittest discover -s tests -p 'test_*.py'
  Ran 469 tests
  OK
  ```

- `:fineract-accounting:checkstyleTest` passed. Module-wide
  `checkstyleMain` reported only 11 pre-existing trailing-space violations in
  two unrelated GL-account files; no G6 file was reported.

- Gate 6 is complete. G5 still requires clean-install and upgrade execution on
  the supported database. G7 remains responsible for exposing sync-engine
  apply/retry/status and for its controlled explicit-key canary.

## 2026-09-07 — G5 versioned journal provenance schema

- Added tenant migration `0336` with the frozen contract table names
  `credesal_arissto_gl_journal` and `credesal_arissto_gl_journal_line`.
- Header uniqueness uses the complete Arissto journal key. Nullable target
  transaction identity is independently unique, allowing reservation and
  lost-response recovery without relying on `ref_num` or descriptions.
- Line uniqueness covers both source detail identity and stable sequence; a
  committed `acc_gl_journal_entry.id` can map to only one provenance line.
- The four legacy text values remain independent `TEXT` columns with required
  SHA-256 columns. Source cents and target Fineract precision use distinct
  `DECIMAL(18,2)` and `DECIMAL(19,6)` fields.
- The schema freezes plan, contract, source-schema, mapping, policy, cutoff,
  fingerprint, and target-baseline bindings and includes report,
  reconciliation, source-key, target-transaction, and account/date indexes.
- XML parsing and the complete sync-engine suite passed:

  ```text
  xmllint --noout 0336_add_arissto_gl_journal_provenance.xml changelog-tenant.xml
  .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
  Ran 469 tests
  OK
  ```

- Fineract resource processing included the new changelog successfully:

  ```text
  ./gradlew :fineract-provider:processResources
  BUILD SUCCESSFUL
  ```

- G5 is not yet closed: clean-install and upgrade execution against the
  supported database remain to be recorded. G6 now enforces successful-row
  immutability and the restricted provenance read boundary.

## 2026-09-02 — cutoff foundation

- Scope: accounting policy/configuration, provider persistence wiring, teller
  direct writes, and investor direct writes.
- Migration inventory confirmed `0320` is the next available tenant migration;
  historical-journal provenance still requires its own migration; the earlier
  `0321` reservation is obsolete because that number is now occupied.
- `git diff --check` passed.
- Repository search found no remaining `JournalEntryRepository.save*` calls in
  the accounting, provider, or investor production sources outside the new
  `JournalEntryPersistenceServiceImpl` boundary.
- Focused Gradle verification passed:

  ```text
  ./gradlew :fineract-accounting:compileJava \
    :fineract-accounting:test --tests '*AccountingCutoffPolicyServiceTest' \
    :fineract-provider:compileJava \
    :fineract-provider:test --tests '*JournalEntryPersistenceServiceImplTest' \
    :fineract-investor:compileJava
  ```

  Result: build successful; four cutoff decision-matrix tests and one final
  persistence-boundary test passed.
- After correcting the two reported import-order issues in cutoff-touched
  files, a second `:fineract-provider:spotlessJavaCheck` reported only 36
  unrelated files in the existing worktree. No broad formatting rewrite was
  applied.
- The Mifos error-handling path was inspected. It already surfaces Fineract
  `defaultUserMessage` values globally, so the backend cutoff rejection will be
  visible without a form-specific bypass. Spanish localization and an optional
  administrative cutoff-status view remain part of the later UI integration
  slice.

## Remaining acceptance evidence

The end-to-end acceptance cases for migrated loan/savings state, mixed-date
batches, authenticated historical-journal import, idempotency, scheduled jobs,
and cross-cutoff reversals depend on the command-scoped origin and historical
import slices documented in `10-implementation-map.md`; they are not claimed by
this foundation validation.

## 2026-09-05 — native table and agency-dimension mapping

- Mapped the native accounting spine: `acc_gl_account` and
  `acc_gl_journal_entry` are authoritative; `m_trial_balance`, annual summary,
  and stretchy reports are derived consumers, not import targets.
- Confirmed Fineract manual journal input supports dimensions at both the
  transaction and individual line level, with line dimensions taking
  precedence.
- Source audit found 13,899 headers, 13,869 populated journals, 74,550 lines,
  no duplicate line keys, no zero lines, no lines carrying both sides, and
  cent-only source amounts.
- Source audit found 1,697 journals with more than one
  `ID_SUCURSAL_DESTINO`, 1,777 with at least one destination different from the
  header, and 8,647 such lines.
- The initial direction was to translate `ID_SUCURSAL_DESTINO` only into a
  per-line `acc_gl_journal_entry.dimensions.office` tag and treat native
  `office_id` as technical context. The 2026-09-07 per-line native office
  correction below supersedes that incomplete interpretation.
- At this stage the two source branches were still unresolved mapping keys.
  Contract versions 9 and 10 subsequently froze their dimension tags and
  native office IDs.
- Business confirmed a known source anomaly: some transferred-loan accruals
  post to the wrong Arissto branch. Historical import preserves the actually
  posted agency tag and records the anomaly; correction must be a separate
  journal.
- Two balanced source journals now use the previously undocumented status `2`.
  They remain quarantined until their ledger effect is confirmed.
- `python -m unittest tests.test_services tests.test_native_shares` passed all
  34 tests after the contract/config assertions were updated.

## 2026-09-02 — loan command slice

- Added a separate `SOURCEEXACTDISBURSE_LOAN` command identity and permission;
  ordinary `DISBURSE_LOAN` remains unchanged.
- Added a test proving the source-exact handler checks the operational-migration
  permission, observes migration origin during the write, and restores native
  origin afterward.
- Added tests proving an entirely historical migration batch suppresses as a
  unit and a mixed-date batch rejects before accounting generation.
- Focused Gradle verification passed: seven accounting cutoff tests, one
  command-wrapper identity test, one source-exact disbursement handler test,
  the final journal-persistence guard regression test, and provider
  compilation.
- The Arissto loan test suites passed all 127 tests after changing the expected
  ordinary source disbursement command to `sourceExactDisburse`.
- `:fineract-loan:spotlessJavaCheck` passed. Accounting, core, and provider
  module-wide checks remain blocked only by unrelated existing formatting
  violations; no cutoff file was reported.

## 2026-09-02 — sequence cutoff snapshot

- Standalone and workflow plans now include an immutable
  `accounting_cutoff` object containing date, timezone, and resolution source.
- Historical implementation wording at that time treated the plan-creation
  calendar date as the direct cutoff and used `--cutoff-date`; this
  operator-facing terminology is superseded by the September 17 correction
  above.
- Workflow execution adopts the parent snapshot before creating child plans,
  preventing midnight rollover or delayed resume from changing the boundary.
- The complete sync-engine unit suite passed: 341 tests, including strict
  `YYYY-MM-DD` override validation.

## 2026-09-06 — cutoff lifecycle decision

- Accepted moving cutoffs for nightly testing only through new plans on newly
  restored disposable-tenant cycles.
- Existing plan snapshots and `ACTIVE` tenant cutoff configurations remain
  immutable. Apply, retry, reconciliation, and workflow children retain the
  parent plan's resolved date.
- At that time, `config/accounting.json.cutoff.date` remained unset and direct
  cutoff resolution used `--cutoff-date` or `sync_run_date`. The September 17
  correction supersedes that operator-facing resolution rule.
- The exact permanent production cutoff is deferred to G12 release approval.
- No implementation change was required: the plan snapshot, explicit override,
  workflow-child inheritance, and tenant lifecycle guards were already covered
  by the 2026-09-02 implementation and tests above.

## 2026-09-06 — source journal status decision

- Read-only source inspection found 13,899 headers: five populated/balanced
  status-`1`, two populated/balanced status-`2`, and 13,892 status-`3`, of which
  13,862 are populated and balanced and 30 are empty.
- The five status-`1` journals belong to the open 2026-09-05 close. Their 11
  account/branch groups have no `CNT_MAYOR_DIARIO` rows.
- The two status-`2` journals are system-14 automatic journals dated
  2026-06-30 and 2026-07-31, with 10/12 lines and balanced totals of
  1,805.53/1,898.54. For all 22 affected account/branch groups, the daily
  ledger equals status-`3` journal totals exactly and excludes status `2`.
- No other system-14 journal exists on either affected close, so there is no
  retained same-close replacement identity to import instead.
- The accepted migration predicate is populated, balanced status `3`. Stable
  quarantine reasons were frozen in `config/accounting.json` for status `1`,
  status `2`, unexpected statuses, empty journals, and unbalanced journals.
- A population control matched 3,907 of 3,915 period/account/branch journal
  totals directly to `CNT_MAYOR`. The eight residual groups are retained as
  reconciliation work around historical opening/liquidation behavior; they do
  not override source journal identity or status eligibility.
- Evidence command:

  ```text
  .venv/bin/python -B -m explore.audit_accounting_journal_status --status 2
  ```

## 2026-09-02 — remaining loan lifecycle slice

- Added distinct source-exact command identities and permissions for repayment
  reversal, undo-disbursement, terminal closeout, and migrated loan charges.
- Routed the sync engine to those commands, leaving the native command paths
  unchanged.
- Added all-or-nothing cutoff evaluation to savings accounting batches and a
  generation guard for due-at-disbursement tax journal groups.
- Fineract core, loan, and provider compilation passed.
- Command identity tests and operational-migration scoping tests for reversal
  undo-disbursement, terminal adjustment, and migrated charge creation passed:
  two command-identity tests and four lifecycle-handler tests.
- The accounting decision matrix passed all six tests, and the final
  persistence-boundary regression test passed.
- The complete sync-engine unit suite passed all 341 tests after asserting the
  dedicated terminal-adjustment and charge command routes.
- `:fineract-loan:spotlessJavaCheck` passed. Core and provider module-wide
  formatting checks remain blocked by unrelated pre-existing violations; the
  provider report currently includes 40 unrelated files and the known
  non-converging notification models. No broad formatting rewrite was applied.

## 2026-09-07 — Gate 2 workflow cutoff binding and zero-native-GL guard

- Local workflows using `activate-frozen-plan` now bind every child plan to the
  ACTIVE tenant cutoff date, timezone, lifecycle, configuration revision, and
  configuration hash.
- Apply and retry verify that exact target binding immediately before the
  child operation and again before the service can complete. Recovery plans
  with a stale cutoff binding are discarded and replanned.
- The workflow now queries only aggregate counts from
  `acc_gl_journal_entry` before the first service and after every reconciled
  service. Any non-manual journal row dated before the frozen cutoff fails the
  workflow in the `accounting-boundary` phase.
- The aggregate check logs counts and date bounds only; it does not read or log
  descriptions, customer identities, or transaction contents.
- `git diff --check` passed for the touched implementation and test files.
- Focused orchestration tests passed: 52 tests.
- The complete sync-engine discovery suite passed:

  ```text
  .venv/bin/python -B -m unittest discover -s tests
  Ran 451 tests
  OK
  ```
- Live restored-tenant evidence remains required before G2 is closed.

## 2026-09-07 — G1 producer and job-boundary completion

- Expanded early cutoff evaluation to client transactions, provisioning and
  its reversal, loan/share reversals, manual and opening journals,
  external-owner transfers, cashier allocation/settlement, vault/bank helpers,
  and the Credesal committee cash producer.
- Operational provisioning and cashier suppression retain their underlying
  business records and skip only the native journal group. Native historical
  attempts still reject before either state change.
- Accounting-bound workflows now fail closed unless `GET /scheduler` confirms
  the tenant scheduler is already in standby before cutoff activation or
  resume. The workflow records only the boolean verification result and never
  changes tenant-wide scheduler state itself.
- The repository inventory still finds no production
  `JournalEntryRepository.save*` outside
  `JournalEntryPersistenceServiceImpl`.
- Focused module compilation passed for accounting, provider, and investor.
- Focused Gradle verification passed: eight cutoff policy tests, one final
  persistence-boundary test, three shared producer-boundary tests, two
  cash/vault helper tests, one provisioning-state test, and one cashier-state
  test.
- The complete sync-engine suite passed:

  ```text
  .venv/bin/python -B -m unittest discover -s tests
  Ran 452 tests
  OK
  ```
- Restored-tenant cross-service execution and zero-native-GL evidence remain
  owned by G2/G10.

## 2026-09-07 — annual-liquidation decision

- Read-only source inspection found exactly nine type-`003` annual-closing
  journals: three balanced, posted stages on December 31 of 2023, 2024, and
  2025. They are the only `LIQ_ING_EGR='1'` headers.
- No source header has `PARTIDA_INICIAL` set, and no annual journal's aggregated
  account/branch vector duplicates another posted journal.
- All 211 result-account/branch rows touched by the annual journals ended
  December at zero and began January at zero. Receiving balance accounts carry
  post-closing `SALDO_FINAL` into January through `CNT_MAYOR` state; no second
  opening transaction exists.
- Excluding type `003`, annual result-account activity remains nonzero.
  Including it makes every affected result-account/branch row and each year's
  aggregate exactly zero. This proves the need for distinct pre-close and
  post-close report views without preserving sampled financial totals here.
- Fineract code inspection confirmed `acc_gl_closure` only rejects posting on
  or before the latest office close date; it generates no closing journals.
  The standard Income Statement Table aggregates all income/expense journal
  rows between its dates and has no native annual-close exclusion. The annual
  summary table is limited to loan-product/asset-owner reporting and has no
  general closing writer.
- Contract version 7 freezes intact source-date import, no generated opening or
  residual entries, provenance-driven exclusion of type `003` for income
  statement/pre-closing trial balance, inclusion for GL/balance-sheet/
  post-closing trial balance, and fail-closed annual shape reasons.
- Evidence command:

  ```text
  .venv/bin/python -B -m explore.audit_accounting_annual_closing
  ```

- The complete sync-engine unit suite passed all 451 tests. JSON/YAML parsing,
  Python compilation, and focused `git diff --check` also passed.

## 2026-09-07 — legacy journal-text preservation decision

- Contract version 8 rejects compacting four source fields into Fineract's
  500-character journal description.
- Header provenance separately stores `CNT_PARTIDAS.CONCEPTO` and
  `CNT_PARTIDAS.DESCRIPCION`; line provenance separately stores
  `CNT_DETALLE_PARTIDAS.CONCEPTO` and `CNT_DETALLE_PARTIDAS.CONCEPTO_AUX`.
- Each full value uses an unrestricted-length text column and its own SHA-256.
  Null, empty, and whitespace-only values remain distinguishable, and no
  normalization or truncation occurs before provenance storage.
- Native `acc_gl_journal_entry.description` remains a deterministic,
  500-character display projection and is not a preservation authority.
- Complete legacy values require a dedicated provenance permission and are
  excluded from plan, status, error, and reconciliation output. No sampled
  source text was read or recorded for this decision.

## 2026-09-07 — agency-dimension crosswalk decision

- A read-only aggregate source audit found exactly two `SUCURSAL` rows for
  company `001`: branch `001` `AGENCIA CENTRAL` and branch `002` `USULUTAN`.
- All 74,630 current `CNT_DETALLE_PARTIDAS` rows use one of those two
  destination branches: 54,545 use `001` and 20,085 use `002`. There are zero
  null, blank, or catalog-unresolved destination values.
- The target bootstrap independently fixes branch `001` as office ID 1 with
  external ID `"1"`, and branch `002` as office ID 2 with external ID `"2"`.
  The crosswalk therefore stores JSON string tags `"1"` and `"2"`, with
  `m_office.external_id` as the stable authority rather than office names.
- The earliest destination-`002` line is dated 2024-11-01, before Fineract
  office 2's corrected operational opening date. The dimension preserves that
  source attribution and is not rejected by the target opening date.
- The local Fineract API was offline during this review. The contract is backed
  by the enforced `ARISSTO_OFFICES` bootstrap definition; live preflight must
  still verify both ID/external-ID pairs before planning or apply.
- Contract version 9 freezes mapping version
  `fineract-office-external-id-v1`, fail-closed reason
  `SOURCE_DESTINATION_BRANCH_UNMAPPED`, and the native post-cutoff namespace.
- Source evidence command:

  ```text
  .venv/bin/python -B -m explore.audit_accounting_branch_dimensions
  ```

## 2026-09-07 — per-line native office correction

- Rejected the proposed single technical office because it would assign every
  imported row to one Fineract office and corrupt native per-office accounting.
- Fineract schema inspection found no uniqueness or consistency constraint
  requiring rows with one `transaction_id` to share `office_id`. Repository
  transaction lookups also group across offices.
- The standard manual-journal API accepts one top-level office and copies it to
  every line, but that is an endpoint limitation rather than a ledger
  invariant. The already-required dedicated historical API will accept native
  office per line.
- Contract version 10 maps destination `001` to native office ID 1 and `002` to
  office ID 2 while retaining one shared transaction ID and complete-journal
  balance. Per-office imbalance is valid for inter-office journals.
- Existing Fineract closure validation queries the latest closure for one exact
  office and rejects a date on or before it. The dedicated writer must validate
  all distinct line offices before persistence; it may not bypass closures.
- Existing manual creation enforces generic `CREATE_JOURNALENTRY` but does not
  explicitly call `AppUser.hasAccessToOffice` for the requested office. The
  dedicated endpoint must require its own historical-import permission and
  verify access to every mapped office before the atomic write.

## 2026-09-07 — USD and exact-cent precision decision

- Arissto company `001` has `MULTIMONEDA='0'`. Its type-`1` base currency is
  USD; the seven other active catalog currencies are type `2`, not base ledger
  currencies under the current company configuration.
- `CNT_DETALLE_PARTIDAS.DEBE` and `HABER` are both declared
  `NUMERIC(18,2)`. Across 74,630 current lines there are zero values beyond two
  decimals, negative sides, both-sides-nonzero rows, or both-sides-zero rows.
- Current values use at most six integer digits and zero rows exceed Fineract
  `DECIMAL(19,6)`'s 13-integer-digit range. A permanent overflow quarantine is
  still required because Arissto's declared source type theoretically permits
  16 integer digits.
- Contract version 11 freezes USD, exact two-decimal canonical strings, no
  binary floating point, no rounding/conversion/recomputation, target USD
  preflight, and stable currency/scale/overflow quarantine reasons.
- Evidence command:

  ```text
  .venv/bin/python -B -m explore.audit_accounting_currency_precision
  ```

## 2026-09-07 — COA-driven report-presentation decision

- A read-only audit found 2,494 company-`001` accounts with no null `BC`/`BG`
  flags and no `TIPO_SALDO` outside `D`/`A`. There are 101 `BC` selectors and
  75 `BG` selectors; every `BG` row is also `BC`. The 26 `BC`-only rows are
  exactly the result-account presentation rows.
- The classifier/nature relation is exact: assets and result-debtors use `D`;
  liabilities, capital, and result-creditors use `A`. Contra-assets remain
  negative under `D` and must not be converted to absolute values.
- Across the latest six closed periods, consolidated `BC` debtor and creditor
  sides agreed exactly. For each period, assets minus liabilities minus equity
  minus current result was `0.00`. Period `00073` tied at `629,805.38` per
  trial-balance side and its balance-sheet equation also differed by `0.00`.
- Populated legacy templates failed semantic validation. `00009` has two
  unresolved mappings and does not reproduce the supplied current report.
  `00010` has one unresolved mapping and all 28 resolved mappings are assets.
  All 19 `00014` mappings are balance accounts (18 assets and one liability),
  not result accounts.
- Contract version 12 freezes `arissto-coa-presentation-v1`, the dedicated
  presentation metadata snapshot, report selectors/formulas, recursive rollup,
  contra sign behavior, office/consolidated scope, deterministic zero-row
  handling, legacy-template rejection, and exact acceptance equations.
- Evidence command:

  ```text
  .venv/bin/python -B -m explore.audit_accounting_report_presentation
  ```

## 2026-09-07 — transferred-loan accrual correction decision

- Existing source evidence distinguishes 166 broad candidates from the
  verified loan-`838` office mismatch. Even for `838`, daily accrual journals
  aggregate multiple loans and do not physically identify the loan on exact GL
  lines; the observed `327.62` cannot authorize an automatic journal.
- Contract version 13 freezes historical preservation, candidate-only
  detection, immutable accounting approval, exact source transaction/account
  allocation, native post-cutover posting, per-office closure and permission
  checks, atomic idempotency, and linked correction provenance.
- The line rule moves each approved side between offices on the same account
  and amount. Acceptance requires complete-journal balance and consolidated
  net change `0.00` for every account and every financial statement. Product
  subledgers and imported journals remain immutable.
- `.venv/bin/python -B -m unittest discover -s tests` passed all 451 tests
  with the version-13 contract assertions.

## 2026-09-07 — G3 read-only accounting inspector

- Registered CLI block `accounting` for `inspect` only. The registry remains
  `planned`, `executable: false`, and exposes no accounting plan/apply/retry/
  reconcile/status route.
- The source reader uses four bulk `SELECT` queries under the existing ODBC
  read-only connection guard. It caps one run at 50,000 headers and 250,000
  lines, scopes exact canaries by
  `COMPANY:BRANCH:PERIOD:JOURNAL`, and never performs a query per journal.
- The inspector freezes the approved COA overrides in contract configuration,
  hashes the four legacy text fields without returning them, and emits only
  source keys, structural counts, SHA-256 values, and stable reason codes.
- A full source inspection at cutoff `2026-10-01` completed with `ready=true`:
  13,909 headers, 74,630 lines, 13,879 populated/balanced journals, 30 empty
  headers, two status-`2` exclusions, nine valid annual-liquidation journals,
  one back-period journal, and the two previously documented journal-number/
  date-prefix mismatches. No unbalanced, invalid-side, precision, account, or
  agency finding was reported.
- A target-selected local run returned the same source counts and also read the
  2,523-account COA, offices, and closure table without finding an unresolved
  target account or closure conflict. The G5 provenance tables are correctly
  reported as absent/not yet populated rather than synthesized.
- `tests.test_accounting` covers complete-key parsing, read-only SQL shape,
  deterministic ordering/hashes, privacy-safe output, and stable classification
  reasons. The complete sync-engine suite passed all 456 tests.
- Two consecutive unsandboxed read-only source inspections over the unchanged
  full company-`001` scope returned the same inspection SHA-256
  `e73d5d6488a98267a62a2ce20d87fa7b190b8c5ecafb68028dcf5af0ede6105a`,
  the same 13,909/74,630 header/line counts, the same 34 finding keys, and the
  same reason counts. This hash was refreshed after G4 separated normalized
  source content from target-mapping bindings; two consecutive full
  inspections returned the new value. This satisfies the G3 deterministic
  replay exit gate.

## 2026-09-07 — G4 deterministic explicit-key planner

- Worktree: `credesal-sistema/fineract-core`, uncommitted G4 implementation on
  the current shared worktree.
- Added `plan --block accounting` for one or more explicit
  `COMPANY:BRANCH:PERIOD:JOURNAL` keys. Accounting remains registry
  `planned`, `executable: false`, with no apply, retry, reconciliation, or
  target writer.
- Canonical actions freeze exact-cent debit/credit strings, stable line order,
  resolved target GL account IDs/codes, per-line office IDs and string
  dimensions, approved display descriptions, raw legacy-text hashes, complete
  source provenance, and action hashes.
- Independent bindings cover source schema/content, contract, COA and agency
  mappings, policy/planner version, target fingerprint and baseline, and the
  complete cutoff snapshot. `assert_accounting_plan_current` fails closed when
  any frozen material differs.
- Missing keys, invalid or on/after-cutoff journals, target provenance hash
  conflicts, and valid already-imported journals produce explicit stable
  `QUARANTINED` or `UNCHANGED` actions; valid new journals produce
  `APPLICABLE`. No requested key is omitted.
- Focused validation:

  ```text
  .venv/bin/python -B -m unittest tests.test_accounting tests.test_services
  31 tests passed
  ```

- Full sync-engine regression:

  ```text
  .venv/bin/python -B -m unittest discover -s tests
  462 tests passed
  ```

- A read-only local canary planned source key
  `001:001:00028:0000000002` twice against cutoff `2026-01-01`, using an
  isolated SQLite state file under `/private/tmp`. Both runs returned one
  `APPLICABLE` two-line journal and the same hashes:
  - plan: `704b80c305489d9d6ca77fb98a22b6f7143036423ef730580dddbf9fa57f8b48`
  - source: `b13ba213777155619865d6d1604baa62f509dcae5961e12e3b7da6642441ce70`
  - action/payload: `0f2a06273d70d99327b1baea65b698c898816beb283e6929d30475a2d69645e3`
- The canary performed only Arissto and Fineract reads; it made no source or
  target business-data writes. The explicit-key determinism exit gate is
  satisfied. Date/period scope expansion remains gated on the later accepted
  apply/retry canary.

## 2026-09-07 — G7 apply, retry, status, and local canary

- Added sequential explicit-key accounting apply through the dedicated G6
  endpoint, failed-only retry with stable request identity, and accounting
  status counts. Apply fails closed unless the scheduler is paused and the
  target fingerprint, contract, ACTIVE cutoff revision/hash, source content,
  mapping bindings, and target baseline still match the frozen plan.
- Sync state atomically retains source key, plan and payload hashes,
  idempotency key, logical request run, target transaction and line IDs,
  disposition, stable error code, error class, and retryability. Network and
  transient HTTP failures are retryable; stable validation failures quarantine;
  binding and identity conflicts are fatal.
- A focused simulated lost-response test proved `retry --failed-only` reuses
  the original idempotency key and logical request run and records the prior
  target transaction/line identities without creating a second journal.
- Preflight passed against local target fingerprint `b9f6834b66790744` and
  source fingerprint `87f2c811788b4c7e`. The tenant had ACTIVE cutoff
  `2026-09-05`, revision `2`, and the scheduler was explicitly paused for the
  canary.
- The first request for key `001:001:00028:0000000002` failed safely with
  `ACCOUNTING_IMPORT_OFFICE_UNAUTHORIZED` and committed no target rows. It
  exposed object-identity comparison between the detached authenticated user's
  office and the reloaded journal office. `AppUser.hasAccessToOffice` now
  compares persistent office IDs; its regression test and all 11 G6 writer
  tests pass.
- The corrected apply run `9c66c10f903c44c7b3ce9a7b021de115`
  imported one journal. Target inspection found exactly one provenance header,
  two provenance/GL line identities, and exact `27000.000000` debit and credit
  totals.
- Reapplying the original plan returned `recovered: 1`. A fresh plan classified
  the key `UNCHANGED`; run `578fdf2414624cb382e53ca2b3a6d1f5`
  returned `unchanged: 1`. Target counts remained one header and two lines, so
  both replay paths created zero additional rows.
- G7 is complete. The registry intentionally remains `planned` and
  `executable: false` until G8 reconciliation and full execution-slice
  acceptance are complete; date/period planning remains disabled.
- Final regression verification passed all 473 sync-engine tests, the focused
  `AppUserTest`, and all 11 `HistoricalJournalImportServiceImplTest` cases.
  Module-wide Spotless checks remain blocked by previously existing formatting
  violations in unrelated accounting/core files.

## 2026-09-07 — Historical journal origin approved and enforced

- Approved the inception route for company `001`: import every otherwise
  eligible status-`3` journal dated on or after 2022-11-18 and strictly before
  the frozen cutoff. Do not create synthetic opening or residual journals, and
  do not replay `CNT_MAYOR*` balances as transactions.
- The read-only origin control found that period `00028` is the first configured
  period containing populated status-`3` journals: 3 journals, 7 lines, and
  exact debit and credit totals of 61,000.00. All 29 `CNT_MAYOR` rows in that
  period have `SALDO_INICIAL=0.00`; their closing balances carry exactly into
  period `00029`.
- Cumulative eligible journals reproduced all 267 compared posting-account,
  branch, and period closing balances through period `00040`, before the first
  annual-liquidation boundary. The reproducible source control is maintained in
  `credesal-db-space/docs/queries/accounting-ledger-origin-control.sql`.
- Contract version 14 freezes policy
  `arissto-journal-inception-v1`. Planning now quarantines any otherwise
  in-scope journal before the approved origin as
  `SOURCE_JOURNAL_BEFORE_HISTORICAL_ORIGIN`, and the policy hash includes the
  complete historical-origin configuration.
- Focused verification passed 36 tests:
  `.venv/bin/python -B -m unittest tests.test_accounting tests.test_services`.
  Full sync-engine regression passed all 474 tests:
  `.venv/bin/python -B -m unittest discover -s tests`.

## 2026-09-07 — G8 direct reconciliation and inception-period acceptance

- Added `accounting-direct-journal-reconciliation-v1` and registered
  `./arissto-sync reconcile --run RUN_ID --target TARGET` for accounting.
  Reconciliation reads immutable provenance and native journal/account/office
  tables directly; it does not use `m_trial_balance` as financial truth.
- Exact checks cover source journal/line identity, target transaction/line
  identity, source/planned and frozen binding hashes, date, `ref_num`, currency,
  account, side, six-decimal target amount, native office, agency dimension,
  descriptions, line count, journal totals, reversal/manual state, and absence
  of product links. Boundary checks reject native non-manual pre-cutoff GL and
  imported GL on or after cutoff.
- The first canary exposed an incorrect reconciler assumption about native
  enums. Fineract persists credit as `type_enum=1` and debit as `type_enum=2`;
  the implementation and regression fixture now use the verified values.
- Added bounded `--period` planning. Plan
  `a2febfd805974472b84c95c562110560` selected all three journals and seven
  lines in inception period `00028`: two `APPLICABLE` and one `UNCHANGED`.
  With the local scheduler explicitly paused, run
  `2bdb367e631e4b6599079c6e740b65b2` imported two and retained one. The
  scheduler was restored after reconciliation.
- Reconciliation v2 matched all three journals with zero journal,
  cutoff, agency-bucket, or consolidated-bucket variances. Expected and actual
  direct-balance hashes were both
  `416419d02b60c8bdc20149efa9dfcf71b4dda94b5dc7218fd4565ef5ec68f18f`.
- The independent inception-ledger control found three eligible journals and
  six posting account/agency buckets; cumulative journal closing matched
  `CNT_MAYOR.SALDO_FINAL` with zero mismatches and `0.00` absolute variance.
  Parent/reporting `CNT_MAYOR` rows are intentionally excluded.
- `gate8_acceptance_ok` now depends only on exact journal/line parity, cutoff
  boundaries, direct balance parity, complete inception-to-control-period
  scope, and the `CNT_MAYOR` closing control. Product-service reconciliations
  remain durable independent evidence but no longer block Gate 8.
- Focused accounting/service verification passes all 39 tests. Full
  sync-engine regression passes all 477 tests.

## 2026-09-07 — G9 native dimension-aware reporting implementation

- Added the read-only Arissto presentation exporter and froze snapshot
  `arissto-coa-presentation-v1` with SHA-256
  `9e4d2a035daf0d21944ef21684a467d26349023e2b2c56e30ffc98385bc56282`.
  It contains 2,494 source accounts, 101 `BC` selectors, and 75 `BG`
  selectors. Twelve obsolete/non-selected source leaves have no exact target
  code; all selected report rows resolve, producing 2,482 target metadata rows.
- Tenant migration `0337` ran successfully for the local `default` and
  `sandbox` tenants. Database inspection confirmed 2,482 rows, 101
  trial-balance selectors, 75 balance-sheet selectors, one version/hash, zero
  source-to-target code disagreement, and the
  `READ_CREDESAL_FINANCIAL_REPORTS` permission.
- Added the native `credesalfinancialreports` endpoint for general ledger,
  trial balance, balance sheet, income statement, agency scope, and
  consolidated scope. It reads direct journals, applies source presentation
  signs and hierarchy, implements type-`003` closing modes through immutable
  provenance, and fails closed on office-dimension disagreement.
- Live sandbox period-`00028` evidence: general ledger returned all 7 lines;
  consolidated post-closing trial balance returned 4 non-zero rows with
  debit=credit=61,000.00 and zero trial-balance and balance-sheet variance.
  Agency `dimensions.office="1"` produced the same totals; balance sheet
  controls were also exact. The income statement correctly normalized itself
  to pre-closing mode and had no non-zero result rows in this inception period.
- Added exact `referenceNumber` filtering to the ordinary journal-entry API.
  Migration `0338` adds the supporting `ref_num` index and was applied
  successfully to the local tenant. A live lookup of `2022110002` returned
  exactly its two lines. Mifos now
  displays and filters the posted journal number, shows it with the distinct
  technical transaction ID on detail, and removes the conflicting writable
  field from manual and frequent-posting forms.
- Verification passed the read-only exporter unit test, Fineract accounting
  and provider compilation, all 3 focused report-service tests, presentation
  Liquibase resource processing, XML validation, Mifos Prettier checks, and
  TypeScript no-emit compilation. Angular's production bundler exited with
  signal 11 under both installed Node launchers; it emitted no TypeScript or
  template diagnostic.
- G9 implementation is delivered but the exit gate remains open. Required next
  evidence is an independently computed source-to-native comparison of every
  selected label/sign/rollup for expanded periods, an imported annual
  type-`003` boundary proving both closing modes, and a multi-agency period
  proving consolidated totals equal the sum of agency scopes.

## 2026-09-07 — G9 expanded multi-agency and annual-close acceptance

- Selected period `00053` (December 2024) because it is the earliest reviewed
  annual type-`003` close containing both destination agencies. Correct
  cumulative balance-sheet proof required the contiguous approved history from
  inception period `00028` through `00053`.
- Initial plan `94c763766c6341a8bc1a7ae31066f09d` contained 5,560 applicable,
  three unchanged, and four quarantined empty headers. Bounded-period apply
  exposed an O(journals) source revalidation path; apply was interrupted before
  its run or any target write, then changed to reuse the frozen period queries.
  The focused accounting/service suite passes all 40 tests.
- The main local run `0ab873c913fc470f95021244c421faa1` imported 5,404 journals
  and safely rejected 156 office-2 journals because the local administrator was
  assigned only office 1. No global authorization rule was weakened. The
  disposable local administrator was explicitly assigned offices 1 and 2;
  recovery run `a468990ab98c49048a90d2ab70adc57f` imported all 156 and retained
  531 already imported journals as unchanged.
- Final full-scope plan `55cd8c4651824ae9b3e0e70da141380e` classified all 5,563
  eligible journals unchanged and retained four explicit source quarantines.
  Run `7300c16dc2cc45bdaf3f964a201bce73` reconciled every eligible journal with
  zero journal/line, cutoff, agency-bucket, or consolidated-bucket variance.
  Its expected and actual direct-balance hash is
  `cd3e7f1d789e040d9e6d1eeeb51be027a6e2c97e723481232e84b26319c1d816`.
- The auxiliary `CNT_MAYOR` year-end control reported three source-state
  differences: two `314002` current-result branch balances and one two-cent
  `2220050501` difference. These are retained as source findings;
  `CNT_MAYOR` is not the imported transaction or Gate-9 reporting authority.
- Added local-only command `./arissto-sync prove-accounting-reports`. It builds
  expected rows independently from read-only Arissto journals, the frozen source
  presentation tree, and the contract mapping, then compares the native API in
  consolidated, office-1, and office-2 scopes.
- The 2024 proof passed all 12 report/scope/closing-mode cases with zero row,
  metadata, sign, measure, or recursive-rollup findings: 101 trial-balance, 75
  balance-sheet, and 26 income-statement selectors per scope. Every requested
  measure was additive across agencies with zero findings.
- The imported type-`003` close materially changed six consolidated
  trial-balance rows, six office-1 rows, and four office-2 rows between pre- and
  post-closing views. All 16,728 2024 general-ledger source lines matched the
  native output with zero variance.
- The local scheduler was paused before all writes and restored after the proof.
  G9's expanded-period, multi-agency, and annual-close exit evidence is complete.

## 2026-09-07 — G9 statement-output acceptance harness

- Added the local-only, read-only
  `arissto_sync.accounting_g9_acceptance` harness and its operator guide. It
  checks the populated sandbox baseline, traces the two named control-account
  families across source journals, daily/monthly mayor, and native imported
  lines, captures all 12 native December statement cases, and compares a
  normalized authoritative Arissto artifact at exact currency precision.
- Sandbox readiness passed: 5,563 provenance journals, 26,820 provenance and
  native lines, 380 period-`00053` journals, 2,065 period lines, three valid
  type-`003` closing journals, 16,728 imported 2024 lines, and zero dimension,
  missing-line, opening-flag, annual-shape, or unprovenanced pre-cutoff
  findings.
- Control trace artifact SHA-256
  `a17a29c3c11cf24db424e257c6a1f604af6e6172d5a8aca105407b391143eaf8`
  found zero source-to-target activity variance and zero daily-mayor rollup
  variance. It identifies an explicit `0.02` source credit on 2024-12-28 in
  descendant `222005050102`; that posting is present in the native ledger, so
  no synthetic correction is authorized. The remaining authoritative-output
  comparison must confirm how Arissto presents parent `2220050501`.
- Native December target artifact SHA-256
  `7bc8d1dca1bd436c5ddc5caaa290b72682da7bdc9e0768fe236d66ff68d35f5d`
  and stable report-case content SHA-256
  `efb39b75518b2b63399e9d272c3aadfc159a92c2ef49c8f7dd9a2215ef94c597`
  were captured from the local `sandbox` API. The existing full-2024
  `prove-accounting-reports` command was rerun and passed all 12 cases, all
  16,728 GL lines, both agencies, additivity, and the annual-closing boundary.
- Nine focused harness tests pass. Tests A, B, and D remain open until the
  authoritative December 2024 and January 2025 Arissto outputs are captured,
  normalized, hashed, and compared. Test E remains blocked on an approved
  cash-flow contract. This diagnostic run does not replace either G11 clean
  cycle.

## 2026-09-09 — G9 authoritative December statements and January continuity

- Normalized the ten reviewed Excel exports from
  `credesal-dec-2024-combined` without copying the source workbooks into the
  repository. Eight office workbooks provide the required direct cases and
  derive 12 office/consolidated cases. The authoritative case-content SHA-256
  is `ac7d4afb06e7c68474c2f9d070a8ff46a125b7a94b591c05ff1769081e81d164`;
  the generated artifact SHA-256 is
  `6370a203cbc090f715b472bc7bbd5dfd2c69b65a3ebe7b4a2211a5722bce1257`.
- Workbook identity is validated from the internal report header, not inferred
  from the Spanish filename. The supplemental
  `estado de resultados-ene-dec-2024-usulutan.xlsx` identifies itself as
  `AGENCIA CENTRAL`; it is retained as a warning and is not used as office-2
  evidence. The office-2 pre-liquidation income statement is valid and covers
  the required native pre-closing case.
- The source exports exposed two report-service defects. Pre-closing had
  removed all historical type-`003` journals, but Arissto removes only the
  current financial year's annual-close lines from profit-and-loss accounts;
  balance accounts keep their transferred results. Income-statement ordering
  also had expenses before income. The native service now implements the
  source boundary and source order.
- The corrected native target artifact SHA-256 is
  `edfdb4ec7bd32b1431fae934e9898be1f519b4d14fe233e3626229af0c4bdc9e`.
  All 12 exact statement cases passed with zero row, order, value, or control
  findings. The comparison artifact SHA-256 is
  `f4742c04d8507a777be23db5fde0fafb17ba6e5a5979f519ca674446a15e4fd2`.
- Readiness remains exact: 5,563 journals, 26,820 provenance/native lines, 380
  December journals, 2,065 December lines, three annual-close journals, and
  16,728 2024 lines, with zero dimension, missing-line, opening-flag,
  annual-shape, or unprovenanced findings.
- Test D no longer depends on a January UI export. The read-only trace compares
  December period-`00053` `SALDO_FINAL` to January period-`00054`
  `SALDO_INICIAL` across all 204 source account/office rows, applies the frozen
  many-to-one chart mappings, reconstructs materialized hierarchy nodes such
  as `314002` and `2220050501` from 202 native direct balances, and finds zero
  source-continuity or native-opening variances. The trace artifact SHA-256 is
  `f48096e0d13f7f508a2e33fea809e6f23eea59094b22833c9c194e01e693e33e`.
  It also retains zero daily-mayor and source-to-native activity variances for
  Tests B and C. No synthetic January opening exists or is required.
- Seventeen focused Python tests and all three focused Java report-service
  tests pass. Repository-wide provider Spotless remains blocked by unrelated
  pre-existing formatting violations in other provider files; the changed
  report-service files passed the focused compile/test path. Test E remains
  blocked on an approved cash-flow contract, and G11 must reproduce this suite
  on both restored clean cycles before release acceptance.

## 2026-09-10 — G10 scoped canary checkpoint

- Restored the disposable sandbox baseline and ran the source-backed positive,
  quarantine, closure, exact-once, lost-response recovery, changed-hash, and
  cutoff-date native posting cases.
- All selected journals and dimensions reconciled exactly. The complete
  inception period independently retained Gate 8 acceptance with zero findings.
- The remaining G10 work is a fresh operational loan/savings suppression run,
  a repeatable mixed live/synthetic harness, and resolution of the transferred-
  loan checklist wording without inventing an exact GL-line allocation.
- Detailed keys, run IDs, hashes, verification commands, cleanup state, and the
  contract conflict are recorded in
  [`../g10-canary-results.md`](../g10-canary-results.md).

## 2026-09-10 — repeatable G10 acceptance harness

- Added local-only `prove-accounting-g10`. It combines live source keys,
  direct target reconciliation, live and synthetic quarantines, cutoff
  boundaries, retry identity, a changed-hash rejection probe, native cutoff-
  date exact-once evidence, and the contract-approved anomaly-preservation
  assertion.
- The local sandbox returned `accepted=true`; evidence SHA-256 is
  `70d536246ea849d5b157d645ddc90cfbe80c73b9337f6d5fded87fe3dacf21a0`.
  Seven imported/recovered journals had zero findings, all negative cases
  passed, and both boundary counts were zero.
- The full sync-engine regression passes all 508 tests. Gate 10 ledger
  acceptance is complete under the explicit assumption that Loans Gate 5 is
  accepted. The fresh whole-tenant cross-service reproduction belongs to G11.

## 2026-09-11 — measured full-ledger scope and guard removal

- A fresh unsandboxed, read-only inspection of Arissto company `001` at cutoff
  `2026-09-11` completed with `ready=true` and measured 14,007 journal headers
  and 75,180 detail lines.
- The date boundary classified 13,991 headers before the cutoff, 16 on the
  cutoff, and none after it. The inspection reported 34 classified findings;
  this entry records aggregate volume only and does not copy source data.
- Removed the unmeasured 50,000-header and 250,000-line abort thresholds from
  inspection, planning, and apply. Full sandbox workflow plans now load and
  record the complete selected source scope rather than enforcing arbitrary
  row-count policy.
