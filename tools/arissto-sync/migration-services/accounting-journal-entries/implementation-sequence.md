# Accounting journal sync engine implementation sequence

## Outcome

Finish the `accounting` sync service so a reviewed operator can inspect, plan,
apply, retry, reconcile, and report every eligible pre-cutoff Arissto journal
through native Fineract accounting tables without duplicate or missing GL.

The authoritative financial result is the combination of
`acc_gl_account` and `acc_gl_journal_entry`. One Arissto journal becomes one
Fineract `transaction_id`; each detail row carries its translated agency in
both native `acc_gl_journal_entry.office_id` and the stable
`dimensions.office` tag. Mixed-office lines retain one transaction ID and
balance across the complete journal.

The service is complete only when the imported journal population can recreate
the general ledger, trial balance, balance sheet, income statement, and
agency/consolidated balances directly from native Fineract journal rows, while
native Fineract owns all accounting dated on or after the cutoff.

## Current state on 2026-09-07

| Area | State | Evidence or remaining work |
|---|---|---|
| Source-table meaning and journal identity | Ready for implementation | `CNT_PARTIDAS` header identity and `CNT_DETALLE_PARTIDAS` line identity are documented. |
| Active source-account mapping | Ready for implementation | Every currently used source posting account has a reviewed Fineract destination; freeze its version in each plan. |
| Native accounting table map | Ready for implementation | `acc_gl_account` and `acc_gl_journal_entry` are authoritative; derived summaries are not import targets. |
| Cutoff configuration and central persistence guard | G1 implementation complete | Migration `0320`, the decision service, all reviewed producer generation boundaries, final persistence guard, and workflow scheduler-standby prerequisite are implemented and covered by focused tests. Restored-tenant cross-service evidence belongs to G2/G10. |
| Frozen cutoff in sync plans | Gate 2 workflow binding delivered | Workflow child plans retain the date/timezone plus the exact ACTIVE tenant configuration revision and hash. Apply/retry verifies that binding before execution and again before completion. |
| Agency dimension and native-office policy | Ready for implementation | Per-line source `001` maps to native office ID 1 and JSON string tag `"1"`; `002` maps to native office ID 2 and tag `"2"`. One transaction may contain both offices. |
| Source eligibility policy | Decided | Only populated, balanced status-`3` journals dated on or after the demonstrated zero origin of 2022-11-18 are eligible by status/integrity. Synthetic opening and residual journals are forbidden. Reversals, annual liquidation, legacy text, agency, currency, report presentation, post-cutover correction, and historical-origin policies are frozen in contract version 14. |
| Accounting inspector, planner, writer, retry, and reconciler | G3, G4, G6, G7, and G8 complete | The registry exposes `inspect`, deterministic explicit-key and bounded-period `plan`, atomic `apply`, failed-only `retry`, direct-journal `reconcile`, and `status`. Period `00028` passed exact target parity plus the independent `CNT_MAYOR` closing control. The service remains `planned` and `executable: false` until the later release gates are complete. |
| Historical-journal provenance schema/API | G6 API complete; G5 database-path acceptance pending | Tenant migration `0336` creates lossless header/line provenance, complete source-key and target-line uniqueness, reconciliation/report indexes, and the restricted provenance-read permission. The dedicated API atomically persists native journal lines and provenance with idempotent replay. A supported-database clean/upgrade run is still required before closing G5. |
| Report parity | G9 journal-derived proof complete; source-output acceptance pending | The native `credesalfinancialreports` API and presentation snapshot passed independent 2024 journal-derived parity across consolidated and both agency scopes. All 12 selector/sign/rollup cases and 16,728 GL lines matched; the imported type-`003` boundary changed the expected pre/post-close rows and agency additivity had zero findings. Exact row-level comparison with authoritative Arissto statement output, including the known `CNT_MAYOR` year-end differences, remains required. Cash flow has no approved source or target contract yet. |

Status in this file is planning evidence, not the executable registry source of
truth. Confirm the live service status with `./arissto-sync services`.

## Non-negotiable quality bar

- One immutable tenant-wide cutoff in `America/El_Salvador` governs every
  financial migration service.
- Dates before the cutoff belong to imported Arissto GL; the cutoff date and
  later belong to native Fineract accounting.
- Every eligible pre-cutoff source journal is imported intact and exactly once.
- One journal is the atomic write and retry boundary; partial debit/credit
  persistence is unacceptable.
- Native product migration creates operational history with its pre-cutoff GL
  suppressed. The accounting service alone creates historical GL.
- The source destination agency is translated on every line into both native
  `office_id` and `dimensions.office`; never force a mixed-office source
  journal through one fixed native office.
- The known transferred-loan accrual defect is preserved as posted and flagged
  in provenance. The importer never silently changes historical office tags.
- Invalid or undecided journals quarantine with stable reasons; they are never
  skipped, rewritten, or balanced with an invented plug.
- Arissto remains read-only. Fineract journal rows are created through a
  dedicated authenticated API, not direct sync-engine SQL.
- Reset means restoring the whole disposable tenant, never deleting selected
  journal rows.

## Dependency path

```text
G0 decisions and frozen contracts
  ├── G1 cutoff guard completion ── G2 cross-service cutoff proof
  ├── G3 read-only source engine ── G4 deterministic planner
  └── G5 provenance schema ──────── G6 atomic Fineract writer
                                      │
G4 + G6 + G2 ── G7 apply/retry/status ── G8 reconciliation
                                             │
                       G9 report compatibility and parity
                                             │
                      G10 canaries ── G11 clean cycle ── G12 production
```

No gate may be marked complete from documentation alone. Its exit evidence
must be recorded in `annotations/30-validation-log.md` with the relevant
commit/worktree, commands, counts, and unresolved failures.

