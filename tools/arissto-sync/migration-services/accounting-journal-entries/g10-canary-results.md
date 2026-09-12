# G10 scoped canary results

## 2026-09-10 disposable-sandbox run

The sandbox tenant was restored from its zero-business-data baseline, upgraded
through the current Liquibase migrations, configured with offices `1` and `2`,
and bound to an active `2026-09-10` accounting cutoff. The scheduler was paused
for historical imports and restored after the run. Arissto remained read-only.

The isolated sync state is `.arissto-sync/g10-2026-09-10/state.sqlite3` and is
not release evidence by itself; the identifiers below make the run auditable
while the disposable tenant still exists.

## Passing source-backed canaries

| Case | Source key(s) | Result |
|---|---|---|
| Ordinary multi-line | `001:001:00028:0000000097` | Exact journal/line reconciliation |
| Both agency tags and destination branch different from header | `001:001:00052:0000005132` | Offices `1` and `2` preserved; exact dimension reconciliation |
| Bank/cash linked | `001:001:00028:0000000002` | Exact account and amount reconciliation |
| Opposite postings | `001:001:00032:0000000101`, `001:001:00032:0000000104` | Imported independently, with no reversal link |
| Annual liquidation | `001:001:00041:0000003078` | Type `003` and liquidation provenance preserved |

Plan `0757fae9fdd6480992beae6a88f1b49c` imported four and recognized two
previously imported journals as unchanged. Run
`4db1e6c264724019b344a6158ce424ea` reconciled all six journals with zero
journal, line, agency-bucket, consolidated-bucket, or cutoff-boundary findings.
Its selective scope intentionally did not satisfy the inception-to-period
`CNT_MAYOR` control; that control is a G8/full-period assertion, not evidence
that a scoped canary differs.

Replanning the same six journals produced plan
`501bc2d404144c568fa9ca7c3a23e3c6` with `UNCHANGED=6`. Run
`7c70cce9947249299d710805e0f435a3` applied no new journal and retained the same
direct-journal control hash
`ced9c8484f11ef6589a5202bb4ec719ac8d47404d30fa9eef5058e3588cb7c6f`.

The independent inception-period control was also rerun. Plan
`5abc612558254810be8e1e602b051adc` covered all three period-`00028` journals;
run `57ba36daff7a424dbbceabd4afec81d6` passed Gate 8 with zero findings and
matching expected/actual balance hash
`416419d02b60c8bdc20149efa9dfcf71b4dda94b5dc7218fd4565ef5ec68f18f`.

## Passing quarantine and recovery canaries

- `001:001:00071:0000013957` quarantined as
  `SOURCE_JOURNAL_EXCLUDED_FROM_LEDGER`.
- `001:001:00045:0000003217` quarantined as `SOURCE_JOURNAL_EMPTY`.
- `001:002:00058:0000007509` quarantined as `SOURCE_JOURNAL_BACK_PERIOD` and
  `SOURCE_JOURNAL_REFERENCE_DATE_MISMATCH`.
- With a temporary office-2 closure, `001:001:00053:0000005650` quarantined as
  `TARGET_OFFICE_CLOSURE_CONFLICT`. The closure was then deleted.
- A real post-commit response-loss injection for
  `001:001:00031:0000000001` produced retryable run
  `cae8d85af98849f4afe1df2a084c4e11`. Normal failed-only retry run
  `03c358e8419a4f90b61d793ae1c3629f` recovered the existing target transaction;
  a subsequent plan classified the source key as unchanged.
- A fresh replay of that imported source key with a deliberately changed
  source hash was rejected by the API as `source.key.conflict`.

The live source snapshot contains no unbalanced, unresolved-account, or
unmapped-agency journal. These reason paths are covered by deterministic
classification tests and must not be represented as live-source findings.

## Cutoff boundary

A native manual journal dated exactly `2026-09-10` was submitted twice with
the same idempotency key. Both requests returned transaction
`a2b7cc138d57`; the target contains one balanced two-line transaction. A fresh
accounting reconciliation after that post still reported zero native
non-manual pre-cutoff GL and zero imported on-or-after-cutoff GL.

Focused verification passed:

- 72 sync-engine accounting/orchestration tests;
- 9 accounting cutoff/origin tests;
- 5 source-exact loan migration-origin tests; and
- 6 journal producer, persistence, cashier, vault, client, investor, and
  provisioning cutoff tests.

## Repeatable acceptance harness

The local-only harness combines the live source-backed journals, deterministic
synthetic reasons that do not occur in the current source snapshot, target
provenance, cutoff boundaries, retry identity, an expected-rejection changed-
hash probe, and the contract-approved anomaly-preservation assertion:

```bash
ARISSTO_SYNC_STATE=.arissto-sync/g10-2026-09-10/state.sqlite3 \
  ./arissto-sync prove-accounting-g10 \
  --target local \
  --cutoff-date 2026-09-10
```

The 2026-09-10 run returned `accepted=true` with evidence SHA-256
`70d536246ea849d5b157d645ddc90cfbe80c73b9337f6d5fded87fe3dacf21a0`.
All seven imported/recovered journals had zero findings; all live and synthetic
quarantines passed; native pre-cutoff and imported post-cutoff counts were zero;
and the cutoff-date native journal existed once as two balanced lines.

The anomaly assertion is deliberately negative and contract-bound. Loan `838`
has no physical loan-to-exact-GL-line allocation, so all 109 selected provenance
lines must retain `knownTransferredLoanOfficeMismatch=false` and a null anomaly
code. An immutable accounting-approved exact-line manifest would require a new
contract version and new acceptance evidence.

Gate 10 ledger acceptance is complete under the explicit project assumption
that Loans Gate 5 and its operational migration lifecycle are accepted. The
fresh whole-tenant cross-service reproduction remains part of Gate 11 rather
than reopening the loan gate here.
