# Loan accrual controls at handoff

The eight monetary targets and accrual controls are separate. Loan migration
must preserve both ordinary-interest and mora paused/running state, effective
dates and source identity. An amount correction never substitutes for a pause,
and a pause never waives existing debt.

## Source mapping and existing methods

The [source metric/control inventory](../../../../../../credesal-db-space/docs/learnings/loan-historical-adjustment-events.md#accrual-control-states)
owns Arissto evidence. The verified source feed is loan type-4 restriction
history in `AFI_BLOQUEO_CUENTA`; it pauses/resumes both ordinary interest and
mora. The approved sync scope treats ordinary interest and mora together. Separate
component control APIs are inventoried for clarity, not selected for Arissto
imports. Independent agreement feeds have not been established. Do not map type-2 restrictions, zero accrual, zero interest or an
edited interest date to one of those controls without further source evidence.

| Scope | Native method | Sync ownership / remaining limit |
| --- | --- | --- |
| Verified general source freeze of both | `sourceExactFreezeHistory`, ordered source IDs/dates and `blocked` states | Existing local extractor, frozen lifecycle, migration handler and read-back import both freeze and unfreeze. Ongoing freeze stays ongoing at `T`; no invented resume date. Active unclosed source-exact loans only; conflicting/terminal histories retain their guards. |
| Independent mora only | `freezeMora`, `unfreezeMora`; `/mora-freeze` read | Native controls exist. No independent Arissto source mapping or source-identity import is claimed by this change. These public commands do not reprocess historical amounts or reverse GL. |
| Independent ordinary interest only | `/interest-pauses` create/read/update/delete | Finite inclusive intervals for eligible loans; Credesal start must follow business date. Resumes after inclusive end. Historical/ongoing independent import requires a reviewed source feed and a migration method; public create is not a historical importer. |

Definitive method behavior: [general source-history service](../../../../fineract-provider/src/main/java/org/apache/fineract/portfolio/loanaccount/service/SourceExactFreezeHistoryService.java),
[mora-only service](../../../../fineract-loan/src/main/java/org/apache/fineract/portfolio/loanaccount/service/LoanMoraFreezeWritePlatformServiceImpl.java),
[interest-pause service](../../../../fineract-loan/src/main/java/org/apache/fineract/portfolio/interestpauses/service/InterestPauseWritePlatformServiceImpl.java).
This increment connects the existing local general history importer to the
final control check. Other local mora/interest control work remains separate;
this document does not claim production deployment.

## Current loans pipeline

1. Read ordered type-4 events through **Arissto through** `S`. Use the dated
   `CRD_HISTORICO_DIARIO.CRD_CONGELADO` flag as a consistency control, not today's
   mutable header. Saved snapshots are read at the plan's observation time;
   COB closure status is informational.
2. Validate alternating freeze/unfreeze events, source ordering, dates through
   `S`, and consistency with the dated flag. A frozen flag without its history
   is quarantined, as is a flag/history conflict. Null with no restriction
   history is the observed source representation of no general freeze.
3. Freeze `lifecycle.accrual_controls`: `ordinaryInterestPaused`, `moraPaused`,
   `sourceDay`, `fineractStarts`, source scope and source event IDs. The existing
   `source_freeze_events` descriptor carries the dated transitions. New plans
   include `accrual_control_revision=1`; older plans must be regenerated.
4. Complete historical replay/catch-up using the existing lifecycle order;
   install the verified source whole-loan history through
   `sourceExactFreezeHistory`. This imports control history without creating a
   financial transaction. Its handler uses the permission-controlled operational
   migration context. Already equal history is a no-op; conflicting target
   history is not overwritten. Existing scoped freeze canaries are linked below.
5. After all loan workers and dependency operations finish, recheck/import the
   frozen source history (covering retained loans as well), then verify effective
   native controls at **Fineract starts** `T = S + 1`. Read freeze history and
   ordinary interest-pause ranges. Check both effective component states,
   including any independent native mora or interest control, plus the persisted
   whole-loan `isFrozen` flag. An unexpected active independent pause cannot
   silently pass as a running source loan. Control checks perform reads only.
6. Only then run the [final eight-metric correction](loan-metric-final-alignment.md).
   A control failure marks that loan failed before the final amount write.
   Monetary equality cannot hide incorrect pause state. The normal reconciliation
   command independently repeats the state check and compares imported history.

A closed historical pause ending through `S` resumes at its real date. An
ongoing source freeze has no synthetic end at handoff. General freeze and
independent component controls are distinct; lifting a mora-only restriction
cannot override an ongoing general freeze. A later history mutation requires
another final control check and amount pass.

## Verification and limits — 2026-10-26

- Eight new Python tests cover freeze/resume planning, missing/conflicting source
  history, invalid chronology, actual importer invocation and read-back, both
  effective states, unexpected independent native controls, and inclusive
  interest-pause end dates. With existing loan/metric tests: 244 passed. The focused staged integration,
  excluding unrelated local mora/interest work, independently passed 228 tests.
  Backend `:fineract-provider:compileJava` also passed.
- Read-only source check, **Arissto through 2026-10-19; Fineract starts
  2026-10-20**: source 1572 has four events and both controls running; source
  1826 has one event and both controls paused. Dated flags agree.
- Previous native freeze-history/COB evidence for these source shapes is in
  [component-alignment-canary.md](component-alignment-canary.md). Its later
  interest-trajectory limitations remain; they are not evidence of source/native
  formula equivalence or a reason to infer additional pauses.
- The existing general-history API/handler is included with this integration;
  no Mifos control behavior changed. Existing
  UI control/read paths remain their respective scopes; no ordinary balance-edit
  control was added. No live mutation, tenant reset or composed workflow was run.
- The user confirmed that interest and mora are handled together. Independent
  component import is outside this sync scope; no separate source feed is needed
  to import the verified general freeze history.

Code: [control planner/reader](../../arissto_sync/loan_accrual_controls.py),
[loans coordinator](../../arissto_sync/loans.py), and
[tests](../../tests/test_loan_accrual_controls.py).
