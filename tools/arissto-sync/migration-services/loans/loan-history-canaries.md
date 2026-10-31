# Historical loan event canaries

Read-only baseline captured 2026-10-19/20 from the local `sandbox` tenant and
Arissto completed close `000000002208` (2026-10-17). The matching key is
`CRD_HISTORICO_DIARIO.ID_CREDITO` to `m_loan.external_id = ARISSTO:CRD:<id>`.
The source interpretation and edit-day closes are in
[the Arissto event inventory](../../../../../../credesal-db-space/docs/learnings/loan-historical-adjustment-events.md).
**Decision, 2026-10-22:** Arissto overdue/pending interest buckets are source
observations, not Fineract import targets or native-method acceptance gates.
Only a change in total interest or a proven GL effect calls for a financial
interest event. Interest adjustments must match the source accounting pattern;
the existing journal trace does not yet prove that pattern for the resets.
The sandbox had no native `m_loan_reschedule_request` or
`m_loan_repayment_schedule_history` rows for the schedule canaries, and none
of the five loans had a native interest waiver. Existing loan transactions and
the current schedule had been imported; the historical revisions had not.

## Canary roles

| Source loan | Revision/event | Acceptance purpose |
| --- | --- | --- |
| `1597` | Revision `240`, 2026-10-15 | Ordered 18-row plan, no edit-day payment. Outstanding principal stays `764.59`; overdue principal falls `112.84 → 4.30`. Tests a dated plan-version transition that changes already-due installment dates. |
| `2355` | Revision `178`, 2026-08-29 | One revision and no payment. Outstanding principal stays `350.14`; overdue principal falls `71.15 → 18.44`. The new final due date moves backward and final interest is `-0.12`; this is an explicit exception test. |
| `2254` | Revisions `184` and `196` within nine total | Remaining-principal plan rebase after `371.38` paid, then `84.15` total-interest reduction. Tests payment baseline and waiver/accounting separately. |
| `2331` | Revision `230`, 2026-10-12 | `32.79` total-interest reduction with a `1.42` overdue residual. Tests a balance-reducing interest event and its GL effect. |
| `2558` | Revision `238`, 2026-10-15 | `72.45` overdue-interest relief while total interest stays `82.79`. Source-only due-state change; the inspected edit-day GL has no separate posting. |

### Frozen schedule signatures for the first two event plans

Each SHA-256 below hashes compact UTF-8 JSON of ordered rows
`[installment_number, ISO_due_date, principal_2dp, interest_2dp]`. The archive
with the revision ID is the before-plan; the current `ID_CREDITO` rows are the
after-plan for these one-revision loans. These are source signatures, not
Fineract plan IDs and not authorization to apply.

| Loan / revision | Before: rows, principal, interest, hash | After: rows, principal, interest, hash |
| --- | --- | --- |
| `1597 / 240` | `18; 1180.00; 636.03; 5d8604e241602bbfd4e1f424fd08fb51af1912e5fc882a06e0db0eaa7096f615` | `18; 1180.00; 702.63; 83c702d745b81f0000144262edd184c5f018204008d3b34e473359b0df554067` |
| `2355 / 178` | `101; 362.00; 140.51; 47993b02b2ac375fdad4934f8c9b593de179c77d5cc8ae8c410ebf70dce8cf33` | `8; 362.00; 58.15; d8c1b0b8db1464ad6de1a50ce6a0a21d8b4a2deb5cad2866aab517d0cf29a3fc` |

## October 17 baseline

The Fineract due-principal column below projects its **current** schedule and
current paid allocations onto October 17. It is a diagnostic, not an as-of
historical Fineract reconstruction. Later target transactions on October 18/19
were interest-only for these loans, so their current principal outstanding is
still comparable to the source close. Fineract's scheduled interest outstanding
contains future contract interest and must not be compared directly with
Arissto's carried `SALDO_INTERES`.

