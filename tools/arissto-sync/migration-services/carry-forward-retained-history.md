# Carry-forward retained historical DTE and GL

Status: implementation contract; historical DTE and GL retention is not yet executable.

## Objective

A new local carry-forward cycle should preserve the identities and rows of
historical DTEs and imported Arissto journals that can be proved unchanged,
as it does for closed loans. The remainder must follow the existing source
import or an explicit blocking disposition. The operator still chooses
**Arissto through** `S` and the workflow derives **Fineract starts**
`T = S + 1 calendar day`. No previous tenant cutoff advances in place.

## Eligibility is per source identity

Do not assume a record is immutable because it has already been imported.
For each candidate, compare a fresh source hash with the accepted old-cycle
hash and with the target provenance hash. Verify the complete target row graph
against the accepted reconciliation and capture. Reject missing or duplicate
source identities, changed target rows, unsupported links, and any target-only
financial activity in the new ownership interval. Freeze the proof and source
observation time in the private immutable replacement plan, then repeat the
checks immediately before replacement.

The [read-only DTE audit](../../../../../credesal-db-space/docs/learnings/fiscal-dte.md#can-dte-changes-be-found-from-a-modification-timestamp)
and [journal audit](../../../../../credesal-db-space/docs/learnings/contabilidad-libro-mayor-y-partidas.md#marca-de-modificación-para-conservar-partidas-históricas)
on 2026-10-08 rule out timestamp-only candidate selection. Fiscal-header
`DT_MOD` is missing on 15,030 of 25,427 coded rows, its other technical update
stamp equals the insertion stamp, and the normalized DTE header and detail
have no modification stamp. Journal `DT_MOD` and `DT_CREO` are null on every
current header and line. Use per-identity source hashes and an identity-set
comparison on every carry-forward run. A populated `DT_MOD` may prioritize a
review, but must never authorize skipping the hash comparison.
The null-as-unchanged assumption is directly disproved: 606 coded DTE rows
with null `DT_MOD` have MH submissions and receptions at least a day after
their insertion; four journals frozen in status `1` later reached status `3`
while retaining null `DT_MOD`. The generic audit tables cover only one fiscal
update path and contain no named journal or normalized-DTE events in the
reviewed aggregate.
More decisively for a last-run filter, one DTE's source hash changed between a
frozen 2026-10-06 plan and two 2026-10-08 reads under the exact same source-hash
contract. Its MH submission is dated 2026-10-08, while its fiscal `DT_MOD`
remains dated 2026-06-10 and its `FECHAHORA_UPDATE` remains at insertion.
The current DTE planner already distinguishes unchanged hashes from a narrowly
permitted MH-timestamp update and flags other drift as a conflict. The current
accounting planner marks matching imported hashes `UNCHANGED` and quarantines
provenance hash drift; it does not rewrite a posted journal automatically.

- DTE identity is the legal `codigo_generacion`. Preserve only the complete
  invoice graph (`m_invoice`, issuer, receiver, lines, related documents, and
  summary) with an exact source hash and target content match. Preserve an
  invoice linked to a loan transaction only when that exact transaction and
  its owner are retained in the loan seed. An unlinked historical invoice
  needs its historical client and office dependencies proved in the stage.
  Otherwise rebuild it after loans. A later MH processing timestamp is a
  source change handled by the existing DTE update policy, not an unchanged
  retention candidate.
- Accounting identity is the complete four-part Arissto journal key. Preserve
  only a complete balanced imported journal group dated before the old
  Fineract start, with matching source/provenance hash, exact native GL lines,
  account and office mappings, target transaction ID, and monthly number.
  A changed source status or detail line needs the current accounting policy;
  it is not an unchanged retention candidate. Native Fineract GL, journals
  dated in the ownership interval, and derived trial-balance or aggregation
  state are excluded. Preserve no journal merely because its header exists.

## Seed and workflow boundary

Copy only verified candidate graphs from the immutable input capture to an
isolated clean-baseline stage. Enumerate table selectors, foreign keys,
application references, ID collisions, and sequence highwaters. Verify row
counts and hashes before and after archive restore. Copy only the exact
old-cycle mappings needed for retained items into the new cycle; never copy
old plans, runs, or checkpoints. The new service plans should mark retained
items as no-write `unchanged` actions and create newly eligible source items.
They must quarantine or block drift instead of silently replaying a copied
legal document or journal. Reconcile every retained and newly imported item,
including journal number uniqueness and the source-ledger control.

Extend the seed preflight and replacement guards only after these proofs are
implemented. The current zero-invoice and zero-GL seed rules remain active
until then. The recovery capture and old cycle stay available for rollback.

## Acceptance cases

Exercise an unchanged DTE linked to a retained loan transaction, an unlinked
historical DTE, a DTE linked to a replayed loan, and a changed MH timestamp.
For GL, exercise an unchanged journal, a later source status or line change,
a newly eligible pre-cutoff journal, a journal in the ownership interval, and
a native Fineract journal. Verify exact IDs, hashes, balanced lines, journal
numbers, no duplicate writes, and restart/resume from a partially completed
workflow. Run these against isolated local databases before a reviewed sandbox
replacement.
