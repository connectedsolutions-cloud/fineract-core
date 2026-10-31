# Scoped loan component alignment canary

## Current handoff gate: active loan opening amounts

Acceptance is the final active-loan state after history replay and opening
adjustments. Compare **exactly** the source close on Arissto's final day `S`
with Fineract on its first day `T = S+1`: due principal, accrued interest, and
mora. One cent of difference fails. Later daily closes can diagnose a mismatch
but are not import acceptance criteria. Historical loan adjustments must not
create GL entries; the accounting service owns those journals. A fresh local
canary must prove exact balances and zero native GL. Earlier proof runs below
have not passed this revised gate.

### Fresh boundary-only proofs — 2026-10-24

All proofs used disposable local `sandbox`, Arissto through **2026-10-19**
and Fineract starts **2026-10-20**. Each successful active loan passed the
end-of-write exact due-principal, as-of accrued-interest, and mora check,
then block reconciliation. Its Fineract loan-linked journal query returned
zero rows. No composed sync or tenant reset ran.

| Active source loan | Proof plan / run | Handoff result |
| --- | --- | --- |
| 2684 | `efb0510eb7614ffeb88e51aefb495ea9` / `af429759fa8341b18b259b7b78b89cb6` | Exact match; migration-scoped interest waiver 3.54; zero linked GL entries. |
| 1572 | `3cf7aef32b1f4bad8966c7a440684ee2` / `ccca6501c55a47d49372fb8d62bda894` | Resumed freeze history; exact match; migration-scoped interest waiver 209.20; zero linked GL entries. |
| 2438 | `4d43ead6cab247daa23ea793dd411a10` / `065a51919a774166869969dcda2d81ed` | Five-loan refinance lineage; positive opening mora 3.83; exact match and zero linked GL entries. |
| 2612 | `f995285f6b3b4a7fbff97c2b8f8dfdd8` / `eb287a3d830640c3a511963a411b4b4d` | Six predecessors imported; active root failed `loan_cutover_interest_below_source`. A waiver cannot increase native interest to the source amount. |

These proofs establish the opening methods for those successful shapes,
including interest reduction and positive mora without native historical GL.
They do not establish a method when **source interest exceeds native interest**.
Keep canonical active loans quarantined until that gap and other active shapes
are handled. The failed 2612 proof remains partial sandbox state.

## Recalculation-on/off follow-up — 2026-10-26

The [paired recalculation canary](interest-recalculation-canary.md) tested five
source loans with insurance and accounting disabled. Its initial four on replay
rejections were repaired through an explicit provisional recalculation path;
all ten histories now complete with exact repayment components and principal.
Only one on proof has exact handoff interest, so the result does not approve
enabling recalculation or changing insurance for canonical imports.

## Earlier diagnosis: live-date comparison was wrong

The later multi-day check below supersedes the initial handoff acceptance
language in this note. The ten-loan run and its replay imported and matched
the balances exposed by Fineract on the day of testing, but that comparison
used Fineract's **current business date** against an earlier Arissto close.
Fineract's cumulative-loan summary projects current-period interest through
its business date. The resulting opening `waiveinterest` transactions removed
interest that belonged to post-handoff days. A read-only reconstruction of
Fineract's schedule projection at the actual boundary shows the proof loans
were short at handoff. Subsequent COB did not restore the missing interest.

The general loans planner now quarantines active canonical loans with
`cutover_exact_component_alignment_unproved`; old plans are invalidated.
The waiver path remains available only with an explicit local proof namespace
for diagnosis. **These canaries do not approve the opening-interest method for
normal sync.** The dated type-4 freeze identities and their final state were
imported successfully, but a resumed loan's future interest still needs
source-to-native daily validation.

## Cohort and boundary

Use the existing loans block with three exact source keys and a fresh local proof
namespace. Do not run a composed workflow or reset the tenant for this canary.
The sandbox's active accounting boundary fixes this trial at **Arissto through
2026-10-19** and **Fineract starts 2026-10-20**. The active boundary and a
completed October 19 loan snapshot for each selected root and every required
refinance predecessor were verified on 2026-10-24.
Arissto also has later closes; they are comparison evidence, not an excuse to
move the existing sandbox boundary. Recheck the source observation and boundary
before planning; a mismatch blocks the run.

| Source loan | Distinct evidence to exercise |
| --- | --- |
| 1572 | Two completed freeze episodes; open loan |
| 1826 | Ongoing freeze with no source resume; open loan |
| 2331 | Reviewed total-interest reduction/waiver candidate, schedule revisions and eight-loan refinance lineage |

`AFI_BLOQUEO_CUENTA` is the source freeze event feed. Completed source
intervals establish that ordinary-interest provision and mora stop together,
while existing debt remains collectible. For 1572, three ordered same-day
events net to a freeze, and a later unfreeze resumes provision. For 1826,
the open freeze leaves observed provision and mora flat. Preserve the raw
same-day event order and the open state. Earlier draft selections expanded to 35, 15 and 13 loans through
refinance links; they were retained only as unapplied diagnostic plans. The
selected three roots expand to exactly ten actual loans, including eight in
the 2331 lineage. None has a source movement or revision after October 19.
The planner now quarantines source movement/revision activity after the fixed
boundary and uses the completed close for monetary comparison fields. Plans
created before this dated-component guard are invalid for apply.

