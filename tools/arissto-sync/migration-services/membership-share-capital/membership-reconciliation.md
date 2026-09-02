# Membership reconciliation control log

## Purpose

This document is the working control log for completing and re-accepting the
membership release chain:

```text
clients
  ├─ membership-share-capital
  └─ savings-deposits
       └─ native-share-capital
```

The requested filename is retained, but the scope intentionally includes
`savings-deposits` and `native-share-capital`. Membership preservation and
savings are independent after clients, while native shares cannot be accepted
unless both have reconciled. A defect in savings therefore blocks completion
of the membership/share-capital release even when the membership archive itself
is correct.

Use this file as the short source of truth for issue status, decisions, test
evidence, and handoff between agents. If it becomes long, keep the issue table
and current checkpoint here and move detailed investigations into linked files.

## Current release decision

**Local testing may continue, but the chain is not approved for production.**

- `membership-share-capital` is locally applied and reconciled.
- The prevention fix for new `savings-deposits` scheduler drift is locally
  proven, but the previously damaged 155-account population is not repaired.
- `native-share-capital` has been applied locally, but three accounts still
  require reconciliation/repair and twelve accounts are expected quarantines.
- Do not apply savings plan `f6c89d83039442b7ad36e0b439a6589c`.
- Do not use the current local result as production acceptance evidence.

No work tracked here authorizes writes to Arissto, deletion of existing
Fineract entities, production execution, or bypassing target selection and
fingerprint confirmation.

## Verified local baseline

| Service | Plan / run | Observed result | Current interpretation |
|---|---|---|---|
| Membership preservation | Plan `0701bf52a7c748d98d5d2e3f0354f31c`; run `0173303aedaf4af688c9da6edecce6f0` | 379 succeeded, 66,243 unchanged; 66,622 total records reconciled | Locally accepted; existing target entities were preserved |
| Savings and DPF | Plan `9506e450d7db45559f3e0e35409c7082`; run `5945601248a64b90a2c485b88fd3313a` | 155 unchanged and 2 reviewed quarantines at apply time | Initial acceptance is no longer sufficient because later native processing introduced drift |
| Native shares | Plan `7adc29d0fc734074b2ad9094c2352ded`; run `d4ca31cf17ca4b6bb54752cdc1ed3a0c` | 43 succeeded, 2 unchanged, 12 quarantined | Applied locally; subsequent plan has 42 unchanged, 3 resume, and 12 quarantine |

The two savings quarantines are reviewed `SUBMITTED_UNFUNDED` DPF placeholders
with zero principal. The twelve native-share quarantines represent shareholders
without a legitimate eligible VISTA prerequisite; the share service must not
manufacture dummy savings accounts for them.

## Issue register

