# AML alerts migration service

## Status

- Registry status: `available`
- Executable: `true`
- CLI block: `aml-alerts`
- Dependency: migrated Fineract clients keyed by
  `AFI_SOCIO.NUMERO_AFILIACION`
- Target schema prerequisite: tenant migration
  `0282_add_credesal_aml_alerts.xml`

The historical sync block implements extraction, readiness inspection,
deterministic planning, bounded target writes, retries, and exact
reconciliation. It imports existing Arissto alerts; it is not an alert evaluator
or transaction trigger.

## Current scope

The first historical scope is Arissto `EVE_EVENTO` subtype `69` and `70` alerts,
their party ownership, and their `EVE_MOVIMIENTOS` source references. The model
is deliberately catalog-driven so future subtypes can be added without creating
one table per rule.

Source meaning and aggregate evidence remain in
[`aml-laft-transaction-monitoring.md`](../../../../../../credesal-db-space/docs/learnings/aml-laft-transaction-monitoring.md).
The detailed migration mapping is owned by [`contract.md`](contract.md), and
the machine-readable settings are in
[`config/aml_alerts.json`](../../config/aml_alerts.json).

## Operating workflow

Run the normal scoped lifecycle from `tools/arissto-sync`:

```bash
./arissto-sync inspect --block aml-alerts --target local
./arissto-sync plan --block aml-alerts --target local --source-key ID_EVENTO
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync status --block aml-alerts --target local
```

Omit `--source-key` only after reviewing a full-block plan. Production retains
the standard exact-fingerprint confirmation guard. The service never writes to
Arissto and never deletes a Fineract alert, subject, reference, or history row.

## Efficiency and safety

- Full extraction uses one parameterized header query and one movement query.
- Client IDs, alert types, existing headers, subjects, and references are read
  in bulk; the normal path has no per-alert lookup queries.
- Canonical source hashes include the header, subject classification, and all
  child movement references, enabling deterministic no-op plans.
- Target writes use batches of 500 inside bounded transactions. A failed batch
  rolls back and retries one alert at a time so one bad row does not block the
  remaining batch.
- Direct SQL is allowlisted only for `upsert_aml_alerts` and only against the six
  versioned AML tables. Target-owned workflow status is preserved on refresh,
  and initial status history is inserted once.

## Local acceptance

On 2026-08-22, migration 0282 passed live inspection and a scoped local run for
Arissto event `67510` created one alert with one subject and three movement
references. Run `06b5173da28b4e4284f182081319e490` reconciled with one match,
zero mismatches, and zero failed or quarantined items. The immediate second plan
classified the event as `unchanged`.

A subsequent full local plan covered all 8,633 subtype 69/70 alerts and 19,446
movement references: 8,632 creates, one unchanged, and no quarantines. Plan
`cfcc824eb6f247788a15cf51ae82c199` was applied on 2026-08-22 as run
`4436af53dfb142e0b4d3872d3d14ab8c`; all 8,633 alerts reconciled exactly with
zero mismatches, failures, or quarantines. The immediate full follow-up plan
classified all 8,633 alerts as `unchanged`.

## Destination model

Tenant migration
[`0282_add_credesal_aml_alerts.xml`](../../../../fineract-provider/src/main/resources/db/changelog/tenant/parts/0282_add_credesal_aml_alerts.xml)
creates:

- `credesal_aml_alert_type`: extensible alert-definition catalog;
- `credesal_aml_alert_status`: workflow-status catalog, initially only `NEW`;
- `credesal_aml_alert`: alert header and source snapshot fields;
- `credesal_aml_alert_subject`: multi-subject client or membership-role links;
- `credesal_aml_alert_reference`: typed Arissto and future Fineract entity or
  movement references; and
- `credesal_aml_alert_status_history`: append-only workflow status history.

These are custom domain tables, not Fineract datatables. They are intentionally
not registered in `x_registered_table`: an alert can have multiple subjects and
multiple references, which does not fit a single parent datatable contract.

## Client and socio identity

Fineract has one person spine: `m_client`. A current cooperative socio is an
`m_client` with membership context in `credesal_member_profile`; there is no
separate native socio person table.

Consequently every resolvable Arissto alert subject links to `m_client.id`.
`credesal_aml_alert_subject.subject_type` preserves whether the alert addresses
that person as `CLIENT` or `MEMBERSHIP`. The source `AFI_SOCIO.ID_ASOCIADO` and
relationship state remain in the source identity/payload, while
`AFI_SOCIO.NUMERO_AFILIACION` resolves the target client external ID.

## Explicitly deferred

- Reproduction of the monthly accumulation rules.
- Runtime event listeners, jobs, or database triggers.
- AML API resources and permissions.
- Analyst assignment, disposition, escalation, and regulatory-filing models.
- Resolution of source movements to native Fineract transaction IDs.

Those capabilities may extend this schema later; none should reinterpret an
imported Arissto alert or overwrite its source identity.
