# Membership and share-capital migration contract

## Principles

This service separates preservation from interpretation:

1. preserve every populated column from every approved source record;
2. promote only well-understood current-member fields into typed columns;
3. never replay snapshots as transactions;
4. never infer dividends, redemptions, or governance membership from empty or
   sparse structures; and
5. never create native Fineract products/accounts until their mandatory business
   dependencies can be mapped truthfully.

Lifecycle interpretation is additionally governed by
[`lifecycle.md`](lifecycle.md). Institutional membership, each share-class
position, certificate state, and financial transactions are separate state
machines. No one state machine may silently drive another.

Arissto is strictly read-only. There are no delete operations in Fineract.

## Identity and client ownership

Each archive identity is:

```text
SOURCE_TABLE|KEY_PART_1|KEY_PART_2|...
```

Key parts come only from the reviewed contract and escape `%` and `|`.
`AFI_SOCIO` uses its declared `(ID_EMPRESA, ID_SUCURSAL, ID_SOCIO)` key.
Other tables use their declared/supported primary or stable composite key.

The cross-domain `OPR_OPERACIONES` table is filtered to membership operation
types `4`, `5`, `6`, `10`, `60`, and `61`, and only when `ID_ASOCIADO`
resolves to the current `AFI_SOCIO` master. `OPR_TIPO_OPERACION` is filtered to
the same six catalog rows. Unresolved legacy operation rows are not migrated,
do not create client-less archive records, and remain available only in the
read-only Arissto research source. This exclusion does not classify them as
tests; it classifies them as outside the current-party migration boundary.
The normalized product names `PLUS SILVER`, `PLUS PLATINUM`, and `PLUS
INFINITE` are an additional unconditional exclusion confirmed by Credesal.
They must not migrate even if a future row happens to resolve to a current
associate.

Where a relationship is reliable, the archive row links to `m_client.id` by
the owning member's `AFI_SOCIO.NUMERO_AFILIACION = m_client.external_id`.
Global catalogs/configuration and unresolved historical records retain a null
client link. A missing client quarantines the typed member summary, but does not
discard a historical/archive record. Two accepted historical rows are retained
without a current-client link.

## Complete field preservation

The engine executes `SELECT *` for each allowlisted source table. Values are
canonicalized as follows before storage and hashing:

- SQL decimal values become exact decimal strings;
- dates/timestamps become ISO values;
- binary values become hexadecimal;
- null remains null;
- integers and booleans retain their JSON types; and
- all keys are sorted for deterministic JSON and hashing.

The `TEXT` payload is portable across Fineract's supported databases and avoids
having the Liquibase migration depend on PostgreSQL-only JSON types. The
contract hash participates in each record hash, so a mapping-contract change
forces explicit re-planning and update classification.

## Typed member profile

`credesal_member_profile` stores the reviewed current view:

- Arissto associate/company/branch/member IDs and affiliation number;
- relationship and lifecycle status IDs/descriptions;
- request, initial-entry, entry, approval, withdrawal, and last-contribution
  dates plus entry/withdrawal reasons and entry type;
- current common/preferred share counts and balances;
- subscribed and paid certificate counts/balances and certificate count; and
- contribution movement count and amount.

Migration 0283 additionally exposes certificate-derived
`common_subscribed_share_count`, `common_paid_share_count`,
`preferred_subscribed_share_count`, and `preferred_paid_share_count`.
The older `preferred_share_count` remains the legacy
`AFI_ACCION.NUMERO_ACCIONES` aggregate and is not a native approved-share
quantity.

Summary amounts come from current `AFI_ACCION`, `AFI_CERTIFICADO`, and
`MOV_APORTACIONES`; histories and annual/period snapshots are retained in the
archive and are not double-counted as transactions.

For a future native-share projection, `AFI_ACCION.NUMERO_ACCIONES` and
`AFI_CERTIFICADO.ACCIONES_SUSCRITAS` are not automatically approved Fineract
shares. Native approved/purchased shares must reconcile to paid shares and paid
capital. Unpaid subscription remains extension/archive data until Fineract has
a truthful pending-subscription mapping.

Certificate history must use at least
`(ID_CERTIFICADO, ID_ASOCIADO, ID_TIPO_ACCION, ID_PERIODO)` for comparison.
`ID_CERTIFICADO` alone is prohibited as a historical mapping key because
Arissto reuses certificate numbers across associates and products.

