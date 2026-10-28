# Fresh/clean full sync with loan recalculation off — next-chat plan

> **Execution record:** the operator subsequently authorized implementation and a
> clean diagnostic run. Implementation `9d021d4efd` and the actual fresh/clean
> 18-service attempt are recorded in the [progress tracker](loan-sync-updates-progress-oct27.md)
> and [final result](investigations/historical-off-clean-run-result-oct27.json).
> The attempt finished failed (11 completed, Loans failed, 6 dependent blocks).
> Native recalculation is off and no interim credits/final corrections were
> posted. Historical transfer-state and observed metric-vector issues remain
> open; this run does not establish full migration acceptance. The preparation
> and authorization wording below describes the original planning conversation.

## Outcome and authorization

Prepare and then execute a **fresh/clean local sync of all 18 services**, with
loan interest recalculation **off** during historical migration. Preserve source
financial facts, complete refinance chains and end-only migration corrections.

**This chat prepared this written handoff only.** It did not implement the off
policy, create a cycle or executable workflow plan, approve/start a workflow,
reset a tenant, change loan/product flags, run tests or replay data. Execution is
for the new chat when the user requests it. This file alone is not authorization
to reset or start anything.

The user explicitly selected fresh/clean, not continuation of the current
partially replayed sandbox. In the execution chat, use the guarded whole-tenant
baseline restore and a new cycle. Do not approximate clean by deleting loan rows,
and do not reuse the old cycle's mappings as the new target lifetime.

## Frozen run specification

| Field | Required value |
| --- | --- |
| Mode | **Fresh/clean** (`fresh-clean`) |
| Workflow | `local-full-sync` |
| Scope | **All 18 services**, with registry dependency ordering; no `--include-service loans` narrowing or silent service skipping. |
| Target | `local`, disposable tenant **sandbox**, database **fineract_sandbox**; never `default` or production. Recheck the current fingerprint before action. |
| Arissto through | **2026-10-26**, inclusive. |
| Fineract starts | **2026-10-27**, exclusive source boundary, America/El_Salvador. |
| Historical loan interest recalculation | **OFF** on both created products and created loans, read back from native Fineract. |
| Insurance, interest rates and source terms | Preserve the approved source contract. Disabling recalculation does not disable interest accrual, waive debt or remove insurance. |
| Corrections | Only after complete historical loan replay/refinance readiness; no compensating credits/payments to force intermediate events. |
| Post-migration recalculation | **Remain off for this run.** Forward-only activation is a separate future capability and is not part of this scope. |
| Baseline and cycle | Revalidate the captured baseline and protected-access procedure; choose an unused cycle ID in the new chat. No new ID or executable plan exists yet. |
| Scheduling | Keep native scheduled processing paused during migration; release only after accepted workflow/handoff checks and user authorization. |

Keep October 27 source payment `0000034318` excluded. Also preserve the exclusions
for later discovered movements `34336`, `34340`, `34341` and `34394`, and exclude
or quarantine all other source activity on/after Fineract starts. Do not let a
new chat's current date silently advance the source-through date. A different
source day requires the user's explicit direction.

The baseline last inspected was `.tenant-baselines/sandbox.dump`, with metadata
hash `0164e24eae39f0e9db2b2863b4e3a8c3104d53586485d55a898760cfcbafa938`.
This is a reference, not a fresh validation or restore approval. Re-read metadata
and verify the actual artifact before execution. The guarded restore must first
capture current protected users, employees, roles/grants, office access,
authentication settings and saved reports, then restore and verify them after
startup. Durable `.arissto-sync/change-tracker.sqlite3` must survive.

## Selected services

Read-only `workflow inspect` on October 27 resolved the following 18 services.
The current workflow/registry remains authoritative if its definition changes.

1. `clients`
2. `employees`
3. `client-staff-assignments`
4. `client-pep`
5. `client-family-references`
6. `client-personal-family-references`
7. `membership-share-capital`
8. `loans`
9. `delinquency-history`
10. `savings-deposits`
11. `savings-account-parties`
12. `native-share-capital`
13. `aml-alerts`
14. `dte-history`
15. `mobile-collections`
16. `accounting-journal-entries`
17. `native-share-yield`
18. `cheque-history`

