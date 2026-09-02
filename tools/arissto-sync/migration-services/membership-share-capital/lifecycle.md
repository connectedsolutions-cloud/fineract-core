# Share lifecycle evidence and native Fineract mapping

## State machines

The migration must keep four related lifecycles separate:

1. **Party relationship:** `AFI_SOCIO.ID_ESTADO_SOCIO` and
   `ID_ESTATUS_SOCIO` describe whether the person is a socio, client, former
   socio, active, retired, excluded, or deceased.
2. **Share-class position:** `AFI_ACCION` is the current aggregate position for
   one associate and one share type.
3. **Certificate:** `AFI_CERTIFICADO` records the legal/documentary state,
   subscribed shares, paid shares, blocks, serials, and book references.
4. **Financial events:** `MOV_APORTACIONES` is the populated current ledger;
   `OPR_OPERACIONES` and the monthly certificate history provide corroborating
   or legacy evidence, not an autonomous current ledger.

Closing one share-class position does not close the other class and does not by
itself deactivate the client.

## Current and former cohorts

The reviewed source snapshot contains:

| Cohort | Parties |
|---|---:|
| Current common and preferred positions | 17 |
| Current preferred-only positions | 23 |
| Current common-only positions | 0 |
| Current clients with former common-only identities | 13 |
| Current clients with former preferred-only identities | 12 |
| Current clients with former identities in both classes | 21 |

The 46 current clients in the last three rows have no current position and no
populated withdrawal/withdrawal-approval date. Their former position is not
active, but the source does not establish a redeem date or payout.

The research evidence is maintained in
[`credesal-db-space/docs/learnings/membresia-aportaciones-y-participaciones.md`](../../../../../../credesal-db-space/docs/learnings/membresia-aportaciones-y-participaciones.md).

## Identity and cutover

Certificate number is not globally stable. Of 99 numbers observed across the
monthly history and current master, 68 were reused for multiple
`(ID_ASOCIADO, ID_TIPO_ACCION)` combinations. Historical comparison must use
the full identity plus period and must not join `OPR_OPERACIONES.REF_ID` to a
current product without corroborating party, type, and date evidence.

The archive contract excludes unresolved `OPR_OPERACIONES` rows entirely. It
retains only the six membership operation types whose associate resolves to the
current party master. Legacy operation rows remain useful research evidence but
cannot become native events or client-less Fineract archive records.

The legacy contribution-account operation stream ends in January 2023. The
current `MOV_APORTACIONES` ledger begins on 2023-02-01, aligned with accounting
period `00031`. This is a contract boundary: pre-cutover withdrawals,
reversals, and liquidations do not inherit a current common/preferred share type
without an explicit crosswalk.

## Evidence grades

| Grade | Minimum evidence | Migration disposition |
|---|---|---|
| A — authoritative event | Current ledger row; exact party/type/certificate; date, paid shares, amount, and balance reconcile | Eligible for native command |
| B — corroborated lifecycle event | Matching event and snapshots/accounting establish both before and after states | Eligible only after a reviewed rule is added to the contract |
| C — state inference | Historical identity disappears or party is now a client, but no financial event exists | Archive and report as former; no native transaction |
| D — collision/ambiguous legacy | ID reused, polymorphic reference, unmatched transfer leg, or legacy type not crosswalked | Quarantine |

One exact monthly identity changes from `PAGADO` to `CERRADO` in January 2023,
reducing 500 legacy type-1 shares and 5,000.00 to zero. An equal-value `PLUS
SILVER` operation is not corroboration: Credesal confirmed that all PLUS
identifiers are irrelevant to its managed products. The closure therefore has
no trusted financial event and cannot create a Fineract redemption.

## Event mapping

The present paid projection is 6,375 common shares and 848 preferred shares.
Preferred certificates contain 2,048 subscribed shares, so the unpaid
1,200-share difference must not inflate Fineract approved shares.
`AFI_ACCION.NUMERO_ACCIONES` is a third, incompatible preferred aggregate of
1,248 and is not a substitute for either quantity. The two `PENDIENTE`
certificates already contain 400 paid shares, so certificate state alone cannot
be used as the native transaction approval state.