## G0 — accounting decisions complete (2026-09-07)

### Work

1. **Complete — cutoff lifecycle approved.** Keep `< cutoff` historical and
   `>= cutoff` native. Each new test plan may use `--cutoff-date` or the
   `sync_run_date` default, and freezes that resolved date for apply, retry,
   reconciliation, and workflow children. Advancing the date requires a new
   restored disposable-tenant cycle; an existing plan or active tenant cutoff
   is never mutated. Approve the one permanent production date at G12.
2. **Complete — journal status policy approved.** Only populated, balanced
   `ESTADO_PARTIDA='3'` journals are eligible by status and integrity. Status
   `1` quarantines as `SOURCE_JOURNAL_NOT_MAYORIZED`; status `2` quarantines as
   `SOURCE_JOURNAL_EXCLUDED_FROM_LEDGER`; unexpected values, empty journals,
   and unbalanced journals have their own stable reasons. The two balanced
   status-`2` journals are excluded from every affected daily-ledger amount;
   balance alone does not make a journal importable.
3. **Complete — reversal handling reduced to ledger preservation.** The
   accounting service does not recreate loan/savings reversal lifecycles and
   does not need to identify or pair reversals to reproduce financial reports.
   Import every independently eligible source journal—including ordinary
   opposite postings—on its own source date, accounts, sides and amounts.
   Never invoke Fineract's reversal operation for historical import and leave
   core `reversed=false` and `reversal_id=NULL`. Reversal flags, labels,
   pointers and inverse vectors are optional audit metadata only; their absence
   never quarantines or excludes an otherwise eligible journal. The cutoff is
   applied independently to each journal by `FECHA_PARTIDA`.
4. **Complete — annual-liquidation treatment approved.** Import each eligible
   type-`003`/`LIQ_ING_EGR='1'` closing journal intact on its actual December 31
   source date. Do not generate a Fineract year-end journal, import `CNT_MAYOR`
   carry-forward state, or create opening/residual entries. `acc_gl_closure` is
   only a posting-date lock and `acc_gl_journal_entry_annual_summary` is a
   product/asset-owner optimization; neither replaces these journals. Require
   immutable header provenance for source type/liquidation/opening flags.
   General ledger, balance sheet, and post-closing trial balance include the
   closures; income statement and pre-closing trial balance exclude only target
   transaction groups whose provenance identifies source type `003`. Never
   infer closure from December 31, `ref_num`, description, or `manual_entry`.
   A disagreement between type `003`, liquidation flag `1`, December 31, or the
   expected zero opening flag quarantines fail-closed with a stable reason.
5. **Complete — legacy text preservation and display handling approved.** Do
   not compact four distinct Arissto fields into Fineract's 500-character
   `description`. The Credesal provenance header stores
   `CNT_PARTIDAS.CONCEPTO` and `DESCRIPCION` separately as unrestricted text;
   each provenance line stores `CNT_DETALLE_PARTIDAS.CONCEPTO` and
   `CONCEPTO_AUX` separately. Preserve decoded Unicode verbatim, including the
   distinction between null, empty and whitespace, and store a deterministic
   SHA-256 for each field. Native `acc_gl_journal_entry.description` is only a
   500-character display projection: line concept, then header description,
   then header concept; auxiliary concept is restricted provenance only. The
   display projection uses NFC, normalized whitespace/control removal, and a
   fixed 499-character-plus-ellipsis truncation rule. The complete four legacy
   fields never appear in ordinary journal APIs, plans, status, errors or
   reconciliation logs and require a dedicated provenance permission; the
   derived display projection remains visible as the ordinary description.
6. **Complete — branch crosswalk frozen.** For source company `001`, translate
   line `ID_SUCURSAL_DESTINO='001'` to `dimensions.office="1"` and `002` to
   `dimensions.office="2"`. Values are JSON strings copied from the uniquely
   matched `m_office.external_id`, never office names or mutable labels. The
   plan freezes mapping version `fineract-office-external-id-v1`, its hash, and
   the resolved value on every line. Missing, blank, foreign-company, unknown,
   duplicate, or target-drifted mappings fail closed as
   `SOURCE_DESTINATION_BRANCH_UNMAPPED`; never fall back to the header branch
   or a fixed journal-wide `office_id`. Historical attribution may predate the
   target office opening date. Native post-cutoff journals must derive the same
   tag from their posting office's external ID so agency reports span cutover.
7. **Complete — native office, authorization, and closure policy approved.**
   Resolve every line's native `office_id` from the same destination-branch
   crosswalk: `001 -> 1`, `002 -> 2`. Keep one transaction ID and require only
   complete-journal balance; an inter-office journal may be unbalanced inside
   each office. Before writing, verify the dedicated historical-import
   permission, user access to every distinct mapped office, and that the
   journal date is strictly after each involved office's latest closure. Any
   failure rejects the complete journal atomically. Never bypass a closure and
   never use the standard one-office manual-journal request for this writer.
8. **Complete — USD and exact-cent precision approved.** Company `001` is
   non-multicurrency and its type-`1` base currency is USD. Preserve `DEBE` and
   `HABER` exactly as Arissto `NUMERIC(18,2)`: canonical plans use plain decimal
   strings with exactly two fractional digits, never binary floats. Fineract's
   `DECIMAL(19,6)` stores the same value with four trailing zeroes; it does not
   authorize sub-cent values, rounding, conversion, or recomputation. Preflight
   requires enabled target USD with two decimal places. Unexpected currency or
   scale quarantines, and any value exceeding the target's 13 integer digits
   quarantines before apply.
