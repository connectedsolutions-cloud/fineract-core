# Loan reconciliation handoff

## Outcome

Make the Arissto loan migration reconcile source-exact in Fineract before
Mobile Collections is allowed to complete repayment links. For every supported
historical loan, the native Fineract result must preserve the frozen installment
dates and principal/interest amounts, every source movement identity/date/total
and component allocation, terminal status, cutover balances, refinance
relationships, and balanced accounting entries.

This is the durable implementation and evidence handoff. It records the
evidence from the full local `default`-tenant exercise on 2026-08-30,
distinguishes fixed engine defects from open portfolio-wide migration defects,
and gives the next investigation a bounded order.

## Safety and operating boundary

- Arissto is strictly read-only. Use only `SELECT` and catalog/metadata reads.
- Work in `tools/arissto-sync`; do not add runtime code to the exploration
  repository.
- Write only to an explicitly selected Fineract target. Do not use production
  for this investigation.
- Never delete or rewrite an active Fineract loan to make reconciliation pass.
- Resolve loans and transactions only by their deterministic Arissto external
  IDs. Never fall back to date-and-amount matching.
- The local `default` tenant is intentionally non-empty and now contains loans
  produced by several proof/full runs. Old exact-identity loans created before
  the source-exact schedule writer are evidence, not a clean acceptance
  baseline.
- Do not run Mobile Collections apply while the corresponding loan repayment
  identities or allocations remain blocking.

## Authoritative evidence baseline

Local preflight selected:

```text
target: local
tenant: default
target fingerprint: 264d304e2927f694
source loan count: 2,490
```

The current contract full plan is
`1eeadbdec4a04d76b02cef67c7dddeee`. Its apply run is
`e8bbff21f3bf42e2abdaf1496eb73c7b`.

The plan covered all 2,490 loans:

| Planned/executed outcome | Count |
|---|---:|
| Newly synchronized | 138 |
| Deterministically recovered | 27 |
| Directly quarantined in the run | 987 |
| Dependency-blocked in the run | 1,238 |
| Root failures | 100 |

Plan-time quarantine classification identified 2,020 loans. Run-time direct
quarantine and dependency-block counts differ because a quarantined or failed
predecessor blocks later refinance dependants. Do not add these categories
together as distinct source loans without evaluating the dependency graph.

Strict reconciliation of the 165 synchronized/recovered loans returned:

| Blocking result | Count |
|---|---:|
| Historical transaction-allocation mismatches | 2,101 |
| Schedule mismatches | 5 |
| Principal/cutover-balance mismatches | 58 |
| Terminal-status mismatches | 29 |
| Missing source-identified target transactions | 29 |
| Total blocking mismatches | 2,222 |
| Loans affected by at least one mismatch | 155 of 165 |

Reconciliation also reported 300 visible, non-blocking variances:

| Reviewed variance | Count |
|---|---:|
| `native_schedule_component_variance` | 146 |
| `accepted_native_allocation_balance_variance` | 82 |
| `full_native_schedule_not_cutover_comparable` | 72 |

These variance classes are not permission to weaken a blocking rule. Any new
exception requires source evidence, a narrow identity/classification, and an
explicit contract decision.

## Work started on 2026-08-30

The first recommended implementation step is now available. Loan reconciliation
can persist a compact JSON artifact that groups blocking mismatches, reviewed
variances, and failed/quarantined items while retaining every affected source
key and a bounded sample per group:

```bash
./arissto-sync reconcile \
  --run e8bbff21f3bf42e2abdaf1496eb73c7b \
  --target local \
  --report .arissto-sync/reports/loan-reconciliation-e8bbff21f3bf42e2abdaf1496eb73c7b.json \
  --sample-limit 3
```

The generated artifact is ignored local evidence. Running it against the
authoritative full run reproduced 2,222 blocking mismatches across 155 source
loans and 300 reviewed variances. The allocation group contains all 2,101
movement mismatches across the same 155 loans; its first three samples are the
three loan `1254` repayments described below.

A read-only/API diagnostic trace of the existing exact-identity target loan
`ARISSTO:CRD:1254` established the first concrete cause boundary:

- movement `0000010987` is posted on the first due date, when Fineract has
  already assessed a `$0.06` installment insurance charge. The ordinary
  repayment strategy therefore consumes `$0.06` as fee and reduces principal
  from the source `$12.03` to `$11.97`;
- movement `0000011203` repeats the same behavior with a `$0.05` assessed fee,
  reducing principal from `$12.17` to `$12.12`; and
- final movement `0000011389` uses the ordinary payoff allocation across
  future native schedule obligations, producing fee/interest/principal
  `$0.16/$2.93/$73.63` instead of source `$0.05/$0.87/$75.80`.

The resulting journal entries balance but follow those native target
components exactly. This rules out reconciliation-only normalization: the
source-exact allocation must be established inside the domain transaction
before charge-paid-by, schedule, balance, and journal processing. No loan or
transaction was created, changed, reversed, or deleted during this diagnostic
pass.

The permission-gated implementation slice is now in place:

- `POST /loans/{loanId}/transactions?command=sourceExactRepayment` maps to the
  dedicated `SOURCEEXACTREPAYMENT_LOAN` permission;
- the request requires principal, interest, fee, and penalty portions whose
  exact sum equals the transaction amount, plus a deterministic external ID;
- the command is rejected unless the loan uses the Credesal accrued-interest
  transaction strategy;
- the frozen requested allocation is persisted on `m_loan_transaction`, copied
  during reverse/replay, and applied component-by-component through native
  installment and charge processing;
- an unrepresentable component fails the command instead of falling through to
  native reallocation; and
- the migration writer uses the new command and immediately verifies both the
  total and all four returned components before continuing the loan.

The zero-cash component-reallocation exception uses a separate migration-only
command, `sourceExactComponentReallocation`, guarded by
`SOURCEEXACTCOMPONENTREALLOCATION_LOAN`. It accepts only an `ARISSTO` external
identity, positive principal, equal negative interest, zero fees/penalties, and
zero transaction amount. The transaction persists the reversal movement IDs
and repayment movement ID, changes the schedule in one transaction, and posts
balanced debit-interest-receivable / credit-loan-portfolio journals. Ordinary
repayment commands still reject negative components.