If every current movement passes entity reconciliation, the expected native
shape is 57 share accounts and 66 purchase events: one initial purchase for
each account and nine later purchases. These are expected contract counts, not
authorization to write the target before prerequisites pass.

| Arissto event/evidence | Native Fineract result | Preconditions |
|---|---|---|
| Current position with paid capital | Create, approve, and activate `m_share_account` through API | Mapped client, reviewed product, independently migrated eligible savings deposit, exact paid balance |
| First paid purchase | Initial requested shares on share application | Whole paid-share quantity and amount reconcile at unit price |
| Later paid purchase | `applyadditionalshares`, then `approveadditionalshares` | Active account; event date is not before existing native transactions |
| Partial paid-capital return | `redeemshares` | Explicit date, class, shares, amount; sufficient unlocked shares |
| Full paid-capital return and position closure | `close` share account | Explicit closure evidence; command creates the full redemption transaction; product market price selected by Fineract must equal the source event price |
| Unpaid subscribed shares | Preserve as pending subscription metadata/archive | Never inflate approved/purchased shares |
| Pending certificate cancelled before payment | Reject pending application/additional-share request | Proven unpaid state; no approved paid shares affected |
| Paid certificate annulled/reissued with unchanged position | Preserve certificate event; no capital transaction | Replacement must reconcile old/new certificate and unchanged paid capital |
| Transfer or sale between holders | Linked source redemption/close plus destination purchase | Both legs, same class/shares/value/date, transfer correlation |
| Source transaction correction/reversal | Quarantine unless it proves a new economic event | Native Fineract share transactions have no supported reversal command |
| Historical identity absent today | No active account and no fabricated transaction | Archive/report as former position |
| Member withdrawal/exclusion/death | Separate party lifecycle decision; close each proven share position independently | Do not deactivate client from share evidence alone |

## Native Fineract records

The service must call the Fineract share APIs; it must not insert these core
rows directly. Successful commands materialize the following native model:

| Fineract record | Role in the projection |
|---|---|
| `m_share_product` | Reviewed common/preferred product definition, market price, limits, and accounting setup |
| `m_share_account` | One client position per mapped share class; active is `status_enum=300`, closed is `600`; `total_approved_shares` is paid shares |
| `m_share_account_transactions` | Purchases use `type_enum=500`; redemptions use `600`; approved events use `status_enum=300` and retain date, shares, unit price, and amount |
| `m_savings_account` | Mandatory active, same-client, same-currency normal savings deposit referenced by `m_share_account.savings_account_id`; it must come from the independently reconciled savings migration |
| `acc_gl_journal_entry` | Accounting entries generated by the native share commands under the reviewed share-product accounting configuration |
| Credesal membership archive | Certificate, subscription, source identity, ambiguity, and legacy evidence that has no exact native column |

The archive and local sync-state mapping are the current source-event
crosswalk. They are sufficient for the preservation service but not yet the
approved durable crosswalk for native transactions. Native table IDs are
results of the API workflow, not source identities.

## Required native inspection and reconciliation

A future native service must block unless it can prove all of the following:

- one intended Fineract share product per mapped Arissto share class;
- a valid, active normal savings account owned by the same client, in the same
  currency, and already reconciled by the savings service;
- paid shares are integral at the applicable unit price;
- purchase minus redemption shares equals current paid shares;
- native transaction amount equals paid capital, not subscribed capital;
- no transaction is backdated before an already-created native transaction;
- full closure has zero remaining paid shares and a defensible closure date;
- every transfer has both legs or is quarantined; and
- reruns resolve by stable source-event identity and do not duplicate commands.

Current evidence supports native purchases for the present paid positions once
the product/savings/accounting prerequisites exist. It does not yet support
native redemption replay for the historical former-position cohort.

## Field-level projection contract

The first native implementation should use the following source precedence.
Fields marked extension remain in the Credesal archive or a dedicated
certificate projection and do not alter native capital.