9. **Complete — COA-driven report presentation approved.** Persist a versioned
   Credesal presentation row per target GL account with source code/name,
   parent, classifier, order, `TIPO_SALDO`, `BC`, and `BG`; never alter journal
   amounts. `D` renders debit minus credit and `A` credit minus debit, retaining
   negative contra balances. Trial balance selects all 101 `BC=1` rollups;
   balance sheet selects the 64 `BG=1` asset/liability/equity rollups and adds
   current result as income minus expense; the 11 memorandum rows stay outside
   that equation. Income statement selects the 26 `BC=1/BG=0` result rollups
   and excludes annual-closing transaction groups by immutable provenance.
   Resolve every selected rollup from posting descendants through the parent
   graph. Populated templates `00009`, `00010`, and `00014` are audit evidence
   only: current mappings are obsolete or semantically drifted, so their labels,
   `SIGNO`, groups, and account IDs cannot drive target reports.
10. **Complete — explicit post-cutover office correction approved.** Historical
    import always preserves the source account, side, amount, and actually
    posted office. Candidate detection never authorizes a posting: even loan
    `838` lacks a physical loan-to-GL-line allocation. Accounting must approve
    an immutable manifest with exact source transactions/provenance lines,
    accounts, sides, amounts, wrong/correct offices, economic window, posting
    date, rationale,
    approver, and evidence hash. A dedicated native correction command posts on
    or after cutoff and after every involved office closure. For each approved
    source debit it credits the same account in the wrong office and debits it
    in the correct office; source credits receive the inverse. The atomic
    journal must leave every consolidated GL account and financial statement at
    exactly zero change. It never edits imported provenance, customer/product
    subledgers, accounts, amounts, or currency, and cannot use a plug, suspense,
    migration origin, direct SQL, or pre-cutoff backdate.
11. **Complete — historical origin approved.** Import every otherwise eligible
    status-`3` journal beginning with the first operating journal on 2022-11-18
    in period `00028` and ending the day before the frozen cutoff. All 29
    materialized ledger rows in the first journal-bearing period start at
    `0.00` and carry exactly into `00029`. Do not create a synthetic opening,
    residual journal, or transaction from earlier configured empty periods.

### Artifacts

- Updated `config/accounting.json` with no unresolved required selections.
- Accepted decisions in `annotations/20-decisions.md`.
- Source evidence for status `2`, report metadata, and transferred-loan office
  candidates in the exploration repo.
- Frozen cutoff and COA/dimension mapping versions and hashes.

### Exit gate

`inspect` may report unresolved source exceptions, but code/config validation
has zero unset policy fields needed to classify or map an otherwise valid
journal. Accounting `apply` remains disabled.

## G1 — complete Fineract cutoff-guard coverage (2026-09-07)

Migration `0320`, the central persistence guard, and reviewed producer
generation boundaries are delivered. Accounting-bound workflows fail closed
unless the operator has already placed the Fineract scheduler in standby.

### Work

1. Inventory every `JournalEntryRepository.save*` and equivalent direct write;
   keep all final persistence behind `JournalEntryPersistenceService`.
2. Complete authenticated migration-origin coverage for:
   - loan lifecycle edge commands and transfer side effects;
   - savings and fixed-deposit transactions, accruals, tax, and reversals;
   - shares, charges, and dividends;
   - provisioning and loan COB accruals;
   - teller, cash, vault, bank, and investor/custom producers.
3. Define all-or-nothing behavior for mixed-date batches. They must reject
   before generation until a reviewed atomic split exists.
4. Pause producing jobs during migration and prove they cannot back-post
   pre-cutoff native GL after activation.
5. Prove ordinary commands cannot select migration origin through a payload,
   header, role, or generic privileged-user mode.
6. Define and test legitimate post-go-live corrections with an economic date
   before cutoff without reopening historical migration mode.

### Exit gate

Decision-matrix and integration tests prove suppression only for authenticated
migration commands before cutoff, rejection for ordinary pre-cutoff activity,
normal native posting on/after cutoff, and defense-in-depth rejection at final
persistence.

### Completion evidence

- Loan, savings/fixed-deposit, and share transaction batches evaluate every
  accounting date before processor fan-out. Mixed pre/post-cutoff batches fail
  before generating a line; COB accruals, scheduled savings interest/tax, share
  charges, and dividends inherit those same bridges.
- Client transactions, provisioning creation/reversal, loan/share reversals,
  manual/opening journals, external-owner transfers, cashier allocation/
  settlement, vault/bank movements, and Credesal committee cash producers now
  evaluate the cutoff before their journal group is built.
- Operational provisioning and cashier migration paths retain their underlying
  business state while suppressing only the pre-cutoff native journal group.
- Every production `JournalEntry` write remains routed through
  `JournalEntryPersistenceService`; the repository inventory has no direct
  `JournalEntryRepository.save*` outside that boundary.
- Only permission-checked source-exact command handlers can establish
  `ARISSTO_OPERATIONAL_MIGRATION`; ordinary payloads, headers, roles, and
  generic privileged-user modes do not select an origin.
- Post-go-live corrections use a native posting date on or after cutoff. Their
  earlier economic date is provenance/report metadata and never reopens the
  historical posting boundary.
- Focused Gradle policy/producer/persistence tests and the complete sync-engine
  discovery suite pass. The restored-tenant, cross-service zero-native-GL proof
  remains the explicit G2/G10 acceptance step rather than being duplicated in
  G1.

## G2 — make every financial migration service cutoff-consistent

### Current implementation status — 2026-09-07

The local `activate-frozen-plan` workflows now bind every child plan to the
exact ACTIVE Fineract cutoff `configurationRevision` and
`configurationHash`. A child apply or retry fails closed if the tenant date,
timezone, lifecycle, revision, or hash differs. A stale recovery plan whose
cutoff binding differs is discarded and replanned rather than executed.

