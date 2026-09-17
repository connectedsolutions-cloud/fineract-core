# Client personal and family references migration service

## Status

- Registry status: `available`
- CLI block: `client-personal-family-references`
- Dependency: `clients`
- Sources: `dbo.AFI_REF_PERSONAL_SOCIO` and `dbo.AFI_FAMILIA_SOCIO`
- Target: Fineract `/clients/{clientId}/familymembers`
- Writer: Fineract API only

The implementation supports inspection, scoped/full planning, API apply,
retry, reconciliation, and dependency-driven local orchestration. Liquibase
migration `0342` is present in the selected target. Controlled sandbox run
`f4c1a333098444a4bcea324b06dc18d0` created and exactly reconciled all 4,195
personal references; follow-up plan `79b8c1e5a05e4aaaaf5696ef5054837a`
classified all 4,195 rows as unchanged.

See [`contract.md`](contract.md) for identities, mappings, and acceptance gates.
Arissto source evidence remains in the exploration repository's
[`familiares-y-referencias.md`](../../../../../../credesal-db-space/docs/learnings/familiares-y-referencias.md).

## Commands

```bash
./arissto-sync inspect --block client-personal-family-references --target local
./arissto-sync plan --block client-personal-family-references --target local \
  --source-key personal:NUMERO_AFILIACION:ID_REF_SOCIO
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync retry --run RUN_ID --failed-only --target local
./arissto-sync status --block client-personal-family-references --target local
```

The service is selectable in the local party-profile and full-sync workflows.
Selecting it automatically includes and locks its `clients` prerequisite.

## Full re-sync

Local `full-resync` is supported through `local-full-resync`. The planner uses
the durable reference identity and source hash to classify each row as create,
update, unchanged, or quarantine. Unchanged rows are no-write actions. Source
absence does not delete a target family member, and the service checkpoint
advances only after exact reconciliation.
