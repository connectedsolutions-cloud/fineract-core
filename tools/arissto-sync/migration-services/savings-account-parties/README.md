# Savings account parties migration service

## Status

- Registry status: `blocked`
- CLI block: `savings-account-parties`
- Dependency: `savings-deposits`
- Blocker: deploy tenant migration `0343_add_savings_account_parties.xml`, restart
  Fineract, and complete a reviewed local plan/apply/reconcile run before marking
  this service executable.

## Scope

This service migrates `AHO_BENEFICIARIO` and `AHO_AUTORIZADO` into separate,
first-class collections attached to the current native Fineract deposit account.
For renewed fixed deposits, the current account is the pointer recorded in
`credesal_savings_migration_account.savings_account_id`; parties are not copied
onto every historical renewal cycle.

The service deliberately does not turn these people into account owners or
Fineract clients. The source DUI remains available for review, while
`linkedClientId` stays empty until an exact, reviewed identity-linking policy is
approved. An authorized-person row records the designation and print flags but
does not itself grant transaction authority because Arissto does not provide a
usable scope, limit, signing mode, validity period, or revocation history.

Source evidence is maintained in
[`familiares-y-referencias.md`](../../../../../../credesal-db-space/docs/learnings/familiares-y-referencias.md).
The complete migration contract is in [`contract.md`](contract.md).

## Permissions

The endpoints intentionally inherit deposit-account access:

- reads require `READ_SAVINGSACCOUNT`;
- writes require `UPDATE_SAVINGSACCOUNT`; and
- normal savings-account office/data-scope validation applies.

No beneficiary-specific or authorized-person-specific permissions are created.

## Commands

```bash
./arissto-sync inspect --block savings-account-parties --target local
./arissto-sync plan --block savings-account-parties --target local
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync retry --run RUN_ID --failed-only --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync status --block savings-account-parties --target local
```

Apply is unavailable through composed workflows while the registry entry is
non-executable. After local acceptance, change the registry status to
`available`, set `executable` to `true`, and add the service after
`savings-deposits` in the applicable workflows.