## Native lifecycle safety boundary

The current archive service still has no permission to write native share
tables. A later native service must use Fineract APIs and obey these rules:

- a current exact `AFI_ACCION` position is eligible for a share account only
  after client, share-product, dividend-savings-account, and accounting
  prerequisites pass;
- `MOV_APORTACIONES` purchases may become native purchase transactions only
  when their member, share class, certificate, paid-share quantity, amount,
  date, and balance reconciliation agree;
- a partial capital return maps to `redeemshares`; a proven full return maps to
  share-account `close`, which itself creates the full redemption transaction.
  Fineract derives that close transaction's unit price from product market
  price, so the command is prohibited unless that price equals the source event;
- certificate `ANULADO` does not by itself reverse paid capital. It may map to
  rejection only while the native purchase/application is still pending and
  only when no paid capital exists;
- disappearance from `AFI_ACCION`/`AFI_CERTIFICADO`, a monthly snapshot gap, or
  a change from `SOCIO` to `CLIENTE` must never fabricate a redemption;
- Fineract has no supported native share-transaction reversal command. Source
  correction/reversal events therefore quarantine unless their economic effect
  is independently proven to be a new redemption/purchase event; and
- Arissto transfer/sale events require both holder legs. Fineract has no atomic
  holder-to-holder share transfer, so a proven transfer would require linked
  source redemption and destination purchase commands plus preserved transfer
  correlation. An unmatched leg quarantines.

Closing a share account does not deactivate the Fineract client or close a
different share-class account. Client deactivation is owned by the client
lifecycle contract and requires its own evidence.

Migration `0283_add_credesal_share_migration_support.xml` creates
`credesal_share_certificate`, `credesal_share_certificate_beneficiary`, and
`credesal_share_native_event_map`. These are Credesal extension tables, not
permission for this preservation service to issue native share commands. The
event map records API results for durable idempotency; it must never be used to
insert or alter a core share transaction directly.

## Exceptional direct SQL boundary

Fineract has no API for the generic archive, and API-per-row datatable writes
would create tens of thousands of calls. Direct PostgreSQL writes are therefore
approved only for the operation
`membership-share-capital.upsert_membership_archive` and only into the two
versioned Credesal extension tables. Statements are parameterized, use stable
`ON CONFLICT` identities, and commit in bounded 500-record transactions.

The allowlist does not permit writes to Fineract core share, savings, client,
accounting, or transaction tables. A batch failure rolls back the whole batch
and journals non-sensitive error types for retry.

## Readiness and planning

Inspection verifies all configured source tables, key/effective-date columns,
the complete destination column sets, client/share/savings prerequisites, and
the archive uniqueness constraint. The schema signature hashes source column
names/types and target schema—not live row counts—so ordinary source activity
does not invalidate a plan. Exact per-record hashes still prevent applying data
that changed after planning.

Plans contain source keys, hashes, action/reason, target ID, and client ID only.
No PII or source payload is placed in the plan or command output. Duplicate
source keys, destination identity collisions, and missing typed-profile clients
are quarantined.

## Apply, retry, and reconciliation

Immediately before apply, the engine re-checks target fingerprint, source
fingerprint, contract hash, production confirmation, and schema signature. It
re-reads planned source rows and requires their hashes to match. Upserts make
retries safe; target writes and local audit state are journaled per batch.

Reconciliation re-reads Arissto and requires exact agreement for source table,
key, client link, canonical payload, and hash. Member summaries additionally
require the typed profile hash to match. A successful second full plan must be
entirely `unchanged` unless new Arissto rows legitimately arrived.

## Prior local acceptance

On 2026-08-21, migration 0281 was applied by normal Fineract startup. Full plan
`641d8d36b1ae4df3918e1bd300cccc74` contained 68,800 creates and no issues.
Run `f410af8b724549f594976d54cd2c4573` succeeded for 68,800 records; exact
reconciliation matched all 68,800 with no failure/quarantine/mismatch. Plan
`2a05afe0a6bc4049bd959b50a9da39dd` then classified all 68,800 as unchanged
under the final constraint/permission-aware schema signature.

This acceptance predates the current-party `OPR_OPERACIONES` filter. The
contract hash has changed and the service is blocked pending a new controlled
local plan, apply, and exact reconciliation. Production is still prohibited
without that acceptance plus independent production inspection, planning,
review, and exact target-fingerprint confirmation.