The focused domain canary reproduces the first loan `1254` divergence shape:
an ordinary `$13.18` repayment would consume the assessed `$0.06` fee, while
the source-exact path preserves `$12.03` principal, `$1.15` interest, and zero
fee. A second test proves that excess component demand is rejected. Provider
compilation and all 233 sync-engine tests pass. Local Fineract restart applied
Liquibase migration `0307`; local preflight and a target-backed inspection of
loan `1254` report no schema blockers, and the permission row is present. This
is implementation and deployment-readiness proof. The posted-lifecycle canary
results are recorded next.

## Sequential posted-lifecycle canary — 2026-08-30

The local `default` tenant was exercised with fresh proof namespaces so the
canaries did not reuse the canonical migration identities or older pre-writer
loans:

```text
1254 proof namespace: alloc1254-20260830
1315 proof namespace: alloc1315-20260830
1905 proof namespace: alloc1905-20260830
```

Proof namespacing changes every target loan, movement, reversal, refinance,
charge, and adjustment external ID, but it does not change the canonical source
hash stored in the plan. Reusing the same namespace deterministically recovers
the proof loan instead of creating another copy.

### Loan 1254

Plan `017b0ba615ab4dfd84cb1332462be4bd` was reapplied as run
`50b6843bebca4f8eb2293357e766e7c1`. The writer recovered the existing proof
loan and did not create another loan or transaction. Reconciliation returned:

```text
ok: true
blocking mismatches: 0
failed/quarantined: 0
```

All three repayments preserve their frozen source components sequentially.
The report retains one reviewed `native_schedule_component_variance`: Arissto's
closed-loan snapshot carries a `$0.05` fee balance while the native target is
closed with `$0.00` fee outstanding. This is visible evidence, not a blocking
transaction-allocation mismatch and not a reconciliation suppression.

### Loan 1315 refinance chain

Scoping source loan `1315` correctly expanded the proof to its native refinance
chain `1315 -> 1411 -> 1541`. Plan
`129afc0a5c544f0291718ce46f168508` was reapplied as run
`7c57a447ebf54c369e755b3ad9a9d00d`; all three proof loans were recovered.

The original-schedule API/reconciliation fix removed the prior false schedule
mismatches on `1411` and `1541`. Every ordinary source-exact repayment in the
chain now matches. Two blocking allocation differences remain, both on the
repayments created atomically by native Fineract top-up disbursement:

| Predecessor | Movement | Source allocation | Native target allocation |
|---|---|---|---|
| `1315` | `0000012554` | P `35.71`, I `0.00`, F `0.00` | P `35.07`, I `0.61`, F `0.03` |
| `1411` | `0000014891` | P `49.18`, I `0.24`, F `0.00` | P `47.95`, I `1.41`, F `0.06` |

This narrows the remaining boundary: the permission-gated source-exact command
is working for ordinary, adjusted, and mobile-collection repayments, but native
loan-to-loan top-up currently creates its predecessor repayment through the
ordinary allocation path. Do not classify these two findings as accepted
variance. The next refinance slice must carry a validated source-exact payoff
allocation through the native loan-to-loan transfer while retaining the native
top-up relationship, balanced accounting, and atomic disbursement behavior.

#### Goodwill bridge risk and evidence of a broader pattern

The current proof writer creates explicitly classified goodwill bridge
transactions when Fineract's dated prepayment quote differs from the frozen
Arissto refinance payoff. Treat these bridges as diagnostic evidence only, not
as accepted production migration behavior. A generic goodwill credit can hide
an incorrect interest, insurance-fee, penalty, or settlement calculation; it
also follows Fineract's native allocation order and can consume components that
the subsequent source-exact payoff needs to preserve.

This is not currently supported as a one-record source anomaly:

- the `1315 -> 1411` refinance required a `$5.35` dated bridge;
- the `1411 -> 1541` refinance required a `$7.33` dated bridge and a further
  `$0.24` post-top-up residual bridge;
- both successfully posted top-ups produced blocking predecessor-payoff
  component mismatches;
- thirteen other successors failed because Fineract considered the predecessor
  outstanding too high for the successor amount; and
- three other refinances reached payoff with a Fineract prepayment quote below
  the source payoff.

These findings show a recurring refinance-semantic boundary, although they do
not yet prove that every refinance has the same cause. Before changing the
native transfer or accepting any exception, enumerate the supported
single-predecessor refinance population and compare, immediately before each
refinance, Arissto versus Fineract principal, accrued interest, insurance/fees,
penalties, and total settlement. Attribute every difference to a component and
business rule, then group exact matches and mismatch patterns.

The preferred outcome is for Fineract to calculate the same settlement as
Arissto from equivalent state. If Arissto intentionally waives or separately
handles a component at refinance, represent that with a narrowly classified,
reviewed native waiver/adjustment and correct accounting. Only if the portfolio
analysis isolates a genuinely exceptional source record may it receive an
identity-specific migration exception. Do not generalize or accept the current
goodwill bridge merely because totals can be forced to close.

#### Source-exact refinance implementation and canary — 2026-08-30

The `1315 -> 1411 -> 1541` discrepancy is now fixed for the supported native
single-predecessor top-up path. The implementation preserves Fineract's native
loan-to-loan transfer and accounting behavior while making every migration-only
piece deterministic and component-exact:

- the plan freezes Arissto's payoff principal, interest, fee, and penalty;
- the dated quote difference is posted through the permission-gated
  `sourceExactGoodwillCredit` command, never through generic goodwill
  allocation;
- `sourceExactTopupDisburse` carries the frozen payoff allocation into the
  atomic predecessor repayment;
- the successor net disbursement, transfer disbursement, and predecessor payoff
  each have their own deterministic external ID; and
- if native top-up processing leaves a residual, its principal/interest/fee/
  penalty summary must add back to the target total and is closed through a
  second component-exact goodwill credit. An inconsistent component summary
  fails closed.

Tenant migration `0309_add_source_exact_refinance_permissions.xml` adds the two
new permissions `SOURCEEXACTGOODWILLCREDIT_LOAN` and
`SOURCEEXACTTOPUPDISBURSE_LOAN`. Readiness requires both plus the existing
`SOURCEEXACTREPAYMENT_LOAN` permission.