| ID | Status | Severity | Issue | Evidence / impact | Required outcome |
|---|---|---:|---|---|---|
| MR-001 | Ready for retest | High | Savings contract drift is not handled by planning | Applied rows store contract hash `b7742d0a123a690bd6cec6389aff9d7e8ec3b78ef54ec6488e7fac754f543e30`; the current contract hash is `1f7bc69c9b1af45699c8e05f96c34c3358dbb798a8f376327ce1bf0028f01de2`. The source hashes for all 155 eligible accounts still match. | Planning must compare the stored contract hash with the current contract and produce an explicit safe action or blocker. |
| MR-002 | Ready for retest | High | Reconciliation collapses source-hash and contract-hash failures | All 155 accounts were initially reported as `migration_hash_mismatch`, and reconciliation stopped before native financial checks. | Report `source_hash_mismatch` and `contract_hash_mismatch` separately and continue safe diagnostic checks where possible. |
| MR-003 | Ready for retest | Critical | A fresh savings plan misses known target drift | Fresh plan `f6c89d83039442b7ad36e0b439a6589c` reports 155 `unchanged` and 2 quarantine even though detailed reconciliation finds 62 mismatched accounts. | The `unchanged` predicate must validate contract identity and sufficient native target state; a second plan must not be empty when reconciliation would fail. |
| MR-004 | Closed | Critical | Midnight processing reverses imported VISTA history | The original midnight run reversed 279 mapped transactions across 35 VISTA accounts. A controlled pre-fix v12 run exposed one additional date-only tax-selection reversal, bringing the existing local repair scope to 280 mapped events across 36 migrations. VISTA proof v13 remained exact across job runs 62, 63, and final deployed run 64. | Implemented: preserve imported manual identity, retain explicit posting dates, and exclude referenced imported tax from native correction candidates. Existing damage is tracked by MR-006. |
| MR-005 | Closed | Critical | Midnight processing creates unmapped DPF interest | The original midnight run created 124 non-manual, referenced, unmapped type-3 interest postings totaling 13,871.21 across 27 DPF accounts. DPF proof v3 remained exact across job runs 63 and final deployed run 64. | Implemented: referenced imported interest is authoritative and explicit user-posting boundaries retain the source date. Existing generated rows are tracked by MR-006. |
| MR-006 | Open | High | Savings acceptance did not cross the scheduler boundary | The original run was declared reconciled before the next midnight processing cycle. After that cycle only 93 of 155 eligible accounts still passed detailed financial reconciliation; 62 failed (35 VISTA and 27 DPF). | Acceptance must include `apply → reconcile → run/wait for relevant jobs → reconcile again → second plan`. |
| MR-007 | Open | High | Native-share local state is not fully reconciled | The post-apply native-share plan reports 42 unchanged, 3 resume, and 12 quarantine. Three pre-fix canary accounts retain journal/mapping inconsistencies. | Repair or safely recreate only the three affected local projections, reconcile all 45 eligible share accounts, and preserve the 12 reviewed quarantines. |
| MR-008 | Open | Medium | Pre-fix share payment mappings remain in the local tenant | Earlier share-product work stored some payment mappings under the savings product type. Code was corrected, but stale local rows may remain and must not be mistaken for valid product configuration. | Inventory the exact stale rows, prove ownership, and repair them with a reviewed migration or narrowly controlled local action—never broad deletion. |
| MR-009 | Open | Medium | Operational documentation contains stale acceptance statements | The membership README still describes an older 66,374-record acceptance. The savings README states that run `594560...` reconciled all 155 accounts, which is no longer true after scheduled processing. | Update service status only after the defects are fixed and the full stability test passes. Preserve historical evidence but label superseded acceptance clearly. |
| MR-010 | Open | High | Cross-service final reconciliation order is incomplete | Native shares consume reconciled VISTA accounts. A successful savings reconciliation before shares or before scheduled jobs does not prove the final combined state. | Final local acceptance order must reconcile membership and savings, cross the scheduler boundary, apply/reconcile shares, and then reconcile savings again. |

## Detailed reconciliation evidence

The diagnostic audit deliberately bypassed only the top-level contract-hash
gate so that the existing native financial checks could run. It did not write
to Arissto or Fineract.

### Population

- Eligible savings accounts: 155
- VISTA: 38
- DPF: 117
- Reviewed savings quarantines: 2
- Current financial matches: 93
- Current financial mismatches: 62

### VISTA findings

- Mismatched VISTA accounts from the original run: 35
- All 35 have the same failure family:
  - ending balance mismatch;
  - mapped transaction mismatch;
  - missing running balance on reversed transactions; and
  - daily running-balance mismatch.
- Current reversed mapped transactions requiring repair: 280 across 36
  migrations. The additional row is a controlled-test DPF withholding-tax event
  that exposed and is now covered by the referenced-tax selection guard.
- Still-active mapped transactions: 1,402
- Daily balance check failures: 1,258
- Thirty-one of the 35 mismatched VISTA accounts are linked to native share
  accounts. Timing proves that share apply was not the primary cause: the
  reversal/recalculation occurred around midnight, before the later share run.

### DPF findings

- Mismatched DPF accounts: 27
- Failure family: `interest_replay`
- New unmapped type-3 interest postings: 124
- New posting amount: 13,871.21
- All 124 postings are non-manual, have native references, and were created in
  the same midnight processing window.
- Native transfer counts generally still match the expected source interest
  events; the additional native interest postings cause the count divergence.

### Accounting observation

The detailed checks did not report unbalanced journals. This is useful but is
not acceptance: balanced accounting entries can still represent duplicated or
unexpected financial events.

## Required implementation sequence

- [x] Reproduce the midnight drift on a controlled scoped VISTA and DPF pair.
- [x] Identify the exact Fineract jobs/commands that reversed the 279 VISTA
      transactions and created the 124 DPF interest postings.
- [x] Decide the cutover contract: imported referenced manual interest and tax
      remain source-authoritative history; native scheduling may own only
      unreferenced future postings.
- [x] Split reconciliation hash diagnostics and remove the current short circuit
      for read-only financial diagnosis.
- [x] Add contract-hash validation to savings planning.
- [x] Add native drift validation to the `unchanged` decision, including mapped
      transaction reversal, current balance, and unmapped generated interest.