The orchestrator also runs one aggregate-only query over
`acc_gl_journal_entry` before the first service and after every reconciled
service. Any `manual_entry=false` row dated before the cutoff fails the
workflow in the `accounting-boundary` phase. This is the shared executable
zero-native-GL guard; individual service reconciliation may keep more detailed
product-specific checks.

Implementation is complete for this workflow enforcement slice. G2 remains
open until a restored clean-tenant workflow supplies live evidence for every
financial service and the remaining COA/configuration compatibility checks are
frozen where required.

### Work

1. Ensure Clients, Savings/DPFs, Native Shares, Loans, Mobile Collections, and
   any enabled cash/bank helper inherit the same frozen cutoff/config hash.
2. For each service, migrate retained operational history under authenticated
   migration context and stop before the cutoff.
3. Reconcile product/subledger state independently from GL.
4. Assert zero native non-manual journal rows before cutoff after every service.
5. Reject apply if a child plan has a different cutoff, timezone, configuration
   revision, COA version, or restored-tenant baseline.

### Exit gate

Every prerequisite service has a controlled local run with reconciled
operational state and zero native pre-cutoff GL on the same restored baseline.

## G3 — implement the read-only accounting inspector

### Current implementation status — complete (2026-09-07)

The `accounting` block is registered only for `inspect` and requires an
explicit cutoff. It bulk-loads bounded headers and lines using the complete
source keys, joins period/type/account metadata, classifies structural and
cutoff issues with stable reason codes, and emits no raw journal prose or
amounts. Source-only inspection requires no Fineract profile. Supplying a
target adds bulk COA, office, closure, and installed-provenance comparisons;
neither mode writes Arissto or Fineract. The registry remains `planned` and
`executable: false`.

### Work

1. Register the reserved `accounting` CLI block only for `inspect` initially;
   leave the service non-executable.
2. Bulk-load bounded headers, all child lines, periods, types, and account codes
   using the complete source keys.
3. Report counts before, on, and after cutoff and classify:
   - populated, empty, balanced, and unbalanced journals;
   - duplicate header/line keys;
   - zero lines or lines with both debit and credit;
   - unsupported statuses, annual liquidation, and back-period rows, recording
     the latter as non-blocking observations with period-end normalization;
   - unresolved/ambiguous accounts and agency tags;
   - blank/invalid reference numbers, dates, currencies, and precision;
   - per-line-office closure conflicts; and
   - known transferred-loan accrual office anomalies when source linkage proves
     them.
4. Avoid per-row source queries and omit free-text financial or customer data
   from summaries and logs.
5. Compare imported provenance keys/hashes when a target is selected, without
   writing either system.

### Exit gate

Repeated inspection over an unchanged bounded scope returns identical counts,
classifications, source keys, and stable reason codes. Source SQL remains
strictly read-only.

## G4 — implement deterministic planning

### Current implementation status — explicit-key and bounded-period slices complete (2026-09-07)

`plan --block accounting` accepts either one or more complete explicit journal
keys or one or more bounded source periods. It sorts and de-duplicates the requested scope, loads each bounded journal
through read-only source queries, resolves the frozen COA and per-line agency
crosswalks against a read-only target snapshot, and emits a canonical payload
with exact two-decimal strings and stable line order.

Each plan independently freezes the source schema, source content, contract,
COA mapping, agency mapping, policy/planner version, target fingerprint, target
baseline, cutoff binding, action payload, and complete plan hashes. Requested
missing, invalid, on/after-cutoff, target-drifted, and already imported keys are
represented explicitly rather than dropped. The registry remains
non-executable and no accounting writer exists.

The explicit-key determinism exit gate is satisfied by focused tests, the full
sync-engine suite, and two live read-only plans with identical hashes recorded
in `annotations/30-validation-log.md`. Bounded period planning is now enabled
for controlled month acceptance; unrestricted date/population expansion remains
gated on clean reconciliation of each preceding scope.

### Work

1. Add `plan --block accounting` for explicit journal keys first, then bounded
   date/period scopes after the canary path is accepted.
2. Normalize the complete journal and line identities and stable line order.
3. Resolve every account through the frozen COA crosswalk.
4. Translate every `ID_SUCURSAL_DESTINO` through the frozen agency crosswalk.
5. Produce one canonical journal payload containing exact date, `ref_num`, USD
   currency, per-line native offices, debit/credit lines, descriptions,
   per-line dimensions, and source provenance.
6. Hash normalized source content, mapping versions, policy versions, target
   fingerprint, cutoff configuration, and planned payload.
7. Emit explicit `APPLICABLE`, `QUARANTINED`, or `UNCHANGED` dispositions with
   stable reason codes. Never omit an in-scope journal silently.
8. Reject plan reuse after any source hash, mapping, cutoff, policy, target, or
   tenant-baseline drift.

### Exit gate

Two plans from unchanged inputs are byte-for-byte equivalent apart from
allowed run metadata and produce identical keys, hashes, lines, mappings,
totals, dimensions, and quarantine reasons.

## G5 — add versioned provenance schema (schema added 2026-09-07)

### Work

1. **Complete:** use tenant Liquibase migration `0336`; `0321` was not reused.
2. **Schema complete:** add Credesal-owned journal-header and journal-line
   provenance tables with:
   - complete source keys and unique constraints;
   - source/planned hashes and mapping/policy versions;
   - cutoff/config, plan, run, and target transaction identities;
   - source and target account identities;
   - source/target amounts, sides, dates, references, and agency tags;
   - independent `TEXT` columns for header concept, header description, line
     concept, and auxiliary line concept, plus one SHA-256 per value;
   - null/empty/whitespace fidelity and the display-policy version, display
     hash, and truncation flag;
   - result, stable failure/quarantine reason, and audit timestamps; and
   - known-anomaly flags, including transferred-loan office mismatch.