## Current native method and remaining boundary

The loans writer imports dated type-4 whole-loan freeze/unfreeze history with
source identities and preserves an ongoing freeze. After historical replay and
accrual catch-up, it aligns **active loans'** collectible interest to the last
completed source close using a dated, deterministic native `waiveinterest`
transaction only when Fineract's projection is higher. A lower Fineract amount
fails rather than being silently increased. Historical refinance predecessors
are excluded from this opening alignment because they close through successor
settlements. Due-principal and accrued-interest components, native freeze
history, and mora terms are reconciled at handoff. Arissto's overdue-interest
bucket is observation only.

This was a cutover **balance** trial. Its waiver amount can include effects of
different historical accrual bases; it is not automatically the amount or
identity of a particular Arissto waiver event. The independent interest-only
pause feed and historical importer, atomic combined interest/mora pause, and
dated schedule revision history remain separate work in [alignment.md](alignment.md).
Source-only `inspect` is not an alignment approval. Use the explicit scoped
plan, source-through date, fresh proof namespace, apply, and reconcile path
for further canaries. The separate bucket-only loan 2558 remains a later case.

## Earlier diagnostic runs — 2026-10-24

The frozen ten-loan plan `3c57a78c0f354329b625c8eb0dbf26cd` used local
`sandbox`, source-through October 19 and proof namespace `align-oct19-final`.
Its first run `50d7347ffc744bfa94621c460dd2f2e9` quarantined the two pause
loans and failed at the first writable loan because the registered mora terms
datatable lacked audit columns inserted by Fineract's datatable API. The
remaining lineage was dependency-blocked. Versioned migration `0433` added
those columns; Fineract applied it to the sandbox on restart.

Because the target schema changed, a new immutable plan
`50361fc722594eda876b002023b0ab1c` was created with the same namespace.
Run `e85585eac92149f2a050624c8b267db1` recovered the first proof loan,
created the other seven loans in the refinance lineage, and quarantined the two
pause loans. Reconciliation found one blocking carried-interest mismatch on
loan 2331 and no other blocking monetary component mismatch among the eight
imported loans. Total-outstanding variances on 2331 accompany that interest
difference. This is diagnostic progress, not handoff acceptance.

At this stage, the missing historical whole-loan freeze importer prevented 1572 and 1826 from being
imported with correct future interest/mora behavior. Loan 2331's source
reduction event is also absent from the general writer. The prior isolated
`waiveinterest` proof established the event's reduction amount, but a single
waiver does not account for this run's entire carried-interest mismatch; do
not apply a residual waiver merely to force parity. Investigate schedule basis,
interest allocation and dated event order before selecting the next native
method. No first-owned-day COB or unchanged replay has passed for this cohort.
The installed ordinary whole-loan command only creates a freeze and refuses
frozen or previously closed periods; it has no matching unfreeze command.
The installed interest-pause command rejects a start on or before business
date. Neither can reconstruct the completed and ongoing source freeze
histories during loan creation. A guarded historical whole-loan history
importer is the next native capability for these two canaries. An independent
interest-only agreement still needs its separate historical pause importer.

### Earlier interest mismatch diagnosis on 2331

The source schedule's original principal and interest match Fineract's
original installment amounts. After historical replay and accrual catch-up,
one native installment has additional `interestDue` and a matching enlarged
accrual transaction, although the imported payment allocations and the
source/target paid-interest counters agree. The source provision counter
continues rising after the audited balance edit and contractual maturity,
while its collectible interest balance stays flat and then reaches zero after
a later repayment. Provision and collectible interest are therefore distinct
source quantities. Trace why the native post-due accrual lands on that earlier
installment; then test the dated reduction and first Fineract-owned COB before
accepting this loan. Do not add a residual waiver solely to clear the mismatch.

A separate, guarded local sandbox trial applied a dated native `waiveinterest`
for the complete remaining collectible-interest difference at the source
handoff. It brought the eight imported loans' reconciliation to no monetary
or schedule mismatches and left due principal unchanged. This proves the
native balance mechanism can reach the handoff state. It does **not** prove
that the full amount is a source waiver event: the original historical edit
explains only part of it, and the enlarged native accrual still needs a cause.
The trial transaction is outside the immutable import plan, so an unchanged
replay or future COB result must not be treated as accepted event mapping.
The first loan-scoped inline COB failed because the new daily mora charge
type did not persist its due date, so the charge validator rejected it.
`LoanChargeService.create` now retains the due date for this type, with a
focused regression test. After rebuilding Fineract, the same proof loan's
inline COB completed: principal and collectible interest remained at their
aligned values, and native daily mora was charged. Its close marker advanced
to the current sandbox business date. Source closes after handoff show the
same qualitative pattern: principal and collectible interest stay flat while
mora rises. This is one successful post-handoff run, not a daily by-date
reconciliation or proof that the manual waiver is the right event mapping.