Fresh proof plan `d5bd2b2940b342e4a629b9aa02bce7f3` used namespace
`refifix1315b-20260830`. The first apply exposed one real native residual after
the otherwise exact `1411` payoff: `$0.24` interest. Local transaction evidence
showed that the payoff itself was already correct at P `49.18`, I `0.24`, F
`0.00`; the remaining amount was scheduled target interest. The recovery path
posted exactly I `0.24` under
`ARISSTO:CRD-REFI-FINAL:1411:1541`, then required the predecessor to be closed.

Reapply run `64932e0db3a54a3196af86f0ff91efaf` recovered all three
loans. Reconciliation returned `ok: true`, three loans, zero mismatches. The
same immutable plan was applied again as run
`9304440fb0714224962716f70c92fba2`; reconciliation again returned `ok: true`
with zero mismatches and reused all deterministic identities.

The canary adjustments are now explicit evidence rather than generic forcing:

| Refinance | Dated component bridge | Final component bridge | Source payoff preserved |
|---|---:|---:|---|
| `1315 -> 1411` | `$5.35` | `$0.00` | P `35.71`, I `0.00`, F `0.00` |
| `1411 -> 1541` | `$7.33` | `$0.24` interest | P `49.18`, I `0.24`, F `0.00` |

This closes the stated canary allocation defect. At the time it did not remove
the graph quarantines; the later `G5-GRF-001` classifier below now removes only
source-proven net-zero reversed edges. Multi-predecessor graphs remain outside
the supported contract.

### Penalty-bearing movement

Loan `1905`, movement `0000020619`, is the penalty canary. Its frozen repayment
is `$66.60`: principal `$58.69`, interest `$7.83`, fee `$0.00`, and penalty
`$0.08`. Plan `8eda9f3a2751429da7ef23c74775964c` completed as run
`a1f941fa7df64bd1af2245f511dfae93`; unchanged replay run
`22415c937433497eb4a44082abd531f3` also reconciled with zero mismatches and
zero variances.

The writer creates a native specified-due-date penalty charge with deterministic
external ID `<movement external ID>:PENALTY` before posting the source-exact
repayment. Direct local database verification showed:

```text
loan transaction 4375: P 58.69, I 7.83, F 0.00, penalty 0.08
loan charge 436: amount 0.08, paid 0.08, outstanding 0.00
charge-paid-by: transaction 4375 -> charge 436, amount 0.08
journal debits: 58.69 + 7.83 + 0.08 = 66.60
journal credits: 66.60
```

The first charge attempt exposed a seed defect: the charge definition had a
null payment mode, causing a Fineract 500 response. Liquibase migration `0308`
now includes a forward-only follow-up changeset that sets regular payment mode
`0` for both already-migrated and fresh tenants.

### Defects found and closed by this canary

- Long proof external IDs previously truncated to the same 50-character
  idempotency key; keys now retain uniqueness with digests.
- Proof namespacing previously changed the frozen source hash; the canonical
  source hash is now computed before local target identity namespacing.
- A late source repayment could request historically accrued interest that was
  not yet representable on the native schedule. The Credesal processor now
  materializes only the missing post-due interest for late source-exact
  repayments and still rejects an impossible same-day component.
- Post-due materialized interest was incorrectly returned as original scheduled
  interest. The loan schedule API now exposes original interest separately, and
  reconciliation compares the frozen source schedule to the original amounts.
- Penalty allocation now uses a deterministic native charge and verifies the
  exact paid-by path instead of accepting an unrepresentable penalty component.

Regression evidence after this slice: all 233 sync-engine tests pass; the 12
focused Credesal transaction-processor tests pass; provider compilation and
local Liquibase startup succeed. Repository-wide `git diff --check` remains
noisy only because the pre-existing generated `logs/fineract.log` contains
trailing whitespace.

## Defects already fixed during the exercise

Do not reopen these unless a regression proves they are still broken.

1. **Full-scope SQL Server parameter overflow.** Lifecycle extraction bound
   more than SQL Server's 2,100 parameters, and the refinance query bound the
   complete ID list twice. Extraction now uses deterministic 900-loan batches
   and deduplicates refinance links across batch boundaries.
2. **Historical product rate envelope.** Eighty-two creates originally failed
   because line `00010` allowed at most 20% per period while frozen historical
   loans reach 30%. The reviewed maximum is now `30.00`; widening only that
   ceiling on an exact migration product is an allowed update and does not
   reprice existing loans. The 82 rate failures fell to zero.
3. **Failed-only retry expansion.** Adding a healthy product prerequisite for
   one failed loan previously selected every sibling loan on that product.
   Retry now starts with failures/crash gaps and includes only their blocked
   descendants. Explicitly failed products still bring their dependants.
4. **Truncated diagnostics.** Fineract validation bodies were cut at 240
   characters before the concrete error code. Loan failures now retain up to
   4,000 safe characters.
5. **Source-exact schedule writer foundation.** Migration products support
   variable installments. New applications preview source-derived variations,
   require an exact comparison, persist them while non-posting, and compare the
   stored schedule again before approval. The writer itself is implemented;
   the edge cases below remain.

All 221 sync-engine tests passed after these changes.

## P0 — historical transaction allocation

### Observation

This is the dominant production blocker: 2,101 movement-level allocation
mismatches affect 155 of the 165 executed loans. Source payment totals may be
correct while Fineract assigns different amounts to principal, interest, fee,
or penalty. The contract correctly treats that as blocking.

Mismatch component shapes were:

| Differing components | Movements |
|---|---:|
| fee + interest + principal | 1,706 |
| fee + principal | 365 |
| fee + interest + penalty + principal | 15 |
| interest + principal | 10 |
| fee + interest | 5 |

Fee is involved in 2,091 of 2,101 mismatches, so charge assessment/allocation
must be investigated first. This is evidence of concentration, not yet proof
of one universal cause.

Representative canaries:

- Loan `1254`, movement `0000010987`: source principal `12.03`, fee `0.00`;
  target principal `11.97`, fee `0.06`.
