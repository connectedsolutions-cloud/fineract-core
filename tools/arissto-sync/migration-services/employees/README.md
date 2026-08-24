# Employees migration service

## Status

- Registry status: `available`
- Executable: `true`
- CLI block: `employees`
- Canonical source identity: `ID_EMPRESA:ID_PERSONA`
- Source tables: `dbo.PERSONAS_EMPRESA`, `dbo.PERSONAS_SUCURSAL`, `dbo.USUARIO`
- Target resources: Fineract staff API / `m_staff` and `credesal_staff_profile`

Local acceptance completed on 2026-08-21. Full plan
`871eb47a1b774fa187cd27f4dba1808f` created 40 staff/profile records in the
local target. Run `41190909f1c94de78bfc58104c4240ab` reconciled all 40 exactly,
with no failure or quarantine, and follow-up plan
`c93716ce729541cbaedf654369b34615` classified all 40 as `unchanged`.

## Business scope

This block creates or updates the main Fineract staff list from Arissto employee
profiles. It owns:

- employee source identity and Fineract `externalId`;
- first and last name;
- active/inactive lifecycle;
- one current or retained office assignment, falling back to the profile branch
  only when the assignment row is absent;
- joining date, using the reviewed source dates and legacy snapshot fallback;
- primary phone and email in Fineract staff core fields; and
- the complete `PERSONAS_EMPRESA` profile in the one-to-one
  `credesal_staff_profile` extension, including identity, HR, payroll, bank,
  pension, social-security, address, emergency-contact, and classification
  fields.

The extension also retains non-permission login metadata for the 38 linked
legacy users: user ID, login name, user type/status, lock state, failed-attempt
count, password date, phone, sex, DUI, and initials.

It explicitly excludes:

- Fineract application-user creation;
- legacy password hashes and permission/group flags;
- client, loan, promoter, executive, and collections assignments;
- `isLoanOfficer` management.

Fineract stores a login separately in `m_appuser` and links it to the employee
with `m_appuser.staff_id`. Its create API requires at least one role and either
a new validated password or email-based password delivery. Therefore the
employee-profile service does not create login accounts while roles and
permissions remain outside the approved scope. Arissto `PASSWORD` is never
read by this service and cannot be reused as a Fineract password.

Arissto source meaning and evidence remain in
[`credesal-db-space/docs/learnings/empleados.md`](../../../../../credesal-db-space/docs/learnings/empleados.md).
The detailed migration decisions are in [`contract.md`](contract.md).

## Safe preparatory commands

```bash
./arissto-sync preflight --target local
./arissto-sync inspect --block employees --target local
./arissto-sync plan --block employees --target local \
  --source-key ID_EMPRESA:ID_PERSONA
```

`inspect` and `plan` are read-only against both databases. Review any
quarantine action before enabling writes. A full-block plan is not authorized
by this document.

## Controlled local verification evidence

The accepted local run verified tenant migration
`0280_add_arissto_staff_profiles.xml`, both mapped offices, the staff API, and
the complete profile datatable. Its population included:

- one active employee using `FECHA_INGRESO`;
- one employee using the branch-assignment start-date fallback;
- one employee using the `2020-10-01` legacy snapshot-date fallback;
- the inactive employee using profile branch `001` because no assignment row
  exists;
- one employee with a populated phone; and
- one employee with populated sensitive HR data.

The accepted workflow was:

```bash
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync plan --block employees --target local \
  --source-key ID_EMPRESA:ID_PERSONA
```

Acceptance produced exact reconciliation and an idempotent second plan. The
registry is therefore `available` with `executable: true` for reviewed runs.

Production remains prohibited until local acceptance, independent production
inspection, an explicit production plan, and fingerprint confirmation are all
complete.
