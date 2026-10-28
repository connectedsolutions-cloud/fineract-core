# Loan quarantine expansion analysis — October 28, 2026

## Finding and scope

The accepted loan plan `7d8308469e774c8db104850ece10d9b8` selects 2,752 source
loans: 2,288 eligible and **464 quarantined** (16.9%). The final loan run
`a0fce5b52e544fad901318f4b98fd0cc` recorded exactly those 464 quarantines.
Completion/reconciliation therefore applies to the eligible population; it does
not establish that every source loan was migrated.

Only **161** loans have a direct reason of their own. **303** (65.3% of all
quarantines) have only propagated refinancing-chain reasons. The planner builds
an undirected graph from predecessor dependencies and quarantines the entire
connected component when a source node has an intrinsic reason. A successor's
later payment can therefore exclude multiple much older predecessors.

This analysis reads the saved immutable plan, recorded items, local code and
Git history only. It makes no Arissto or Fineract network query and changes no
quarantine policy, financial record, cycle, plan, run or scheduler state.
The frozen boundary remains **Arissto through 2026-10-26 / Fineract starts
2026-10-27**. Current source conditions must be corroborated before repairs.

## Complete breakdown without double counting

For this report only, assign intentional no-write cases first, then boundary,
closed-freeze, remaining-schedule and mora reasons. This reporting priority is
not a change to planner eligibility or causal precedence. Other reason tags
remain preserved in the machine-readable evidence.

| Primary group | Loans | Interpretation |
| --- | ---: | --- |
| After-boundary source activity / historical reconstruction | **319** | Current extraction has later source history which the bounded source-day projector could not prove safe to exclude. Includes connected predecessors/successors. |
| Closed loans with historical freeze/unfreeze events | **104** | Blanket closed-state history guard, including connected loans; excludes the one voided attempt counted below. |
| Reviewed intentional no-write cases | **23** | 22 fully voided refinancing attempts and superseded undisbursed shell 2120 (replacement 2121). |
| Remaining-principal source schedule signature | **7** | Remaining cases after removing overlap with the boundary group; direct roots 2427 and 2573. |
| Source mora/schedule balance inconsistency | **11** | Six direct roots and five connected loans. |
| **Total** | **464** | 161 direct-reason loans and 303 propagation-only loans. |

The two largest review areas account for **423/464 (91.2%)**. The 23 intentional
omissions are not automatically repair candidates. Nor does classification of
the other groups prove that all their loans are eligible or safely recoverable.
Saved lifecycle labels are active=95, closed=368 and pending=1; these are saved
plan labels, not an independent reconstruction of every quarantined loan at S.

## Raw reason families and overlaps

| Reason | Direct tag | Unique affected including propagation | Notes |
| --- | ---: | ---: | --- |
| `source_events_after_fineract_accounting_boundary` | 91 | 319 | One additional direct schedule root also sits inside a boundary-affected component. |
| `historical_source_freeze_terminal_unsupported` | 39 | 105 | Includes voided attempt 549; assign that loan to intentional omissions in the non-overlapping table. |
| `missing_final_metric_source_snapshot` | 18 | 58 | All 58 already belong to the 319 boundary group. Missing/unproven evidence is not necessarily a missing database row. |
| `reviewed_voided_refinance_attempt_omitted` | 22 | 22 | Intended net-zero omitted origins; no chain-only spread from this reason. |
| `source_exact_remaining_schedule_signature_mismatch` | 5 | 17 | Roots 2427, 2435, 2563, 2573, 2633. Ten affected loans already fall in the boundary group. |
| `mora_schedule_balance_mismatch` | 6 | 11 | Roots 26, 83, 317, 340, 359, 435. |
| `source_mora_cutover_snapshot_missing` | 3 | 5 | Roots 2761, 2762, 2763; overlaps the boundary/metric groups. |
| Reviewed superseded undisbursed shell | 1 | 1 | 2120, replacement 2121. |

These rows overlap and must not be summed.

## Pattern 1: later activity excludes much older refinancing history

Of the 91 direct boundary roots:

- **88** have a frozen disbursement before T; **3** (2761–2763) have disbursement
  on/after T. The latter are genuinely outside the selected origination window.
- **82** have only ordinary/mobile repayment roles among their retained
  after-boundary events. Of these, 80 have incoming refinancing, 68 already have
  frozen final metric targets, five include earlier reversals, one includes an
  earlier adjusted repayment, and two are consolidations. These features overlap.
- The other nine comprise three later originations, two later refinancing payoff
  cases (2435, 2654), adjusted payment 2556, repayment/reversal 2609, and two roots
  (2550, 2668) with the guard tag but no normalized later writer event.
- All **93 retained normalized later events** are dated October 27. This does
  not classify the raw revision/event counts omitted from the saved action.

