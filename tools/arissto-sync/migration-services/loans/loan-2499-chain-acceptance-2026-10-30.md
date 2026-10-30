# Loan 2499 refinance-chain import acceptance — 2026-10-30

The scoped chain 2210 → 2354 → 2499 imported and reconciled successfully on
the disposable local `sandbox` tenant. An unchanged application of the same
immutable plan also passed without changing native transactions, schedule rows,
metric values or alignment audit version. Future collection/accrual smoke tests
remain separate and were not performed on this imported target.

## Boundary and scope

- Target: local `sandbox`, fingerprint `b9f6834b66790744`.
- Existing cycle: `sandbox-2026-10-29-full-clean-a`; no reset or new cycle.
- **Arissto through: 2026-10-29**; **Fineract starts: 2026-10-30**.
- Plan: `73b17d66a4a344dbbaa4059dcfea4af1`.
- Initial run: `8c71c716637644ccac402ce39ea7b2e2`.
- Unchanged retry run: `80051ebbb08a482ba770afb046f4995e`.
- Explicit source selection `2499` expanded through the supported loan-block
  planner to exactly three source loans. The only additional plan action was
  unchanged product `00010`. No other migration services were applied.
- Source observed at the immutable plan's recorded observation time. This did
  not advance the active accounting boundary or promise later source commits.

This was a scoped block-level continuation of the existing target lifetime,
using the documented `plan --block loans --source-key 2499`, `apply`, and
`reconcile` commands with the existing cycle state file. It was not a new
fresh/clean run, a full-portfolio resumed workflow or a checkpointed full re-sync.
The composed workflow CLI currently scopes by service, not by individual loan.
An exclusive target workflow lock and a verified paused scheduler protected both
applications. Fineract was already listening when the authorized guarded start
helper ran. The scheduler was active, was stopped before financial writes, and
was left paused after acceptance; it was not restarted automatically.

## Native result

| Arissto loan | Fineract loan | Native state |
| --- | ---: | --- |
| 2210 | 2740 | Closed, status 600 |
| 2354 | 2741 | Closed, status 600 |
| 2499 | 2742 | Active, status 300 |

The native historical replay verifier passed all dated transaction identities,
amounts, allocations and refinance transfers/payoffs for the three loans.
Loan 2499 retains its actual August 28 refinance. Its 22 payments occur exactly
once and total 129.29 = 78.24 principal + 50.71 ordinary interest + 0.34 mora.
The native repayment count is 16. After the final alignment transformation,
continuation reconciliation proves **16 contractual rows plus one additional
migration metric baseline**, with future interest preserved as forecast rather
than added to already accrued ordinary interest. The initial 73.91 principal /
50.04 interest bridge remains in immutable projection provenance. The aligned
native settlement rows intentionally differ from their initial projected
amounts; the 36 reported schedule differences are verified continuation
variances, not blocking mismatches.

| Frozen source / native metric | Amount |
| --- | ---: |
| Paid principal | 78.24 |
| Outstanding principal | 93.76 |
| Paid ordinary interest | 50.71 |
| Outstanding accrued ordinary interest | 0.64 |
| Due principal | 1.90 |
| Outstanding mora | 0.00 |
| Insurance paid | 0.00 |
| Insurance outstanding | 0.00 |

Initial apply reported three successful loans and one metric adjustment.
Closed predecessors skipped final active-loan metric alignment. Official initial
and retry reconciliations both returned `ok=true`, no mismatches, no failed or
quarantined items, and one proven continuation schedule. The retry recovered
all three loans and performed zero metric adjustments. Independent before/after
comparison confirmed identical transaction IDs, amounts, dates, allocations,
reversal flags, native schedule rows, eight metrics and alignment audit version.
No interim refinance goodwill bridge or predecessor cutover adjustment was
applied; their recorded amounts are zero.

## Implementation follow-up found before apply

Live planning exposed a mutable portfolio header with 15 approved installments.
The original application still records 30. The first generated plan was not
applied; commit `b9dc029c94739775e8b825705347b75bf034c308` corrected provenance
priority and added a regression before the accepted plan was generated.
Its descriptor records original application 30, current header/source rows 15,
and native projected rows 16 separately. The correction passed 272 relevant
regression tests. The principal-chain implementation is commit
`0083583917fcede700920d978eb5cff8427d2e87`; durable change-tracker entries 61
and 62 own implementation and validation status.

## Remaining acceptance boundary

The existing backend supported the controlled import and unchanged recovery;
no backend change was required for this case. This acceptance does not prove a
future collection, reversal, reschedule or native COB/accrual operation. Those
operations require a separately controlled servicing test; they must not be
inferred from handoff equality or run automatically against the imported loans.

See [the revision-chain policy](dated-principal-revision-chain.md),
[final metric alignment](loan-metric-final-alignment.md), and
[the source loan narrative](../../../../../../credesal-db-space/docs/learnings/prestamos.md)
for their respective contracts and evidence. Native run/plan/reconciliation
records remain in the cycle SQLite database; this note contains no borrower
identity, credentials or sampled transaction payloads.
