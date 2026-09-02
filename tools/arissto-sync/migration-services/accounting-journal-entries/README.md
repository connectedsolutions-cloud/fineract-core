# Accounting journal entries migration service

## Status

- Registry status: `planned`
- Executable: `false`
- CLI block: none
- Source identity: `(ID_EMPRESA, ID_SUCURSAL, ID_PERIODO, ID_PARTIDA)`
- Source tables: `CNT_PARTIDAS` and `CNT_DETALLE_PARTIDAS`
- Target writer: pending
- Target chart of accounts prerequisite: tenant migration `0310`

This folder is the base scaffold for a future historical general-ledger
migration service. It does not make accounting journal migration runnable and
must not be interpreted as permission to write source or target entries.

## Business scope

The eventual service will migrate reviewed Arissto general-ledger journal
headers and their balanced debit/credit lines into Fineract
`acc_gl_journal_entry`. The initial design covers source journal identity,
line grouping, account-code resolution, dates, descriptions, journal type,
module provenance, reversals, source numbering, and exact reconciliation.

It explicitly excludes:

- chart-of-accounts creation, which belongs to the versioned
  [`chart-of-accounts`](../chart-of-accounts/README.md) tenant bootstrap;
- importing `CNT_MAYOR`, `CNT_MAYOR_DIARIO`, or annual/monthly balances as new
  transactions;
- regenerating or renumbering historical Arissto journals;
- reproducing Arissto's daily/monthly/year-end close engine; and
- importing any journal whose economic effect is already represented by a
  native Fineract loan, savings, share, client, or provisioning transaction.

The detailed mapping and blockers are in [`contract.md`](contract.md). Source
meaning and evidence remain in
[`contabilidad-libro-mayor-y-partidas.md`](../../../../../../credesal-db-space/docs/learnings/contabilidad-libro-mayor-y-partidas.md#numeración-que-se-reinicia-por-período).
The Fineract-side monthly-number generator requirements are maintained in
[`FINERACT_MONTHLY_GL_JOURNAL_NUMBERING_REQUIREMENTS.md`](../../../../../docs/FINERACT_MONTHLY_GL_JOURNAL_NUMBERING_REQUIREMENTS.md).

## First implementation boundary

The smallest safe executable version should operate on a reviewed list of
source journal keys, not a full accounting period. It must:

1. extract one header and all of its lines in one bounded read;
2. prove the source journal balances exactly;
3. resolve every posting account by reviewed Arissto code to Fineract GL
   account identity;
4. classify the journal as importable, already represented natively, or
   quarantined;
5. create one grouped Fineract journal transaction only for an importable
   source journal;
6. preserve the exact Arissto `NUMERO_PARTIDA` in Fineract `ref_num`; and
7. reconcile line count, debit total, credit total, accounts, date,
   `ref_num`, and durable source-to-target identity.

No full-period plan is acceptable until this scoped path, interrupted-run
recovery, reversal handling, and an unchanged second plan pass locally.

## Preconditions

- Arissto remains strictly read-only.
- The target fingerprint is explicit and migration `0310` has installed the
  reviewed Credesal chart of accounts.
- Every source posting account resolves to exactly one target GL account.
- The product-accounting ownership matrix is complete enough to prevent double
  posting against native product migrations.
- The target write mechanism and idempotency mapping are reviewed.
- Controlled source identities are selected explicitly.

## Commands

None. Add `inspect`, `plan`, `apply`, `retry`, `reconcile`, and `status` only
after the extraction, readiness inspection, deterministic planner, writer,
reconciliation, and tests exist. Keep `executable: false` until a controlled
local run and unchanged replay succeed.

## Reconciliation and acceptance

Acceptance will require, per source journal:

- exact preservation of the full Arissto source key;
- one target transaction group and no duplicate group;
- exact normalized `ref_num` equality;
- exact entry date and currency;
- exact debit and credit line totals at Fineract precision;
- exact target-account resolution for every source line;
- explicit disposition of reversals and annual-liquidation journals;
- zero overlap with accounting already produced by native product services;
- deterministic retry after a partial failure; and
- an unchanged second plan.

## Performance and access pattern

Inspection and planning should bulk-load a bounded set of headers and all child
lines, then index them in memory by the full source journal key. Target GL
accounts, existing source mappings, and candidate native transaction links
must also be loaded in batches. Reconciliation should compare bulk snapshots,
not issue one database or API lookup per line.

Writes remain sequential initially because a journal is one atomic balanced
unit and partial debit/credit persistence is unacceptable. Reuse the source
connection, target connection or authenticated HTTP session, and normalized
account indexes for the complete phase.

## Open decisions and blockers

1. Approve the product-accounting ownership matrix and historical cutoff so
   native product accounting and imported general-ledger journals cannot both
   represent the same economic event.
2. Choose the target writer: standard manual-journal API with a durable
   source-to-generated-transaction crosswalk, or a narrowly reviewed extension
   that supports deterministic source identity.
3. Define reversal pairing and whether reversed source journals are imported
   as original-plus-reversal or represented through native reversal behavior.
4. Decide how source journal type, module, period, close, and status are
   preserved without overloading `ref_num`.
5. Define treatment of unbalanced, empty, back-period, and unresolved-account
   journals.
6. Prove that `ref_num` is queryable enough for operator lookup while the
   durable migration mapping remains the idempotency authority.
