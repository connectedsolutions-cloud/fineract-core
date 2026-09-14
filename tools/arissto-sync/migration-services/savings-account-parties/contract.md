# Savings account parties contract

## Identity and account attachment

- Collection source identity:
  `AHO_ACCOUNT_PARTIES|ID_EMPRESA|ID_SUCURSAL|ID_CUENTA_AHORRO`.
- Beneficiary identity:
  `ARISSTO:AHO-BEN:ID_EMPRESA:ID_SUCURSAL:ID_CUENTA_AHORRO:ID_BENEFICIARIO`.
- Authorized-person identity:
  `ARISSTO:AHO-AUTH:ID_EMPRESA:ID_SUCURSAL:ID_CUENTA_AHORRO:ID_AUTORIZADO`.
- The destination account must already resolve through the reconciled
  `credesal_savings_migration_account` row.
- A missing account mapping is quarantined; the service never creates or
  selects a deposit account heuristically.

## Beneficiaries

`NOMBRE_BENEFICIARIO`, `APELLIDO_PROPIETARIO`, `PORCENTAJE`,
`FECHA_NACIMIENTO`, `EDAD`, `DUI`, `PARENTESCO`, `DIRECCION`, `TELEFONO`, and
`COMUNICAR_DESIGNACION` map losslessly to the beneficiary extension table.
Despite its suspicious source name, `APELLIDO_PROPIETARIO` is treated as the
beneficiary surname because it is the only surname field on the row; this
interpretation remains explicitly traceable to the source column.

Every non-empty active beneficiary collection must total exactly `100.00`.
The entire collection is replaced in one Fineract transaction, so an invalid
allocation cannot leave a partially updated beneficiary set. An empty
collection is permitted and deactivates the existing set.

## Authorized persons

`NOMBRE_AUTORIZADO`, `APELLIDO_AUTORIZADO`, `DUI`, `FECHA_NACIMIENTO`,
`DIRECCION`, `TELEFONO`, `PARENTESCO`, `IMP_CONTRATO`, `IMP_LIBRETA`, and
`FIRMA` map to the authorized-person extension table. `FIRMA_IMG` is deferred:
the audited source population is empty, and binary transport/storage requires a
separate approved contract if data appears later.

The collection-level replace endpoint is the migration path. Item create,
update, and soft-delete endpoints remain available for ordinary application
maintenance. Designation data does not alter withdrawal or signing enforcement.

## API and authorization

- `GET/PUT /v1/depositaccounts/{accountId}/beneficiaries`
- `GET/PUT /v1/depositaccounts/{accountId}/authorized-persons`
- `POST /v1/depositaccounts/{accountId}/authorized-persons`
- `PUT/DELETE /v1/depositaccounts/{accountId}/authorized-persons/{personId}`

All access inherits `READ_SAVINGSACCOUNT` or `UPDATE_SAVINGSACCOUNT` and the
normal account data-scope check. No granular party-table permissions exist.

## Idempotency and reconciliation

Planning hashes both ordered collections as one account aggregate. Apply uses
deterministic external IDs and collection replacement. Reconciliation reads the
two API collections and compares their canonical field content to the current
source hash. Retry is limited to failed/quarantined run items selected by the
standard engine state contract; Arissto remains read-only.
