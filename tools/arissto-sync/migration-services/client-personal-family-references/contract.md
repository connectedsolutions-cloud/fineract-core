# Client personal and family references migration contract

## Outcome

Represent both selected Arissto related-person sources in native Fineract
`m_family_members` while keeping their meanings distinguishable:

- `AFI_REF_PERSONAL_SOCIO` → `isFamilyMember=false`;
- `AFI_FAMILIA_SOCIO` → `isFamilyMember=true`.

This is a separate service from the already accepted
`client-family-references` migration for `AFI_REF_FAMILIAR_SOCIO`, preserving
that service's durable identities and replay evidence.

## Dependency and ownership

The service depends on `clients`. Both sources join to `AFI_SOCIO` by
`ID_EMPRESA + ID_SUCURSAL + ID_SOCIO`; joined `NUMERO_AFILIACION` resolves the
existing Fineract `m_client.external_id`. Missing or ambiguous owners quarantine
the row. Names are never used as owner identity.

## Durable identities

| Source | Sync source key | Fineract external ID |
|---|---|---|
| `AFI_REF_PERSONAL_SOCIO` | `personal:<NUMERO_AFILIACION>:<ID_REF_SOCIO>` | `arissto:afi_ref_personal:<NUMERO_AFILIACION>:<ID_REF_SOCIO>` |
| `AFI_FAMILIA_SOCIO` | `family:<NUMERO_AFILIACION>:<ID_FAMILIA_SOCIO>` | `arissto:afi_familia_socio:<NUMERO_AFILIACION>:<ID_FAMILIA_SOCIO>` |

The namespaces prevent collisions between tables and leave existing
`arissto:afi_ref_familiar:*` identities unchanged.

## Mapping

### Personal references

| Arissto | Fineract | Rule |
|---|---|---|
| `NOMBRE_REF_SOCIO` | `firstName` | Preserve the full trimmed source name; do not infer surname boundaries. |
| `TELEFONO`, `TELEFONO2` | primary/secondary mobile | Preserve trimmed values. |
| `DIRECCION` | `address` | Preserve trimmed plain text. |
| `TIPO_REFERENCIA` | `sourceRelationship` | Preserve the source category for display/audit. |
| no established kinship | `relationshipId` | Resolve the bootstrapped `Sin especificar` value. |
| source table classification | `isFamilyMember` | Always `false`. |

`MONTO`, `CUOTA`, `SALDO`, `ACTIVO`, opening/cancellation dates, and
`LIQUIDAR_CREDITO` describe the source's financial-reference assessment. They
are intentionally not converted into family attributes. They remain source-only
until a separate KYC/liability destination is approved.

### Detailed family rows

| Arissto | Fineract | Rule |
|---|---|---|
| `NOMBRE_FAMILIAR` | `firstName` | Preserve trimmed value. |
| `APELLIDO_FAMILIAR` | `lastName` | Preserve trimmed value. |
| `TELEFONO_PERSONAL`, `TELEFONO_TRABAJO` | primary/secondary mobile | Preserve trimmed values. |
| `DIRECCION_PARTICULAR` | `address` | Preserve trimmed plain text. |
| `PARENTESCO` or catalog fallback | relationship and `sourceRelationship` | Prefer nonblank free text; otherwise use `AFI_RELACION_FAMILIAR.RELACION_FAMILIAR`. Resolve through the reviewed mapping. |
| `FECHA_NACIMIENTO` | `dateOfBirth` | Preserve date without time. |
| `DEPENDIENTE_ASOCIADO` | `isDependent` | Strict nullable boolean conversion. |
| source table classification | `isFamilyMember` | Always `true`. |

Identity documents, geography, occupation/employer, income, nationality, and
economic-profile fields require their own reviewed destinations and are not
silently copied into unrelated native fields.

## Planning and safety

- `create` when neither durable external ID nor mapping exists.
- `update` when the durable target exists and the normalized payload changed.
- `unchanged` when every mapped field and owner matches.
- `quarantine` for invalid identity, missing name/owner, unresolved family
  relationship, conflicting mapping, invalid date, or invalid dependent flag.
- stale mappings are reported; source absence never deletes a target row.

Plans and state contain keys, hashes, target IDs, and non-PII reason codes only.
Arissto remains read-only and all Fineract writes use the family-member API.

Apply loads the selected source cohort and the target client/external-ID indexes
once, then performs the required API writes sequentially. Reconciliation also
bulk-loads source and client identity. It reads each recorded child through the
family-member API because Fineract does not expose a tenant-wide native family
member listing endpoint.

## Readiness and reconciliation

Readiness requires both source schemas, the owner join, target schema including
`is_family_member`, unique family-member external IDs, required permissions,
relationship catalog values, and exact owner resolution.

Reconciliation re-extracts the source and verifies the target ID, owner,
external ID, names, phones, address, relationship, birth date, dependency, and
family/personal flag through the API.

## Availability gate

The current source contains 4,195 personal-reference rows for 1,013 owners;
`AFI_FAMILIA_SOCIO` currently contains zero rows. Controlled sandbox run
`f4c1a333098444a4bcea324b06dc18d0` created and exactly reconciled all 4,195
personal-reference rows, and follow-up plan
`79b8c1e5a05e4aaaaf5696ef5054837a` classified the full cohort as unchanged.
The service is therefore `available`. The empty detailed-family path is
schema-tested but must be reaccepted when source rows first appear.