3. Make provenance immutable after a successful import except for narrowly
   defined retry/audit fields.
4. **Complete:** add indexes for source-key lookup, target transaction lookup,
   reconciliation, and operator search without duplicating the accounting
   ledger.
5. Verify clean install and upgrade paths on the supported database.

### Exit gate

Liquibase tests pass; duplicate source identities are impossible; the schema
can recover a committed journal after a lost API response without using
`ref_num` or descriptions as identity.

### Implementation

Tenant migration `0336_add_arissto_gl_journal_provenance.xml` adds
`credesal_arissto_gl_journal` and
`credesal_arissto_gl_journal_line`. The database enforces one header per
complete Arissto journal key, one line per source detail/sequence, one target
transaction per imported header, and one target journal-entry row per imported
line. Nullable target identities permit reservation before the native write;
G6 owns the narrowly defined lifecycle that freezes successful provenance and
may update only retry and reconciliation audit fields afterward.

The header stores the frozen plan, cutoff, mapping and policy versions plus
lossless header text and hashes. Each line stores exact source and target
account, amount, side, date, reference, office/dimensions, text hashes, display
projection evidence and anomaly flags. These are reconciliation facts tied to
`acc_gl_account`, `m_office`, and the native journal row, not a second ledger.
The schema contract tests and Gradle resource processing pass. G6 now enforces
the successful-row immutability boundary. G5 remains open until the same
changelog is exercised on both a clean and an upgraded supported database.

## G6 — atomic historical-journal API complete (2026-09-07)

### Current implementation status

The dedicated `POST /v1/arisstohistoricaljournals` endpoint accepts exactly one
complete journal. One Spring transaction reserves the full source identity,
creates a shared deterministic `transaction_id`, persists every native journal
line and its lossless provenance, then freezes the successful result. The
ACTIVE cutoff row is locked before the source-key lookup, serializing concurrent
duplicate submissions; an identical completed retry returns the prior target
identity without writing again, while changed or incomplete identities fail
closed.

The endpoint validates the frozen cutoff date, timezone, revision and hash;
USD precision; exact balance; source/text/binding hashes; target account state;
per-line native office and canonical `dimensions.office`; access to every
office; and every involved office closure before the first write. It establishes
`ARISSTO_HISTORICAL_GL_IMPORT` only around native journal persistence. Imported
rows are manual GL with no product, entity, payment, loan, savings, client, or
share linkage. Full legacy text is available only through the separately
permissioned provenance endpoint.

### Work

1. Add a dedicated endpoint/command for historical GL import; do not turn the
   ordinary manual-journal API into a generic cutoff bypass.
2. Require the narrowly scoped historical-import permission and authenticated
   migration execution context.
3. Accept one complete source journal with native office and dimensions on
   every debit/credit line. Resolve all offices and validate all closures and
   permissions before persisting any row.
4. In one target transaction:
   - validate cutoff, ACTIVE state, timezone/config hash, currency, accounts,
     authorization, closure policy, balance, and dimensions;
   - reserve the source key/hash;
   - create one manual journal group with a shared `transaction_id`;
   - copy exact `ref_num` and the contract-normalized effective `entry_date` to
     every line while preserving the unmodified source journal date; and
   - persist header/line provenance and returned line IDs.
5. Return the prior success for an identical key/hash retry.
6. Reject changed hashes, duplicate/conflicting keys, partial payloads,
   on/after-cutoff dates, unbalanced lines, invalid dimensions, and unauthorized
   requests without committing journal or provenance fragments.
7. Do not populate product/entity/payment foreign keys or unfinished
   `transaction_date`; imported GL must not pretend to be product-generated.

### Exit gate

Backend tests cover atomic rollback, identical retry, changed hash, concurrent
duplicate, lost response, cutoff violation, closure conflict, line-dimension
precedence, multi-agency balance, and unauthorized access.

### Completion evidence

- The focused G6 suite passes 11 tests covering every exit case plus the
  separate restricted-provenance permission.
- The complete `fineract-accounting` suite passes 20 tests.
- `fineract-provider` compiles with the endpoint, entities, repositories, and
  tenant changelog on its runtime classpath.
- The complete 469-test sync-engine suite and XML parsing pass unchanged.
- The scoped Spotless check passes for every G6-touched Java file. The
  module-wide check continues to report unrelated pre-existing formatting
  violations outside this slice.

## G7 — implement apply, retry, and status

### Current implementation status — complete (2026-09-07)

### Work

1. Add `apply --plan ... --target ...` only for plans that pass all G0-G6
   preconditions and target fingerprint checks.
2. Write journals sequentially initially; reuse connections/sessions and batch
   target reads, but preserve one-journal atomicity.
3. Store source key, plan hash, request idempotency key, target transaction ID,
   line IDs, disposition, and errors in sync state.
4. Classify failures as retryable, quarantined, or fatal without retrying a
   changed payload.
5. Add `retry --run ... --failed-only` that never resends successful journals
   as new identities.
6. Add `status --block accounting` with counts for planned, imported,
   unchanged, failed, quarantined, drifted, and reconciled journals.
7. Keep production confirmation tied to the exact target fingerprint.

### Exit gate

Interrupted and lost-response runs converge to one journal per source key;
unchanged replay creates zero target rows; failures retain actionable stable
reasons without exposing sensitive descriptions.

### Completion evidence

- Apply verifies scheduler standby, target fingerprint, production
  confirmation, contract, exact ACTIVE cutoff revision/hash, source content,
  mappings, and target baseline immediately before writing.
- One journal is posted sequentially through the G6 endpoint. Sync state keeps
  the plan/payload hashes, stable request identity, logical request run,
  transaction ID, line IDs, disposition, error class, and retryability.
- A simulated lost-response test reuses the same idempotency key and logical
  request run on `retry --failed-only` and recovers the prior target IDs.
