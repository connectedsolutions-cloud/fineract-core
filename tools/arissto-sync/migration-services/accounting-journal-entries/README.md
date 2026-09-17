# Accounting journal entries migration service

## Status

- Registry status: `available`
- Executable: `true`
- Category: `accounting`
- CLI block: `accounting` (`inspect`, explicit-key `plan`, `apply`, `retry`, `reconcile`, and `status`)
- Source identity: `(ID_EMPRESA, ID_SUCURSAL, ID_PERIODO, ID_PARTIDA)`
- Source tables: `CNT_PARTIDAS` and `CNT_DETALLE_PARTIDAS`
- Target writer: dedicated atomic Fineract historical-journal API; G6-G7 complete
- Target chart of accounts prerequisite: tenant migration `0310`
- Target cutoff guard schema: tenant migration `0320`
- Target provenance schema: tenant migration `0336`
- Target report-presentation schema: tenant migration `0337`
- Target journal-number lookup index: tenant migration `0338`

G3-G10 are complete. Source-backed journal, quarantine, retry, drift, dimension,
and cutoff-date canaries have passed and are recorded in
[`g10-canary-results.md`](g10-canary-results.md). The service is available for
reviewed local workflows. Gate 11 clean-cycle reproduction and Gate 12 remain
production-promotion requirements. The dashboard defaults to the complete
bounded pre-cutoff ledger; an explicit source period can narrow a test when
needed.

Create a read-only explicit-key plan with:

```bash
./arissto-sync plan --block accounting --target local \
  --source-key COMPANY:BRANCH:PERIOD:JOURNAL \
  --cutoff-date YYYY-MM-DD
```

Repeat `--source-key` to plan a reviewed list, or use a reviewed `--period`.
Plans freeze independent hashes
for source content, the COA and agency crosswalks, policy, source schema, target
baseline, target fingerprint, and cutoff configuration. Every requested key is
emitted as `APPLICABLE`, `QUARANTINED`, or `UNCHANGED`; none is silently
omitted.

Re-run the accepted local Gate 10 matrix against its isolated sandbox state:

```bash
ARISSTO_SYNC_STATE=.arissto-sync/g10-2026-09-10/state.sqlite3 \
  ./arissto-sync prove-accounting-g10 --target local --cutoff-date 2026-09-10
```

This service is the historical accounting boundary for the sync engine. It
imports every eligible Arissto journal dated before the approved cutoff,
preserves provenance, and reconciles the resulting GL. Other migration services
create the complete retained historical operational state with native Fineract
GL suppressed. Native Fineract workflows become the sole accounting owner on
the cutoff date.

## Full re-sync

Accounting full re-sync preserves the original accepted cutoff. New eligible
pre-cutoff journals are imported atomically, exact source hashes are unchanged
and produce no write, and changed hashes for an already imported immutable
journal quarantine as drift. Source absence never deletes native journal rows.
The checkpoint advances only after direct-journal reconciliation succeeds.

## Business scope

The eventual service will migrate reviewed Arissto general-ledger journal
headers and their balanced debit/credit lines into Fineract
`acc_gl_journal_entry`. The initial design covers source journal identity,
line grouping, account-code resolution, dates, descriptions, journal type,
module provenance, reversals, source numbering, and exact reconciliation.

The four legacy text values are not compacted into Fineract's native
500-character description. Header concept and description are separate columns
in the Credesal provenance header; line concept and auxiliary concept are
separate columns in each provenance line. The native description is only a
deterministic display projection. Tenant migration `0336` implements the
versioned provenance tables. G6 implements their atomic writer and a separately
permissioned lossless provenance read endpoint.

Historical agency attribution is also line-specific. For source company `001`,
destination branch `001` maps to JSON string `dimensions.office="1"` and `002`
maps to `"2"`; these are the corresponding unique `m_office.external_id`
values, not office labels. The same crosswalk sets native `office_id` 1 or 2 on
each line. Unknown values quarantine without falling back to the journal-header
branch or one fixed import office.

The first import version is USD-only and retains Arissto's exact two-decimal
posting values. `DEBE` and `HABER` are source `NUMERIC(18,2)`; canonical plans
keep two fractional digits without binary floats, rounding, conversion, or
recomputation. Fineract's `DECIMAL(19,6)` column stores the same cents with four
trailing zeroes and is not permission to create sub-cent historical amounts.