The existing projector in
[`loan_source_window.py`](../../arissto_sync/loan_source_window.py) supports a
narrow, proven active snapshot followed by ordinary payments. It requires exact
source-day snapshots and paid counters and rejects revisions/reversals and
unsupported refinancing relationships. The incoming top-up proof additionally
requires an exact closed predecessor snapshot, same owner, unique link, no later
predecessor activity and other terminal evidence. A valid successor metric
snapshot alone does not satisfy the predecessor/history proof.

Therefore, the 82 ordinary-payment cases are a high-value investigation group,
not 82 confirmed safe unquarantines. The saved plan does not retain all raw
inputs or individual failed projector predicates. In particular, the guard's
`post_cutover_source_event_counts` are not copied into the final action and the
projector returns no structured rejection explanation. Roots 2550/2668 require
targeted source corroboration to distinguish revisions or omitted raw events.

Representative dependency amplification:

| Direct trigger | Quarantined connected loans | Example of older excluded members |
| --- | ---: | --- |
| 2664: boundary | 13 | 1328, 1434, 1536, 1725 |
| 2556: boundary/adjusted repayment | 13 | 1885, 1943, 1965, 2049 |
| 2710: boundary | 9 | 1873, 1928, 1973 |
| 2541: boundary + missing metrics | 7 | 18, 937, 947, 1157 |

All 158 affected graph components are entirely quarantined; there is no mixed
eligible/quarantined component in this frozen plan. Simply detaching older loans
could misrepresent a predecessor's state or a payoff across the boundary.

## Pattern 2: any historical freeze on a closed loan is unsupported

`_guard_unmapped_loan_events` adds
`historical_source_freeze_terminal_unsupported` whenever source freeze events
exist and the source state is not active. It does not distinguish an ended past
freeze from a still-open freeze in that closed-loan branch. Active loans instead
receive frozen control history.

This is an implementation support limit, not evidence that all 39 direct source
loans are corrupt. The exact intervals are not retained in these closed actions,
so this analysis cannot count which ended before closure. Example: direct root
1540 excludes a seven-loan component (658, 1015, 1137, 1248, 1457, 1540, 2291).
Safe support must preserve historical control evidence and terminal state,
without giving closed loans active final metric/accrual obligations.

## Smaller schedule patterns

The remaining-schedule guard expects a specific proof of historical paid
principal/interest plus an effective remaining schedule. A changed source
adjustment signature is not admitted by the earlier narrow classifier. Root
2427 is also documented in the October 2 investigation: its return here merits
comparison of the frozen adjustment/history signature rather than an ID allowlist.
All five direct remaining-schedule roots are preserved in the raw reason table;
only 2427/2573 and their five connected loans are exclusive to that group.

The mora guard recomputes the amortizing principal balance from source schedule
capital and requires each source `SALDO_ANTERIOR`/`SALDO_ACTUAL` to match. Its six
roots affect 11 loans. It is a source schedule interpretation/data consistency
question; the saved tag alone cannot decide which side should be corrected.

## Why the historical 19 differs

The September 13 Gate 5 evidence records **2,528 supported loans + 19 reviewed
no-write cases** (2,547 total), consisting of 18 voided attempts and the
superseded shell. The current source population is 2,752, and the same omission
categories now total 23 (22 voided + the shell). This is a category/count
comparison; the retained September plan was not available for an exact ID diff.
The October 2 note already documents growth to 20 intentional omissions and
12 extra schedule/chain cases at that time.

Git history establishes that both the closed-freeze guard (583edd0dc1) and the
loan after-boundary guard (6035616b9f) were introduced on October 26. Graph
propagation itself already existed in ee176e73cf on September 12. The larger
count reflects broader checks, later source activity against a fixed source day,
and propagation through long refinancing chains, in addition to population growth.

In this latest historical-off cycle, quarantine counts went **476 → 464 → 464**
across the three saved child plans. Active-only metric scope removed 12 closed
metric-snapshot-only cases. The insurance-template correction changed no
quarantine membership. Thus this investigation must not attribute the entire
increase to disabling interest recalculation or to the 11 insurance fixes.

Historical references:
[September acceptance](README.md),
[October 2 expansion](loan-reconciliation.md#october-2-full-sync-quarantine-increase),
[historical refinance projection](historical-refinance-source-window.md), and
[active-only metric repair](loan-failure-pattern-repair-oct27.md).

## Prioritized follow-up

1. Diagnose the 91 boundary roots with structured failed-proof predicates;
   start with the 82 ordinary/mobile-later-payment cases and their predecessor
   snapshots. Preserve S/T and exclude later financial events. Quantify the
   proven chain closure recoverable by each supported reconstruction pattern.
2. Review closed freeze histories, distinguishing ended intervals and closure;
   establish a guarded closed-history contract before admitting the 104 cases.
3. Investigate the two standalone remaining-schedule roots and six mora roots.
4. Keep the 23 intentional omissions separately labeled, with their provenance.

No release count is promised by this analysis. No live source comparison or
planner/apply change was performed. Full per-loan reasons, graph components,
root membership and overlapping/non-overlapping counts are in the
[machine-readable analysis](investigations/loan-quarantine-patterns-oct28.json).