## Native ten-loan proof — 2026-10-24

The current proof used Arissto through **2026-10-19**, Fineract starts
**2026-10-20**, local `sandbox`, and roots 1572, 1826, and 2331. The third
root expands to eight refinance-linked loans. Plan
`bddc742688a7439096e9b23fed3d24c3` in namespace `alignment-v2` contained
ten `create-loan` actions, one unchanged product, and no quarantines. Run
`895ccadc162a4e0fb98c061e7e19ff85` imported all ten. Reconciliation
found no blocking mismatches in source status, outstanding or due principal,
collectible interest, mora, fee, schedule, or freeze history. The only reported
variances are the documented Fineract full-schedule total and allocation
total presentation for 1572. The later as-of-date check found that this
point-in-time comparison was insufficient for interest acceptance.

The writer's first unchanged replay exposed two recovery guards: a posted
opening-interest waiver prevents resetting a selected portfolio account, and
an ongoing frozen loan cannot run historical accrual catch-up again. Both
guards now verify the already-posted native state. Replay run
`f10e0817851d49f79d98dea99dbd11ad` recovered all ten loans and again
reconciled with no blocking mismatches. The proof did not create a replacement
sync cycle or reset the tenant.

A loan-scoped inline COB on only the three active proof loans (1572, 1826,
2331) completed after replay. Principal stayed stable. The ongoing freeze on
1826 kept collectible interest and mora unchanged; 1572 and 2331 received
native daily mora charges. This checks immediate post-handoff behavior, not a
full daily accrual comparison against later Arissto closes. The interest
alignment is an opening-state technique and does not yet attribute every
portion of the adjustment to an individual historical Arissto event.

## Additional daily-accrual controls — 2026-10-24

Read-only Arissto screening selected open, unfrozen, unrestructured roots
2695, 2684, and 2635: their principal and paid-interest counters were stable
while collectible interest rose across completed October 19–23 closes. The
three roots expanded to eight loans. Local proof plan
`686f6e0338924368b072dffbab38c1d8` in namespace `daily-accrual-v2`
imported all eight in run `4a18a322ea3047d8aada4a23232ecb4a`. The
existing reconciler reported no blocking mismatches, but a scoped COB on the
three active roots left collectible interest at its opening value while
Arissto's daily closes had increased it. The no-freeze control 2695 also had
an opening waiver, so this is not explained by freeze history alone.

The read-only as-of reconstruction found the concrete date error: Fineract's
summary uses its current business date, while the writer compared it with the
last Arissto-owned close. For the clean control, the projected interest before
the waiver follows the source's later daily growth when compared at matching
calendar boundaries; the waiver made that trajectory too low. The resumed
freeze loan additionally needs its post-freeze daily interest rate checked
against actual outstanding principal. Build an as-of-boundary projection and
prove subsequent daily accrual before enabling canonical loan alignment.

A catalog and close-history search found no independent interest-only pause
event feed yet. The rare type-2 loan restriction records are four same-day
toggles on one loan, and no active, unfrozen loan in the screened October
19–23 interval had both collectible interest and cumulative provision flat
with unchanged payments. Do not synthesize an interest-only pause from these
observations. The historical interest-only Fineract import path remains open.

### Date-matched follow-up

The read-only command below now pairs each completed Arissto close on `S`
with the cumulative Fineract schedule projection at business date `S+1`.
It accepts only proof loans in local `sandbox`, reads no customer identity,
and changes no loan state:

```bash
.venv/bin/python -m arissto_sync.loan_daily_interest_canary \
  --proof-namespace daily-accrual-v2 \
  --source-key 2695 --source-key 2684 --source-key 2635 \
  --from-date 2026-10-19 --through-date 2026-10-23
```

On disposable proof loans, the original opening waivers were reversed to
separate the native schedule trajectory from the cutover adjustment. The
clean no-freeze/no-due-principal control 2695 then matched all five source
closes exactly without an opening waiver. Loan 2684 had a largely constant
opening excess: a smaller as-of waiver matched the first close and left only
a few cents of drift over the next four closes. Loan 2635 started below the
source and fell farther behind each day, so a waiver cannot solve it.
The resumed-freeze loan 1572 also matched its opening close after a corrected
as-of waiver but drifted downward each following day. The ongoing freeze
1826 and the already-zero collectible-interest case 2331 remained flat and
matched all five closes. These are sandbox trial adjustments outside the
immutable import plan; rerunning that plan against the modified proof loans
is not an acceptance check.

This diagnostic established why the prior live-date waiver was wrong. The
current opening check computes interest **as of Fineract start `T`** from the
native schedule. A later source trajectory is useful when investigating a
specific loan, but the active-loan import gate is the exact three-component
handoff comparison stated above. Keep the canonical quarantine until a fresh
proof passes that gate and the adjustment commands are verified GL-free.
