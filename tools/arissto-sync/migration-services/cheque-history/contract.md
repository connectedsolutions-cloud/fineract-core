# Historical cheque import contract

Status: executable for controlled local acceptance; registry `status: testing`
and `executable: true`. Production apply remains disabled. This specifies the accepted
migration boundary and does not authorize a target run. See [README.md](README.md).

## Source identities and selected fields

| Kind | Internal source predicate and key | User-facing cheque facts |
|---|---|---|
| Issued | `BNC_LIBRO_BANCO.CODIGO_SISTEMA=11`, `ID_TRANSACCION='00002'`; `ID_LIBRO_BANCO` | `COMPROBANTE` as text; `MONTO`; `FECHA_MOVIMIENTO`; bank resolved from `ID_CUENTA_BANCARIA → BNC_CUENTA_BANCARIA → BNC_BANCO`; direction "issued"; explicit `ANULADO` if shown. |
| Received | `CJA_REF_CHEQUE.ID_REF_CHEQUE` | `NUMERO_CHEQUE` as text; `MONTO_CHEQUE`; `FECHA_CHEQUE` when populated; bank resolved through `CJA_BANCO`; direction "received". |

Keep source kind and ID as hidden technical keys for idempotency and exact
joins. The user-facing model is cheque number, bank, amount, date, direction
and linked transactions; Arissto IDs are not business fields. A cheque number,
even combined with bank account, is not unique in the observed source.
Preserve optional nulls; never invent a date or cheque number from another
field. Do not import `NUM_COMPROBANTE`, Arissto notes/closing IDs, account
numbers, holder names, series or other metadata into the first version.
Issued and received banks use different catalogs and require a reviewed
crosswalk or clear source labels in the Fineract search/filter UI.

## Financial and relationship boundary

The target is a small cheque lookup, not a copy of the Arissto records. Native
`m_payment_detail` can hold cheque/bank fields on one owning product payment;
amount and date live on that transaction. It cannot represent a standalone
cheque or one cheque shared by multiple movements. Credesal's current
`m_treasury_movement` create API posts accounting. Neither is a safe single
target for all observed relationships, so the lookup supplies one-cheque
identity plus a separate link set. The current implementation resolves exact
imported GL, loan, and savings transactions as links; adding native payment
details to existing transactions remains a separate reviewed metadata-only
enhancement.
No import write may produce a GL entry or affect a live treasury balance.

Link issued cheques by exact `ID_LIBRO_BANCO` through
`CNT_DETALLE_PARTIDAS`, `CNT_DET_TRANSAC`, `BVD_DET_BANCO`,
`AHO_MOVIMIENTOS`, and `CRD_DET_LIQUIDACION`/`CRD_ENC_LIQUIDACION` as
applicable. Link received cheques by exact `ID_REF_CHEQUE` through
`AHO_MOVIMIENTOS`, `CRD_MOVIMIENTOS_CARTERA`, `CAJA_MOVIMIENTOS` and
`CNT_PAGO_COMBINADO`. A source relationship becomes a target link only if its
owning movement was migrated and resolved exactly. Preserve multiple links per
cheque; never attach by cheque number, amount or date. Keep unmatched or
ambiguous target links empty and count them in inspection and reconciliation.

The journal report's `No. Cheque` value follows the first linked bank-book
row of a *whole journal*, which is a distinct projection from one lookup row
per issued `ID_LIBRO_BANCO`. Its existing provenance enrichment and required
metadata-only backfill remain in the accounting service contract.

## Excluded states

Do not import or derive delivered, collected, rejected, cleared, or
outstanding state. Do not interpret missing delivery dates or zero/constant
flags as negative evidence. Do not import empty chequebook or payroll-cheque
tables as activity. A later reconciliation contract must use independent bank
statement evidence. `ANULADO` is an explicit source cancellation fact and may
be displayed as such; it must not be treated as a clearing status.

## Inspect, plan, apply and reconciliation

- Extract the two populations with a required inclusive `source_through_date`
  (`S`). The Fineract accounting boundary is the following calendar day
  (`T = S + 1`). An issued cheque is eligible when
  `BNC_LIBRO_BANCO.FECHA_MOVIMIENTO < T`; a received cheque is eligible when
  `CJA_REF_CHEQUE.DT_CREO < T`. `FECHA_CHEQUE` describes the instrument and
  must not determine ownership. Do not filter on delivery or clearing flags.
- Freeze kind, hidden source ID, selected basic fields, source hash and every
  verified relationship key in a target-specific reviewed plan. Preview
  creates, unchanged rows, changed-source conflicts and unresolved links
  without logging cheque values.
- Write to versioned tenant metadata tables with a unique `(kind,
  source_id)` key. Repeated identical plans are no-ops; conflicting changes
  require review. The current block contract permits controlled, parameterized
  PostgreSQL writes **only** to the dedicated `credesal_historical_cheque` and
  `_link` metadata tables under a reviewed target-specific plan and
  post-write verifier. It never writes core GL, product transactions or
  treasury balance tables.
- Reconcile source keys, selected field hashes and the link sets independently
  for issued and received rows, including nulls. Assert that GL journal
  count/amounts and live treasury balances are unchanged. The later
  2026-10-09 scan's 852 issued and 49 received rows are a reference sample
  only; 25 received cheques each have two combined-payment component links.
- Verify the Mifos lookup list, detail, exact and partial cheque-number
  search, bank/date/amount filters, linked-transaction navigation, sorting and
  export, and English and Spanish labels. The UI must show issued versus
  received, but no Arissto IDs or delivery/clearing status.

Apply writes all rows in one serializable transaction. A failed apply can be
replanned and repeated without duplicating committed rows. Keep registry status `testing` until the schema/API, extraction, planning,
writer, reconciliation, tests and controlled local run are complete.
