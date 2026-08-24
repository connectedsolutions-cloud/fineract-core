# Client family references migration service

## Status

- Registry status: `available`
- CLI block: `client-family-references`
- Canonical source identity: `NUMERO_AFILIACION:ID_REF_FAM`
- Relational source identity: `ID_EMPRESA:ID_SUCURSAL:ID_SOCIO:ID_REF_FAM`
- Source table: `dbo.AFI_REF_FAMILIAR_SOCIO`, joined to `dbo.AFI_SOCIO`
- Target writer: extended Fineract client-family-member API only

The contract, Fineract schema/API extension, readiness inspection, planning,
API-only writer, retry, and reconciliation are implemented. A controlled local
full-block run reconciled all 1,960 records exactly, produced a fully unchanged
second plan, and recovered the same target from an isolated empty sync-state
database through the durable Fineract external identity.

See [`contract.md`](contract.md) for the reviewed design and blockers. Source
meaning and aggregate evidence remain in the exploration repository's
[`familiares-y-referencias.md`](../../../../../../credesal-db-space/docs/learnings/familiares-y-referencias.md).

## Business scope

The first version migrates the populated personal/family reference contacts in
`AFI_REF_FAMILIAR_SOCIO`. It preserves their relationship to the existing
Fineract client and makes them visible through the existing family-members tab,
which the Credesal UI labels as personal and family references.

The scope includes both Arissto institutional classifications stored in
`AFI_SOCIO`: `CLIENTE` and `SOCIO`. On 2026-08-14, the populated reference set
covered 976 `CLIENTE` parties with 1,929 references and 21 `SOCIO` parties with
31 references. The word **client** in this service name refers to Fineract's
technical `m_client` parent, where the existing clients migration represents
both Arissto classifications; it does not mean “Arissto CLIENTE only.”

It explicitly excludes:

- `AFI_FAMILIA_SOCIO`, because it currently has no rows;
- affiliation, certificate, and savings beneficiaries, which express separate
  legal/product designations;
- automatic deletion of Fineract rows when a source reference disappears; and
- inference of gender, dependency, surname boundaries, or other facts not
  present in the source.

## Implemented preparation

- A versioned, unique external/source identity was added to the Fineract
  family-member resource and exposed through its API.
- The source address, second phone, and original relationship text are preserved in
  versioned Fineract fields/API properties.
- The family-member API create/update validation and nullable-field behavior
  described in the contract were corrected.
- The target `RELATIONSHIP` code values are bootstrapped with a reviewed,
  target-independent semantic mapping.
- Readiness inspection, extraction, planning, writer, reconciliation, retry,
  and tests were added to the sync engine.

The Credesal UI can read imported rows through the native family-member API.
Improving its manual edit form for unknown surname/gender and displaying every
preserved audit field remains a separate UI enhancement, not a sync-readiness
requirement.

## Commands

```bash
./arissto-sync inspect --block client-family-references --target local
./arissto-sync plan --block client-family-references --target local \
  --source-key NUMERO_AFILIACION:ID_REF_FAM
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync status --block client-family-references --target local
```

Omitting `--source-key` creates a full-block plan. Review that plan before
apply; registry availability does not authorize an unreviewed full or
production run.

## Chained client flow

The service can be triggered for the exact client affiliations processed by a
reviewed client plan:

```bash
./arissto-sync apply --plan CLIENT_PLAN_ID --target local \
  --with-family-references
```

The workflow is deliberately failure-gated:

1. apply the client plan;
2. reconcile the resulting client run;
3. stop without starting references if client reconciliation is not exact;
4. derive successful client `NUMERO_AFILIACION` source keys from that run;
5. plan and apply only reference rows owned by those clients; and
6. reconcile the dependent family-reference run before reporting success.

A scoped client plan therefore triggers a scoped family-reference plan. A
normal client `apply` without the flag remains client-only. Production still
requires the exact production fingerprint, which is passed to both applies.

## Acceptance evidence

The 2026-08-14 local acceptance run proved exact client ownership, complete
field and null preservation, recoverable idempotency after local-state loss,
an unchanged 1,960-row second plan, and successful API reconciliation for all
1,960 rows. Run IDs and current plan IDs remain in ignored local sync state and
are intentionally not copied into this durable guide.