| Loan | Principal outstanding: Arissto / Fineract | Due principal: Arissto / current Fineract schedule | Current installment row differences |
| --- | ---: | ---: | ---: |
| `1597` | `764.59 / 764.59` | `4.30 / 4.30` | `1 / 18`; first installment interest is `89.23 / 263.05` |
| `2355` | `339.27 / 339.27` | `136.94 / 123.30` | `8 / 8` |
| `2254` | `1228.62 / 1228.62` | `132.20 / 0.00` | `200 / 200` |
| `2331` | `471.04 / 471.04` | `471.04 / 471.04` | `2` differences including one extra native schedule period |
| `2558` | `1511.00 / 1511.00` | `29.38 / 29.38` | `0 / 250` |

## Gates before an event writer can apply

1. Freeze each source event ID, effective date, recorded timestamp, old/new
   plan hashes, paid-principal baseline, and adjacent completed closes in an
   immutable loan-scoped plan. A revision with unchanged financial plan rows
   is not a schedule write.
2. Prove a native Fineract transition on a disposable proof loan, including
   already-due installments, existing repayments, schedule history, and
   transaction reprocessing. The existing current-schedule import does not
   provide this dated event. A source-exact command must reject an
   unrepresentable plan atomically.
3. For `2254` and `2331`, compare a proposed native interest waiver's amount,
   date, remaining interest, and journal entries with Arissto before importing
   it. For `2558`, require no financial adjustment unless a separate
   total-interest or GL effect is proven.
4. Reconcile principal outstanding, due principal, total carried interest,
   plan version, transaction identities, and GL effects at
   each completed close after an event, then at the October 17 final close.
   Retain overdue interest only as source classification evidence, not parity.
   Any mismatch remains explicit; no synthetic repayment or balance bridge is
   allowed to force parity.

## Fast isolated mechanism proof

Use the existing scoped loan planner with a unique `--proof-namespace`; it
imports only the requested loan and its required refinance predecessors, not
the complete workflow. For `1597`, the dependency closure is `489 → 747 →
1597` (three loans); for `2355`, it is five loans. The target must be local
`sandbox`. The source-through date supplied to the loan plan must match the
tenant's active accounting boundary (`Fineract starts = Arissto through + 1
day`). Check `GET accountingcutoff` before planning; a mismatched date is
rejected by Fineract after partial loan creation. The October 19 sandbox has
an active October 20 boundary. An October 17 completed source close can still
serve as an intermediate balance control for that proof.

The new `loan-event-canary` command freezes the archived before schedule and
current after schedule into a SHA-256 addressed plan. It verifies source and
target fingerprints, event timestamp, both source schedule hashes, current
native schedule hash, transaction count, proof-loan ID, and namespace before
calling native `sourceExactResyncSchedule`. It only supports `1597/240` and
`2355/178` and only namespaced local proof loans. Stage the archived plan,
then separately plan and apply the after revision:

```bash
./arissto-sync plan --block loans --target local --source-key 1597 \
  --proof-namespace hist-1597-oct17 --source-through-date 2026-10-19
./arissto-sync apply --plan LOAN_PLAN_ID --target local
./arissto-sync reconcile --run LOAN_RUN_ID --target local
./arissto-sync loan-event-canary plan --target local --source-key 1597 \
  --revision-id 240 --proof-namespace hist-1597-oct17 \
  --phase before --source-through-date 2026-10-19
./arissto-sync loan-event-canary apply --target local --plan BEFORE_PLAN_ID
./arissto-sync loan-event-canary plan --target local --source-key 1597 \
  --revision-id 240 --proof-namespace hist-1597-oct17 \
  --phase after --source-through-date 2026-10-19
