# AML alerts migration contract

## Contract state

This is the executable contract for historical Arissto subtype `69` and `70`
alerts. The target schema is a versioned Liquibase change, and the sync block
implements inspection, planning, bounded upserts, retry, and reconciliation.

## Source identity and scope

- Alert identity: `EVE_EVENTO.ID_EVENTO`.
- Included alert definitions: `EVE_SUBTIPO_EVENTO.ID_SUBTIPO_EVENTO IN (69,70)`.
- Party identity: `EVE_EVENTO.ID_ASOCIADO` joined to
  `AFI_SOCIO.ID_ASOCIADO`.
- Stable client bridge: `AFI_SOCIO.NUMERO_AFILIACION` to
  `m_client.external_id`.
- Related movement rows: `EVE_MOVIMIENTOS.ID_EVE_MOVIMIENTOS` and each
  non-null contribution, savings, or credit movement reference.

The bare numeric `ID_ASOCIADO` must never be treated as a Fineract client ID.
An alert whose party cannot resolve through the reviewed client mapping is
quarantined; it is not inserted as an unowned target alert.

## Alert-type catalog mapping

| Source subtype | Target type code | Comparison basis | Known aggregation |
|---:|---|---|---|
| `69` | `ARISSTO_69` | `DECLARED_MONTHLY_AMOUNT` | `SINGLE_OR_ACCUMULATED` |
| `70` | `ARISSTO_70` | `MONTHLY_INCOME` | `SINGLE_OR_ACCUMULATED` |

The catalog description preserves the exact Arissto subtype message. Unknown
window, threshold-source, reversal, and cross-product calculation details are
not encoded as executable settings. A future rule implementation must version
reviewed settings rather than infer them from current profile values.

## Alert-header mapping

| Arissto source | Fineract target | Rule |
|---|---|---|
| `ID_EVENTO` | `source_alert_key` | Decimal text under `source_system='ARISSTO'`; composite unique identity |
| `ID_SUBTIPO_EVENTO` | `alert_type_id` | Resolve through `ARISSTO_69` or `ARISSTO_70` |
| `ID_TIPO_EVENTO` | `source_event_type_code` | Preserve source code; both current types use `1` |
| `ID_ESTADO_EVENTO` | `source_status_code` | Preserve source code without translating it into target workflow state |
| `ID_TIPO_ALERTA` | `source_alert_class_code` | Preserve source classification code; current 69/70 rows are global alerts |
| `TEMPORAL` | `source_temporary` | Preserve source value |
| `DT_EVENTO` | `occurred_at` | Exact source timestamp |
| `FECHA_EVENTO` | `business_date` | Preserve when present |
| `DT_CREO` | `detected_at` | Fall back to `DT_EVENTO` only when source creation time is null |
| `EVENTO` | `source_message` | Preserve the event-instance message |
| `MONTO` | `triggering_amount` | Triggering transaction amount, not accumulated activity or threshold |
| `TIPO_PRODUCTO` | `product_type_code` | Preserve source code; do not replace inferred `2/3/4` meanings |
| complete reviewed row | `source_payload`, `source_hash` | Canonical JSON plus deterministic SHA-256 for lossless evidence and idempotency; never emit payload in plans/logs |

`observed_amount`, `threshold_amount`, evaluation-period dates, currency, and
severity remain null unless a reviewed source or future native detector provides
them. Arissto user codes are retained in the payload and are not written into
Fineract `m_appuser` foreign keys.

Every imported alert starts in target status `NEW`, with an initial
`credesal_aml_alert_status_history` row. This does not claim the alert was open,
reviewed, or unresolved in Arissto; its original state is kept separately in
`source_status_code`.

## Subject mapping

`credesal_aml_alert_subject` supports more than one subject per alert. For the
initial header owner:

1. resolve `EVE_EVENTO.ID_ASOCIADO` to `AFI_SOCIO`;
2. resolve `AFI_SOCIO.NUMERO_AFILIACION` to `m_client.external_id`;
3. store the resulting `m_client.id` in `client_id`;
4. store source type `AFI_SOCIO` and source key `ID_ASOCIADO`; and
5. classify `subject_type` from the reviewed relationship state:
   `003` is `CLIENT`; `001`, `004`, `006`, and `007` are `MEMBERSHIP`.

The business role is separate from the person FK. This allows a future alert to
link the same person in different roles or to link multiple involved people
without adding nullable client/socio columns to the alert header.

`EVE_PERSONA_INVOLUCRADA` is not in the initial writer contract because current
events repeat the same header associate under three unresolved role codes. It
must not create three apparently distinct subjects until those role meanings are
verified.

## Movement and entity references

For every `EVE_MOVIMIENTOS` row, create one
`credesal_aml_alert_reference` per non-null source movement column:

| Column | `source_entity_type` | Relationship |
|---|---|---|
| `ID_APO_MOVIMIENTO` | `MOV_APORTACIONES` | `RELATED_MOVEMENT` |
| `ID_AHO_MOVIMIENTO` | `AHO_MOVIMIENTOS` | `RELATED_MOVEMENT` |
| `ID_CRD_MOVIMIENTO` | `CRD_MOVIMIENTOS_CARTERA` | `RELATED_MOVEMENT` |

Use `RELATED_MOVEMENT`, not `TRIGGER_TRANSACTION`, until the exact one-to-one
trigger relationship is proven for every row shape. Unresolved source movement
IDs are retained rather than dropped. `target_entity_type` and
`target_entity_id` remain null until a separate product migration can resolve a
native Fineract transaction identity.

`source_reference_key` preserves `EVE_MOVIMIENTOS.ID_EVE_MOVIMIENTOS`, while
`source_entity_key` preserves the referenced contribution, savings, or credit
movement ID. This distinction is required because one child row may contain
more than one populated movement-reference column.

The target entity pair is intentionally polymorphic and therefore cannot carry
a database FK. Application writers must validate allowed target entity types and
their IDs before populating it.

## Idempotency and write boundary

- Alert upsert identity: `(source_system, source_alert_key)`.
- Subject identity: alert plus role and stable source-subject identity.
- Reference identity: alert plus relationship, source-entity identity, and
  `EVE_MOVIMIENTOS` child-row identity.
- Existing source-owned fields may update only after source-hash comparison.
- Target workflow status/history must not be reset by a later source refresh.
- Direct SQL is limited to the reviewed `upsert_aml_alerts` allowlist and the six
  AML tables from migration 0282. Writes use batches of 500 in bounded
  transactions, fall back to one-alert retries after a batch rollback, and are
  verified by exact reconciliation.

## Preconditions and acceptance

- Migration `0282_add_credesal_aml_alerts.xml` is applied by normal Fineract
  Liquibase startup.
- Parent client migration has reconciled successfully.
- All source columns and target constraints pass inspection.
- Duplicate alert, subject, and reference identities are zero after
  normalization.
- A controlled local plan/apply/reconcile preserves exact source identities and
  field mappings.
- A second plan is entirely unchanged unless new Arissto alerts arrived.

## Open decisions

1. Exact subtype `69` threshold source.
2. Confirmation that subtype `70` uses the effective historical income value.
3. Accumulation window, reversals, and threshold-crossing semantics.
4. Meanings of the three `EVE_PERSONA_INVOLUCRADA.TIPO_PERSONA` values.
5. Future analyst workflow statuses, dispositions, and filing/case tables.