- Loan `1254`, movement `0000011389`: source fee/interest/principal
  `0.05/0.87/75.80`; target `0.16/2.93/73.63`.
- Loan `1315`, movement `0000011759`: source fee/interest/principal
  `0.00/1.78/23.22`; target `0.19/3.70/21.11`.

### Questions to answer

1. Is the fee difference the debt-insurance charge timing, a different
   installment charge base, a source `MONTO_OTROS`/`MONTO_SEGURO` mapping issue,
   or a combination?
2. Does Fineract assess a fee that Arissto had not yet assessed on the movement
   date?
3. Is post-due interest materialized on the same value date and outstanding
   principal that Arissto used for each movement?
4. Do adjusted repayments and Cobro Móvil repayments use the same component
   contract as ordinary repayments?
5. Are reversals restoring the exact original source components or merely
   reversing Fineract's native allocation?
6. Can Fineract's current transaction strategy express every frozen historical
   allocation without changing future native behavior?

### Recommended approach

Start with a migration-only, source-exact allocation path rather than adding
more heuristics to the general repayment strategy. The preferred design is a
permission-gated Fineract command/API used only by the migration writer that:

- accepts the frozen principal, interest, fee, and penalty components;
- validates that components equal the source payment total exactly;
- validates that the components can be applied to the native loan state;
- preserves the source movement external ID and date;
- updates native schedule, charge-paid-by, balances, and accounting through
  Fineract domain services rather than direct migration SQL;
- remains reversible by the deterministic original/reversal relationship; and
- is idempotent under response loss and failed-only retry.

This recommendation must be validated against Fineract's domain invariants. If
an explicit allocation command cannot produce valid native balances and
journals, document that result before considering a cutover adjustment. A
synthetic adjustment must never disguise a customer payment allocation
difference.

### Smallest useful proof

1. Reproduce only loan `1254` from a clean pending identity or clean tenant.
2. Trace charge assessment, accrued interest, and balance state immediately
   before movement `0000010987`.
3. Post that movement with the proposed exact allocation.
4. Verify transaction components, charge-paid-by rows, schedule paid/outstanding
   fields, balances, and journals.
5. Continue through movement `0000011389` to prove sequential state, not only
   one isolated payment.
6. Add loan `1315` as the second canary because its repeated fee and interest
   divergence is larger.
7. Add one movement from the 15 penalty-involved cases before declaring the
   allocation mechanism complete.

## P0 — source-exact schedule edge cases

The general schedule-writing mechanism works. The exact-half-cent and
full-leap-year Actual/Actual classes are now resolved; the structurally
different cases below remain blocking.

### Exact-half-cent interest — fixed and proved 2026-08-31

The cent-residual schedule failures were not isolated to `2243`. A bounded
audit identified 18 loans where the unrounded actual/365 interest ended exactly
in half a cent and Arissto selected the lower cent. Examples include `2182`,
`2243`, `2249`, `2288`, and `2346`. This differs from loan `1484`'s
operator-adjusted schedule history, loan `1864`'s full-leap-year Actual/Actual
denominator, and invalid duplicate-date or all-zero plans.

Fineract now applies `HALF_DOWN` to installment interest only for products using
`credesal-accrued-interest-first-strategy`; ordinary products retain the tenant
rounding mode. The setting is propagated through both new-application preview
and persisted schedule regeneration. The writer also prepares a refinance
predecessor before invoking a non-posting preview that carries `loanIdToClose`,
and proof namespaces now cover refinance penalty-charge identities.

Fresh plan `2b986e0021a142969eac817b9cdf15ec`, run
`75c5795f91854e51adb5a682c61eeeca`, completed the full three-loan chain ending
in `2096 -> 2243`. Reconciliation returned `ok: true`, no failed or quarantined
items, and no mismatches. Loan `2243` stored 120 installments with principal
`786.00` and interest `369.19`; installment 44 is principal `5.70`, interest
`3.93`, and installment 120 principal is `9.16`. Unchanged replay run
`6d72bc623ad34c229e5494be39384347` recovered all three loans without a new
write and reconciled with the same zero-mismatch result.

### Full-leap-year Actual/Actual denominator — fixed and proved 2026-08-31

Fineract cumulative daily-interest schedules now derive an `ACTUAL` denominator
from the period-start year. A period beginning in 2027 therefore uses 365 even
when it ends in 2028, while periods beginning in 2028 use 366. Fixed-365,
fixed-360, non-daily, and PMT paths retain their previous behavior.

Focused unit coverage exercises a normal 2027 period, the 2027-to-2028
boundary, a 2028-start period, and fixed-365/fixed-360 controls. Scoped plan
`098dfdc61d5f4e47a8613a3ec6a12634` passed the exact preview for loan `1864`
with source aggregate interest `2071.05`. Run
`cefea617cc97417e892e160a873921df` recovered its complete persisted lifecycle;
reconciliation verified the exact schedule and movements, terminal state, and
balanced journals without a blocking mismatch. Same-plan replay
`e1712be224184eb196c2d89b36d5f416` remained mismatch-free.

### Preview mismatches before approval

Fifteen loans failed the non-posting exact preview:

```text
1484, 1864, 1895, 1964, 1973, 1996, 2010, 2016, 2028, 2036,
2047, 2176, 2276, 2307, 2471
```

Across these diagnostics there were 52 principal-installment differences, 39
interest-installment differences, and 15 aggregate-interest differences.
Patterns are not uniform:

- Loan `1484` has large redistribution across almost the entire 18-installment
  schedule; source/target aggregate interest is `797.59/884.19`. The source
  proves that its current plan follows two operator-created archived plan
  versions. Treat the current exact plan as authoritative and retain the
  archived versions as provenance; do not replay those edits as loan-service
  behavior. `G5-SCH-002` is closed by a loan-specific reviewed exception: the
  native schedule variance stays visible and non-blocking, while movements,
  component totals, cutover balances, and terminal status remain exact.
- Loan `1864` formerly differed mainly by cents in installments 43–48;
  aggregate interest was `2071.05/2071.19`. The resolved `G5-SCH-006` native
  cumulative-schedule fix now uses 366 for its periods starting in leap year
  2028 and 365 for the cross-year period starting in 2027. The source-wide
  audit found the discriminating signature in 5,289 rows across 897 current
  loans; no loan-specific exception was introduced.
