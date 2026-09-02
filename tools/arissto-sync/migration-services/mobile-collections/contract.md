# Mobile collections contract

## Ownership boundary

This service owns only Cobro Movil operational metadata. The `loans` service
owns the native loan and every native loan transaction, including the repayment
to which a mobile collection may eventually link.

Applying this block must never:

- call a loan repayment endpoint;
- create, reverse, or adjust `m_loan_transaction` rows;
- create journal entries;
- create teller or cashier transactions; or
- infer that physical custody changed because a mobile record was captured.

## Source identities and cardinality

| Entity | Authoritative Arissto identity | Target identity |
|---|---|---|
| Route | `MCD_RUTA.ID_RUTA` | `credesal_mobile_collection_route.arissto_route_id` |
| Assignment | `MCD_ASIGNACION_RUTA.ID_ASIGNACION_RUTA` | `credesal_mobile_collection_assignment.arissto_assignment_id` |
| Routed account | `dbo.cuenta.id_cuenta` | `credesal_mobile_collection_account_assignment.arissto_account_id` |
| Batch | `MCD_MST_COBRODIARIO.ID_MST_COBRODIARIO` | `credesal_mobile_collection_batch.arissto_master_id` |
| Collection item | `(ID_EMPRESA, ID_SUCURSAL, ID_PERIODO, ID_COBRODIARIO, ID_MOV_COBRODIARIO)` | the same five columns under a unique constraint |
| Application bridge | `MCD_MOVIMIENTOS.ID_MCD_MOVIMIENTO` | `credesal_mobile_collection_item.arissto_mcd_movement_id` |
| Loan repayment | `MCD_MOVIMIENTOS.ID_MOVIMIENTO_CARTERA` | `m_loan_transaction.external_id = ARISSTO:CRD-MOV:{ID_MOVIMIENTO_CARTERA}` |

`ID_DET_COBRODIARIO` is preserved as evidence but is not used as the sole item
identity because the declared Arissto primary key is the five-column composite
key.

## Relationship resolution

### Clients

Route assignments store `MCD_ASIGNACION_RUTA.ID_ASOCIADO`, a logical reference
to `AFI_SOCIO`. Resolve it through `AFI_SOCIO` and then use
`AFI_SOCIO.NUMERO_AFILIACION = m_client.external_id`. Do not use bare
`ID_ASOCIADO` as a cross-service target key.

Collection items resolve their declared
`(ID_EMPRESA, ID_SUCURSAL_SOCIO, ID_SOCIO)` foreign key to `AFI_SOCIO`, then use
the same `NUMERO_AFILIACION` target identity.

### Staff and offices

Arissto employee identities resolve as `ID_EMPRESA:ID_PERSONA =
m_staff.external_id`. Branch-to-office resolution must use the reviewed office
crosswalk; branch codes must not be treated as Fineract numeric IDs.

### Loans and repayments

`dbo.cuenta` is the authoritative current account-level route list. Resolve its
`id_cliente` through `dbo.cliente2.numero_cliente`; that affiliation number is
the target `m_client.external_id`. Do not infer account membership by including
every loan owned by a client in `MCD_ASIGNACION_RUTA`.

For `CREDITOS`, `dbo.cuenta.numero_cuenta` resolves to
`CRD_CARTERA.NO_PRESTAMO`; use the loans-service external-ID contract to resolve
the resulting native `m_loan`. For `AHORROS`, the exact source bridge is
`dbo.cuenta.numero_cuenta = AHO_CUENTA_AHORRO.NO_CUENTA`. The matched savings
row supplies `(ID_EMPRESA, ID_SUCURSAL, ID_CUENTA_AHORRO)`, which resolves the
savings-service identity
`m_savings_account.external_id = arissto:savings:{company}:{branch}:{account}`.
Do not join the route account number to `AHO_CUENTA_AHORRO.ID_CUENTA_AHORRO`.
Account number, client, route, amount, or date proximity must not be used as a
guessed target link. An unresolved target account is preserved with a null
native link and an explicit `link_status`.

`NUM_CUENTA` is preserved for evidence. Target loan identity uses
`ARISSTO:CRD:{CRD_CARTERA.ID_CREDITO}` and native repayment identity uses
`ARISSTO:CRD-MOV:{MCD_MOVIMIENTOS.ID_MOVIMIENTO_CARTERA}`, as defined by the
loans contract.

