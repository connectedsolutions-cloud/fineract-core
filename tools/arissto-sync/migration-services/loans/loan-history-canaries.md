# Historical loan event canaries

Read-only baseline captured 2026-10-19/20 from the local `sandbox` tenant and
Arissto completed close `000000002208` (2026-10-17). The matching key is
`CRD_HISTORICO_DIARIO.ID_CREDITO` to `m_loan.external_id = ARISSTO:CRD:<id>`.
The source interpretation and edit-day closes are in
[the Arissto event inventory](../../../../../../credesal-db-space/docs/learnings/loan-historical-adjustment-events.md).
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
| `2558` | Revision `238`, 2026-10-15 | `72.45` overdue-interest relief while total interest stays `82.79`. Tests due-state change without a waiver. |

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
   it. For `2558`, require zero financial waiver and test the due-state result.
4. Reconcile principal outstanding, due principal, total carried interest,
   overdue interest, plan version, transaction identities, and GL effects at
   each completed close after an event, then at the October 17 final close.
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
$29.51. The current Fineract scheduled-interest total is not directly
comparable to Arissto's carried-interest balance, which was zero at the later
October 17 close. Full as-of and final balance parity remain unproved.

Fineract produced two October 12 GL lines for the waiver: **credit** $32.79
to `1141039901` (interest receivable) and **debit** $32.79 to `73` (credit-loss
expense). The Arissto interest-ledger trace in the `fineract-reports` project
found no separately identifiable $32.79 or $29.51 journal line or loan
reference around this event; source accounting is visible only as portfolio
batch provision entries. Therefore the native waiver is proven as a balance
mechanism, but its GL mapping and due-state effect are **not accepted** as the
historical import contract. Do not apply this waiver to canonical loans or
production from this proof.

## Interest-event mechanism decision after audit-sequence review

The same `FECHA_ULTIMO_PAGOINT` edit is not one business operation. The
[source audit sequence](../../../../../../credesal-db-space/docs/learnings/loan-historical-adjustment-events.md#a-date-edit-can-express-different-operator-intentions)
separates at least two branches, with source movement and completed-close
checks required before either can be imported:

| Observed branch | Source effect | Closest Fineract mechanism | Import decision |
| --- | --- | --- | --- |
| Balance-reducing recalculation (`2254`, `2331`; 16/17 comparable future-date edits) | Carried interest falls without payment; overdue interest may fall by a different amount. Financial plan rows stay the same. | Native `waiveinterest` can reduce the total by the exact amount, as the 2331 proof showed. | Hold. It also reduces native overdue interest by the waiver amount and posts interest receivable against credit-loss expense. Neither due effect nor source GL is matched. An `interestPaymentWaiver` is also a financial loan transaction, not an overdue-only transfer. |
| Pending-interest due relief (`2558`, revision `238`) | `SALDO_INTERES_PENDIENTE` $0 → $82.79, overdue $72.45 → $0, total $82.79 unchanged, no payment, financial plan unchanged. | Interest grace or reschedule can change contractual due dates, but Fineract regenerates the schedule; a waiver reduces the financial balance. | Hold for a source-exact due-state mechanism or a proven native projection with identical financial plan, no GL, unchanged total and principal, and an event-day overdue drop. Do not turn the $72.45 overdue delta into a waiver or repayment. |
| Ordered plan revision (`1597`) | Due dates and installment amounts change. | Source-exact schedule transition can represent the row changes on an isolated proof loan. | Continue schedule-specific canary; preserve before/after versions and transaction replay. |

The `2558` sequence is especially important: revisions `235` and `236` on
October 14 made and undid a balance-reducing edit, then revision `238` on
October 15 selected pending-interest treatment. Classify the *final audited
sequence*, not just the date field or net daily delta. Other pending-interest
edits on October 15 were revisions `237`/loan `2556`, `242`/`2573`, and
`244`/`2588`; payments or accruals make their close deltas less clean.

The next isolated proof should stage loan `2558` under a fresh namespace and
measure Fineract's schedule-derived interest due before and after any proposed
native command. Acceptance requires zero interest waiver, zero synthetic
repayment, unchanged financial installment signature, unchanged total interest
and principal, no new journal, and the source overdue-interest transition.
If no native command meets all conditions, the migration needs an explicit
loan due-state event/projection in Fineract rather than a forced reschedule.

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
interest. The overdue-interest gap is real in the target's current state, but
a date-exact event effect cannot be isolated from this current summary alone.
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
the source's unchanged plan evidence. For 2558, an exact event needs a
reviewed extension to interest-due state or its projection, with source event
identity, effective date, unchanged receivable/GL, and arrears recomputation
that remains stable after later repayments and COB.
