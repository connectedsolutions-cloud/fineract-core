# Client family references migration contract

## Outcome

Migrate each populated Arissto personal/family reference to the existing
Fineract client that owns it, without treating the reference as a complete
household member, beneficiary, dependent, or independent Fineract client.

The operator-facing destination is Fineract's native family-member resource
(`m_family_members` and `/clients/{clientId}/familymembers`) because the
Credesal frontend already presents that resource as **Referencias Personales y
Familiares**. A generic client datatable would preserve fields more quickly but
would leave the existing references tab empty and create two competing models.

## Verified source and pre-migration target state (2026-08-14)

### Source

- `AFI_REF_FAMILIAR_SOCIO` contains 1,960 rows for 997 parties.
- The population spans both current Arissto relationship classifications:
  1,929 references for 976 `CLIENTE` parties and 31 references for 21 `SOCIO`
  parties. Neither classification is excluded by this service.
- Every reference resolves to `AFI_SOCIO` through the declared
  company/branch/socio foreign key.
- The stable relational row key is the owning party plus `ID_REF_FAM`; the
  latter is a per-party slot with values 1, 2, or 3, not a global person ID.
- All rows have a name, 1,939 have relationship text, 1,937 have a primary
  phone, 14 have a second phone, and 1,952 have an address.
- `NO_SOLICITUD` is blank in every row.
- The single full-name field cannot be split reliably: current values range
  from one to six whitespace-delimited words.
- One owner has two references with the same normalized name, so name alone is
  not a safe target identity. No duplicate was found on owner, normalized name,
  relationship, and primary phone, but mutable content is still not a durable
  identity.

### Local Fineract target before implementation

- All 997 source owners currently resolve to Fineract clients through their
  joined `AFI_SOCIO.NUMERO_AFILIACION` and `m_client.external_id`.
- `m_family_members` exists and currently contains zero rows.
- It stores client, name parts, qualification, relationship, marital status,
  gender, birth date, age, profession, mobile number, and dependency flag.
- It does not store an external/source ID, address, second phone, or original
  free-text relationship.
- It has only a generated primary key and no uniqueness constraint that can
  recover a source mapping after sync-state loss.
- The family-member API and READ/CREATE/UPDATE/DELETE permissions are present.
- The current `RELATIONSHIP` options are Padre, Hermano, Familiar, Amigo,
  Compañero trabajo, and hijo. They are too coarse to preserve the observed
  source vocabulary without an explicit canonical mapping.

## Identity and ownership

### Parent client

Extraction must join the source child row to `AFI_SOCIO` using:

```text
AFI_REF_FAMILIAR_SOCIO.ID_EMPRESA  = AFI_SOCIO.ID_EMPRESA
AFI_REF_FAMILIAR_SOCIO.ID_SUCURSAL = AFI_SOCIO.ID_SUCURSAL
AFI_REF_FAMILIAR_SOCIO.ID_SOCIO    = AFI_SOCIO.ID_SOCIO
```

The joined `AFI_SOCIO.NUMERO_AFILIACION` is the canonical client key. The
writer resolves it through the existing clients mapping or exact Fineract
`externalId`. A bare child-table `ID_SOCIO` must never be treated as the
cross-service identity.

Fineract uses `m_client` as the technical parent for both imported Arissto
`CLIENTE` and `SOCIO` records. References are therefore linked to the resolved
Fineract client regardless of the current Arissto classification; the
classification remains owned by the existing clients service and its
`tipo_cliente` tag.

### Reference row

Canonical source key:

```text
<NUMERO_AFILIACION>:<trimmed ID_REF_FAM>
```

Target external ID:

```text
arissto:afi_ref_familiar:<NUMERO_AFILIACION>:<ID_REF_FAM>
```

The target must enforce uniqueness for this value. Planning must resolve both
the current local mapping and the target external ID and quarantine any case
where they point to different family-member rows.

`ID_REF_FAM` behaves as a current reference slot. If the contents of a slot
change, the service updates the same target entity. It does not claim to
preserve historical occupants of that slot.

## Source-to-target mapping

| Arissto source | Proposed Fineract destination | Rule |
|---|---|---|
| joined `NUMERO_AFILIACION` | `m_family_members.client_id` | Resolve the existing client; missing or ambiguous owner quarantines the row. |
| joined affiliation + `ID_REF_FAM` | new `external_id` | Deterministic legacy-owned identity; immutable after create. |
| `NOMBRE_FAMILIAR` | `firstname` | Preserve the complete trimmed source name in one field; do not guess surname boundaries. |
| no verified source | `middlename`, `lastname` | Null; the UI must allow the unsplit full-name representation. |
| `TELEFONO` | `mobile_number` | Trimmed legacy-owned primary phone. |
| `TELEFONO2` | new `secondary_mobile_number` | Preserve when populated. |
| `DIRECCION` | new `address` | Preserve as legacy-owned plain text. |
| `PARENTESCO` | `relationship_cv_id` | Resolve through an explicit normalized mapping; never hard-code target IDs. |
| `PARENTESCO` | new `source_relationship` | Preserve the exact trimmed original text for audit and unmapped-value review. |
| no verified source | `gender_cv_id` | Null; do not infer gender from a gendered relationship word or name. |
| no verified source | `is_dependent` | Null; being a reference does not prove dependency. |
| no verified source | marital status, profession, qualification, birth date, age | Null. |
| `NO_SOLICITUD` | none | Excluded because it is blank in all current rows. |