- Local canary `001:001:00028:0000000002` imported one provenance header and
  two target lines with exact `27000.00` debit and credit totals. Reapplying the
  original plan recovered the same transaction; a new plan classified it
  `UNCHANGED` and its apply created zero rows.
- The canary uncovered detached-entity office comparison in
  `AppUser.hasAccessToOffice`; office access now compares persistent IDs, with
  a focused regression test. The rejected attempt committed no journal or
  provenance row.
- G8 direct reconciliation is implemented and passed for the three-journal
  inception period. Full pre-cutoff expansion remains the only G8 acceptance
  run; product-service reconciliation is tracked independently.

## G8 — direct-journal reconciliation implemented; acceptance pending

### Current implementation evidence — 2026-09-07

Reconciliation version `accounting-direct-journal-reconciliation-v4` joins the
immutable source header/line provenance directly to `acc_gl_journal_entry`,
`acc_gl_account`, and `m_office`. It validates complete source and target
identities, all frozen hashes, date, reference, currency, account, side, exact
amount, native office, redundant agency dimension, line/totals balance,
manual/reversal state, and absence of product links. It separately fails on
native non-manual pre-cutoff rows or imported on/after-cutoff rows and compares
agency plus consolidated balance buckets from direct journals. For the final
closed period in the plan, it also proves that the plan contains every eligible
journal from the approved inception and that cumulative journal balances match
posting-key `CNT_MAYOR.SALDO_FINAL` values. Ordinary parent/reporting ledger
rows are excluded because they repeat descendant balances. Hybrid accounts
that also receive direct annual-liquidation lines are accepted only when their
direct signed movement is zero, all immediate child mayor rows exist, and the
parent balance equals the exact child sum; otherwise reconciliation fails with
`SOURCE_HYBRID_ACCOUNT_ROLLUP_UNSAFE`. The verified `314002` control accounts
for two accepted agency rollups totaling `37,880.08` without creating an
additional journal.

The controlled period-`00028` plan contained all three inception journals and
seven lines. Local run `2bdb367e631e4b6599079c6e740b65b2` imported two and
retained one immutable prior-generation journal as unchanged. Reconciliation
matched all three journals, all seven direct balance buckets, and both cutoff
guards with zero variance. The source ledger control independently matched all
six posting account/agency buckets with zero variance. The scheduler was
restored after the run.

The G8 exit gate remains open because full direct-journal parity immediately
before cutoff has not been executed. Product-service reconciliation is a
separate migration/cutover control and does not determine historical-ledger
correctness unless it creates competing native pre-cutoff GL; that condition is
already checked directly by the accounting boundary control.

### Work

1. Reconcile each source journal to exactly one target transaction and each
   source line to exactly one target line.
2. Compare date, `ref_num`, currency, account, side, amount, native line office,
   agency tag, line count, debit total, credit total, and source/planned hash.
3. Assert no native non-manual journal before cutoff and no imported journal on
   or after cutoff.
4. Recalculate opening, period debit, period credit, and closing balances from
   `acc_gl_journal_entry` plus `acc_gl_account`; do not accept `m_trial_balance`
   or source `CNT_MAYOR*` as the primary truth.
5. Compare direct-journal results with Arissto ledger/trial-balance evidence at
   a closed month and immediately before cutoff.
6. Reconcile agency tags separately and consolidated totals together. An
   individual agency may be unbalanced because inter-agency lines exist.
7. Track loan, savings/DPF, shares, and other product reconciliation in their
   owning service gates, independently of Gate 8 journal-import identity.

### Exit gate

Every in-scope source journal has exactly one final disposition, every imported
line agrees exactly, consolidated debits equal credits, report balances match
the approved source controls, and all unexplained variances are zero.

## G9 — make native Fineract reporting dimension-aware

### Work

1. Use canonical `dimensions.office` filters/grouping as the report agency
   selector.
2. Validate that the canonical tag agrees with the mapped native office
   external ID on every imported and native line, and that per-line
   `office_id` reproduces the same source agency balances.
3. Implement direct native queries for:
   - general ledger;
   - trial balance;
   - balance sheet;
   - income statement;
   - agency variants; and
   - consolidated variants.
   Income statement and pre-closing trial balance exclude imported source
   type-`003` transaction groups by immutable provenance. General ledger,
   balance sheet, and post-closing trial balance include them.
4. Encode approved `TIPO_SALDO`, `BC`, `BG`, and `CNT_REPORTES*` presentation
   rules outside journal amounts.
5. Validate `ref_num` display/search/filter behavior in Mifos and remove or
   separate any conflicting free-form reference input.
6. Treat `m_trial_balance`, annual summary, and stretchy reports as derived
   consumers. Rebuild or fix them only after direct-journal parity is proven.

### Exit gate

For the approved test periods, each report is reproducible from native journal
rows, agency filters use `dimensions.office`, consolidated results equal the
sum of agency-tagged postings under the approved consolidation rules, and
legacy presentation differences are either matched or explicitly signed off.

### Implementation evidence (2026-09-07)

- Tenant migration `0337` creates and validates 2,482 mapped presentation
  rows from a 2,494-row read-only Arissto snapshot. It freezes 101 trial-balance
  selectors, 75 balance-sheet selectors, account nature, classifier/order,
  hierarchy, labels, version, and SHA-256 identity.
- `GET /v1/credesalfinancialreports/{reportType}` reads
  `acc_gl_journal_entry` directly for `general-ledger`, `trial-balance`,
  `balance-sheet`, and `income-statement`. Agency scope uses
  `dimensions.office`; every request fails closed if that value is missing
  or disagrees with the row's native office external ID.
