# Historical loan delinquency categories

The reviewed `Mora Estandar` range is A1 for **0–7 days**. Native Fineract
calculation assigns A1 to an open loan with zero days past due. This range
defines future calculated tags; it does not determine Arissto's stored
historical classifications.

For a historical import, map `CRD_HISTORICO_DIARIO.CLASIFICACION` directly to
the native delinquency range, independently of `DIAS_MORA`. An E row with zero
days must remain E. `arissto_sync.delinquency_history.compress_classifications`
provides the category-only, per-loan interval compression: `added_on_date` is
inclusive, `lifted_on_date` is exclusive, and missing daily observations leave
a gap. It rejects duplicate loan/date rows and unknown categories. The native
`m_loan_delinquency_tag_history` table stores a range ID and dates without a
days-past-due condition, so the target model can represent these exceptions.
Mifos displays the saved category and effective dates in the loan's
Delinquency Tags tab. It does not append the range's configured age threshold
to a historical tag, since an imported E can have zero source days past due.

The native tag-history importer scans all completed Arissto closes through
the selected inclusive source day and creates the compressed transitions. The
`carry-forward-rebuild` workflow now runs this service after the loans step
reconciles, using the workflow's frozen **Arissto through** date. It remains
available through its standalone CLI for a reviewed existing target:

```sh
./arissto-sync delinquency-history plan --target local --source-through-date 2026-10-07
./arissto-sync delinquency-history apply --target local --plan PLAN_ID
./arissto-sync delinquency-history reconcile --target local --run RUN_ID
```

**Arissto through** is the supplied date; **Fineract starts** on the next
calendar day. The selected date may be today; only completed closes observed
when the source is read contribute historical classifications. Planning is
read-only and returns an immutable source hash,
source-row count, transition count, mapped count, pending unmapped source loans,
reviewed quarantined loans excluded from native tags, and target create/unchanged
counts. The quarantine evidence is the latest reconciled loans run in the open
local target cycle (or the selected target's own state ledger when no cycle is
used); its run ID and decision hash are frozen in the plan. Planning fails if
there is no accepted loan run. Apply and reconcile recheck that evidence so a
later loan decision requires a new plan. Review that plan before apply. Apply requires
the versioned Fineract provenance migration `0391`, re-reads the source, and
rejects source drift, unknown classes, duplicate closes, missing range mappings,
unreviewed native tag overlaps, or conflicting provenance. An unsourced native
tag created on the final Arissto-owned day and still open or lifted exactly on
**Fineract starts** is frozen by ID, loan, and range in the plan and moved to
**Fineract starts** on apply. A boundary-lifted tag becomes an empty transition.
Empty same-day native
add/lift transitions carry no historical interval. Any other positive native
interval in Arissto-owned dates fails review. The same serializable transaction
then writes Arissto's closed historical intervals to
`m_loan_delinquency_tag_history` and a one-to-one source crosswalk. Apply and
reconcile verify the moved native tags and the imported source intervals. The accepted manifest freezes one source
timeline. Reapplying the same timeline is idempotent; a newly mapped loan can
be added with a fresh plan for that same source date. Advancing the source date
requires a clean target rebuild until an incremental extension contract has
been reviewed. Reviewed quarantines are excluded from the native tag expectation
and reported separately from pending unmapped loans; neither can be written to
native tag history because it requires a native loan ID. A quarantine with an
existing native loan mapping fails closed. Source observations remain in
read-only Arissto; excluded IDs are recorded in the import plan.

This is a controlled direct-SQL exception for historical native tags: the
normal Fineract `assigndelinquency` command recalculates from days past due and
uses the current business date. Historical reporting can read the native
intervals with `addedon_date <= as_of_date` and
`(liftedon_date IS NULL OR liftedon_date > as_of_date)`. The report reconstructs
balances and days past due from native loans, schedules, and transactions;
these values may differ from Arissto's original daily close facts. Liquibase
`0392` replaces the report SQL and drops the retired daily portfolio tables.

## Local unmapped-loan audit, 2026-10-08

Read-only comparison of delinquency plan `778add7f70574b6c87fa6f52a8f185ed`
(Arissto through 2026-10-07) with the preserved October 6 carry-forward loan
run `474eda2a2f774727829c367bacde01c2` explains its 27 unmapped loans:

| Cause | Loans | Source IDs | Next dependency |
|---|---:|---|---|
| Quarantined as reviewed voided refinance attempts | 9 | 420, 465, 500, 549, 1765, 1809, 1820, 2149, 2154 | Preserve the reviewed no-write policy unless loan migration policy changes |
| Quarantined as refinance chain after loan 1728's remaining-schedule signature mismatch | 4 | 1044, 1212, 1494, 1728 | Resolve and review the source-exact schedule mismatch and its chain |
| First eligible completed close was 2026-10-07, after the loan run's inclusive source-through date of 2026-10-06 | 14 | 2663–2676 | Migrate these native loans in a later reviewed loan sync |

The four loans in the 1728 chain had succeeded in the preceding October 5
full-sync cycle; the October 6 carry-forward cycle quarantined them under its
new frozen plan. Their older target IDs do not identify loans in the current
rebuilt sandbox.

The last loan run recorded 24 quarantines overall. Its other 11 quarantined
loans had only `ID_ESTADO_CARTERA` 2 or 3 in completed historical close rows
through October 7, so the native tag importer’s eligible-row filter
(`ID_ESTADO_CARTERA=1` and no embargo) did not select them. All 27 IDs above
were still absent from the local sandbox `m_loan` mapping on October 8. This
audit describes the inspected cycle and source date, not a standing quarantine
count for future cycles.
