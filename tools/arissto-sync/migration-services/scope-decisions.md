# Migration scope decisions

This register is the central index of reviewed decisions to exclude, defer, or
retire Arissto source scope from the Fineract migration. It records migration
decisions only; source-table meaning and evidence remain in
`credesal-db-space/docs/`.

A decision here does not authorize deleting source or target data. Deferred
scope remains available in read-only Arissto and must be reconsidered when its
review trigger occurs. Service contracts should link to the applicable decision
ID and retain any implementation details needed to enforce the boundary.

## Decision index

| ID | Status | Source scope | Decision | Owning service | Review trigger |
|---|---|---|---|---|---|
| `SCOPE-001` | Deferred | Standalone `dbo.CRD_SOLICITUD_CREDITO` rows without `dbo.CRD_CARTERA`, including their non-originated guarantor rows | Do not synchronize for now. The loans service may still read application fields required to construct an originated loan. | `loans`; future application-history service if approved | A business, regulatory, audit, or operational requirement to retain rejected, withdrawn, or otherwise non-originated application history in Fineract |
| `SCOPE-002` | Excluded | Empty `dbo.CRD_BURO_SOCIO_CREDITO` loan-to-credit-bureau associations and the otherwise unreferenced `dbo.CRD_BURO_CREDITO` provider catalog | Do not synchronize. The association table has no records, so there is no loan-level bureau evidence to preserve and no migration use for the two provider catalog rows. | `loans`; future credit-bureau or application-history service if approved | `dbo.CRD_BURO_SOCIO_CREDITO` becomes populated, or an approved requirement needs credit-bureau providers or results in Fineract |
| `SCOPE-003` | Deferred | Operational bank-account master, bank-book subledger, and bank-reconciliation summaries in `dbo.BNC_CUENTA_BANCARIA`, `dbo.BNC_LIBRO_BANCO`, and `dbo.BNC_CONCILIACION` | Do not synchronize these operational structures for now. Preserve their accounting consequences through the accounting-journal migration, without replaying bank-book rows as duplicate journal entries. | `accounting-journal-entries`; future treasury or bank-reconciliation service if approved | An approved decision to operate treasury or bank reconciliation in Fineract or an external tool, together with a defined cutover and requirement for open items, balances, or historical bank-book and reconciliation data |

## SCOPE-001 — Standalone credit applications

- **Decision date:** 2026-09-14
- **Decision:** Defer synchronization of credit applications that did not
  produce a `CRD_CARTERA` portfolio record.
- **Included boundary:** Application data required by an originated loan remains
  part of the `loans` source graph and may be read and mapped by that service.
- **Excluded boundary:** Standalone applications and guarantor rows attached
  only to those applications are not written to Fineract.
- **Reason:** There is no current business requirement to operate or preserve
  non-originated application history in Fineract.
- **Reconsider when:** Credit-origination history, declined/withdrawn application
  reporting, regulatory retention, or application-level audit workflows become
  an approved target requirement.

## SCOPE-002 — Empty loan credit-bureau associations

- **Decision date:** 2026-09-14
- **Decision:** Exclude `dbo.CRD_BURO_SOCIO_CREDITO` and its provider catalog
  `dbo.CRD_BURO_CREDITO` from the current migration.
- **Excluded boundary:** No loan-to-bureau association, bureau classification,
  DataShare indicator, or standalone bureau-provider catalog row is written to
  Fineract.
- **Reason:** A read-only source check found exactly zero rows in
  `dbo.CRD_BURO_SOCIO_CREDITO`. The provider catalog contains only `EQUIFAX`
  and `INFORED`, but no source loan references either provider through this
  structure. Migrating the catalog alone would preserve configuration without
  any associated business evidence.
- **Reconsider when:** The association table becomes populated, another source
  structure is verified as the authoritative credit-bureau history, or bureau
  provider/results retention becomes an approved business, regulatory, audit,
  or operational requirement.

## SCOPE-003 — Operational bank book and reconciliation

- **Decision date:** 2026-09-14
- **Decision:** Defer synchronization of `dbo.BNC_CUENTA_BANCARIA`,
  `dbo.BNC_LIBRO_BANCO`, and `dbo.BNC_CONCILIACION` as operational treasury
  structures.
- **Included boundary:** The accounting-journal migration continues to preserve
  the GL accounts and journal entries representing bank balances and postings.
  Native target payment-channel mappings may continue to route new operations
  to the applicable GL accounts.
- **Deferred boundary:** Do not create a bank-account master from
  `BNC_CUENTA_BANCARIA`, replay `BNC_LIBRO_BANCO` as a second set of journal
  entries, or write `BNC_CONCILIACION` summaries into technical migration
  reconciliation fields.
- **Reason:** Fineract has no native one-to-one bank-account master, operational
  bank-book subledger, bank-statement matching, or per-account reconciliation
  model. The current source includes four operational bank accounts,
  approximately 4,184 bank-book movements, and approximately 176 reconciliation
  summaries, but the line-level reconciliation table is empty. Importing these
  structures without an approved treasury design would either lose their
  operational meaning or duplicate accounting history already preserved in the
  general ledger.
- **Reconsider when:** Credesal approves whether future treasury and bank
  reconciliation will run in a versioned Fineract extension or a separate tool,
  and defines whether cutover requires only open items and balances or also
  historical bank-book and reconciliation data.
- **Source evidence:**
  [`bancos-y-conciliacion-fineract.md`](../../../../../credesal-db-space/docs/learnings/bancos-y-conciliacion-fineract.md).
