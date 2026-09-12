# Cutoff implementation map

## Foundation delivered in migration 0320

- Tenant-local cutoff configuration with `DRAFT`, `ACTIVE`, and `SEALED`
  lifecycle states.
- Explicit `America/El_Salvador` timezone validation.
- Immutable active/sealed date semantics and audited activation/sealing users
  and timestamps.
- Deterministic configuration revision and SHA-256 hash.
- Read, draft configuration, activation, and sealing API operations.
- Central decision service for native, operational-migration, and historical-GL
  origins.
- A guarded journal persistence service used by the standard accounting helper,
  teller writes, and investor accounting helper.
- A permission-checked operational-migration execution scope used by the
  source-exact loan disbursement, repayment, component-reallocation,
  goodwill-credit, top-up, and refinancing handlers.
- All-or-nothing cutoff evaluation at the loan accounting bridge. Mixed-date
  batches reject before journal generation instead of posting a partial batch.

## Producer coverage completed on 2026-09-07

1. Explicit migration-only commands cover the reviewed loan, savings/fixed-
   deposit, and native-share lifecycle operations. A general request header or
   globally privileged user mode is not an accepted origin mechanism.
2. Loan, savings/deposit, and share accounting bridges apply all-or-nothing
   batch evaluation before processor fan-out. COB accrual, scheduled interest,
   tax, charge, and dividend rows inherit those bridges.
3. Single-date generation guards cover clients, provisioning, reversals,
   manual/opening journals, teller/cash/vault/bank helpers, committee cash
   movements, and external-owner accounting.
4. Accounting-bound workflows require an already paused Fineract scheduler
   before cutoff activation or resume, and verify zero native pre-cutoff GL
   before and after each service.

Tenant migration `0336` provides the historical journal header/line provenance
schema. G6 supplies the dedicated atomic historical-journal API with per-line
agency dimensions. G7 now supplies explicit-key apply, failed-only retry, and
status with persistent recovery identity and accepted local replay evidence.
G8 direct-journal reconciliation is the next implementation slice.

## Known direct persistence inventory

The initial repository inventory found direct journal writes in the shared
accounting helper, teller service, and investor accounting helper. All three
now route through `JournalEntryPersistenceService`. Future direct
`JournalEntryRepository.save*` additions must be treated as boundary defects.