- Income statement and pre-closing trial balance exclude imported type `003`
  through immutable provenance. General ledger, balance sheet, and
  post-closing trial balance include it.
- The period-`00028` live sandbox check returned all seven general-ledger
  lines. Trial balance and balance sheet returned zero debit/credit and
  accounting-equation variance in both consolidated and agency-`1` scope.
- The ordinary journal API now accepts an exact `referenceNumber` filter.
  Tenant migration `0338` adds its supporting `ref_num` index.
  Mifos displays and filters the posted journal number, shows it beside the
  technical transaction ID on detail, and no longer submits the conflicting
  free-form field from manual or frequent-posting forms.
- `./arissto-sync prove-accounting-reports --target local --from-date 2024-01-01
  --to-date 2024-12-31` independently calculates expected output from Arissto
  journals and the frozen presentation tree. It passed all 12 combinations of
  report, closing mode, and consolidated/office scope with zero findings: 101
  trial-balance, 75 balance-sheet, and 26 income-statement rows per scope.
- All 16,728 general-ledger lines matched exactly and every report measure was
  additive across offices 1 and 2. Type-`003` materially changed six
  consolidated, six office-1, and four office-2 trial-balance rows between the
  pre- and post-closing modes. This completes the journal-derived portion of
  G9; exact parity with authoritative Arissto statement output remains pending.

### Statement-output parity acceptance tests

The read-only sandbox harness and exact operator commands for these tests are
documented in [`g9-test-environment.md`](g9-test-environment.md). Its readiness,
control-trace, target-capture, and exact-comparison commands write hashed JSON
artifacts under the ignored sync-state directory.

These tests close the distinction between a report independently reconstructed
from source journals and the values actually presented by Arissto. They must
use an authoritative Arissto export or the exact production UI/report
invocation. Do not treat the obsolete or account-ID-drifted `CNT_REPORTES*`
templates as authority merely because their stored procedures remain callable.
Freeze the source report identity, parameters, period, agency scope, generation
timestamp, row labels/order, and extracted values with the evidence.

#### Readiness and gate dependencies

| Test group | Readiness | Dependency |
|---|---|---|
| December 2024 trial balance, balance sheet, and income statement | Complete on the populated sandbox | Reviewed December exports for both offices are normalized into 12 office/consolidated cases and compare exactly with the native report endpoint. G11 must reproduce the accepted hashes on two restored clean tenants. |
| `314002` annual-result trace | Ready now | Requires the December output plus the three source closing journals and `CNT_MAYOR.SALDO_FINAL`/`SALDO_FINAL_LIQ`; all are read-only evidence. |
| `2220050501` two-cent trace | Ready now | Requires journal, daily-major, monthly-major, and final statement-row comparison. No migration adjustment is authorized by the discrepancy alone. |
| January 2025 carry-forward | Complete on the populated sandbox | The read-only trace compares December `SALDO_FINAL` with January period-`00054` `SALDO_INICIAL` for every used posting/presentation account and with Fineract's journal-derived opening. A January UI export is not required and no carried balance is imported as a journal. |
| Cash-flow statement | Not ready | Arissto's discovered cash-flow template has no usable account mapping, its populated balance tables are empty, and no native Credesal cash-flow report contract exists. An authoritative export/calculation contract must be approved before implementation or parity testing. |
| Repeatability and release acceptance | Deferred to G11 | Run the complete accepted report suite in both clean migration cycles. Production remains blocked through G12. |

Open G10-G12 gates therefore do not prevent running the December diagnostic
comparisons now. They do prevent treating one populated local tenant as final
release evidence: G10 must still exercise scoped lifecycle canaries, G11 must
repeat the report suite on two restored clean tenants, and G12 controls
production enablement.

#### Test A — December 2024 authoritative statement parity

1. Capture the exact Arissto outputs for period `00053` for consolidated,
   agency `001`, and agency `002` scopes.
2. Cover balance sheet, income statement, and every available pre-/post-closing
   trial-balance view. Record whether each Arissto column uses `SALDO_FINAL` or
   `SALDO_FINAL_LIQ` rather than inferring its meaning from the report name.
3. Generate the corresponding native Fineract reports from the same date range,
   agency, currency, closing mode, and zero-row policy.
4. Compare row selection, label, order, sign, opening, debit, credit, closing,
   subtotals, current-year result, accounting equation, and grand totals at
   currency precision.
5. Require consolidated measures to equal the approved combination of the two
   agency outputs. Preserve inter-agency behavior explicitly rather than
   requiring each agency to balance independently.

Pass only when every row agrees exactly or an accounting owner signs a named,
quantified presentation difference with its durable rule. A generic tolerance
or an unexplained net-zero offset does not pass.

#### Test B — annual liquidation and account `314002`

1. Trace the three period-`00053` type-`003` journals: income close, expense
   close, and transfer of the net result to `3140020100` or `3140020200` for
   each agency.
2. Prove that pre-closing income statement and trial balance exclude precisely
   those transaction groups, while general ledger, post-closing trial balance,
   and January carry-forward include them.
3. Reconcile the journal-derived balance, `CNT_MAYOR.SALDO_FINAL`,
   `SALDO_FINAL_LIQ`, the authoritative Arissto statement row, and the native
   Fineract row. Determine whether `314002` is a materialized presentation
   result, a hierarchy rollup, or evidence of a missing posting.
4. Require the final balance-sheet equation and current-year-result row to
   match in every scope. Do not create an additional opening, closing, or
   residual journal when the difference is only derived presentation state.

#### Test C — account `2220050501` two-cent difference

1. Recompute the account/agency balance from source journal lines from the
   approved inception through period `00053`.
2. Compare it by day and period with `CNT_MAYOR_DIARIO`, `CNT_MAYOR`, the
   authoritative source statement row and ancestor rollups, and native
   Fineract journal/report rows.