- Loans `1895` and `1964` are cent-level residual cases with aggregate interest
  off by `0.01`.

Do not solve all 15 with one rounding tolerance. Dates and each principal and
interest amount are contractually exact. Group the cases by frequency,
days-in-year basis, final residual, and whether the source contains irregular
principal/interest redistribution. Confirm that the variation payload changes
the intended installment and that Fineract is not recalculating another
component afterward.

### Non-monotonic source schedules

- Loan `2120`: `validation.msg.loan.modifiedinstallments.not.greater.than.zero`.
  Later source tracing proved this was an undisbursed all-zero shell superseded
  by valid loan `2121`, not a supported schedule-generation case. It is now an
  explicit reviewed source-error quarantine; the planner must create no target
  loan for `2120` and must keep the replacement identity visible in reporting.
  Scoped plan `b992ad92435242d49a97bd3fa7f52d4f` emitted the expected
  `quarantine-loan` and no `create-loan`. Target loan `249` on the current local
  tenant predates this policy and remains evidence from the failed attempt; the
  sync engine does not delete or rewrite it.
- A live read-only audit found nine current schedules whose final installment
  date is not strictly after the preceding installment: `945`, `1117`, `1743`,
  `1748`, `2069`, `2241`, `2254`, `2355`, and `2374`. Eight move backward and
  `2374` duplicates `2026-11-08` across installments 99 and 100. Seven also
  carry negative final interest, and eight have source adjustment history.
- Loan `2241` moves installment 160 backward from installment 159 on
  `2027-01-02` to `2026-12-17`, a date already used by installment 143.
- Loan `2374` therefore failed with
  `validation.msg.loan.variable.schedule.modify.date.can.not.be.due.date`
  because the source itself asks Fineract to persist two contractual periods on
  `2026-11-08`; changing the API anchor would not make that schedule valid.

These are source-plan chronology failures, not evidence for a Fineract date
override. The planner now emits `non_monotonic_source_schedule_dates` before
any Fineract API call. The already reviewed line `00001` loan `945` retains its
narrow native-schedule exception; the other eight remain explicit whole-loan
quarantines. Full sync-engine tests pass. Scoped plan
`6a60ac321b954f2d92ebc62a01f95e4f`, run
`8706155b05d64157957dc473734b9314`, and reconciliation all reported the exact
same eight `quarantine-loan` outcomes with null target IDs and no financial
state. This closes `G5-SCH-003` without a Fineract date override.

### Historical insurance on reviewed native schedules

The same scoped run exposed a separate issue on reviewed exception loan `945`.
Arissto has eleven `CRD_DETALLE_CARGOS` rows of `$0.66`, each linked to the
corresponding repayment and matching `CRD_MOVIMIENTOS_CARTERA.MONTO_SEGURO`,
for `$7.26` of historical insurance. The accepted native Fineract schedule
assessed `$7.18`. After ten source-exact payments, target loan `451` had `$0.58`
of fee outstanding; movement `0000015500` required another `$0.66`, so the
permission-gated command correctly failed with an unrepresentable `$0.08` fee
remainder.

Do not weaken that validation and do not classify the difference as a schedule
date variance. The loan contract already requires exact historical insurance
charges and paid-by allocations before cutover. The writer currently
materializes historical penalties but not those insurance facts. `G5-CHG-001`
owns the missing implementation: first spike a flat specified-due-date fee
charge through existing native APIs, then add source extraction, deterministic
charge identities, paid-by and journal reconciliation, and unchanged replay.
Fineract Java code is justified only if the native charge path cannot represent
the proved source contract.

### Resolved post-lifecycle schedule presentation

The old target identities for loans `1934` and `2262` combined two effects.
They predated source-exact repayment allocation, so later post-due interest
used principal balances that had already diverged from Arissto. The schedule
API also exposed current interest including materialized post-due interest even
though original contractual interest remained intact.

A clean local proof namespace replayed both histories with exact components.
Every repayment identity, total, principal, interest, fee, and penalty matched
the frozen source event. Contractual interest remained in
`interestOriginalDue`; `interestDue` contained contractual plus separately
tagged post-due interest.

The remaining structural difference came from charge materialization, not
interest regeneration. A specified-due-date penalty after contractual maturity
appended a charge-only period with zero original principal and interest.
Reconciliation now excludes only such non-contractual periods from
principal/interest schedule cardinality while continuing to require exact
charge identity, amount, paid-by allocation, balances, and balanced journals.

Both clean runs and their unchanged replays reconciled with zero mismatches and
zero variances. Replay recovered the same identities without adding another
transaction, charge, schedule row, or derived-interest amount.

## P0 — closed-loan cutover and missing transactions

Twenty-nine source-closed loans ended active in Fineract, retained principal
and total outstanding, and were missing one source-identified target movement.
Each generated four related blocking findings: terminal status, principal
balance, cutover total, and transaction missing.

Affected loans:

```text
1379, 1920, 1928, 1931, 1948, 1952, 1958, 1961, 1965, 1972,
1991, 2011, 2022, 2025, 2026, 2046, 2055, 2059, 2064, 2075,
2088, 2093, 2094, 2096, 2119, 2123, 2130, 2226, 2279
```

Example loan `1379` is source state `3` with zero source balance, but the target
remained Active with principal `183.87` and total `197.95`; movement
`0000015621` was missing.

First determine why the movement was not posted. Do not repair terminal state
independently while a source cash movement is absent. After the movement path
is fixed, reassess whether the existing bounded goodwill/cutover adjustment is
still necessary and whether its date, maximum, accounting, and reversal rules
remain valid.

## P1 — refinance and top-up failures

The source-exact native top-up mechanism is implemented and proved on the
`1315 -> 1411 -> 1541` chain above. The cases in this section remain the next
portfolio-validation set; do not treat the canary result as evidence that these
different balances or graph shapes are automatically safe.

### Native top-up domain rejection — boundary fixed 2026-08-31

Thirteen successors failed with
`error.msg.loan.amount.less.than.outstanding.of.loan.to.be.closed`: the new loan
amount was not greater than Fineract's outstanding predecessor balance.

