# Loan quarantine recovery — October 28, 2026

## Requested outcome and boundary

Import all real loan histories in the selected source-through scope. The user
confirmed that fully voided refinancing attempts and superseded applications
remain provenance only; they are not new financial loan histories. Preserve
**Arissto through 2026-10-26 / Fineract starts 2026-10-27**, local disposable
sandbox only, and interest recalculation off. Later originations remain outside
this source-day scope. No boundary advance is implied by the request.

## First repair: fully paid POST snapshot with an active state flag

Live read-only source comparison found63 successor histories where the
predecessor movement POST snapshot still has state1 although its paid-principal
counter equals the predecessor's original disbursement. Current and dated
predecessor states are closed. The canonical full-close classifier already
handles that combination, but the historical projection required POST state3.
That contradictory restriction quarantined whole connected refinancing chains.
The observations do not establish the source application's internal update order.

The projection now admits a state1 POST only with an exact unique identified
POST row and fully paid principal, while retaining closed current and exact
source-day snapshots, zero debt, no later predecessor payments, matching payoff
components, unique same-owner historical link, complete cash history and all
other existing checks. Partial, missing, duplicated, mismatched or unclosed
proofs remain rejected. The proof is frozen in the source-window descriptor.
The explicit versioned `source_window_projection_policy` changes the contract
hash; previous immutable plans cannot be mistaken for this policy.

Read-only source/target dry composition of the323-record extraction closure
reduces quarantines **323→136**, with **187 newly admissible real histories**.
This is not native runtime acceptance and does not yet establish that all464
quarantines are resolved. Four of the323 extraction records are reversed-attempt
provenance pulled in by raw links, beyond the earlier319 effective graph scope.
Focused regressions pass **305 tests**, including full-payoff, partial/ambiguous
POST, source ownership, dated closure and immutable-contract negative controls.

No target financial write, new cycle, tenant reset, sync run or scheduler
release has occurred for this repair. Further reconstruction, closed-history
support and controlled planning/execution remain in progress.

Evidence: [source predicates](investigations/paid-refinance-post-state-proof-oct28.json),
[dry admission comparison](investigations/paid-refinance-projection-dry-build-oct28.json).
The [original quarantine analysis](loan-quarantine-analysis-oct28.md) remains the
frozen pre-repair baseline. Source evidence is recorded in the exploration
[refinancing note](../../../../../../credesal-db-space/docs/learnings/refinanciamientos.md).


## Real history admission and repaid freeze history

The next read-only composition admits **2,665 / 2,752** records and excludes87:
**377 newly admissible** compared with the accepted2,288, with **zero previously
accepted loans newly excluded**. All38 real repaid loans with valid historical
freeze restrictions now carry those events. This is planning evidence, not a
claim that the new population has been written or reconciled in Fineract.

Historical revisions created and effective before the boundary no longer block
an unrelated later payment. Historical repayment reversals use the canonical
exact-component LIFO pairing; paired originals remain in replay history but are
excluded from paid-counter corroboration. Unpaired or mismatched reversals,
future reversals, and disbursement reversals still require further proof.

Consolidations prove every predecessor independently, reject duplicate legs and
cap combined payoff at the successor disbursement. Source-authorized legacy
cross-client links require the same liquidation, payoff movement and operator
identity used by the canonical writer. A proved net-zero abandoned attempt does
not erase an otherwise real loan's effective refinancing history.

The native freeze-history command now accepts obligations-met loans closed
strictly before T, with the same imported-source identity, boundary, chronology,
and idempotence checks. Domain freeze/unfreeze methods update restriction flags
and history only; closed status is preserved and there is no cash/GL replay or
active final-metric alignment. An administrative restriction entered after the
last financial movement is retained when still before T. No synthetic unfreeze
is added. Voided records retain evidence only.

Mifos inspection confirmed that the loan header and actions follow the native
closed-obligations-met status. This change adds no new UI field or status; no
separate freeze-history UI was found in the current Mifos flow.

Validation: **347 Python loan tests** and **6 native freeze-history tests** pass.
The projection policy is versioned as `dated-source-real-history-v3`; repaid
history is versioned as `active-and-repaid-history-v2`, preventing old immutable
plans from silently using changed behavior. The local running Fineract process
has not been reloaded and no financial writes have been made for these changes.

Detailed IDs and remaining reasons: [read-only admission evidence](investigations/real-history-admission-oct28.json).


## Complete source-day reconstruction

The complete read-only composition admits **2,726 real histories**:
2,196 closed,521 active and9 pending. **438 histories are newly admissible**;
all2,288 previously accepted histories remain eligible. The remaining26 source
records are exactly22 voided attempts, superseded application2120, and the3
originations after S (2761–2763). There are no remaining in-scope real-history
quarantine roots. Native import/reconciliation is still pending.

The v4 reconstruction freezes exact repayment reversal timing. A pre-S payment
reversed after S remains effective at S; an entirely later pair is excluded.
Canonical exact-component pairing is required. Later adjusted repayments can be
excluded with the same complete paid-counter corroboration as ordinary cash.

Six later schedule revision cases (1890,2550,2559,2587,2668,2682) have a first
future archive whose comparable contract fields exactly match the S daily row.
Restore that archive and dated header terms, retaining excluded revision IDs
and snapshot identity as proof. Never infer maturity from the last installment.
Reconstruction is staged on copies; failed contract/cash proof leaves input
unchanged. Later payoff/disbursement source links are outside the S graph,
with both movement identities, dates and lifecycle directions verified and the
complete edge preserved as provenance. This prevents future originations from
excluding earlier real loans.

The six mora-balance cases26,83,317,340,359,435 are proved closed in both header
and exact dated state, fully principal-paid, with no dated debt or later source
events. Their stale before/after schedule balances remain disclosed historical
reference variances. Cash history and native financial reconciliation stay
mandatory; the active forward-COB balance identity is unchanged.

Remaining-plan proofs now include the native refinance payoff in principal
conservation. They can use an earlier full-principal archive with exact dated
paid/unpaid conservation when later revisions edit interest/dates. Multiple
anchors are accepted only when they prove identical bridge economics, retaining
every corroborating ID; conflicting historical interest remains rejected.
This resolves2427,2563,2573,2633 without per-loan filter exceptions.

Focused reconstruction, existing-payment recovery and orchestration validation:
**185 tests pass**. An additional331 loan/orchestration/state tests pass with
`TMPDIR=/private/tmp`; the default macOS temporary directory caused SQLite I/O
errors in the broad run. Two old repayment-recovery mock families were updated
to the approved recalculation-off contract. The unrelated savings minimum-
balance assertion still fails in the broad suite and is outside this change.
Native freeze-history validation remains6 passing tests.

See [complete admission evidence](investigations/complete-real-history-admission-oct28.json).