For the newer cohort, `MCD_MOV_COBRODIARIO.ID_MCD_MOVIMIENTO` directly resolves
to `MCD_MOVIMIENTOS`, whose `ID_MOVIMIENTO_CARTERA` identifies the authoritative
Arissto loan movement. Older applied items frequently lack the direct bridge.
They must not be matched by amount and date alone. A separately reviewed,
deterministic legacy linkage rule is required before those transaction links
can be populated.

## Field ownership

All five extension tables are migration-owned snapshots of Arissto operational
state. Native Fineract loan balances, schedules, transaction components, and
accounting remain authoritative for financial reporting.

No visit date is stored in these migration tables. For a linked routed loan,
the default visit date is the due date of its earliest incomplete native
Fineract repayment-schedule installment. This derived workload must never
update the installment's contractual due date.

Important preserved fields include:

- route name, status, responsible employee, company, and branch;
- routed account source identity, product type, transaction type, account
  number, route, client, and nullable native loan or savings-account link;
- batch composite key, responsible employee, promoter, dates, totals,
  difference, remitted amount, close references, status, and observation;
- item client/account references, receipt and stub references, source amount,
  transaction code, application/control flags, capture/load/application times,
  and bridge identifiers; and
- nullable native `loan_id` and `loan_transaction_id` links.

There is no verified Arissto route-to-batch foreign key. The target schema must
not invent that relationship.

## Pending and unmatched records

The implemented link-status taxonomy is:

| Entity | Status | Meaning |
|---|---|---|
| Routed account | `LINKED` | Exact native loan or savings-account identity resolved |
| Routed account | `UNRESOLVED_TARGET_ACCOUNT` | Source account is preserved but its exact native account is not yet present |
| Collection item | `LINKED` | Exact `ID_MOVIMIENTO_CARTERA` repayment identity resolved |
| Collection item | `MISSING_REPAYMENT` | Exact source repayment identity exists, but the native repayment is not yet present |
| Collection item | `UNRESOLVED_LEGACY` | Applied legacy item has no deterministic application bridge |
| Collection item | `PENDING` | Application was requested but has not completed |
| Collection item | `NOT_APPLICABLE` | Unapplied operational history with no repayment link expected |

An unapplied collection is valid operational history. It is stored with a null
`loan_transaction_id` and `link_status = 'NOT_APPLICABLE'` or `PENDING` as
appropriate.

An applied item with no deterministic repayment match is preserved with a null
native transaction and `link_status = 'UNRESOLVED_LEGACY'`; that link remains
quarantined from inference and is not guessed into a target transaction. Rare,
immaterial amount differences may be accepted only when a stronger source
identifier establishes the relationship; the difference is reported during
reconciliation rather than used to reject the identity.

Missing required target clients quarantine the affected party assignment or
routed account and do not block unrelated metadata. The accepted local run has
four such assignments and two such routed accounts. These are reviewed,
explicit quarantines rather than guessed links. A new quarantine reason or an
unexpected increase in production requires operator review.

## Idempotency

- Routes, party assignments, routed accounts, and batches use their durable
  numeric Arissto IDs.
- Items use their declared five-column source primary key.
- A second plan against unchanged source data produces no writes.
- Updates may refresh migration-owned operational columns but cannot reassign a
  link to a different native repayment without an explicit reviewed repair.
- Nothing is deleted from Fineract when a source row disappears or becomes
  inactive.

## Reconciliation requirements

Reconciliation proves:

- counts and source identities for all five entities;
- all route and batch employee links that should resolve;
- all resolvable party links through `NUMERO_AFILIACION`, with missing-client
  entities explicitly quarantined and counted;
- every populated routed-account link resolves to the authoritative native loan
  or savings account, with unresolved links reported by `link_status`;
- batch totals versus preserved source items, reported without assuming the
  currently ambiguous `DIFERENCIA` and `REMESADO` semantics;
- every populated native repayment link resolves to the authoritative
  loans-service transaction;
- source amount versus native repayment amount, with discrepancies listed; and
- an idempotent second run with zero financial transactions and zero duplicate
  extension rows.

## Resolved implementation prerequisites

- The locally verified loans-service lifecycle and frozen
  external-ID contract.
- The reviewed branch-to-office crosswalk (`001 -> 1`, `002 -> 2`).
- Legacy item-to-repayment links remain unset unless the exact source bridge is
  present.
- Payment-type-to-clearing-account behavior remains separate; that accounting
  configuration belongs to the loans/product contract, not this metadata
  service.

The writer contract explicitly permits controlled, parameterized upserts only
to the five `credesal_mobile_collection_*` extension tables. Deletes and writes
to native Fineract financial tables are forbidden.
