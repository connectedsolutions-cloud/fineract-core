# Employee profile migration contract

## Identity and ownership

The Arissto employee identity is the declared `PERSONAS_EMPRESA` key:

```text
ID_EMPRESA:ID_PERSONA
```

The exact composite string is both the sync-engine source key and Fineract
`m_staff.external_id`. It is not prefixed and does not use name, DUI, user ID,
or office as identity.

The service writes through the Fineract staff and datatable APIs only.
PostgreSQL access is read-only and is used for schema readiness, collision
detection, planning, and reconciliation. Arissto remains strictly read-only.

## Field mapping

| Arissto | Fineract staff | Rule |
|---|---|---|
| `ID_EMPRESA:ID_PERSONA` | `externalId` | Trim both components and join with `:` |
| `NOMBRE_PERSONA` | `firstname` | Required, trimmed, maximum 50 characters |
| `APELLIDO_PERSONA` | `lastname` | Required, trimmed, maximum 50 characters |
| `ID_ESTADO_PERSONA=01` | `isActive=true` | `ACTIVO` |
| `ID_ESTADO_PERSONA=02` | `isActive=false` | `INACTIVO` |
| `PERSONAS_SUCURSAL.ID_SUCURSAL` | `officeIds=[officeId]` | Preferred office; `001 -> 1`, `002 -> 2` |
| `PERSONAS_EMPRESA.ID_SUCURSAL` | `officeIds=[officeId]` | Fallback only when no assignment row exists |
| `FECHA_INGRESO` | `joiningDate` | Preferred date source |
| `PERSONAS_SUCURSAL.FECHA_INICIO` | `joiningDate` | Fallback only when `FECHA_INGRESO` is null |
| `2020-10-01` | `joiningDate` | Final fallback when both legacy dates are null; common Arissto assignment-snapshot date |
| first populated of `TELEFONO`, `TELEFONO1`, `TELEFONO2` | `mobileNo` | Trimmed, maximum 50 characters |
| `EMAIL` | `emailAddress` | Trimmed, maximum 150 characters |

Fineract derives `display_name` as `lastname, firstname`. The planner checks
for a collision before any write because `m_staff.display_name` is unique.

The API receives `officeIds` rather than only `officeId`, so an update makes
the reviewed Arissto office set exact in `m_staff_office`. The current contract
supports exactly one office per employee.

Tenant migration `0280_add_arissto_staff_profiles.xml` exposes staff email in
the Fineract API, permits duplicate staff phone values found in Arissto, and
registers `credesal_staff_profile` as a one-to-one `m_staff` datatable. Every
`PERSONAS_EMPRESA` column is preserved there, including fields also promoted
to core, so the original profile remains queryable without inventing mappings.
The destination includes salary, bank account, DUI/NIT/NUP/ISSS, AFP,
birth/residence, address, emergency-contact, employment type, job, civil
status, and legacy role flags as data—not as Fineract permissions.

The same profile stores selected `USUARIO` account metadata needed for a later
user migration: legacy user ID/login, type/status, lock state, failed attempts,
password date, phone, sex, DUI, and initials.

## Explicit exclusions

`PERSONAS_EMPRESA.ID_USUARIO` and `dbo.USUARIO` still do not create Fineract
application users. A staff member and an application user are separate
Fineract resources. `m_appuser.staff_id` is their link. Creating an app user
requires office IDs, at least one role, email, names, username, and either a
new policy-compliant password or password delivery by email. Account creation
therefore requires a later permissions/security contract.

`PROMOTOR`, `EJECUTIVO_CUENTA`, and `GESTOR_COBRO` are preserved in the profile
but do not assign clients or loans. `isLoanOfficer` remains new-system-owned
and omitted from core create/update payloads.

Arissto `PASSWORD`, `USER_GROUP`, `GRUPO`, `TIPO_ACCESO`, `AUT_*`, and other
permission flags are deliberately prohibited by contract validation. Legacy
password material is not compatible with Fineract password policy/encoding,
and copying permission flags without a reviewed role model would create an
authorization risk.

## Readiness checks

`inspect --block employees` verifies:

- required source tables and columns;
- unique `ID_EMPRESA:ID_PERSONA` extraction;
- source-level per-row issue counts without returning personal values;
- `m_staff`, `m_staff_office`, and every `credesal_staff_profile` column;
- unique Fineract external-ID and display-name constraints;
- configured target offices;
- `credesal_staff_profile` registration against `m_staff`;
- absence of the legacy-incompatible unique-mobile constraint;
- staff and staff-profile read/create/update permissions (or `ALL_FUNCTIONS`); and
- a destination schema signature stored on the plan.

Per-row source problems do not block valid employees. They become quarantine
actions. Missing schema, mappings, constraints, offices, target PostgreSQL, or
permissions are global blockers and make a plan non-applicable.

## Quarantine policy

An employee is quarantined when any of these conditions holds:

- missing/invalid composite identity;
- duplicate composite identity from multiple assignment rows;
- missing or over-length first/last name;
- unknown employee lifecycle status;
- absent or unmapped office after checking assignment and profile branch;
- lifecycle-inconsistent populated office assignment;
- target external-ID/mapping collision; or
- target display-name collision.

No name suffix or identity is invented. The reviewed office and date fallbacks
exist specifically to preserve the complete historical employee roster:

- use `PERSONAS_EMPRESA.ID_SUCURSAL` only when the declared assignment row is
  entirely absent; and
- use `2020-10-01`, the common legacy assignment-snapshot date, only when both
  employee and assignment dates are null.

The 2026-08-21 source audit found 40 employee profiles. All names fit Fineract,
no duplicate display names exist, and all 40 pass the reviewed contract after
the deterministic fallbacks above. Twenty-one use the legacy snapshot-date
fallback. One inactive employee has no assignment row and therefore uses its
populated profile branch `001`.

Thirteen profiles have a primary phone, none currently has email, and 38 link
to a resolved `USUARIO` row with a login. Sparse or blank values remain null in
the profile; populated sensitive fields are retained exactly after whitespace
normalization and date/number conversion.

## Planning, apply, retry, and reconciliation

Plans contain only source keys, normalized hashes, coarse actions/reasons, and
target IDs. They never contain names or payloads.

Immediately before each create/update, apply re-reads the exact source key and
requires the hash to match the plan. Create recovery searches the staff list by
the exact external ID, making interrupted creates retry-safe. There are no
delete operations.

Reconciliation re-reads Arissto and PostgreSQL and requires exact agreement for
the legacy-owned fields:

- external ID;
- first and last name;
- active status;
- joining date;
- primary office;
- the one-row `m_staff_office` assignment set;
- mobile and email; and
- every mapped `credesal_staff_profile` value.

`isLoanOfficer` and excluded fields do not participate in equality. A second
plan after successful reconciliation must classify the same scope as
`unchanged`.

## Local acceptance

On 2026-08-21, local plan `871eb47a1b774fa187cd27f4dba1808f`
created all 40 employees. Run `41190909f1c94de78bfc58104c4240ab`
reconciled 40 exact matches with no failure or quarantine. Follow-up plan
`c93716ce729541cbaedf654369b34615` classified all 40 as `unchanged`, proving
the full block idempotent. The registry is therefore `available` and
`executable: true`.

Production still requires an independent inspection and plan against the
production fingerprint plus the explicit production confirmation guard.
