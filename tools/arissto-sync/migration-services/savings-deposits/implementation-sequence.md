# Native savings implementation sequence

## Outcome and quality bar

The completed service must cover the 38 `VISTA` accounts and 119 current
master `PLAZO` accounts with exact financial reconciliation. Eligible funded
positions migrate into native Fineract deposit lifecycles; reviewed
zero-principal submitted/unfunded placeholders remain quarantined rather than
becoming artificial positions. A result is unacceptable if it only matches ending
balances, duplicates accrued interest, taxes an historically untaxed event,
duplicates the joint DPF, or requires direct writes to native financial tables.

## Phase 1 — schema and static contract

1. Apply migrations 0288 and 0290 through normal local Fineract startup.
2. Verify the account/owner/event and product-crosswalk extension tables, FKs,
   unique constraints, and indexes.
3. Load and validate `config/savings_deposits.json`.
4. Keep the registry service non-executable until the full acceptance gate is
   proven; promote it to `available` only after the final empty-write plan.

Exit: migration is idempotent and the contract rejects unknown types, states,
movement roles, unsafe identifiers, and missing cutoff decisions.

## Phase 2 — read-only inspection

1. Bulk-read product lines, accounts, owners, clients, movements, type-1/type-2
   history, latest daily state, retained provisions, and accounting references.
2. Build canonical identities and account-local chronological event streams.
3. Verify the known population and expose changes without PII.
4. Bulk-inspect target clients, products, accounts, migration tables, tax
   groups, GL accounts, permissions, backdating settings, and closed periods.
5. Report blockers separately for product, account, ownership, movement,
   interest, tax, cutoff, and accounting layers.

Exit: inspection performs bounded queries, reports every known ambiguity, and
has zero financial side effects.

## Phase 3 — approved native products

1. Approve one VISTA product contract and the required fixed-deposit product
   contracts derived from reviewed Arissto lines.
2. Map source GL roles to target IDs.
3. Approve tax-group behavior and account-level applicability.
4. Create/update products through APIs with stable external IDs.
5. Re-inspect and freeze product hashes in the plan.

Exit: product calculations and accounting configuration are reproducible and
no account is attached to an approximate product.

## Phase 4 — controlled lifecycle proof

The representative matrix passed locally on 2026-08-28, covering:

- **Passed 2026-08-27:** active VISTA with deposits, withdrawals, quarterly
  interest, and ISR. The controlled account reconciled 25 native transactions,
  ending balance 972.70, and balanced journals;
- active monthly DPF transferring interest to VISTA;
- at-maturity DPF with exact native cutoff;
- closed DPF with source-authoritative cancellation;
- reversed opening/correction audit no-op;
- four native renewal cycles ending in maturity; and
- the joint DPF with two preserved owners and one native owner.

Replay into a clean local target, run native interest/accrual/transfer jobs, and
compare every transaction, balance, tax result, cutoff provision, and journal.
If standard commands cannot represent a verified source event, stop and define
a narrow Fineract migration command that invokes domain/accounting services.

Exit: achieved. Financial events, balances, transfers, tax, lifecycle status,
and journals reconcile. A post-posting cutoff calculation difference remains a
reported diagnostic while the exact source cutoff is preserved as
non-transactional migration state.

## Phase 5 — deterministic planning and writer

1. Plan VISTA accounts before linked DPFs.
2. Make plans target-specific and include source, contract, schema, product,
   cutoff, and accounting hashes.
3. Apply sequentially per account and chronologically per event.
4. Persist account/owner provenance and each native event map immediately after
   the corresponding native command succeeds.
5. Recover interrupted creates by external ID and event map without duplication.
6. Quarantine account-atomically.

Exit: retry is safe after every command boundary and a second plan is empty.

## Phase 6 — reconciliation and release

1. Reconcile each account at identity, transaction, balance, interest/tax, and
   accounting layers.
2. Reconcile institution totals without joint-owner duplication.
3. Run the complete local population and repeat from a clean target.
4. Test source and target drift, partial failure, closed periods, backdating,
   missing destinations, and unknown movements.
5. Change registry status only after controlled local acceptance.

Exit: local reruns are idempotent, all expected records reconcile, and every
excluded/quarantined item has a stable non-sensitive reason.

## Immediate next work

Completed on 2026-08-26: migrations 0288 and 0290 were applied and inspected locally; the
configuration validator, canonical identity/event builder, and aggregate
read-only inspection are active; the one joint DPF now has a deterministic,
validated primary-owner rule.

Next:

1. **Completed:** inspection freezes the latest completed `CIERRE_DIARIO`,
   verifies a unique daily row per account, and selects
   `AHO_HISTORICO_DIARIO.INTERESES_PROVISIONADOS` for both retained cutoff
   amounts. Native replay reconstructs unrounded calculation precision.
2. **Completed for VISTA:** native Actual/Actual calculation and value `1` API support are implemented
   with focused tests. The product contracts and their exact
   API/product/account linkage are enforced by `config/savings_deposits.json`.
   Local inspection reports the effective basis on both products and accounts.
   The VISTA lifecycle and both DPF cutoff strategies passed.
3. **Completed:** all 19 line-specific source GL codes and the six established
   Fineract shared roles resolve to enabled, correctly classified target
   accounts in inspection.
4. **Completed:** historical ISR classification is inspection-enforced and the
   local Fineract fork exposes an explicit linked-VISTA type-18 command using
   native tax groups, transaction tax details, balance processing, journals,
   reversal, permissioning, reference recovery, and account locking. Migration
   0292 and the controlled tax lifecycle passed locally on 2026-08-26, including
   both retry paths and reversal journals. Complete the remaining controlled
   lifecycle proof for enum value `9`, linked VISTA transfer, cutoff accrual,
   DPF maturity, and their reversals/journals before exposing planning or
   writes. VISTA's own Actual/Actual/posting/ISR path is complete.
5. **Completed:** exact historical VISTA capitalizations use native type-3
   `explicitInterestPosting`, while future accrual remains calculator-driven.
   Migration 0299 supplies the command permission. The local canary proved
   source references survive later recalculation and that all journals balance.
6. **Completed:** DPF native replay covers linked gross transfers, linked-VISTA
   ISR, renewal chains, maturity, source-authoritative cancellation, correction
   no-ops, joint ownership, cutoff snapshots, durable account/owner/cycle/event
   provenance, and balanced journals.
7. **Completed:** the general deterministic planner is exposed through the
   normal CLI. Population-level extraction
   now also models generic-labelled legacy DPF funding, three submitted/unfunded
   applications, one adjacent-day DPF funding event, linked-DPF VISTA credits
   and ISR without double posting, and the single VISTA withdrawal reversal.
8. **Completed:** the general writer, retry, and reconciler are available. DPF principal funding is
   independent of the linked VISTA for 115 of 119 accounts, so migration 0302
   and native `migrationLink` attach the active same-client VISTA after direct
   DPF activation without inventing a principal transfer.

Local acceptance completed on 2026-08-29. All 157 source accounts were covered:
155 eligible accounts reconciled, 2 zero-principal submitted/unfunded
placeholders were reviewed and quarantined, and the final second plan contained
no create or update actions. The registry service is now `available`.