3. Identify the first date where the two cents appear and classify it as a
   source posting, an explicit rounding/materialization rule, or corrupt/stale
   mayor state.
4. If a source posting exists, it must enter through the ordinary immutable
   journal contract. If no posting exists, do not synthesize one; either encode
   the proven report-rounding rule or obtain explicit accounting sign-off for
   the exact two-cent statement variance.

#### Test D — January 2025 opening continuity

1. Compare December 2024 post-closing posting-account balances with Arissto
   January 2025 `SALDO_INICIAL`, by agency and consolidated.
2. Compare those same values with Fineract opening balances calculated from
   journals strictly before January 1, 2025.
3. Verify that result accounts closed by type `003` open at zero and that the
   balance accounts receiving profit or loss carry forward exactly once.
4. Assert that no synthetic January opening journal or imported `CNT_MAYOR`
   state exists in Fineract.

#### Test E — cash-flow contract and parity

Before implementing or testing cash flow, obtain an authoritative Arissto
cash-flow output and identify its account-to-line mapping, signs, operating/
investing/financing classification, treatment of non-cash journals,
inter-agency eliminations, and opening/closing cash definition. Freeze that as
a separate versioned presentation contract, implement the native report from
direct journals, and then apply the same row-, scope-, and total-level parity
criteria above. An empty legacy table or placeholder template is not an
acceptable expected result.

#### Evidence required for acceptance

- immutable source-output artifacts or hashes plus their exact invocation;
- machine-readable row-level expected/actual differences for every scope;
- explicit traces for `314002` and `2220050501`;
- December-to-January continuity evidence;
- zero unexplained differences and no synthetic balancing postings; and
- the same accepted hashes and totals in both G11 clean cycles.

## G10 — run scoped end-to-end canaries

Run on a restored disposable tenant using explicit source journal keys:

1. an ordinary multi-line journal;
2. a journal containing both agency tags;
3. a line whose destination branch differs from its header branch;
4. a known transferred-loan accrual office anomaly;
5. a bank/cash-linked journal;
6. a loan or savings journal whose operational transaction migrated with GL
   suppressed;
7. two known opposite-posting journals, without requiring a reversal link;
8. an annual-liquidation journal;
9. a back-period journal that proves period-end normalization, plus a separate
   target-closure quarantine case;
10. status-`2`, empty, unbalanced, unresolved-account, and unmapped-agency
    quarantines;
11. an interrupted/lost-response retry and changed-hash rejection; and
12. a native Fineract transaction dated exactly on the cutoff.

### Exit gate

Eligible canaries import exactly once, invalid/undecided cases quarantine,
agency dimensions and anomaly flags reconcile, no native GL exists before
cutoff, and the cutoff-date native transaction posts exactly once.

## G11 — complete two identical clean migration cycles

1. Apply Liquibase/bootstrap and configure the cutoff on a disposable tenant.
2. Capture the whole-tenant baseline and pause accounting-producing jobs.
3. Migrate catalogs, clients, savings/DPFs, shares, loans, collections, and all
   other retained operational state under the same cutoff.
4. Prove zero native pre-cutoff GL and reconcile each product/subledger.
5. Inspect, plan, apply, retry, and reconcile all eligible historical journals
   through the day before cutoff.
6. Generate and compare every direct-journal acceptance report.
7. Review and sign every quarantine; no in-scope journal may disappear from
   counts.
8. Seal migration mode, advance to the cutoff business date, enable jobs, and
   exercise the first native transaction/accrual/provision/dividend flows.
9. Rerun unchanged plans and require zero new records.
10. Restore the same baseline and repeat the complete cycle. Require identical
    plan hashes, counts, dispositions, target journal content, and reports.

### Exit gate

Both clean cycles produce identical accepted evidence and zero unexplained
differences. Reset used whole-tenant restore and never row deletion.

## G12 — enable the service and approve production

Only after G0-G11 pass:

1. Add the final registry dependencies and CLI commands.
2. Change the registry entry to `available` and `executable: true` in the same
   reviewed change that records the controlled local run evidence.
3. Approve production source and target fingerprints, cutoff/config hash,
   frozen mappings, quarantine disposition, backup/restore plan, jobs pause and
   resume checklist, and rollback boundary.
4. Run production `inspect` and `plan` independently; never promote a local
   plan or inferred fingerprint.
5. Require the exact production fingerprint confirmation on apply.
6. Reconcile before sealing migration mode or enabling native jobs.

### Production stop conditions

- cutoff, timezone, target, COA, dimension, policy, or source hash drift;
- a new unsupported status, account, agency, currency, or line shape;
- an annual journal whose type, liquidation flag, December 31 date, or opening
  flag does not match the frozen annual-liquidation shape;
- any native pre-cutoff or imported on/after-cutoff journal;
- an unbalanced request or partial target transaction;
- duplicate source or target identity;
- unexplained report or product-subledger variance;
- unavailable backup/restore, paused-job evidence, or authorized operator; or
- any attempt to correct a known Arissto anomaly silently during import.

## Recommended implementation slices

1. **Decision slice:** complete; G0 is frozen in accounting contract version
   14.
2. **Read-only slice:** implement G3 and explicit-key G4 with no target writer.
3. **Safety slice:** finish G1-G2 while building and testing G5 independently.
4. **Atomic-write slice:** implement G6 and its backend tests.
5. **Execution slice:** implement G7-G8 for explicit-key canaries.
6. **Reporting slice:** complete G9 before expanding to a full period.
7. **Scale and release slice:** run G10-G12, expanding scope only after each
   prior canary reconciles.

The smallest useful next build is the read-only inspector for an explicit list
of journal keys plus the G0 configuration validator. It creates deterministic
evidence for the unresolved decisions without granting accounting write access.