Financial reports are reconstructed from native journals plus the versioned
`arissto-coa-presentation-v1` account metadata snapshot. It preserves source
`TIPO_SALDO`, `BC`, `BG`, classifier/order, hierarchy, and labels without
changing ledger amounts. The populated legacy `CNT_REPORTES*` templates are
retained only as hashed audit evidence because their account IDs have drifted
and no longer describe their labels reliably.

Known transferred-loan accrual office anomalies are never repaired during
historical import. A correction requires an accounting-approved exact manifest
and becomes a separate native post-cutover cross-office journal. It moves each
approved account/amount between offices while requiring `0.00` consolidated
change per account; the original journal and product subledger stay immutable.

It explicitly excludes:

- chart-of-accounts creation, which belongs to the versioned
  [`chart-of-accounts`](../chart-of-accounts/README.md) tenant bootstrap;
- importing `CNT_MAYOR`, `CNT_MAYOR_DIARIO`, or annual/monthly balances as new
  transactions;
- regenerating or renumbering historical Arissto journals;
- reproducing Arissto's daily/monthly/year-end close engine; and
- journal-by-journal product-ownership classification or decomposition.

The approved operating direction is a strict date boundary: pre-cutoff GL comes
from imported Arissto journals; accounting dated on or after cutoff comes from
native Fineract. Structurally invalid, unbalanced, unsupported-status or
unmapped historical journals quarantine instead of posting.