./arissto-sync loan-event-canary apply --target local --plan AFTER_PLAN_ID
```

This is a **schedule mechanism proof**: the native command replaces the
current plan and reprocesses transactions, but does not yet create a dated
Fineract reschedule history entry or import a waiver. It must not be presented
as completed historical event migration. `2355` is expected to fail before
posting because its eighth new installment has a backward date and negative
interest. Waiver and due-only canaries remain read-only until their native
accounting and as-of balance behavior are proved.

The first controlled `1597` proof chain (local namespace
`hist-1597-oct17`) completed after correcting the CLI to use the active
accounting boundary and allowing namespaced proof IDs through the native term
portfolio account and refinance quote checks. Retry run
`a81ddf7b4d7848728cf1048c0e584a67` reconciled all three loans with no
blocking mismatches. It still reported accepted native interest and total
balance variances for `1597`; those are not source parity. The subsequent
archived-plan application was rejected atomically: its June 5, 2027 maturity
differs from the proof loan's selected June 20, 2027 term portfolio account
maturity. A reviewed accounting reclassification and dated schedule-history
mechanism are required before this event can be imported. The canary planner
now detects this selected-account conflict before writing. The `2355` plan
is rejected from source rows before creating its five-loan dependency chain.
The isolated `1597` proof loan still has zero native reschedule-request and
repayment-schedule-history rows after the rejected transition.

The nonposting `prove-loan-schedule` calculator runs after a guarded local
server restart. For `1597`, its generated schedule has 36 principal/interest
installment mismatches even though due dates and total principal match, so
exact source installments are required for this test.

## Interest waiver trial: 2331

The scoped loan plan in namespace `hist-2331-oct12` imported only 2331 and
its seven refinance predecessors. Local run `cb5227cb660f42d0854c87ec52d18f52`
reconciled all eight loans with no blocking mismatch. The isolated target loan
is 2689. Its principal outstanding is $471.04, equal to the October 17 source
close; native scheduled interest outstanding is $116.94 and is not a direct
measure of Arissto's carried interest.

Source revision 230 and audit 6396407 occurred on October 12. Adjacent
completed closes show carried interest $34.21 → $1.42, a $32.79 reduction,
while overdue interest changed $30.93 → $1.42. Paid principal and interest
were unchanged across those closes. The October 17 source close has carried
and overdue interest at zero after a later repayment.

`loan-interest-canary` freezes this source event, the adjacent and final
closes, target loan identity, transaction IDs, balances, target fingerprint,
and accounting dates in a SHA-256 plan. It targets only a namespaced local
`sandbox` proof loan and submits Fineract's native `waiveinterest` transaction
with the source date and exact $32.79 amount. Reconciliation reads the waiver,
loan balance changes, and linked GL rows. It does not use a complete sync.

```bash
./arissto-sync loan-interest-canary plan --target local \
  --proof-namespace hist-2331-oct12 --source-through-date 2026-10-19
