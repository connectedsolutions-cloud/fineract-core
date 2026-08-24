# Client PEP sync contract

## Scope

The machine-readable contract is [`config/client_pep.json`](../../config/client_pep.json).
This service owns exactly one mapping:

```text
dbo.AFI_SOCIO.PEP -> credesal_client_pep.es_pep
```

`AFI_SOCIO.NUMERO_AFILIACION` is the source key and must resolve to an existing
Fineract `m_client.external_id`. The service does not create, update, activate,
or deactivate the parent client.

## Value and row-presence rules

| Source value | Normalized value | Required target state |
|---|---|---|
| `1` | `true` | One row with `es_pep=true` |
| `0` | `false` | One row with `es_pep=false` |
| null or blank | unknown | No row |
| any other populated value | invalid | Quarantine as `invalid_boolean` |

Unknown is not false. An unexpected existing row for an unknown source value is
quarantined as `unexpected_target_row`; the service never deletes or clears it.

## Dependency contract

The registry declares `depends_on: ["clients"]`. There are two enforcement
layers:

- independent PEP planning is non-applicable if any scoped source key lacks a
  matching target client; and
- `apply CLIENT_PLAN --with-pep` applies and reconciles clients first, then
  scopes PEP to the successful/unchanged parent client items. A failed client
  reconciliation prevents PEP planning and writing.

This is a synchronous local CLI workflow, not a scheduler or background
trigger. The operator explicitly opts into the chain when applying the reviewed
clients plan.

## Excluded source and target fields

The service does not read or map `PER`, `PEX`, `NOMBRE_PER`,
`ID_RELACION_PER`, political-role fields or dates, legal-representative fields,
`INGRESOS_PEP`, `AFI_DATO_PEP`, or `AFI_PARTIDO_POLITICO`. All destination
columns other than `es_pep` remain outside this service.

## Planning and safety

- Arissto access is read-only.
- Fineract writes use the datatable API; direct SQL is used only for read-only
  inspection, planning, and reconciliation.
- Plans contain source keys, actions, and hashes, not customer values.
- Invalid values and unexpected rows are quarantined per client.
- Production apply requires the exact target fingerprint.
- No delete path exists.

## Reconciliation

For every nonfailed run item, reconciliation re-reads the current source value,
checks its hash, and verifies exact target state:

- true/false requires a row with the matching boolean;
- unknown requires row absence;
- a missing client, changed source, wrong boolean, unexpected row, failed item,
  or quarantine makes reconciliation unsuccessful.

The service is idempotent: after a fully reconciled run, replanning the same
scope produces only `unchanged` actions.

## Target prerequisite

Fineract Liquibase migration `0248` creates and registers
`credesal_client_pep`; migration `0263` supplies its audit timestamps. No new
schema migration is required for this service.
