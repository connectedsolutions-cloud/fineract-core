# Membership and share-capital migration service

## Status

- Registry status: `available`
- Executable: `true`
- CLI block: `membership-share-capital`
- Dependency: migrated Fineract clients keyed by `AFI_SOCIO.NUMERO_AFILIACION`
- Target: `credesal_member_profile` and `credesal_arissto_membership_record`

The narrowed current-party contract completed local re-acceptance on
2026-08-26. Plan `47dee8bef987401caa8dfd42b32201e6` applied 66,374
in-scope records. Run `d058e51a5257444f8e6c1f45bbb2fb2a` reconciled all
66,374 exactly with no failure, quarantine, linkage issue, or mismatch. Final
plan `156557aa4a8e4e8385aace42ad02cbfa` classified all 66,374 as
`unchanged`. Older out-of-scope archive rows remain preserved and are not
deleted. This acceptance authorizes only the preservation service; native
financial shares remain separately gated.

## What is migrated

The service covers the 40 reviewed Arissto tables listed in
[`config/membership_share_capital.json`](../../config/membership_share_capital.json):

- member identity, relationship/lifecycle catalogs, and status history;
- current common/preferred share positions and share-type configuration;
- certificates, beneficiaries, states, operations, cancellation reasons, daily
  and monthly histories, and annual yields;
- contribution movements, designed movement detail, annual/period snapshots,
  contribution types, accounting rules, and payment channels;
- dividend configuration, calculations, discounts, movements, and yield rates;
- share emissions and books;
- withdrawal design and catalogs;
- cooperative governing bodies and their sparse membership;
- external-membership/standalone-shareholder designs; and
- the current-party membership subset of the cross-domain operation log and
  its six applicable type-catalog rows.

Empty but relevant designed tables remain in inspection and in the contract, so
future population becomes visible rather than silently falling outside scope.
`AFI_FAMILIAR_DIRECTIVO` and legacy `APORTE` are inspection-only because they
are empty and their ownership/identity contracts are not yet reliable.

`OPR_OPERACIONES` is intentionally narrower than the source research corpus.
Only operation types `4`, `5`, `6`, `10`, `60`, and `61` whose
`ID_ASOCIADO` resolves to the current `AFI_SOCIO` master are migrated. The
reviewed snapshot contained 380 such rows. Another 2,699 rows used unresolved
legacy associate IDs; they remain in Arissto for research and are not copied to
Fineract. This is a scope decision, not a claim that those rows are tests.
Credesal confirmed that `PLUS SILVER`, `PLUS PLATINUM`, and `PLUS INFINITE` are
irrelevant identifiers that it does not manage. Their nine opening/transaction
rows are excluded explicitly by normalized product name, independently of the
current-party rule, and are never treated as common/preferred shares.

The typed current member profile includes only reviewed cooperative relationship
codes (`001`, `004`, `006`, `007`). Current Arissto data has 40 `001/SOCIO`
rows. The 990 `003/CLIENTE` parties are not mislabeled as cooperative members.

Source meaning and evidence remain in
[`credesal-db-space/docs/learnings/membresia-aportaciones-y-participaciones.md`](../../../../../../credesal-db-space/docs/learnings/membresia-aportaciones-y-participaciones.md).
Migration behavior is defined in [`contract.md`](contract.md).
The ordered schema, prerequisite, native-engine, acceptance, and production
work is maintained in [`implementation-sequence.md`](implementation-sequence.md).
The active cross-service defect, reconciliation, retest, and handoff queue is
maintained in [`membership-reconciliation.md`](membership-reconciliation.md).

## Destination model

Tenant migration `0281_add_arissto_membership_archive.xml` adds:

- `credesal_member_profile`: a one-to-one, registered `m_client` Person
  datatable containing lifecycle dates/statuses and current share, certificate,
  and contribution summaries; and
- `credesal_arissto_membership_record`: a normalized archive with stable source
  identity, record kind, optional client link, effective date, exact canonical
  payload, and deterministic hash.

Every column returned by each migrated Arissto table is retained in
`source_payload`, including PII and financial fields. Plans and command output do
not include these payloads. This prevents data loss without inventing an
incorrect native Fineract meaning for legacy-specific fields.

Tenant migration `0283_add_credesal_share_migration_support.xml` prepares the
next native phase without modifying Fineract core tables. It adds explicit
common/preferred subscribed and paid quantities to the member profile, a
queryable current-certificate projection, its beneficiary child records, and a
durable source-event-to-native-transaction crosswalk. The current preservation
service populates the new profile quantities after that migration is applied;
certificate projection and native-event mappings are owned by the separate
`native-share-capital` service.

## Native Fineract shares

Native share-account creation is implemented by the separate, available
`native-share-capital` service. Fineract requires a
real, active savings-deposit account owned by the same client for each share
account. This requirement remains unchanged even though individual Arissto
dividends are not migrable. Creating dummy savings accounts, attaching
unrelated accounts, using fixed-term deposits, or making the native
relationship optional would corrupt Fineract product meaning.

The savings domain is therefore a hard prerequisite, not a convenience for
shares. It must first migrate the real Arissto savings products, ownership,
accounts, movements, interest postings, and accrual state through Fineract's
native savings logic and reconcile them independently. The source audit finds
active `VISTA` accounts for 34 of the 40 shareholders. They can support 45 of
57 current share accounts after savings reconciliation. The other six
shareholders account for 12 share accounts and remain blocked until the
business legitimately opens an eligible savings account. The share service
must never create that account implicitly.

The source lifecycle has now been separated into institutional membership,
share-class position, certificate document, and financial transaction events.
Current Arissto data contains 17 socios with common and preferred positions and
23 with preferred positions only; there are no current common-only socios.
Historical monthly data also contains former positions, but certificate IDs are
reused and disappearance from the current master is not sufficient evidence for
a native redemption.

The evidence grades and implemented native commands are maintained in
[`lifecycle.md`](lifecycle.md). The native projection uses paid shares—not
subscribed shares—as Fineract approved/purchased shares,
must keep membership/client status independent from each share account, and
must quarantine inferred closures that lack a dated financial event.

The registry dependency is intentionally one-way:
`clients → membership-share-capital → native-share-capital`. Native shares also
depends on `savings-deposits`; membership preservation does not. Membership and
savings may run in either order after clients, but both must reconcile before
native shares. The complete manual order is documented in
[`orchestration.md`](../orchestration.md#current-manual-membership-to-native-shares-flow).

## Operating workflow

```bash
./arissto-sync preflight --target local
./arissto-sync inspect --block membership-share-capital --target local
./arissto-sync plan --block membership-share-capital --target local
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync status --block membership-share-capital --target local
```

Use `--source-key` only with the canonical `TABLE|KEY_PART...` source identity.
Review every plan. Production requires an independent production inspection and
plan plus the exact production fingerprint confirmation.