./arissto-sync loan-interest-canary apply --target local --plan PLAN_ID
./arissto-sync loan-interest-canary reconcile --target local --plan PLAN_ID
```

The first `waiveinterest` attempt was rejected atomically by the active
accounting cutoff: a native transaction dated October 12 precedes **Fineract
starts October 20**. The proof loan remained at 80 transactions, zero waiver,
and zero linked native journal rows. For local canary testing, the policy now
allows native pre-cutoff posting only when the tenant identifier is `sandbox`;
other tenants retain the rejection. The sandbox exception is temporary while
the clean-sync contract is established.

After the local server restart, plan
`c95dacfd75c1f7f3507ab17cb7071b589cbfc34d658d12e782ed8391778914c9`
created native waiver transaction `81442` for $32.79 on October 12. A repeat
apply recovered the same transaction. Native interest outstanding and overdue
both fell $116.94 → $84.15; waived interest became $32.79, and principal
remained $471.04. The **total-interest event delta matches** Arissto's $32.79
reduction. The **overdue delta does not**: Arissto fell $30.93 → $1.42, or
$29.51. This difference is not an import gate. The current Fineract scheduled-interest total is not directly
comparable to Arissto's carried-interest balance, which was zero at the later
October 17 close. Full as-of and final balance parity remain unproved.

Fineract produced two October 12 GL lines for the waiver: **credit** $32.79
to `1141039901` (interest receivable) and **debit** $32.79 to `73` (credit-loss
expense). The subsequent [read-only accrual and accounting trace](../../../../../../credesal-db-space/docs/learnings/loan-interest-accrual-accounting.md)
found normal provision entries on the edit day, with event-day receivable
credits fully explained by source loan-movement subledger lines. Loan `2331`
had no movement on that close. Its ordinary provision journal was created
hours after the balance edit; cumulative loan provision increased $3.28
despite the $32.79 reduction in carried interest. No separate $32.79 receivable-credit or
credit-loss-expense posting appeared in the inspected journal pattern. Thus
the native waiver is proven as a balance mechanism, while its isolated
sandbox GL posting differs from the inspected source edit-day entries. That
trial used a temporary exception to the historical accounting cutoff; it is
not a valid loan-state handoff comparison. Keep canonical and production
mapping gated on transaction replay, due-principal and accrued-interest parity
at cutover, and correct future accrual after COB. Historical GL ownership is
the accounting service's separate invariant.

For the next loan-state canary, use **Arissto through October 19** and
**Fineract starts October 20**. Stage `2331` with the October 12 waiver as a
historical operational event under the authenticated migration context; the
ordinary waiver endpoint is not sufficient because its handler does not enter
that context. At the October 19 close, compare unpaid due principal and
carried interest from `CRD_HISTORICO_DIARIO` with the native installment
outstanding amounts and Fineract's due plus not-yet-due accrued-interest
projection. Run Fineract COB for October 20 and later dates for which Arissto
has completed closes; compare normal-interest accrual, due principal, and
mora generation after each close. Preserve the exact historical waiver and
repayment order through replay. Arissto overdue-interest buckets are not an
acceptance gate. The isolated sandbox trial did not run this handoff flow.

## Interest-event mechanism decision after audit-sequence review

The same `FECHA_ULTIMO_PAGOINT` edit is not one business operation. The
[source audit sequence](../../../../../../credesal-db-space/docs/learnings/loan-historical-adjustment-events.md#a-date-edit-can-express-different-operator-intentions)
separates at least two branches, with source movement and completed-close
checks required before either can be imported:

| Observed branch | Source effect | Closest Fineract mechanism | Import decision |
| --- | --- | --- | --- |
| Balance-reducing recalculation (`2254`, `2331`; 16/17 comparable future-date edits) | Carried interest falls without payment; overdue interest may fall by a different amount. Financial plan rows stay the same. | Native `waiveinterest` can reduce the total by the exact amount, as the 2331 proof showed. | Candidate pending historical replay, cutover accrued-interest, and subsequent COB proof. The accounting service owns historical GL independently. Overdue-interest parity is irrelevant. |
| Pending-interest due relief (`2558`, revision `238`) | `SALDO_INTERES_PENDIENTE` $0 → $82.79, overdue $72.45 → $0, total $82.79 unchanged, no payment, financial plan unchanged. | No native due-state method is needed under the revised migration scope. | No interest write: the inspected edit-day GL has ordinary provision and movement-backed collection entries, with no separate due-only posting. Do not turn the $72.45 overdue delta into a waiver or repayment. |
| Ordered plan revision (`1597`) | Due dates and installment amounts change. | Source-exact schedule transition can represent the row changes on an isolated proof loan. | Continue schedule-specific canary; preserve before/after versions and transaction replay. |

The `2558` sequence is especially important: revisions `235` and `236` on
October 14 made and undid a balance-reducing edit, then revision `238` on
October 15 selected pending-interest treatment. Classify the *final audited
sequence*, not just the date field or net daily delta. Other pending-interest
edits on October 15 were revisions `237`/loan `2556`, `242`/`2573`, and
`244`/`2588`; payments or accruals make their close deltas less clean.

No further Fineract due-state proof is needed for `2558/238`. Its inspected
edit-day accounting has no separate GL effect, so this is a no-write source
event under the current contract. Do not use the overdue-interest transition
as a target balance acceptance value.

### Isolated 2558 baseline and read-only event classifier

The scoped plan `4a5f408c7434433ab55b7a95e197c92b` used **Arissto through
October 19 / Fineract starts October 20**, selected source loan `2558` plus
six required refinance predecessors, and imported them into namespace
`hist-2558-due`. Run `87f8532a1f5f4251ad6bbab9efaa2b95` reconciled all
seven loans with no block-level mismatch. The resulting proof loan is Fineract
`2696`; no interest waiver was posted.

At the latest source close `000000002210`, Arissto shows principal outstanding
`1501.00`, due principal `25.48`, carried interest `77.79`, and overdue
interest `0.00`. The proof loan shows principal outstanding `1501.00`,
principal overdue `22.42`, scheduled interest outstanding `1595.38`, and
interest overdue `252.42`. Fineract's scheduled interest outstanding includes
future contract interest and is not the same measure as Arissto carried
interest. The overdue-interest gap is expected under the revised migration
scope and is not an acceptance failure; the current summary also cannot
isolate a date-exact event effect.
The proof remains untouched after its initial import.

`loan-interest-event-inspect` now reads a single source revision without
selecting or changing any Fineract target. It returns the ordered nearby audit
edits, adjacent closes, same-close movement IDs, before/after financial-plan
hashes, and a conservative family. It **never** marks a target write allowed.
Use it to select the next proof event:

```bash
./arissto-sync loan-interest-event-inspect --source-key 2558 --revision-id 238
```

The source-backed checks classified `2254/196` and `2331/230` as
`interest_balance_recalculation`, `2558/238` as
`pending_interest_due_relief`, and `2558/235`, `2558/236`, `2556/237`,
`2573/242`, and `2588/244` as `mixed_or_unresolved`. Same-close payment,
changed plan, or an inconsistent combination of total and overdue balances
forces review. This classification is discovery only; the historical event
writer must still pass the native effect and GL gates above.

### Native Fineract methods checked for 2558

The local Fineract implementation derives `summary.interestOverdue` from
unpaid interest on repayment installments whose due date precedes the
business date (`LoanArrearsAgingServiceImpl.calculateArrearsForLoan`). It does
not derive this amount from `graceOnArrearsAgeing` or a separate pending-interest
balance. This explains why changing an arrears-ageing grace value alone cannot
recreate Arissto's zero overdue interest on 2558.

| Method | Code behavior | Fit for the 2558 due-only event |
| --- | --- | --- |
| Reschedule request with `graceOnInterest` | Adds a `GRACE_ON_INTEREST` term variation and regenerates future repayment installments; preview uses `rescheduleNextInstallments`. | Best *standard* candidate for a real contractual deferral, but it changes the native schedule. Arissto's before/after 2558 financial-plan signature is identical, so it fails exact plan parity unless a later source version establishes a contractual schedule change. |
| Re-age, including payable/full-interest handling | Creates a `REAGE` transaction and can regenerate the schedule. Its validator requires a **progressive** schedule with the **advanced payment allocation** strategy. | Unavailable on proof loan `2696`, which has a cumulative schedule and `credesal-accrued-interest-first-strategy`. Its read-only preview has the same eligibility gate. |
| Re-amortize | Creates a `REAMORTIZE` transaction and redistributes schedule amounts. It has the same progressive/advanced-only eligibility gate. | Unavailable on the 2558 proof loan and would change installment allocation. |
| `interestPaymentWaiver` | The assembler creates a repayment-type financial transaction; the advanced processor handles it as repayment. | Cannot move due interest to pending while keeping the amount owed unchanged. |
| `waiveinterest` | Trial on 2331 reduced interest outstanding and overdue together and posted receivable/expense GL. | Financial forgiveness, not the 2558 operation. |

The 2558 proof loan reports `loanScheduleType=CUMULATIVE` and
`transactionProcessingStrategyCode=credesal-accrued-interest-first-strategy`.
The strongest remaining native experiment is a **reschedule preview** on a
future, truly plan-changing deferral canary. Applying it to 2558 would erase
the source's unchanged plan evidence. The earlier due-state-extension proposal
is superseded by the 2026-10-22 migration decision above.

### Interest-grace reschedule preview on 1597 (2026-10-20)

The isolated `hist-1597-oct17` proof loan `2681` was still active with its
current 18-installment plan and no existing reschedule request. Source revision
`240` is a genuine plan change, although it also rewrites installments already
due on its October 15 effective day. The proof loan still could not stage its
archived before-plan because the earlier maturity conflicts with its selected
term portfolio account. The native preview therefore tests the **shape** of
one interest-grace variation on the current proof loan; it is not a replay of
revision `240`.

A sandbox-only `LoanRescheduleReason` value
`ARISSTO_CANARY_INTEREST_GRACE_1597` (code-value ID `921`) enabled a pending
request with `rescheduleFromDate=2026-10-20`, `graceOnInterest=1`, and no
approval. `GET /rescheduleloans/2?command=previewLoanReschedule` returned:

| Installment | Current native principal / interest | Preview principal / interest | Arissto current-plan principal / interest |
| --- | ---: | ---: | ---: |
| October 20, 2026 | `63.45 / 37.49` | `62.92 / 0.00` | `63.45 / 37.49` |
| November 20, 2026 | `65.43 / 35.51` | `64.87 / 73.03` | `65.43 / 35.51` |

The preview kept 18 repayment installments and total principal `1180.00`,
but changed 11 schedule periods counting the initial zero period. It moved
interest to the next installment, altered principal allocations, and
recalculated the earlier January 20 interest from the imported `263.05` to
`89.23` (the source's value). Baseline native scheduled interest summed to
`876.45`; preview interest summed to `703.70`, versus `702.63` in Arissto's
current plan. Only 9 of 18 repayment installments in the preview matched the
Arissto current plan. The preview's earlier-period recalculation means an
approval could affect past schedule evidence even when the requested grace
starts in October; that must be checked on any accepted native reschedule.

Request `2` was rejected after preview. Its stored reason is correctly code
value `921`, and read-back confirmed the proof loan's schedule and transaction
IDs did not change. An initial request `1` was also previewed and rejected:
the code-value creation response's `resourceId` identified the **code** (`23`),
not the new value (`921`), and the request validator accepted that unrelated
value ID as a reason. Both requests remain rejected audit records in the
disposable sandbox; neither was approved and neither posted a transaction or
changed the loan schedule. A reusable canary must resolve the reason value by
reading back `codes/23/codevalues`, then check that its stored reason ID and
code name match before relying on its preview.

**Decision:** Interest grace is a valid native deferral mechanism to evaluate
when Arissto explicitly changes future interest installments. It is not a
source-exact implementation of `1597/240`, and it does not solve the unchanged
plan, due-only `2558/238` event. The next native reschedule candidate should
have future-only source plan changes and no selected-maturity account conflict;
the source scan identified revisions `2565/197` and `2586/206` as date-shift
candidates, pending movement and product checks.

### Date-shift canaries `2565/197` and `2586/206` (2026-10-20)

Read-only source chronology changed their classification. Both revisions were
recorded on the disbursement day, before the first scheduled installment. Each
archived-to-current plan changes **only due dates** by exactly one day:
`2565` has 45 daily installments and unchanged $300.00 principal / $49.62
interest; `2586` has 40 and unchanged $200.00 principal / $29.37 interest.
The completed origination-day closes already show the corrected next-payment
date and November 2 maturity. `2586` also has a September 23 repayment on the
archived first due date; that movement remains a separate event. The
[source note](../../../../../../credesal-db-space/docs/learnings/loan-historical-adjustment-events.md)
has the adjacent-close details.

Two dependency-closed **isolated local sandbox** plans used
`--source-through-date 2026-10-19` (Arissto through October 19; Fineract
starts October 20), with namespaces `hist-2565-r197` and `hist-2586-r206`.
Plan `29b1d6d31a0d4211b86c4bc2697f270c` imported one loan; its run
`3640bfc4e2c84654b759b3b537f0c06b` reconciled with no variances. Plan
`5d2b92c1a2434424ba244c6c9f64ac74` imported loan `2586` plus required
successor `2685`; run `b868cd987a194a47af76d71f0ad9bd1a` has **no
variance for `2586`**, but `2685` retains an interest-balance variance
($5.86 source / $5.38 target), a full-schedule total-outstanding variance
($291.13 / $341.97), and an accepted native-allocation cutover-total
variance ($291.13 / $288.79). The chain is therefore not fully reconciled.

The resulting proof loans `2697` and `2698` both have Fineract status
**Closed (obligations met)**, with every installment marked complete. A native
`adjustedDueDate` reschedule preview could not be submitted on either proof:
Fineract's `LoanRescheduleRequestDataValidatorImpl.validateForCreateAction`
requires an active loan and an installment whose obligation is not met. No
reschedule request was created or approved for these two loans. This result
supports importing their corrected **initial schedule**, with ordinary
repayments replayed separately; it does not prove a dated reschedule command.
The next mechanism test needs an active proof staged at the actual revision
point with its archived schedule and outstanding installments. It must also
handle the selected term portfolio account before changing maturity.

### Open-loan native date-shift canary `1869/109` (2026-10-20)

A read-only scan of the 131 revised loans at the completed October 19 Arissto
close found `1869` still open, with $1,804.43 outstanding principal. Its one
source revision has 28 future-dated archived installments and a mostly
one-day-forward monthly date change. The revision was recorded on the
disbursement day, so this is a **mechanism probe**, not an accepted historical
deferral replay. `1728` was excluded because it has five revisions and
nonmonotonic archived trailing due dates. The [source note](../../../../../../credesal-db-space/docs/learnings/loan-historical-adjustment-events.md)
records those observations.

Isolated local plan `175334252c2741a6a737a081ce2e6489` used namespace
`hist-1869-r109`, with Arissto through October 19 and Fineract starting
October 20. It imported loan `1869` and two required linked loans. Run
`d9cd6fbf3f814f8ba63dbba8daec63ba` reconciled principal for `1869`,
but its existing target interest balance is $101.66 versus Arissto $83.05,
and its fee balance is $15.34 versus Arissto $1.08. These baseline variances
must not be attributed to a reschedule.

Proof loan `2702` was active with unpaid installments. Native reschedule
request `3` (reason code value `922`) previewed `rescheduleFromDate` November
18, 2026 and `adjustedDueDate` November 19. The 28-installment preview
changed **24 periods**. Despite the requested later date, November 18 moved
to November 17 and subsequent monthly due dates also moved to the 17th.
November principal/interest changed from `$44.13 / $90.12` to
`$46.04 / $87.21`; earlier May and August interest was recalculated too.
Scheduled interest changed from `$1,782.13` to `$1,771.89`, whereas
Arissto's revised plan totals `$1,763.48`. Thus this native
`adjustedDueDate` preview does **not** reproduce the source's date or amount
pattern, even as a shape test. Do not approve it as an event-import mapping.

Request `3` was rejected. Read-back confirmed the 28 baseline periods and all
transaction IDs remained unchanged; no reschedule was approved. The native
mechanism remains unproven for source-exact one-day deferrals. A later-dated
source revision with an unambiguous before/after plan and a proof loan staged
before the event is still needed for historical parity testing.