```text
2049, 2121, 2141, 2165, 2181, 2182, 2183, 2217, 2241, 2242,
2243, 2278, 2288
```

All thirteen source successors exceed their source-exact payoff. The rejection
was caused by the target predecessor quote carrying excess replay-created
interest/fees before successor application validation. The writer now obtains
the dated quote and posts the permission-gated, component-exact goodwill bridge
*before* creating the successor. It then refetches the quote and requires exact
convergence; principal or fee shortfalls still fail closed.

Local evidence:

- plan `c69f3580bfc94d14b931bc6bccab3714`, run
  `98e50088d1d44fd89210698b6c79cbbf`, recovered `1965 -> 2049` and
  `2130 -> 2278` after applying `$248.00` and `$206.17` dated component
  bridges respectively;
- both predecessor loans had `$0.00` post-top-up residual and no refinance
  mismatch; and
- the broader fresh-identity plan `eef023ad96304e82a5094163a4b3b972`
  executed 69 of 83 supported loans. Its remaining failures were schedule
  preview/modification defects plus two newly exposed penalty-timing cases,
  not `loan.amount.less.than.outstanding` rejections.

Continue comparing, immediately before successor creation:

- source predecessor payoff;
- Fineract predecessor principal, interest, fee, and penalty outstanding;
- source successor approved/disbursed amount; and
- any allocation or accrual difference already introduced by prior replay.

Do not weaken Fineract's ordinary top-up rule. The bridge is deterministic,
permission-gated, source-component bounded, and used only by the migration
writer.

### Payoff/prepayment shortfall — fixed and proved 2026-08-31

Three refinances reached payoff but Fineract's available prepayment was below
the source payoff:

| Successor loan | Target prepayment | Source payoff |
|---|---:|---:|
| `2076` | 49.79 | 50.28 |
| `2112` | 21.05 | 24.67 |
| `2175` | 60.05 | 61.03 |

The three historical cases were replay-allocation/accrual timing differences.
The exact top-up command now settles the predecessor using the frozen source
component total instead of requiring equality with the native quote. Only a
missing source interest component may be materialized by the Credesal exact
repayment processor; principal, fee, and penalty shortfalls remain blocking.
The successor net cash is therefore source disbursement minus source payoff,
not source disbursement minus a drifting native quote.

All three independent fresh-identity chains completed without a failed or
quarantined loan, refinance mismatch, or post-top-up residual:

| Historical case | Proof run | Result |
|---|---|---|
| `1961 -> 2076` | `dfbc51c944eb4f78a7278eab5ee5c07c` | exact through descendant `2131` |
| `1952 -> 2112` | `144d0e66369443a68665876dc6d2e4d2` | exact through descendants `2317`, `2490` |
| `2025 -> 2175` | `a1ecdb3039c044108c81647117eeff71` | exact through descendants `2378`, `2473` |

The broader proof exposed source payoff penalties of `$0.09` and `$0.07` that
were absent from the target quote. The planner now freezes the historical
penalty-charge identity and the writer assesses that charge before quoting.
Run `61e588561b354508b77cf49ae2e58aea` proved `2334 -> 2427` with a zero final
residual. The `2096 -> 2243` chain is now proved by run
`75c5795f91854e51adb5a682c61eeeca`. Refinance preparation runs before the
non-posting preview because Fineract applies ordinary top-up validation when
`loanIdToClose` is present. The preparation is deterministic and recoverable;
its penalty-charge identity is proof-namespaced during isolated runs.

### Reviewed voided attempts and consolidation implementation

The original source inspection found 1,364 refinance links: 1,346 active and
18 reversed. The latest 2026-09-01 audit found 1,369 links: 1,351 active and
the same 18 reversed. The apparent ambiguity is deterministic but not a normal
top-up:

- all 16 ambiguous predecessors have one reversed refinance followed by one
  later active refinance;
- the other two reversed links have no later successor; and
- every predecessor payoff has an exact `4/00004`, while every abandoned
  successor contains only an exact `4/00002 -> 4/00030` pair and is canceled
  with zero disbursement and balances.

These are fully voided attempts, not target financial history to replay. The
planner now preserves all four source movement IDs, emits a reviewed no-write
action for each abandoned successor, omits both net-zero pairs, and removes
only the reversed edge from the effective graph. A partial signature continues
to fail closed.

The 12 multi-predecessor successors are true two-loan consolidations. In every
case successor principal exceeds the combined source payoffs. Fineract now uses
the existing refinancing header as a compatibility aggregate plus one persisted
settlement row per predecessor. The dedicated source-exact command atomically
settles both frozen payoffs and disburses the remaining net cash.

Ownership divides this cohort. Successors `2252`, `2402`, and `2406` have two
predecessors owned by the successor client. The other nine each contain one
predecessor owned by a different client. The latter are not eligible for the
same-client native contract without an explicit authorization/participant
model.

Full plan `8567fd648ada4edc99cc6aa769ecf946` classified all 18 attempts,
produced 18 provenance-only omitted successors, and left zero reversed or
ambiguous graph quarantines. Scoped plan `3b2dff35aa2c4b39b236c3367520caf1`
proved `186 -> [voided 346] -> active 347`. Plan
`3f68a7d075b94309b4f0bc82436464d8` proved that the two predecessors without a
later successor, `278` and `1521`, remain migratable while abandoned successors
`549` and `1765` remain no-write actions. No financial canary is required
because this policy creates no target state.

Planner, writer, reconciliation, API, and UI support is implemented for the
same-client shape. Namespaced plan `fe97d37686904e1bbc75e1904ca1e3fa` proved
`2042 + 2205 -> 2406`; run `3b2e253daee3432dafd03e66a178957e`
and unchanged replay `4f8cb9a347a645b98ebc0814d717f891` both reconciled
with `ok=true`, zero failed or quarantined items, and zero blocking mismatches.
Replay recovered all six chain loans without duplicate financial state. The
full 12-successor cohort remains `PENDING` until the nine cross-client cases
receive an approved ownership/authorization design and equivalent canary.
Consolidations are never flattened through the legacy single-predecessor input.

## P1 — pre-writer local identities