| Source field/evidence | Fineract destination | Rule |
|---|---|---|
| `AFI_TIPO_ACCION.ID_TIPO_ACCION` | `m_share_product.external_id` | Stable class crosswalk; exactly one product for common and one for preferred |
| `AFI_TIPO_ACCION.TIPO_ACCION` / `CODIGO` | product name / short name / `numberingCode` | Reviewed labels; store `1AC` for common and `1AP` for preferred under migration `0315`; do not derive products from `OPR_OPERACIONES.PRODUCTO` |
| `AFI_EMISION_ACCIONES.VALOR_ACCION` | product/unit market price | 5.00 for both classes; seed price history effective no later than the first migrated purchase |
| `AFI_EMISION_ACCIONES.NUMERO_ACCIONES` | product issuance metadata, not automatic capacity | Preferred configured issuance is 100 although current subscribed/paid positions exceed it; block until business-approved product limits are supplied |
| `AFI_TIPO_ACCION.ID_CUENTA` | candidate `shareEquityId` | Resolves to distinct common/preferred equity GL codes; target GL crosswalk still must be reviewed |
| `AFI_TIPO_ACCION.ID_CUENTA_PROVI/ID_CUENTA_COSTO` | accounting evidence, not direct role mapping | Arissto yield/provision accounts do not directly establish Fineract `shareReferenceId`, `shareSuspenseId`, and `incomeFromFeeAccountId` |
| `AFI_ACCION.ID_ACCION` | `m_share_account.external_id` | One account per current `(ID_ASOCIADO, ID_TIPO_ACCION)` position |
| `AFI_SOCIO.NUMERO_AFILIACION` | `m_share_account.client_id` through `m_client.external_id` | Client must already exist and match uniquely |
| paid certificate sum by associate/type | `m_share_account.total_approved_shares` | Use 6,375 common + 848 preferred in aggregate; never use preferred `AFI_ACCION.NUMERO_ACCIONES=1,248` or subscribed 2,048 |
| first reconciled `MOV_APORTACIONES` row | initial purchase transaction | Shares = `MONTO / VALOR_ACCION`; use `FECHA`; amount and position balance must reconcile |
| later reconciled `MOV_APORTACIONES` rows | additional-share apply + approve | Deterministic order by `FECHA`, then stable movement source key |
| `AFI_CERTIFICADO.ACCIONES_SUSCRITAS/SALDO_SUSCRITO` | extension metadata | Preserve unpaid subscription; never approve it as paid capital |
| certificate state, serial/range, book/folio, blocks and beneficiaries | extension/archive | Fineract native share tables have no equivalent legal-certificate model |
| daily/monthly histories | archive snapshots | Never replay as native transactions |
| explicit proven partial/full return | redeem/close API command | No current post-cutover source rows qualify |

All 57 current positions presently reconcile exactly: 66 source movements at
5.00 produce 7,223 paid shares and 36,115.00, equal to the certificate paid
totals. This makes the purchase projection source-ready, but not target-ready.

## Remaining target decisions

Before native writes are enabled, the implementation still needs:

1. apply the already approved common/preferred product capacity and per-client
   limits during native product provisioning;
2. apply tenant migration `0295_seed_native_share_accounting.xml`, then require
   inspection to resolve the approved reference, suspense, class-equity, fee,
   and payment-channel mappings. Cash is canonical across offices and journal
   `office_id` carries the office dimension;
3. completion of the independent native savings migration, including real
   products, ownership, movements, posted interest, accrual state, and
   accounting reconciliation;
4. one real, active, same-client, same-currency `SAVINGS_DEPOSIT` for every
   migrated share account; current source coverage supports 45 of 57 positions,
   while the other 12 remain blocked rather than receiving synthetic accounts;
5. a queryable certificate extension design if legal certificate data must be
   used operationally rather than only retained losslessly; and
6. a durable source-event-to-native-transaction crosswalk so reconciliation and
   idempotency do not depend only on the local sync-state database.
