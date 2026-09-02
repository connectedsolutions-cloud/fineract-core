# Midnight savings drift investigation

## Finding

Fineract job `6`, **Post Interest For Savings**, caused both observed drift
families during its successful local run on 2026-08-30 from `00:00:00.005` to
`00:00:02.857`.

At `00:00:02` the original job:

- reversed 279 mapped VISTA transactions across 35 accounts: 239 referenced
  manual interest postings and 40 associated withholding-tax postings; and
- created 124 non-manual, unmapped DPF interest postings across 27 accounts,
  totaling 13,871.21.

Aggregate checks found no replacement transaction for any of the 279 reversed
mapped VISTA events. No PII or account identifiers were retained in this note.

## Code path

The scheduled path is:

```text
PostInterestForSavingTasklet
  -> SavingsSchedularInterestPoster.postInterest
  -> SavingsAccountWritePlatformServiceJpaRepositoryImpl.postInterest
  -> SavingsAccountInterestPostingServiceImpl
```

`SavingAccountMapperForInterestPosting` selected `tr.is_manual` but discarded
it when constructing `SavingsAccountTransactionData`, and did not select
`tr.ref_no`. Consequently the scheduler could not recognize imported explicit
interest postings as referenced manual history. It recalculated those dates,
reversed VISTA postings whose source-authoritative amounts differed from the
current calculator, reversed their associated tax, and generated DPF catch-up
postings for history it did not recognize as manual.

## Implemented guard

The interest-posting query now preserves both `is_manual` and `ref_no` in the
transaction data. Scheduled correction treats a non-reversed manual interest
posting with a reference as authoritative and does not replace it when the
current calculator derives a different historical amount.

Two controlled reruns exposed and fixed adjacent boundary defects:

- explicit user/manual posting boundaries now use the source posting date
  (`period end + 1`) even when the product normally posts at the current period
  end, preventing one-day-early duplicate interest; and
- withholding correction candidates exclude referenced imported tax rows, so
  date-only native matching cannot consume a different source event's tax.

The sync planner independently blocks:

- stored/current contract-hash differences;
- reversed mapped transactions;
- VISTA native-balance drift; and
- unmapped DPF interest.

Reconciliation reports source-hash and contract-hash differences separately,
continues native financial diagnostics, and returns aggregate diagnostic-family
counts even when detailed mismatches are truncated.

## Verification and remaining repair

- All 223 Python sync-engine tests pass.
- Focused Fineract core and provider regression tests pass, including exact
  manual-boundary dating, referenced-manual preservation, and referenced-tax
  candidate exclusion.
- Fineract core formatting passes. The provider-wide formatting task remains
  red because of pre-existing formatting violations in unrelated modified
  files; the changed savings files were not among the reported violations.
- Read-only local plan `b2b6f34ed8a74f95b1f077f8c6545fef` is
  non-applicable and reports 155 contract-hash blockers, 35 reversed-event
  blockers, 35 VISTA balance blockers, 27 unmapped-interest blockers, and the
  same two reviewed quarantines.

The final change is deployed locally. Controlled VISTA proof v13 remained at 25
transactions, zero reversals, and balance 972.70 after job runs 62 and 64.
Controlled DPF proof v3 retained four active interest postings totaling 808.00
and zero reversals after runs 63 and 64. Final run 64 succeeded and did not
increase either global drift counter.

The original damaged population still needs a narrowly reviewed local repair:
280 mapped events are reversed across 36 migrations and 124 active unmapped DPF
interest postings remain across 27 migrations. The 280th reversal was introduced
by the controlled pre-fix v12 run and exposed the referenced-tax defect now
covered by regression testing. No production or Arissto writes were performed.