Sixty-seven exact-identity loans in `default` failed
`existing_loan_schedule_mismatch_before_continue`. They were created by older
proof runs before the source-exact schedule writer. The guard is correct and
must remain fail-closed.

These failures do not prove that a fresh migration would create the wrong
schedule. Use a clean tenant or clean, never-migrated identities for acceptance.
Do not add an in-place schedule rewrite for approved, disbursed, or active
loans. The complete list remains in run
`e8bbff21f3bf42e2abdaf1496eb73c7b` and can be queried from local sync state.

## P1 — portfolio quarantine prerequisites

The historical pre-fix full plan classified 2,020 loans for quarantine. Reason
counts overlap because 115 loans have multiple reasons; these figures are
retained as provenance and are not the current acceptance baseline:

| Reason | Loan occurrences |
|---|---:|
| Target staff exists but is not a loan officer | 1,097 |
| Missing or inactive target loan officer | 909 |
| Source movement component residual | 107 |
| Invalid source application-date order | 48 |
| Reversed refinance top-up unsupported | 36 |
| Ambiguous refinance successor | 16 |
| Multi-predecessor refinance unsupported | 12 |
| Missing target client | 2 |
| Unpaired reversal | 2 |
| Orphan repayment reversal | 1 |

Treat these as separate workstreams:

- **Staff prerequisites:** verify employee sync coverage, active status, office,
  and native loan-officer eligibility. Do not drop the officer assignment just
  to increase migration counts without a business decision.
- **Missing clients:** repair the upstream client sync/mapping before retry.
- **Component residuals:** completed by `G5-DAT-001`; the current 55-row cohort
  is fully classified through returned cash, independently proven pre-detail
  insurance, or one net-zero reversed manual adjustment pair.
- **Date order:** completed by `G5-DAT-002`; the bounded legacy stamp is
  preserved as provenance without silently reordering financial events.
- **Refinance/reversal graph anomalies:** retain explicit quarantines until a
  dedicated supported lifecycle exists.

The historical staff reasons dominated that plan and could hide loan-engine
progress. Current plans must use the lossless three-role staff-assignment
contract and report remaining upstream prerequisite gaps separately.

## Movement-component acceptance (`G5-DAT-001`) — 2026-09-01

The original 107-row count came from the raw diagnostic formula before the
typed historical-insurance interpretation. Recomputing after that mapping left
55 movements across 40 loans. Every row has a source-backed classification:

- 41 movements across 27 loans have components exactly equal to
  `MONTO_PAGADO`, while `MONTO - MONTO_PAGADO` exactly equals
  `REINTEGRO_MONTO`. The writer posts only the applied amount. Two zero-applied
  Cobro Movil receipts are omitted as fully refunded collections.
- 12 movements across 12 loans predate typed charge detail. `MONTO_OTROS` is
  accepted as debt insurance only when exact PRE/POS other-balance changes and
  one equal insurance-account credit independently confirm it.
- Two movements on loan `9` are an exact adjusted-payment/reversal pair. They
  are net-zero manual-adjustment history and are discarded together.

