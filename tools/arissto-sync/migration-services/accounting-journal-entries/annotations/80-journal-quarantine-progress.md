# Journal quarantine follow-up

Last updated: 2026-09-17

This note tracks the reviewed follow-up for the journal-integrity findings from
sandbox workflow run `49f3500aa8bf42d9973caf131d4c2645`. The counts below are
that run's baseline, not permanent source totals. Arissto remains read-only.

| Finding | Baseline | Current position | Next evidence needed |
|---|---:|---|---|
| `SOURCE_JOURNAL_EMPTY` | 30 | Correctly quarantined; item review pending | Confirm each distinct header has no monetary detail and classify why it exists. |
| `SOURCE_JOURNAL_EXCLUDED_FROM_LEDGER` | 15 | Correctly quarantined; item review pending | Confirm distinct status-2 keys and their absence from every affected `CNT_MAYOR_DIARIO` group. |
| `SOURCE_JOURNAL_NOT_MAYORIZED` | 4 | Source condition cleared after the frozen plan; ready for reviewed re-planning | Confirm the daily-close transition with accounting, then import the four now-eligible keys through a new immutable plan. |

## Progress checklist

- [x] Stable quarantine reasons are documented in the service contract.
- [x] Current executable tests preserve the fail-closed behavior.
- [x] Export and deduplicate the exact source keys from the recorded run.
- [ ] Record the accounting explanation and intended disposition for every key.
- [ ] Decide whether each category remains quarantined, becomes an explicit
      non-error exclusion, or requires a reviewed contract change.
- [ ] If the contract changes, update implementation, tests, and reconciliation
      expectations together.
- [ ] Re-run the accounting service from a guarded fresh/clean sandbox and
      record the new counts and evidence in this note.

## Non-mayorized investigation — 2026-09-17

The four distinct keys were:

- `001:001:00074:0000014174`
- `001:001:00074:0000014175`
- `001:001:00074:0000014176`
- `001:001:00074:0000014177`

The frozen sandbox plan classified all four as status `1` and created no target
transaction or durable mapping. A later read-only source inspection found that
all four had advanced to status `3`. They are generated, balanced journals dated
2026-09-16, with 11, 16, 2, and 8 detail lines respectively. Each now carries
daily-close, registration-close, and mayorization-close ID `000000002177`; that
close has operation date 2026-09-16 and state `1`.

Period `00074` remains open (`CERRADO='0'`). Therefore the earlier status was
not waiting for the monthly accounting period to close. Arissto's SQL Server
clock is UTC, and the exact timeline was:

| Event | UTC | America/El_Salvador |
|---|---|---|
| Journal `14174` inserted | 2026-09-16 23:14:51.987 | 2026-09-16 17:14:51.987 |
| Journal `14175` inserted | 2026-09-16 23:14:58.790 | 2026-09-16 17:14:58.790 |
| Journal `14176` inserted | 2026-09-16 23:15:03.763 | 2026-09-16 17:15:03.763 |
| Journal `14177` inserted | 2026-09-16 23:17:54.130 | 2026-09-16 17:17:54.130 |
| Accounting child plan frozen | 2026-09-17 13:50:28.574 | 2026-09-17 07:50:28.574 |
| Accounting apply started | 2026-09-17 13:50:59.030 | 2026-09-17 07:50:59.030 |
| Daily close `2177` mayorized them | 2026-09-17 13:55:24.303 | 2026-09-17 07:55:24.303 |
| Accounting apply finished | 2026-09-17 13:56:28.093 | 2026-09-17 07:56:28.093 |
| Four quarantine events recorded | 2026-09-17 13:56:28.712 | 2026-09-17 07:56:28.712 |

The journals were still status `1` when the immutable child plan was created
and when accounting apply began. They became status `3` while the apply was
processing the larger accounting plan: 4 minutes 55.729 seconds after the plan
snapshot was taken, 4 minutes 25.273 seconds after apply started, and 64.409
seconds before the stale quarantine events were recorded.
Current inspection reports each key as populated, balanced, source-only, and
free of classification or target-readiness findings.

This is a plan/apply race, not a monthly-close dependency. The writer correctly
did not silently expand an immutable plan, but the workflow should detect that a
transient status-1 quarantine changed before it records the final result and
surface a stale-plan/re-plan outcome. Whole-day runs should also freeze their
source snapshot only after the Arissto daily close or an approved source
watermark.

Recommended disposition: import all four through a newly reviewed immutable
plan. Do not replay the old plan because it correctly preserves the earlier
status-1 snapshot. Preserve the target's already-active accounting cutoff when
planning against the current sandbox lifetime, then reconcile all four target
transactions and their detail lines.

A replacement explicit-key plan was created for review in the same sandbox
cycle state:

- Plan ID: `826d7ed1cd914f6c8b793952ba3baa79`
- Plan hash: `24d95abb1a5ae8acfd6ccb166ac1fb34ee692a71d97b1ea198d8b29356014c17`
- Target fingerprint: `b9f6834b66790744`
- Frozen Fineract cutoff: 2026-09-17 (the existing active boundary)
- Counts: four `APPLICABLE`, zero quarantined or unchanged

The plan has not been applied.

## Completion criteria

This follow-up is complete when every distinct key has an accounting-approved
disposition, no journal is posted without ledger evidence, and a fresh/clean
sandbox run reproduces the approved result with reconciliation passing.