The detailed mapping and blockers are in [`contract.md`](contract.md). Source
meaning and evidence remain in
[`contabilidad-libro-mayor-y-partidas.md`](../../../../../../credesal-db-space/docs/learnings/contabilidad-libro-mayor-y-partidas.md#numeración-que-se-reinicia-por-período).
The Fineract-side monthly-number generator requirements are maintained in
[`FINERACT_MONTHLY_GL_JOURNAL_NUMBERING_REQUIREMENTS.md`](../../../../../docs/FINERACT_MONTHLY_GL_JOURNAL_NUMBERING_REQUIREMENTS.md).
The native-accounting cutoff guard is specified in
[`FINERACT_PRE_CUTOFF_NATIVE_ACCOUNTING_GUARD.md`](../../../../../docs/FINERACT_PRE_CUTOFF_NATIVE_ACCOUNTING_GUARD.md).
The staged delivery and clean-tenant test sequence are in
[`implementation-sequence.md`](implementation-sequence.md).
The runnable read-only G9 statement comparison environment is in
[`g9-test-environment.md`](g9-test-environment.md).
Ordered implementation notes and validation evidence are indexed under
[`annotations/00-index.md`](annotations/00-index.md).

## Cutoff decision

Every plan carries one frozen cutoff date in `America/El_Salvador`. By default,
the engine resolves it to the calendar date on which the sync plan is created.
Operators may provide `--cutoff-date YYYY-MM-DD`; apply, retry, reconciliation,
and workflow child plans continue using the frozen plan value rather than
recomputing the date.

For local workflows that activate the accounting boundary, every child plan
also freezes the exact ACTIVE tenant cutoff revision and hash. The orchestrator
verifies that binding before and after each child apply and requires zero
non-manual Fineract journal rows dated before the cutoff before any reconciled
service can be marked complete.

Nightly test cycles may therefore advance the cutoff by creating a new plan
against a newly restored disposable tenant. They must not change the cutoff of
an existing plan or an `ACTIVE` tenant. Production instead receives one
reviewed permanent cutoff during release approval.

- Source journals strictly before the cutoff are historical import candidates.
- Fineract owns scheduled accruals, provisions, dividends, and native product
  accounting on and after the cutoff.
- A journal on or after the cutoff is outside historical import scope.
- Opening balances are reconciliation controls or explicitly measured residual
  entries. They must not duplicate balances already produced by imported
  history or native Fineract transactions.

The concrete override remains unset in
[`../../config/accounting.json`](../../config/accounting.json). Its declared
default is `sync_run_date`, frozen at plan creation. Before financial apply, the
tenant's active Fineract cutoff must match that frozen plan value.

## Automatic Fineract accounting boundary

The Fineract cutoff guard must cover these accounting producers before a full
plan is applicable:

| Fineract producer | Expected automatic effect | Required cutoff behavior |
|---|---|---|
| Native loan transactions | Disbursement, repayment, charges, write-off/charge-off, reversal and related GL | Suppress under authenticated migration context before cutoff; post normally on/after cutoff |
| Loan periodic accrual | Interest/fee/penalty accrual through Loan COB or jobs | Jobs paused during migration; reject pre-cutoff output after activation |
| Loan-loss provisioning | Provision creation and prior-provision reversal | Preserve operational state but suppress the complete historical journal group; require the scheduler boundary |
| Savings and fixed-deposit accounting | Transactions, interest, charges, tax and reversals | Suppress migration-native GL before cutoff; post on/after cutoff |
| Native shares | Purchases, redemptions, charges and dividends | Suppress migration-native GL before cutoff; post on/after cutoff |
| Mobile collections | Native loan repayment GL | Inherit the loan cutoff decision |
| Client charges and payments | Client-level cash/income journal pairs | Evaluate the transaction date before processor fan-out |
| Teller, vault, bank, and committee cash | Cash allocation, settlement, funding, and clearing journal pairs | Evaluate once before the atomic journal group; never suppress the underlying operational cash state |
| External asset-owner transfers | Investor sale/buyback journal and ownership mappings | Evaluate before journal or companion mapping creation |

For workflows that activate the accounting boundary, scheduler standby is a
fail-closed prerequisite. The workflow does not silently change tenant-wide
scheduler state; an operator pauses it explicitly, and each workflow start or
resume verifies that it remains paused.

## First implementation boundary

The smallest safe executable version should operate on a reviewed list of
source journal keys, not a full accounting period. It must:

1. extract one header and all of its lines in one bounded read;
2. prove the source journal balances exactly;
3. resolve every posting account by reviewed Arissto code to Fineract GL
   account identity;
4. classify the journal as importable or quarantined by integrity/mapping;
5. create one grouped Fineract journal transaction for an importable source
   journal;
6. translate each line's `ID_SUCURSAL_DESTINO` into the approved Fineract
   agency dimension tag;
7. preserve the exact Arissto `NUMERO_PARTIDA` in Fineract `ref_num`; and
8. reconcile line count, debit total, credit total, accounts, agency tags, date,
   `ref_num`, and durable source-to-target identity.

No full-period plan is acceptable until this scoped path, interrupted-run
recovery, opposite-posting preservation, cutoff-guard proof, and an unchanged second plan
pass locally from a restored disposable-tenant baseline.

## Preconditions

- Arissto remains strictly read-only.
- The target fingerprint is explicit and migration `0310` has installed the
  reviewed Credesal chart of accounts.
- Every source posting account resolves to exactly one target GL account.
- The cutoff guard proves zero native pre-cutoff GL for every enabled financial
  migration service.
- The plan cutoff equals the reviewed cutoff and every dependent native service
  reconciled on the same restored target baseline.
- Automatic accounting job configuration is captured before apply and remains
  unchanged through reconciliation.
- The target write mechanism and idempotency mapping are reviewed.
- Controlled source identities are selected explicitly.

## Commands

Read-only source inspection, with an optional read-only target comparison:

```bash
./arissto-sync inspect --block accounting --cutoff-date YYYY-MM-DD
./arissto-sync inspect --target local --block accounting --cutoff-date YYYY-MM-DD
./arissto-sync inspect --block accounting --cutoff-date YYYY-MM-DD \
  --source-key COMPANY:BRANCH:PERIOD:JOURNAL
./arissto-sync plan --block accounting --target local --period PERIOD \
  --cutoff-date YYYY-MM-DD
```

The cutoff is explicit so repeated runs do not silently change scope. The
inspector loads the complete selected scope, records the actual header and line
counts, hashes raw legacy text without emitting it, and reports only structural
keys, counts, hashes, and stable reason codes. Gate 8 adds direct-journal `reconcile` for applied
explicit-key or bounded-period runs, plus a posting-key closing comparison to
`CNT_MAYOR` for the final closed period. The local full-sync workflow may use
the bounded full-company loader for sandbox acceptance; standalone operator
runs continue to require explicit keys or periods.

The closing comparison detects accounts that are both parents and direct
annual-liquidation posting targets. It accepts their `CNT_MAYOR` difference
only when direct annual activity nets to zero and the parent balance is exactly
recreated from complete child mayor rows. Accepted rollups are measured in
`accepted_hybrid_rollup_count` and `accepted_hybrid_rollup_variance`; they are
never imported as balancing journals. Any unproven hybrid shape fails closed.

Apply an accepted explicit-key plan while the tenant scheduler is paused:

```bash
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync retry --run RUN_ID --failed-only --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync status --block accounting --target local
```

The configured Fineract API user must be explicitly assigned to every office
referenced by the frozen agency mapping. Inspection reports the assigned,
required, and missing office IDs and blocks readiness with
`TARGET_API_USER_OFFICE_ACCESS_INCOMPLETE` before any journal write. A runtime
`office.unauthorized` response is fatal because it indicates target access
configuration, not a source journal that may be quarantined. The disposable
tenant baseline should therefore retain the same multi-office assignment.

Apply fails closed when the scheduler is active or when the target fingerprint,
contract, cutoff revision/hash, source content, mappings, or target bindings no
longer match the frozen plan. Production additionally requires the exact target
fingerprint through `--confirm-production`.

## Repeatable full-test reset

The accounting block must never implement a row-level GL wipe. Native financial
operations fan out into product transactions, schedules, accrual state,
provisioning history, journal lines and running balances; deleting only
`acc_gl_journal_entry` would leave an invalid tenant.

Full test cycles use a disposable local tenant and the whole-database
snapshot/restore workflow in
[`TEST_TENANT_RESET.md`](../../../../docs/TEST_TENANT_RESET.md). The baseline is
captured after Liquibase and intentional bootstrap configuration but before
any migration cycle. Reset restores both native and direct accounting effects,
and archives the matching local sync-state file. Production never exposes a
reset or wipe operation.

## Reconciliation and acceptance

Acceptance will require, per source journal:

- exact preservation of the full Arissto source key;
- one target transaction group and no duplicate group;
- exact normalized `ref_num` equality;
- exact entry date and currency;
- exact debit and credit line totals at Fineract precision;
- exact target-account resolution for every source line;
- ordinary preservation of opposite postings; intact inclusion of annual
  liquidation in GL/balance-sheet/post-close views; and provenance-driven
  exclusion of type `003` from income-statement/pre-close views;
- zero native non-manual journal entries before cutoff;
- deterministic retry after a partial failure; and
- an unchanged second plan.

## Performance and access pattern

Inspection and planning should bulk-load a bounded set of headers and all child
lines, then index them in memory by the full source journal key. Target GL
accounts, existing source mappings, and candidate native transaction links
must also be loaded in batches. Reconciliation should compare bulk snapshots,
not issue one database or API lookup per line.

The final source-ledger control uses separate indexed reads for the control
period summary, journal closing buckets, and `CNT_MAYOR` rows, then compares
those bounded results in memory. This is semantically equivalent to the prior
single CTE control without forcing SQL Server to repeatedly expand the same
eligible-journal CTE.

Inspection also requires the final eligible source accounting period to end
strictly before the cutoff. A mid-period cutoff reports
`SOURCE_LEDGER_CONTROL_PERIOD_NOT_CLOSED_BEFORE_CUTOFF`; operators must select
an approved period boundary rather than weakening the closing-balance control.

Writes remain sequential initially because a journal is one atomic balanced
unit and partial debit/credit persistence is unacceptable. Reuse the source
connection, target connection or authenticated HTTP session, and normalized
account indexes for the complete phase.

## Open decisions and blockers

1. Set the concrete historical cutoff after proving the first automatic-job
   boundary on a restored tenant.
2. Implement the reviewed journal API extension against migration `0336` so
   journal creation and source-identity reservation are one atomic action.
3. Decide how source journal type, module, period, close, and status are
   preserved without overloading `ref_num`.
4. Resolve any future unresolved-account journals. Back-period dates are now a
   non-blocking observation: the engine posts them on the final calendar day of
   `CNT_PERIODO.ANIO/MES` and retains the original `FECHA_PARTIDA` in provenance.
   Empty and unbalanced journals still quarantine under the frozen
   status/integrity policy.
5. Prove that `ref_num` is queryable enough for operator lookup while the
   durable migration mapping remains the idempotency authority.
6. Complete cutoff-guard coverage for loan accrual, loan-loss provisioning,
   savings/DPF accrual, share dividends, cash, bank and vault helpers.