- [ ] Add focused automated tests for every issue in this register.
- [ ] Repair the local savings state without deleting unrelated/default-tenant
      entities.
- [ ] Resolve the three native-share resume cases and audit stale payment maps.
- [ ] Execute the complete local acceptance sequence below.
- [ ] Update registry/readmes only after acceptance evidence exists.
- [ ] Independently inspect and plan production; do not reuse local plans.

## Required local acceptance sequence

1. Verify clients remain reconciled.
2. Inspect, plan, apply if needed, and reconcile `membership-share-capital`.
3. Inspect and plan `savings-deposits`; review every writable action.
4. Apply and reconcile savings.
5. Execute or cross all relevant Fineract scheduled-processing boundaries.
6. Reconcile savings again and require all 155 eligible accounts to match.
7. Generate a second savings plan; require no unexplained writable action and
   no false `unchanged` classification.
8. Plan/apply/reconcile `native-share-capital`; require all 45 eligible accounts
   to match and retain exactly the 12 reviewed prerequisite quarantines.
9. Reconcile savings again after native shares.
10. Reconcile membership again and record the final identifiers and counts here.

## Update protocol

For each work session:

1. Update the issue status in the register (`Open`, `In progress`, `Blocked`,
   `Ready for retest`, or `Closed`).
2. Add one short dated checkpoint below with commands/run IDs and aggregate
   results only. Do not include credentials, PII, or large mismatch payloads.
3. Link code, tests, or a detailed investigation note instead of expanding this
   control file indefinitely.
4. Close an issue only when a regression test and controlled local proof both
   pass.

## Checkpoints

### 2026-08-30 — Control log created

- Captured the post-midnight savings reconciliation failure and current
  membership/native-share state.
- Created diagnostic savings plan `f6c89d83039442b7ad36e0b439a6589c`;
  it must not be applied because it falsely classifies all 155 eligible
  accounts as unchanged.
- No implementation change or target repair was performed as part of creating
  this document.

### 2026-08-30 — Scheduler cause and planning guards implemented

- Confirmed **Post Interest For Savings** job `6` ran from `00:00:00.005` to
  `00:00:02.857` and caused both drift families; see
  [midnight-savings-drift.md](midnight-savings-drift.md).
- Added planner contract/native-state blockers and split reconciliation hash
  diagnostics without applying or repairing target financial records.
- Read-only plan `b2b6f34ed8a74f95b1f077f8c6545fef` is non-applicable:
  155 blocked, 2 reviewed quarantines; blocker families are 155 contract hash,
  35 reversed mapped events, 35 VISTA balances, and 27 unmapped DPF interest.
- Added the Fineract preservation fix for referenced manual interest history.
  All 221 sync tests and both focused Java regression tests pass. Local service
  redeployment, scoped scheduler proof, and existing-state repair remain open.

### 2026-08-30 — Scheduler prevention accepted on controlled VISTA/DPF proofs

- Deployed three complementary Fineract guards: preserve `is_manual`/`ref_no`
  in scheduler reads, retain the explicit source date for user-posted interest
  boundaries, and exclude referenced imported withholding tax from date-only
  native correction candidates.
- VISTA proof v13 (account `480`) replayed 25 source events and remained at 25
  active transactions, zero reversals, six referenced manual interest postings,
  and balance 972.70 after jobs 62 and 64. Exact event and journal
  reconciliation passed.
- DPF proof v3 (cycle accounts `482`-`486`, linked VISTA `481`) retained four
  active historical interest postings totaling 808.00, zero reversed interest,
  and balanced journals after jobs 63 and 64.
- Final deployed job run 64 succeeded from `22:54:44.442Z` to
  `22:54:46.115Z`. Global damaged-state counters did not increase: 280 reversed
  mapped events across 36 migrations and 124 active unmapped DPF-interest rows
  across 27 migrations.
- All 223 sync-engine tests and the focused Fineract core/provider regression
  suites pass. MR-004 and MR-005 are closed for prevention; MR-006 remains open
  for narrow repair and complete 155-account re-acceptance.

## Next-agent handoff

Design and review a narrow local repair for the existing 280 reversed mapped
events across 36 migrations and 124 unmapped DPF postings across 27 migrations,
then run the complete acceptance sequence. Preserve existing local tenant
entities and event identity, keep Arissto strictly read-only, and do not apply
any diagnostic plan. The local Fineract process already has the accepted
scheduler-prevention code loaded.