Inspection reported no structural blockers and definition hash
`0c61a1fdc2edcb9e8438ece259b6eab4fbf2236fc7ed2a2b81c2650edc5e7d24`.
It also reported **cheque-history is testing**, permitted by this workflow's
existing `allow-executable` policy. Preserve and disclose that warning; do not
silently drop the eighteenth service or edit the registry to hide its status.
Structural workflow readiness does **not** mean recalculation-off is implemented.

## Implementation prerequisites — before any restore or run

The current engine still hardcodes recalculation on. A CLI plan generated with
unchanged code would therefore be the wrong plan. Complete these prerequisites
as one coherent service change, without more exploratory on/off campaigns or
starting another isolated test stack.

| Area | Required change/check |
| --- | --- |
| `config/loans.json`, `LoanContract.load`, product payload/comparison helpers | Define the approved historical off policy consistently. The current constant and contract loader require daily recalculation on; changing one JSON boolean is insufficient. |
| Loan plan creation, lifecycle policy, plan/apply guards | Freeze the off policy in the immutable plan; update revision/hash validation so old on-mode plans cannot be mistaken for off-mode plans. Actively verify native product **and loan** flags are false. |
| Product capability/retry logic | Remove enable-only backfill from the off migration path. Do not silently reuse incompatible on-mode products/loans. Fresh/clean avoids an unreviewed in-place conversion of the existing partial sandbox. |
| Source schedules and ordinary replay | Install the frozen source calendar before servicing and preserve identities, dates and exact allocations. Keep genuine dated source reversals/reschedules/charges; internal derived-state recomputation must not rewrite source facts. |
| Historical refinance service | Preserve recorded source payoff allocations, predecessor/successor identities and borrower net cash. The ordinary off-mode payoff quote may include future scheduled interest. Do not blindly substitute it for the recorded source payoff. Eliminate dependence on interim `CRD-REFI-CUTOVER` compensating credits before historical disbursement. If the settlement path cannot satisfy this, report a blocker before resetting/running. |
| Final correction coordinator | Stop interim/per-loan corrective migration writes. Require a complete financial replay barrier: no failed/blocked required loan chain before final adjustments. The current final-metric loop adjusting only successful outcomes is insufficient. |
| Legacy off-mode branches | Review `daily-native-v1` conditionals and `_assert_active_cutover_components`; do not accidentally reintroduce a pre-adjustment parity gate or convert failures to nonblocking variances just to obtain green results. |
| Insurance, source accrual controls and accounting | Preserve genuine source insurance/penalty ownership and freeze/resume history. Separate these source facts from corrective cutover debt/balance changes. Keep complete eligible historical GL import once, with no double posting from operational books or loan replay. |

**End-only** means all historical operations that can affect a loan—including
refinance successors, partial paydowns, consolidations and later predecessor
payments—must be finished before correcting its final migration state. If a
later selected service can write loan financial state, final loan correction
must wait for that service too. Use workflow finalization if necessary; do not
add a nineteenth registered service or weaken final reconciliation.

Do not enable recalculation after alignment as part of this run. Product switching
can copy a loan's flag and trigger schedule regeneration; it is not a safe
forward-only handoff. The agreed direction and code evidence are in the
[historical replay decision](historical-replay-design-decision-oct27.md).

Preserve unrelated existing worktree changes, especially mora/interest-pause
work and the already-dirty loan contract/canary notes. Stage/commit only changes
belonging to this implementation. Inspect existing Mifos product/loan settings
and schedule display for the off values; do not introduce an activation UI or
claim future activation is implemented.

## Focused implementation checks

Use the existing evidence and focused automated checks for changed code. Do not
restart the per-loan patch/retry campaign or claim the deferred complete-lifecycle
baseline was built. The changes must establish:

- Off-mode products and loans are planned, created, compared and retried
  consistently; wrong/missing native flags and old on-mode plans fail closed.
