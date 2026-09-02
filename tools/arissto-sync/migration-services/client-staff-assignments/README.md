# Client staff assignments

## Status

- Registry status: `blocked`
- Executable: `true` for a reviewed local acceptance pass
- Acceptance boundary: the revised lossless assignment contract no longer
  derives or modifies native Fineract loan-officer eligibility

Return this service to `available` only after the expanded contract completes a
controlled local apply, exact reconciliation, and unchanged second plan.

This dependent block preserves the three employee relationships stored directly on `AFI_SOCIO` for every Arissto party:

- `ID_PROMOTOR` → promoter;
- `ID_EJECUTIVO_CUENTA` → account executive; and
- `ID_GESTOR_COBRO` → collections manager.

It depends on successful `clients` and `employees` synchronization. Client identity resolves by `NUMERO_AFILIACION = m_client.external_id`; employee identity resolves by `ID_EMPRESA:ID_PERSONA = m_staff.external_id`. A missing dependency quarantines the party and makes the plan non-applicable.

The three roles remain independent. This service does not choose one as a
generic Fineract loan officer and never changes `m_staff.is_loan_officer` or
employee active status.

## Destination

Liquibase migration `0289_add_arissto_client_staff_assignments.xml` creates and registers the one-to-one `credesal_client_staff_assignment` client datatable. It stores both the original Arissto person IDs and foreign keys to the corresponding `m_staff` rows.

This table is authoritative for migrated relationships. The service intentionally does not update native `m_client.staff_id` or the existing `m_client.gestor_id`: Fineract applies office-hierarchy rules to those fields, while verified Arissto data contains valid cross-office assignments. A future reviewed projection may populate native fields for the compatible subset.

## Operation

```bash
./arissto-sync inspect --block client-staff-assignments --target local
./arissto-sync plan --block client-staff-assignments --target local
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
```

Use `--source-key NUMERO_AFILIACION` for a canary plan. Apply writes only through Fineract's datatable API. Readiness and reconciliation use read-only SQL. The service never deletes destination rows or changes Arissto.

## Composed workflow

This block remains independently runnable. In the proposed first composed
daily workflow it runs after both `clients` and `employees` have applied and
reconciled successfully. The dependency graph and future runner requirements
are defined in [`../orchestration.md`](../orchestration.md).

See [contract.md](contract.md) for field ownership and failure behavior. Source evidence is maintained in the exploration repository's `docs/learnings/empleados.md`.