Generic `MONTO_IVA` was zero in the cohort. Generic `MONTO_OTROS` remains
excluded unless the narrow evidence rule above succeeds, preserving the
existing protection against double-counting separately itemized insurance.
[Source evidence](../../../../../../credesal-db-space/docs/learnings/prestamos.md#g5-dat-001-residuos-de-componentes).

Full cohort plan `33ba1eacf71042f1b15a90701856d945` produced 39
applied-after-refund events, two omitted fully refunded rows, 12 deterministic
legacy insurance charges, one discarded manual pair, and zero component
residuals. Its only two quarantines were unrelated first-accrual signature
guards on loans `1` and `2`.

Local run `a1a06df48b6c4cffafdf2c9969845f4c` successfully synchronized refund
loan `241`, manual-adjustment loan `9`, and required successor `577`, all with
zero reconciliation mismatches. Legacy representative `3` was blocked before
creation by an independent exact-schedule preview mismatch. Replacement run
`c13ee2b678f3433286b764ab4884c7ef` synchronized legacy-insurance loan `6` and
successor `217`; reconciliation returned `ok=true` with zero mismatches,
failures, or quarantines. This closes the component issue without weakening
the schedule guard. Same-plan replay `841e0dc93d234cf6b010dd52d777c7f7`
recovered loans `241`, `9`, and `577` and reproduced only loan `3`'s independent
schedule failure. Same-plan replay `75dada70399b4a9c8d468764fc3c73bb`
recovered loans `6` and `217` and reconciled with `ok=true`, zero mismatches,
failures, or quarantines. Neither replay created duplicate financial state.

## Inclusive first-accrual and legacy-timeline acceptance — 2026-09-01

The two coupled acceptance items `G5-SCH-007` and `G5-DAT-002` are complete.
The source-derived schedule classifier selected
`legacy-inclusive-first-accrual-day` for loan `5`, setting
`interestChargedFromDate` to `2023-03-29` and `daysInYearType` to `365` without
using a loan-ID allowlist or date cutoff. The plan retained the separately
classified `legacy-late-approval-stamp` timeline and used the effective
disbursement date for native approval while preserving the raw source dates in
the provenance datatable.

Fresh namespace `g5-sch007e-20260901` produced plan
`871e3b5aa06749caba5e157fa83491cb`. Apply run
`cd4ab91fb4814e7fb4b63027dd0a1536` completed loan `5` through application,
approval, disbursement, and disbursement reversal. Strict reconciliation
returned:

```text
ok: true
loans: 1
products: 1
legacy timelines: 1
staff assignments: 1
blocking mismatches: 0
variances: 0
adjustments: 0
failed/quarantined: 0
```

Reapplying the identical plan produced run
`831e1c25556541ccb17a403d196ea758` with `loans_recovered: 1` and no new loan or
financial lifecycle. Its independent reconciliation returned the same exact
zero-finding result. Together with the exact full-schedule previews for loans
`5` and `40`, the source-wide 44-inclusive/1,309-exclusive/zero-ambiguous
classification audit, and later exclusive loan `51` as the regression control,
this closes the bounded legacy first-accrual behavior without weakening normal
Fineract schedule handling.

## Terminal charge-only schedule rows — 2026-09-01

`G5-SCH-010` is complete for loans `381`, `1775`, `1871`, and `2006`. The
planner now treats the source schedule as historical reference only when its
complete bounded signature is present: exactly one terminal row has zero
principal and interest with positive `MONTO_OTROS`; contribution,
restructuring, and deferred markers are absent; preceding installments allocate
the full principal; installment numbers are sequential; and dates are strictly
increasing. Any near-match returns to exact-source schedule enforcement and
remains blocking. The classification does not synthesize an installment,
payment, adjustment transaction, or charge from the terminal row.

Fresh namespace `g5-sch010-20260901` produced sandbox plan
`578ee952e59b4515897b585a1c4be190`. The four requested loans expanded to eight
loans through required refinance dependencies. Apply run
`e74a6f9629644ec0aad3e908f0dde9e3` completed all eight, and strict
reconciliation returned:

```text
ok: true
loans: 8
products: 1
staff assignments: 8
blocking mismatches: 0
failed/quarantined: 0
```

The reviewed terminal-row differences remain visible as
`historical_reference_only_schedule_variance`. Charge identity and paid-by
history, cutover insurance, future recurring insurance for the active loans,
source movements, balances, terminal status, and accounting were reconciled
independently; none produced a blocking finding. Reapplying the immutable plan
produced run `39a2022411cb42ae82e0fad855a79fd0` with `loans_recovered: 8` and
`unchanged: 1`. Its independent reconciliation returned the same counts with
zero failures, quarantines, or mismatches. Both runs used tenant `sandbox`
backed by `fineract_sandbox`; the local default database was not targeted.

## Current completion boundary and remaining sequence — 2026-09-01

The compact reconciliation report, source-exact historical repayment
allocation, normal/adjusted/Cobro Movil/reversal handling, penalty
materialization, and supported single-predecessor refinance payoff mechanisms
are implemented and canary-proved. The high target-outstanding and source
payoff-shortfall classes are also fixed for the supported one-predecessor path.
Do not continue to report those mechanisms as unimplemented.

Loans is nevertheless **not complete**. Gate 5 remains open until this remaining
sequence is finished:

1. Resolve the remaining structurally distinct source-exact schedule-preview
   and variable-installment API/modification failures. The exact-half-cent,
   full-leap-year Actual/Actual, and legacy inclusive-first-accrual classes are
   complete; this does not clear unrelated redistribution or duplicate-date
   classes. The all-zero loan `2120` is separately classified and quarantined.
2. Re-run the previously failing schedule/API and post-lifecycle cases,
   including the closed-loan population, and require exact movement, terminal,
   cutover-balance, and journal reconciliation.
3. Complete clients and employees on the selected target, verify active native
   loan-officer eligibility, and re-plan. Do not bypass staff prerequisites by
   omitting the source loan officer.
4. Review the remaining portfolio quarantine classes. Movement-component
   residuals and invalid application-date ordering are complete and should not
   be counted as open classes; missing clients must be repaired upstream.
5. Retain reviewed provenance for fully voided refinance attempts without
   replaying their net-zero financial pairs; quarantine any partial signature.
   Allow the proved same-client consolidation lifecycle. Keep cross-client
   consolidations quarantined until an explicit participant/authorization
   contract is approved and proved.
6. Run the strict matrix on a clean local tenant or never-migrated identities;
   old approved/active proof loans with pre-writer schedules are not an
   acceptance baseline and must not be rewritten.
7. Run a fresh full supported-population plan, apply, and reconciliation. Zero
   failed supported loans and every acceptance criterion below are required.
8. Build a second full plan and require zero unintended loan, transaction,
   charge, paid-by, transfer, or journal writes.
9. Only after Loans passes may Mobile Collections be planned and applied for
   final repayment-link coverage. It must link by deterministic transaction
   identity and create no second repayment or other financial row.

## Acceptance criteria

Gate 5 and downstream Mobile Collections linking remain blocked until all of
the following are true for the selected supported population:

- zero blocking installment count/date/principal/interest mismatches;
- zero aggregate scheduled principal/interest mismatches;
- zero source movement identity, date, total, type, reversal, or component-
  allocation mismatches;
- zero missing source-identified target movements;
- exact source terminal status and reviewed cutover balances;
- supported refinance predecessors/successors reconcile exactly;
- every generated journal balances and uses the reviewed accounts/dimensions;
- entity quarantines are explicit, stable, explained, and do not leak partial
  lifecycle writes;
- failed-only retry touches only failed/crash-gap actions and their dependency
  descendants;
- an unchanged replay creates no loan, transaction, charge, paid-by row, or
  journal entry; and
- Mobile Collections links by deterministic transaction identity and never
  creates the repayment owned by the loans service.

## Useful reproduction commands

From `tools/arissto-sync`:

```bash
./arissto-sync preflight --target local
./arissto-sync inspect --block loans --target local
./arissto-sync inspect --block loans --target local --source-key 1254
./arissto-sync plan --block loans --target local --source-key 1254
./arissto-sync reconcile \
  --run e8bbff21f3bf42e2abdaf1496eb73c7b --target local
./arissto-sync status --block loans --target local
```

The persisted plan/run state is local and ignored at
`.arissto-sync/state.sqlite3`. It is diagnostic evidence, not a portable or
committed source of truth. Promote durable conclusions back into this document,
the loan contract, or the implementation sequence.

## Suggested new-thread prompt

```text
Work from tools/arissto-sync and read:
- migration-services/loans/loan-reconciliation.md
- migration-services/loans/contract.md
- migration-services/loans/implementation-sequence.md

Goal: close the P0 historical loan transaction-allocation gap using a bounded
local proof before broad portfolio work. Start with source loan 1254 and trace
movement 0000010987 through source components, Fineract charge/accrual state,
native transaction allocation, balances, paid-by records, and journals. Treat
Arissto as read-only. Do not modify or delete existing active loans, do not
weaken strict reconciliation, and do not run Mobile Collections apply. Propose
and implement the smallest migration-only source-exact allocation mechanism
that preserves Fineract domain/accounting invariants, add tests, run the bounded
canary, reconcile it exactly, and update the handoff document with evidence.
```