All migrated fields are legacy-owned. Target-generated database IDs remain
new-system-owned and must never be copied between environments.

## Implemented Fineract changes

Implement these beside the versioned Fineract Liquibase migrations and API
code; this contract is not a second schema source of truth.

1. `m_family_members` is extended with a unique `external_id`, address, secondary
   phone, and original relationship text.
2. Those fields are exposed in create, read, and update API payloads.
3. Optional create and update fields preserve explicit nulls instead of turning
   unknown facts into empty strings or `false`.
4. The update path uses the consistent `relationshipId` property.
5. Nullable numeric and code-value updates use null-safe handling.
6. The deserializer throws accumulated validation errors.
7. The versioned relationship bootstrap and unique external-ID constraint are
   applied through normal Fineract Liquibase startup.

The Credesal frontend already reads the native resource. Displaying every
preserved audit field and improving manual editing for unknown surname/gender
remain UI enhancements outside the sync service's availability gate.

Direct SQL writes remain disallowed. The sync writer must use the Fineract API.

## Relationship catalog contract

The source relationship is free text with spelling, accent, abbreviation, and
gender variants. The existing six target values are insufficient for lossless
semantic display.

A versioned target bootstrap must define reviewed canonical relationship
values and a configuration mapping from normalized source strings to semantic
names. At minimum, the mapping must distinguish parent, child, sibling,
spouse/partner, grandparent, grandchild, aunt/uncle, niece/nephew, cousin,
in-law, friend, and other family/related person when supported by observed
source values.

Target code-value IDs must be resolved independently in local and production.
Unknown nonblank source relationships quarantine the row until mapped; blank
source relationships require an explicit `Unknown/Not provided` business
decision before apply. The original text is preserved regardless of mapping.

## Planning and action rules

- `create`: target external ID and mapping are absent.
- `update`: the target external ID or existing current mapping resolves one row
  and the normalized payload hash changed.
- `unchanged`: target resolution succeeds and the normalized hash matches.
- `quarantine`: missing owner, owner collision, external-ID collision, missing
  required name, unresolved relationship, or invalid target catalog state.
- `stale-source`: a previously mapped target row is absent from the current
  source. Report it for review; never delete it automatically.

Plans and state store only source keys, hashes, action classifications, and
target IDs. They must not store names, phones, addresses, or payloads.

## Inspection readiness

`inspect` must remain not-ready unless all of the following pass:

- required source tables and columns exist;
- the Arissto login remains read-only;
- every source row joins to exactly one `AFI_SOCIO` and has one affiliation
  number;
- canonical reference source keys are unique;
- the target family-member schema and API extensions exist;
- required family-member permissions exist for the API user;
- required relationship values exist, are active, and are unambiguous;
- existing target external IDs are unique;
- target external IDs and local mappings do not conflict; and
- every scoped owner resolves to exactly one current Fineract client.

## Reconciliation

For every successful action, reconciliation must verify through the API and,
when PostgreSQL inspection is configured, the database:

- target external ID and generated target ID;
- exact owning `client_id`;
- exact preserved full name, phones, address, and source relationship;
- resolved relationship semantic value;
- null treatment for unknown gender, dependency, and other absent fields; and
- normalized payload hash.

The controlled local acceptance set must include clients with one, two, and
three references; missing relationship; missing phone; second phone; accented
relationship variants; multiword names; and the observed same-owner duplicate
name case.

Acceptance requires:

1. the reviewed scoped plan creates or updates exactly the intended rows;
2. no unrelated client or family-member row changes;
3. a second plan is entirely unchanged;
4. deleting local mapping state still recovers the same target rows through
   external IDs without creating duplicates; and
5. retrying a partial failure does not repeat successful writes.

## Deferred scope

`AFI_FAMILIA_SOCIO` remains a separate future decision. If it becomes
populated, its detailed household-member semantics and richer fields must be
inspected independently. It must not be silently unioned with references.

Beneficiary tables also remain separate services because their percentages and
product/legal ownership have different reconciliation requirements.

## Implemented client-flow integration

`client-family-references` is an available service with a declared dependency
on `clients`. Standalone plan/apply/reconcile remains supported. The opt-in
client workflow `apply --with-family-references` adds ordered orchestration:

```text
client apply → client reconcile → owner-scoped family plan
             → family apply → family reconcile
```

The family step receives only exact `NUMERO_AFILIACION` keys whose client run
items succeeded or were unchanged. It never derives ownership from names or
target-generated IDs. A client reconciliation failure stops the chain, normal
client apply remains independent, and production confirmation applies to both
services.
