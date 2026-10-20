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

The historical DTE writer already creates the native `m_invoice` aggregate,
including its issuer, receiver, lines, summary, legal status, and MH state.
`source_lifecycle_json` preserves the raw Arissto workflow codes for audit;
the mapped terminal state is also written to native `status`,
`authority_status`, `mh_transmission_status`, and `mh_validation_status`.
Migration `0414` concerns GL journal and voucher fields and requires no DTE
writer change.

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
| `ARISSTO:CRD-MOV:{ID_MOVIMIENTO_CARTERA}` | exact `m_loan_transaction.external_id` when the movement was migrated; otherwise `m_invoice.source_loan_movement_external_id` |
| `NUMERO_AFILIACION` | exact `m_client.external_id` and loan-client validation |
| source branch | `m_office.external_id` for documents without a target loan transaction |
| constant `ARISSTO_HISTORY` | `m_invoice.source_origin` |
| canonical contract + durable source content hash | `m_invoice.source_hash` |
| raw `DTE_ESTADO`, `ANULADO`, `INVALIDADO` | `m_invoice.source_lifecycle_json` |

Regular IVA is stored separately from IVA perceived and withheld. Discount
totals are allocated only when each
discounted source line has exactly one non-subject, exempt, or taxable category;
ambiguous allocations or a header/detail discount variance are quarantined.

No source-local fiscal IDs, duplicate client ID, duplicate loan movement ID,
receiver-type copy, or obsolete document path are retained. The generation
code identifies the invoice. When the source movement has a target transaction,
`loan_transaction_id` identifies it and its loan identifies the client. When
there is no target transaction, the invoice retains the mapped client and
office in `historical_client_id` and `historical_office_id`, plus the source
movement external ID. This preserves legal DTE history without creating a
financial transaction or posting. Reconciliation follows either ownership path.
Source-local fiscal IDs and the obsolete path are also excluded from the hash,
so changes to non-durable extraction metadata cannot create false conflicts.

`ANULADO` has precedence and maps to `VOIDED`. Otherwise a reception seal maps
to `ACCEPTED`. A seal-less state `3` row with an error maps to `REJECTED`.
Other lifecycle combinations are quarantined rather than guessed. A reversed
loan movement does not void a legally sealed DTE.

The target transaction is optional for this reviewed source cohort. The
source DTE must still have exactly one Arissto loan movement and a valid mapped
client; an unlinked document also requires a mapped source branch. Documents
with no exact source movement are a separate, unreviewed cohort.

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

DTEs whose exact source loan movement has no imported transaction use the
historical owner columns in migration 0385. The importer never substitutes a
nearby payment, amount, date, or client match. Existing source hashes retain
the version-1 basis so already imported DTEs remain unchanged.

The 2026-10-07 carry-forward audit confirmed that all 82 DTEs quarantined for
`missing_target_loan_transaction` have exactly one source loan-movement link:
79 belong to a quarantined refinance chain and three have `REVERSION=1` on
migrated loans while retaining a legal reception seal. They motivated a
historical-document owner path with no invented financial transaction. A separate 84
normalized type-`01` DTEs lack an exact source loan-movement link and are
outside this version-2 cohort. Those records need a distinct, reviewed
standalone-document contract. Native invoice creation still requires a loan,
savings, or client transaction. The historical SQL importer instead sets a
mapped client, office, and source movement reference on the existing invoice
aggregate. Fineract GET by invoice ID and Mifos DTE preview support this
path; the invoice listing resolves the owner directly when the transaction is
absent. Source evidence is in
[`fiscal-dte.md`](../../../../../../credesal-db-space/docs/learnings/fiscal-dte.md#carry-forward-dte-link-audit-on-2026-10-07).

On 2026-10-07, local sandbox plan `87a86abad7d8462f94c336c5506fd8ef`
created all 82 previously quarantined DTEs in run
`8cf9c28c1b63475196facf41f2f06685`; reconciliation matched 82 of 82.
The sandbox has 24,638 imported historical DTEs, of which exactly 82 have no
loan transaction and all 82 have a mapped client, office, and distinct source
movement. `m_client_transaction` remains empty. The invoice API returned one
of these documents by ID with three lines, and `listado facturas` found it
under its client and office filters.

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
