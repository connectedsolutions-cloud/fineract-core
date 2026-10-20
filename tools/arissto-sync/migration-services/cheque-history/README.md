# Historical cheques

## Status

- Registry status: `testing`; `executable: true` for controlled local acceptance
- CLI block: `cheque-history` with read-only inspect, reviewed plan, guarded
  apply, and reconciliation
- Source identities: `(issued, ID_LIBRO_BANCO)` and `(received, ID_REF_CHEQUE)`
- Sources: `dbo.BNC_LIBRO_BANCO` and `dbo.CJA_REF_CHEQUE`
- Target: Liquibase `0397` creates the small Fineract cheque lookup and link
  tables; a read-only `/v1/cheques/history` API and Mifos Treasury view are
  implemented in the current checkout but not locally accepted yet

## Business scope

Import basic number, bank, amount, date and direction for both issued bank
cheques and received third-party cheques, plus their verified relationships
to movements. A later scan on 2026-10-09 found 852 issued and 49 received
records; those counts are a dated reference, not a frozen plan count. Arissto
IDs are hidden reconciliation keys. The lookup must never post GL, create a
live treasury movement, or change a treasury balance. The GL importer
separately enriches Informe Auxiliar de Mayor with the journal-level
`No. Cheque` reference.

Delivery, collection, rejection, clearing and outstanding status are outside
this block. The source fields do not establish those states reliably. An issued
cheque's explicit `ANULADO` flag is separate from those excluded states.

See [contract.md](contract.md) for the field, identity, exception and
reconciliation rules. The [project requirement](../../../../../docs/ARISSTO_CHEQUE_HISTORY_SCOPE.md)
owns the cross-stack scope. The [Arissto source note](../../../../../../credesal-db-space/docs/learnings/cheques-arissto.md)
owns source evidence.

## Commands and activation gate

```bash
./arissto-sync cheque-history inspect --target local --source-through-date YYYY-MM-DD
./arissto-sync cheque-history plan --target local --source-through-date YYYY-MM-DD
./arissto-sync cheque-history apply --plan PLAN_ID --target local
./arissto-sync cheque-history reconcile --run RUN_ID --target local
```

The required `--source-through-date` is the inclusive last Arissto-owned day.
Fineract starts the following calendar day. Issued cheques are scoped by bank
movement date, and received cheques by their creation timestamp; the received
instrument date remains the displayed cheque date. The code reads the eligible
cheque facts in one observed Arissto snapshot. A new source row is a new insert
on a later plan; a changed existing source fact fails
closed for review. Target link resolution can advance from unresolved to an
exact imported GL, loan or savings transaction without changing the cheque
fact. The plan freezes source and target hashes. Apply requires the same
fingerprints and a source/target re-read. Production requires the exact target
fingerprint confirmation. No user-visible Arissto ID, GL posting, live treasury
movement or balance change is produced.

This block is executable only against the local target during acceptance.
The full fresh/clean and carry-forward workflows include it with an explicit
`testing` warning, after accounting and its product-transaction prerequisites.
Before promoting it to `available`, verify the tenant migration, the read API
and Mifos search/detail/export, exact source and target relationship counts,
and an idempotent controlled local second plan. The dedicated metadata tables are the only controlled SQL write
targets for this block.
