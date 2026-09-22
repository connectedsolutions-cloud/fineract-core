# Native share-yield migration service

## Status

`available` for reviewed local workflows and checkpointed local full re-sync.
The controlled local workflow completed with exact reconciliation. Enabling the
`Accrue Share Yield` scheduler remains a separate operational decision.

This service migrates the financial meaning that the purchase-only native
share projection previously omitted. It reads preferred-share rows from
`FNC_PROVISIONES`, resolves each source certificate through
`credesal_share_certificate`, and posts a source-exact native yield event to
the owning `m_share_account`.

Each imported event preserves:

- source reference `FNC_PROVISIONES|ID_FNC_PROVISION`;
- certificate-to-native-account ownership;
- accrual date, share balance, annual rate, and Actual/Actual denominator;
- exact eight-decimal accrual and two-decimal booked amount; and
- the corresponding native share transaction.

Historical journal creation follows the global accounting cutoff. Pre-cutoff
imports populate the native subledger without duplicating journal entries that
are owned by `accounting-journal-entries`. Post-cutoff scheduled accrual entries
are owned by Fineract and debit `7110040100` / credit target liability
`222099910101`. Arissto source account `222099940101` is translated to that
target account by the reviewed accounting crosswalk; share-yield configuration
must use the target GL identity. The `Accrue Share Yield` scheduler uses the
Fineract business date but is not a loan COB step.

## Controlled local acceptance commands

```bash
./arissto-sync inspect --block native-share-yield --target local
./arissto-sync plan --block native-share-yield --target local
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync reconcile --run RUN_ID --target local
./arissto-sync retry --run RUN_ID --failed-only --target local
```

Planning freezes source hashes, native account mappings, target schema, product
configuration, and the accounting cutoff. Apply is idempotent by source
reference and Fineract command idempotency key. Reconciliation reads the target
subledger independently and compares ownership, date, exact accrual, and booked
amount.

## Controlled local acceptance gates

1. Deploy tenant migration `0349` on a restored disposable `sandbox` tenant.
2. Run `native-share-capital` and reconcile every certificate in scope.
3. Configure preferred yield through `POST /v1/shareyield/products/{productId}`.
4. Inspect and plan `native-share-yield`; review counts and totals.
5. Apply and reconcile with zero source-reference or monetary mismatches.
6. Replay the same plan and prove every row is unchanged.
7. Prove the accounting cutoff creates no duplicate historical journals.
8. Execute `Accrue Share Yield` for one post-cutoff business day and prove one
   account/day accrual plus balanced expense/payable journal entries.
9. In a disposable account only, settle an amount to the linked VISTA account
   and prove debit payable / credit savings control without changing share
   capital.

The scheduler row is installed inactive. Enabling it is a separate operational
decision after these gates pass.

## Known reconciliation boundary

The retained native subledger and the historical GL are not interchangeable.
The current retained source population begins from zero on 2024-11-12 and its
booked certificate balance is the amount imported here. The liability account
also contains older system-22 credits. Those remain under the historical GL
service and must not be fabricated as member-level accruals without a source
allocation. The controlled acceptance must report that legacy difference
explicitly rather than force the subledger to equal lifetime GL credits.
