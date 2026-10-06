# DTE history migration contract

## Scope and dependencies

`dte-history` depends on `clients` and `loans`. A source row is eligible only
when all of these facts are true:

- `FAC_MOVIMIENTOS.CODIGO_GENERACION` and `NUMERO_CONTROL` match the normalized
  `facturacion.comprobantes` projection;
- `tipodocumento = '01'` and normalized detail exists;
- exactly one `CRD_MOVIMIENTOS_CARTERA` row links by the fiscal composite key;
- the operational client resolves through `CLIENTE` to
  `AFI_SOCIO.NUMERO_AFILIACION`; and
- the legal lifecycle maps to `ACCEPTED`, `REJECTED`, or `VOIDED`.

The generation UUID is both the sync source key and the native invoice legal
identity. Integer fiscal and projection keys are extraction details only; they
are not copied to Fineract and must never be joined to one another.

`numero_control` is unique within the DTE emission calendar year, while the
generation UUID remains globally unique. A control number reused in another
year retains its exact Arissto value. Inspection blocks only repeated
`(numero_control, emission year)` pairs in the source; a plan marks those as
`duplicate_source_control_number_in_year`. Existing target ownership checks
use the same year and report the actual `source_origin`. The target database
enforces uniqueness by control number and emission year. Source evidence is recorded in
[`fiscal-dte.md`](../../../../../../credesal-db-space/docs/learnings/fiscal-dte.md#control-number-reuse-across-calendar-years-observed-on-2026-09-24).

Arissto leaves `tipomodelo` and `tipooperacion` null for the reviewed ordinary
cohort. When both fields are missing and neither a contingency type nor a
contingency reason is present, the importer uses CAT-003 model `1` (prior
receipt) and CAT-004 operation `1` (normal transmission). It does not apply
that fallback to a row with any contingency signal or a partially populated
mode pair.

## Target mapping

| Arissto | Fineract |
|---|---|
| `CODIGO_GENERACION` | `m_invoice.codigo_generacion` |
| `NUMERO_CONTROL` | `m_invoice.numero_control` |
| `tipodocumento`, `tipos_dte.version_json` | `tipo_dte`, `version` |
| `tipomodelo`, `tipooperacion`, `fecha_emision` | identification model, operation, date, and time |
| configured `target.ambiente`, USD | `ambiente`, `tipo_moneda` |
| reception/annulment/error evidence | terminal invoice and MH status fields |
| normalized receiver fields | `m_invoice_receiver` |
| normalized detail | `m_invoice_line` |
| normalized totals and line-classified discounts | `m_invoice_summary` |
| `monto_iva` | `m_invoice_summary.total_iva` |
| `ARISSTO:CRD-MOV:{ID_MOVIMIENTO_CARTERA}` | exact `m_loan_transaction.external_id` |
| `NUMERO_AFILIACION` | exact `m_client.external_id` and loan-client validation |
| constant `ARISSTO_HISTORY` | `m_invoice.source_origin` |
| canonical contract + durable source content hash | `m_invoice.source_hash` |
| raw `DTE_ESTADO`, `ANULADO`, `INVALIDADO` | `m_invoice.source_lifecycle_json` |

Regular IVA is stored separately from IVA perceived and withheld. Discount
totals are allocated only when each
discounted source line has exactly one non-subject, exempt, or taxable category;
ambiguous allocations or a header/detail discount variance are quarantined.

No source-local fiscal IDs, duplicate client ID, duplicate loan movement ID,
receiver-type copy, or obsolete document path are retained. The generation
code identifies the invoice; `loan_transaction_id` identifies the migrated
movement; and the loan transaction's loan identifies the client. Those native
relationships are authoritative and are what reconciliation follows.
Source-local fiscal IDs and the obsolete path are also excluded from the hash,
so changes to non-durable extraction metadata cannot create false conflicts.

`ANULADO` has precedence and maps to `VOIDED`. Otherwise a reception seal maps
to `ACCEPTED`. A seal-less state `3` row with an error maps to `REJECTED`.
Other lifecycle combinations are quarantined rather than guessed. A reversed
loan movement does not void a legally sealed DTE.

## Write boundary

The block uses narrowly allowlisted, parameterized PostgreSQL transactions to
create one native invoice aggregate or correct MH timestamps on an imported
aggregate. This exception exists because
the operational invoice API validates new UUID-v4 documents and is designed to
submit them to MH, while Arissto history contains pre-existing UUID-v3 legal
identities.

The writer must never delete an invoice, call an MH endpoint, create or reverse
a loan transaction, or create accounting entries. A generation UUID or same-year
control number already owned by another invoice is quarantined. If an imported
Arissto document changes,
the planner permits an MH-timestamp correction only when every other mapped
invoice, receiver, summary, and line field still matches Fineract. The writer
locks and checks the same history identity and previous hash, verifies the
non-timestamp fields again, then updates only `authority_processed_at`,
`mh_submitted_at`, `mh_processed_at`, the source hash, and audit columns in one
transaction. Other source changes remain conflicts pending a broader reviewed
update policy. Existing source hashes retain the create-only contract's hash
basis, so this policy change does not schedule unchanged invoices for updates.
Fineract checks
`m_invoice.source_origin` and rejects both metadata updates and MH submission
for imported records.
Mifos also renders every terminal `ACCEPTED`, `REJECTED`, or `VOIDED` invoice
read-only.

DTEs whose exact source loan movement has no imported transaction remain
quarantined. A parent loan/refinance quarantine must be resolved in the Loans
contract first. A reversed payoff movement on a migrated loan also needs a
reviewed transaction or historical-document ownership rule; the DTE importer
must not substitute a nearby payment, amount, date, or client match.

Create and timestamp-correction actions are sorted by generation code, grouped into bounded atomic
batches, and may run on up to four worker-owned PostgreSQL connections. The
SQLite run journal remains coordinator-owned and is written in bulk only after
the corresponding PostgreSQL transaction commits. If a batch fails, the whole
transaction rolls back and is divided until the bad source key is isolated;
successful documents retain the same controlled-write and reconciliation guarantees
as a single-document run.

The API user must resolve to one unique `m_appuser` for audit columns. Issuer
identity is copied from the singleton `m_mh_company_config`; inspection blocks
and names every missing required issuer field. For local and production
workflows, the service prepare phase may fill missing singleton values from the
reviewed, non-secret issuer identity frozen in the DTE contract. The bootstrap
preserves existing nonblank target values, verifies the required fields after
the transaction, and does not expose copied values in workflow events. It never
writes `password_pri`, `firma_secret`, `signing_api_key`, or the mutable
`last_dte_correlativo`; those remain target-owned operational configuration.

## Reconciliation and promotion gate

Reconciliation requires the same source hash, legal identities, terminal
status, exact loan transaction, exact client, and exact line count. Quarantines
are reported but nonblocking; failed or mismatched records fail reconciliation.

Registry status is `available`. Controlled reconciliation, unchanged replay,
and explicit `01` environment validation remain runtime acceptance checks and
must fail closed when the target is not configured for the historical
population.
