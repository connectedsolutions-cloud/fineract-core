# Client PEP sync service

- Service ID: `client-pep`
- CLI block: `client-pep`
- Status: `available`
- Depends on: `clients`
- Configuration: `config/client_pep.json`
- Detailed contract: [`contract.md`](contract.md)

This service synchronizes only the verified direct party-level PEP answer from
`dbo.AFI_SOCIO.PEP` into `credesal_client_pep.es_pep`. It does not create
clients, and it never maps related-person, legal-representative, political-role,
income, party, or repeatable-detail fields.

## Recommended chained workflow

Create and review a normal clients plan, then opt into the dependency chain:

```bash
./arissto-sync inspect --block clients --target local
./arissto-sync inspect --block client-pep --target local
./arissto-sync plan --block clients --target local \
  --source-key NUMERO_AFILIACION
./arissto-sync apply --plan CLIENT_PLAN_ID --target local --with-pep
```

The chained command performs these steps in order:

1. apply the reviewed clients plan;
2. reconcile that clients run;
3. stop without starting PEP if client reconciliation is not successful;
4. build a PEP plan for exactly the successful or unchanged client source keys;
5. apply the PEP plan; and
6. reconcile the PEP run.

The JSON result includes both run IDs, both reconciliations, and the point at
which the workflow stopped if any gate fails. The `--with-pep` flag requires a
`clients` plan and is mutually exclusive with other post-client workflow flags.

## Independent workflow

The service can also run independently after its parent clients already exist:

```bash
./arissto-sync inspect --block client-pep --target local
./arissto-sync plan --block client-pep --target local \
  --source-key NUMERO_AFILIACION
./arissto-sync apply --plan PEP_PLAN_ID --target local
./arissto-sync reconcile --run PEP_RUN_ID --target local
./arissto-sync status --block client-pep --target local
```

Planning refuses application when a scoped Arissto party has no matching
Fineract client, which enforces the parent dependency even outside the chained
workflow. Omitting `--source-key` creates a full-block plan and still requires
explicit review before apply.

Production requires its independently inspected plan and exact target
fingerprint confirmation. Registry availability does not authorize a
production or full-block apply.

## Verified local evidence

The 2026-08-14 source audit found 1,029 parties: 3 true, 416 false, 610 unknown,
and no invalid PEP values. The completed local proof reconciled all 1,029
clients. An aggregate target check found exactly 419 sync-managed rows—3 true
and 416 false—while the 610 unknown values had no row. A subsequent plan marked
all 1,029 unchanged. One unrelated PEP row belonging to a local-only Fineract
client was preserved.

Source semantics and evidence are maintained in the
[Arissto PEP investigation](../../../../../../credesal-db-space/docs/learnings/clientes-pep.md).