- Full servicing sequences preserve payment/reversal identities, dates,
  allocations and charge ownership, including early insurance and penalty cases.
- Complete connected refinance chains conserve source payoff/net cash and
  remain correct through subsequent repayments; no interim corrective bridge.
- Any failed or dependency-blocked financial chain prevents final corrective
  migration writes. Final reconciliation remains strict.
- Source-through/Fineract-start dates and accounting ownership are unchanged;
  no October 27 source transaction is imported.

A fix is accepted at the complete service/chain level, not because its first
failed repayment now posts. Source-boundary cases such as 18's chain through
2541 and 2435→2763 remain independent: neither an off flag nor a clean target
creates missing historical source snapshots. Preserve quarantine unless an
approved source-through reconstruction proves the complete chain. Do not replay
an old target-bound plan against the new tenant lifetime.

## Execution sequence for the new chat

1. Read this handoff, engine/parent `AGENTS.md`, engine `README.md`,
   `workflows/README.md`, `workflows/local-full-sync.json`,
   `migration-services/orchestration.md`, `sync-dashboard/README.md`, and
   `../../../docs/ARISSTO_SYNC_RUN_MODES.md` from the engine directory.
2. Implement and commit the prerequisite off-mode/shared replay changes. Finish
   the focused checks and document any blockers before proposing a restore.
3. Re-inspect current cycles/runs, target identity, workflow selection, baseline
   integrity and protected-access readiness. Surface the concrete fresh/clean
   run manifest: all 18 services, local sandbox/database, both dates, off flags,
   correction ordering and any quarantines/warnings. Execution requires an
   actual user request in that chat; this planning file is not one.
4. Once authorized, use the supported guarded dashboard/orchestrator flow for
   whole-sandbox restore, protected-access restoration and new-cycle creation.
   Do not manually launch Docker, invoke a separate Fineract process, wipe rows,
   or use the stopped `lsreg_*` preparation environment.
5. Generate the new immutable `local-full-sync` workflow plan against the verified
   clean target with **Arissto through 2026-10-26**. Surface its actual ID,
   service order, counts, off settings, source boundary and blockers for review
   before approval/start. Do not invent a plan ID or treat this document as the
   executable plan.
6. Execute through the workflow control plane, monitor recorded cycle/run IDs,
   preserve existing failure/ownership guards, and avoid changing the writer
   underneath an active replay. If a shared failure stops the run, finish and
   preserve that attempt before implementing a coherent service fix.
7. Reconcile all 18 services and complete refinance chains, verify native off
   flags, exact final metrics, correct source charge/reversal/settlement state,
   no duplicate source events, excluded October 27 transactions absent, and
   correct GL/checkpoint ownership. Do not accept a partial run with successful
   items plus failures/blocks. Keep scheduler/COB gated until acceptance.
8. Update the existing progress tracker and durable change tracker, record
   actual plan/cycle/run/reconciliation IDs, and commit the final implementation
   and results. Do not turn on post-migration recalculation in this run.

Read-only starting commands (no reset/start):

```bash
./arissto-sync workflow list
./arissto-sync workflow inspect --workflow local-full-sync
./arissto-sync health
```

Use current executable help for mutating command syntax. Reset, cycle creation,
planning, approval/start and recovery must follow the reviewed operational flow;
do not infer a composed run by stitching individual block apply commands together.

## Opening message for the new chat

> Read `migration-services/loans/recalculation-off-full-sync-handoff-plan.md`
> in the Arissto sync engine. Implement the coherent historical replay policy
> with loan interest recalculation off, source-exact refinance/payoff handling,
> and corrections only after complete replay readiness. Then prepare and run a
> fresh/clean `local-full-sync` with all 18 services through the guarded control
> plane when I authorize execution in this chat. Preserve protected access and
> the existing evidence, use a new cycle after the guarded sandbox restore, keep
> Arissto through October 26 / Fineract starts October 27, and exclude October 27
> source payments. Do not enable recalculation afterward or start another
> exploratory test campaign. Surface the concrete run manifest and actual
> immutable plan; stop on unsupported shared behavior instead of forcing partial
> acceptance.
