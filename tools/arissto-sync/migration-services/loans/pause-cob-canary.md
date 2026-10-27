# Shared interest/mora pause: live COB canary — 2026-10-26

**Later normal-CLI acceptance:** [planning repairs and actual loan-sync/COB evidence](loan-flow-cob-acceptance.md) supersede the archived-lifecycle limitation. The dated evidence below is retained.

**Superseded diagnostic:** see the [passed repair and fresh recalculation-enabled proof](cob-continuation-repair.md). The dated failure below is retained as evidence.

**Outcome: failed acceptance.** Remaining frozen works in the tested loan;
resumption on the exact source date without catch-up is **not verified**.
A new full loan-sync replay was blocked before apply. Existing proof loans
allowed a narrower source-control → final metric baseline → native COB test,
which found a resumed-loan interest discontinuity and a subsequent mora failure.
Do not describe this as a passed end-to-end migration or certify the next-cycle
recalculation-enabled setup from these results.

## Target and boundaries

- Explicit target: local disposable `sandbox`, database `fineract_sandbox`,
  fingerprint `b9f6834b66790744`; existing ACTIVE accounting boundary unchanged.
- **Arissto through 2026-10-19; Fineract starts 2026-10-20**.
- Requested roots: source `1572` and `1826`. Native diagnostic proof loans:
  `2715` and `2716`, namespace `freeze-history-v3`.
- Both existing proof loans have **interest recalculation disabled** and
  periodic accrual accounting enabled. They are not fresh loans created under
  the new recalculation default. No canonical loan, production tenant, tenant
  reset, new cycle or composed workflow was used.

The source histories were read again: 1572 has three same-day transitions on
February 3 and resumes on **2026-04-22**; 1826 freezes on **2026-05-30** and has
no source resume through `S`. Source dated flags agree. No resume was invented
for 1826. The October COB test does not replay 1572's actual April resume date.

## Fresh sync attempt

The current immutable scoped loan plan was prepared under namespace
`pause-cob-oct26-a`, plan `c5d982e9e67c47a5bd35cf2ffdf1edb9`. It was not
applicable and was not applied:

- `product:00010:external_id_product_contract_differs`;
- source 1572: `source_events_after_fineract_accounting_boundary`.

These are current engine guards, not waived canary conditions. The diagnostic
below does not bypass that plan or establish that a full fresh replay succeeds.

## Diagnostic execution

Frozen local plans/results are in `.arissto-sync/pause-cob-proofs/`:

| Artifact | SHA-256 / purpose |
| --- | --- |
| `existing-proof-plan.json` | `6f2a9f98a73f788109d5eaf7569d9667843af4c3b3947299edd3ae3b9690c8d1`; exact proof IDs, source histories/targets and initial journal/transaction fingerprints. |
| `daily-cob-plan.json` | `ed40f3206c1aecbcb333c919a01584198118b326d2b199cad5a23849aa350949`; public date controls and scoped daily COB, replacing the unavailable test-only close-marker endpoint. |
| `daily-cob-result.json` | Opening native states and completed October 20/21 snapshots. The October 22 batch failed. |
| `frozen-recovery-plan.json` | `54fab378b261cbe4cd0bf020dc927e23cbced1cc918afcc85341a147056ccb6b`; source 1826 only for October 22–25. |
| `frozen-recovery-result.json` | Four additional frozen-day results. |
| `checks.json` | Sanitized aggregate outcome, original transaction comparison and restoration checks. |

The existing history importer/read-back and actual Python final-metric helper
ran on the two namespaced loans. Paid-insurance targets were corroborated using
the existing identified source allocations. Before COB, source control checks
and all eight target amounts matched; global journal and selected loan
transaction-row fingerprints were unchanged by these correction steps.

The first harness attempt requested the TEST-profile-only internal close-marker
API and received HTTP 404; that endpoint was not enabled and no close-marker
write occurred. The recovery plan used the normal public APIs instead:
`configurations/44`, `businessdate`, and `jobs/LOAN_COB/inline` with only the
explicit proof loan IDs. The actual `LOAN_CLOSE_OF_BUSINESS` step configuration
included periodic accrual, arrears aging, and delinquency/mora charge processing.
A successful HTTP response alone was not treated as proof: persisted close
markers and native monetary state were read after each day.

## Observed native results

| Source loan | Opening interest / mora | October 20 | October 21 | October 22–25 | Result |
| --- | --- | --- | --- | --- | --- |
| 1826, frozen | 54.04 / 0.34 | 54.04 / 0.34 | 54.04 / 0.34 | 54.04 / 0.34 every day; last close advances through October 25 | **Frozen behavior passed for six days.** No source resume exists in this window. |
| 1572, already resumed | 12.35 / 0.00 | 86.59 / 0.20 | 86.39 / 0.20 | October 22 COB fails | **Failed continued-operation acceptance.** Opening interest increases by 74.24 immediately; no claim of correct daily progression or no catch-up. |

The first interest increase is an observed discontinuity after final metric
alignment, not yet an attribution that exactly 74.24 represents paused days.
It requires investigation of the final baseline, accrual materialization and
normal COB calculation paths. Equal opening amounts alone did not prove that
continued operations would preserve the intended state.

The October 22 failure is concrete:

```text
LoanChargeAdjustmentException:
Transaction amount cannot be higher than the available charge amount for adjustment: 0.000000
LoanChargeWritePlatformServiceImpl.loanChargeAdjustmentEntranceValidation
LoanChargeWritePlatformServiceImpl.adjustmentForLoanCharge
LoanChargeWritePlatformServiceImpl.applyCredesalDailyMoraForLoan
ApplyDelinquencyRangeChargesBusinessStep.execute
```

The daily mora path requests a reduction via normal charge adjustment, whose
native availability validation rejects it. This is not evidence of a safe
resume. The failed resumed loan was not repeatedly retried; frozen-loan COB
continued separately under its recovery plan.

Original transaction IDs, dates, amounts, component portions and reversal
flags exposed by the API were compared before/after: **zero original
transactions changed** on either loan. COB can add its normal accrual/charge/GL
records; GL-free claims here concern the preceding migration corrections, not
normal Fineract-owned COB accounting.

## Cleanup and remaining acceptance work

The prior `enable-business-date=false` setting was restored and read back.
There were originally no saved business-date rows. Public date updates created
saved October 26/25 rows; these remain stored with the feature disabled and
are not asserted to be an exact restoration of the original empty date table.
No source database writes were made. The Gradle runtime is stopped after the
verification session.

Acceptance still needs:

1. A valid source-bounded, two-loan fresh sync plan with the current product
   prerequisites and **recalculation enabled**, without bypassing guards.
2. Diagnosis/repair of the post-baseline ordinary-interest discontinuity and
   the zero-available-amount mora adjustment failure during normal COB.
3. A chronological test crossing a verified freeze and resume boundary, including
   the actual first resumed day and following days. An ongoing freeze alone
   cannot prove resumption; 1572's October running state cannot prove April 22
   resumption or exclusion of all previously frozen days.

These are normal continuation and explicit pause/resume acceptance checks.
They do not reinstate a requirement for final metric corrections to survive
arbitrary later reversals or historical schedule replay.
