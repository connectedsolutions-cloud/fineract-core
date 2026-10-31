# Refinance accounting and atomic disbursement reversal

Implements the cross-stack [refinancing requirement](../../docs/REFINANCING_SURPLUS_REPAYMENT.md). Source accounting evidence remains in the [Arissto research note](../../../credesal-db-space/docs/learnings/refinanciamientos-contabilizacion-y-caja.md).

## Posting contract

Ordinary `disburse` remains the default. Omitted/false `applyRefinancingSurplusAsRepayment` closes the selected predecessors and makes the remaining cash payable; `disburseToSavings` deposits the remainder into the linked savings account. Explicit true retains the remainder as a native repayment on the full new principal. Native payoff quoting and repayment allocation are preserved.

One combined origination voucher debits the successor's selected portfolio account and credits predecessor principal/interest/charge components, origination charges/tax, any retained repayment components, and the actual cash remainder payable. Offset fund-source/activity-100 entries are captured before persistence and replaced by these components. This removes artificial gross CAJA/fund turnover. Separate native accrual recognition remains separately dated and journaled. Every line retains its own loan, office, dimensions and currency. The combined origination has one journal business number.

Cash delivery is a later event: debit `222099910201`, credit `1110010199`. A real cash return debits `1110010199` and credits `222099910201`. Both create native cashier ledger records, so cashier cash and GL follow the same movement. Internally funded refinancing transactions are excluded from cashier cash summaries/audits. Retained and savings proceeds never enter the cash-delivery queue.

Committee preprocessing skips refinancing principal/payable recognition. Native refinance origination is the single posting owner and pays applicable available-at-cashier charges as well as disbursement charges. VAT uses the charge's configured tax group. Reduce-disbursal charges split their gross withholding between charge income and tax instead of crediting both the gross fee and tax. Tax postings retain the native charge-payment transaction link.

## API

| Route | Permission | Purpose |
| --- | --- | --- |
| `GET /loans/{id}/refinancing` | `READ_LOAN` | Operation, affected predecessors, retained payment, cash entitlement/delivery/return, journal pointer, reversal date and blockers. |
| `GET /loans/refinancing-payouts?officeId=...` | `READ_LOAN` | Office-scoped outstanding cash, across origination dates. Excludes retained, savings, paid, reversed and return-in-progress operations. |
| `POST /loans/{id}?command=payoutRefinance` | `PAYOUTREFINANCE_LOAN` | Record an actual cash delivery, including partial delivery. |
| `POST /loans/{id}?command=returnRefinance` | `RETURNREFINANCE_LOAN` | Record actual recovery of previously delivered cash. |
| `POST /loans/{id}?command=undodisbursal` | `DISBURSALUNDO_LOAN` | Atomic tracked-refinance unwind; ordinary-loan behavior is preserved. |

Cash commands require `transactionAmount`, `transactionDate`, `note`, `externalId`, `locale`, and `dateFormat`. The amount must be positive and have valid currency precision. Exact retries return the existing movement; conflicting reuse of an external ID fails. Payout cannot exceed undelivered proceeds; return cannot exceed outstanding delivered cash. Once a return starts, additional delivery is blocked. Actual cash commands require exactly one open cashier session belonging to the operator and loan office, and the current business date. Payout also checks available cashier cash.

Refinance undo requires a reason and the current business date. It locks related loans, and linked savings when applicable, then checks office scope, accounting boundaries/branch closure, later user activity, journal provenance and cash recovery. Delivered-but-unreturned cash blocks undo. A later loan payment/refinance or savings activity must be resolved first. Independently changing a transaction owned by an active refinancing is blocked: use the atomic refinance action.

Undo reverses predecessor settlements through native loan adjustment/reprocessing, undoes the successor and linked retained repayment/savings transfer through native services, and posts exact counterentries linked to the original journals. Accounts, loan references, office/dimensions, currency and amounts come from the original entries. Undelivered payable is cancelled without CAJA. Real payout/return events remain in the audit trail. A repeated completed undo returns `alreadyReversed` without more postings.

## Persistence and release unit

[Migration 0441](../fineract-provider/src/main/resources/db/changelog/tenant/parts/0441_refinancing_operations.xml) owns the PostgreSQL schema:

- `m_loan_refinancing_operation`: versioned operation, dates, proceeds mode and delivered/returned counters; one active operation per successor.
- `m_loan_refinancing_operation_transaction` and `_journal`: exact ownership of native transactions and journal entries, including operation-created accruals.
- `m_loan_refinancing_cash_movement`: unique external reference, operator/reason, date/amount, voucher and native cashier-transaction links.

The migration adds cash permissions and changes activity 102 from the known CAJA header `111001` to enabled posting detail `1110010199`, only when that exact old mapping and target exist. Activity 100 is unchanged. Activity 202 must resolve to enabled detail liability `222099910201`; origination validates it. Cash delivery validates 102 and the canonical enabled detail asset. Missing/wrong mappings fail atomically.

Deploy schema, backend and [Mifos flow](../../mifos-core/docs/refinancing-operations.md) together. Grant the new cashier permissions to appropriate roles. The local acceptance run applied the migration SQL only to disposable clones; it did not apply migrations, restart, reset, or insert fixtures into original `default` or `sandbox`. Normal release still needs migration 0441 and a matching backend/frontend build. Review other pending migrations independently; do not use a blanket tenant reset as rollout.

## Configuration and supported scope

Use the approved combined cash/payable accounts above, with office retained on each line. Keep short/long portfolio and interest categories distinct: microcredit `1141030101`/`1142030101` and `1141039901`/`1142039901`; consumer long principal uses posting child `114204010101`. Existing persisted loan selections are honored. No historical journals or existing loan/product balances are relabeled. A new synthetic prospective product verified the canonical microcredit short-to-long mapping. Existing default products using generic interest account `1520` still need a reviewed prospective product/account configuration rollout; this feature does not silently migrate them.

Native payoff and interest policies remain the product's policies. For example, the original non-recalculating test profile quotes remaining contractual interest. Account alignment alone does not establish monetary parity with an Arissto payoff calculated under another policy.

The native extension supports individual single-disbursement full refinancing/consolidation without down payments or savings-paid withholding charges. Source-exact historical import/partial-paydown commands remain separate. Previously disbursed, untracked refinancings cannot be safely adopted by guessing journal or cash ownership; their reversal preview explicitly requires reviewed provenance. Historical adoption and additional unsupported product shapes are not delivered by this change. Closed-period or independently changed-journal cases fail closed rather than rewriting accounting history.

## Verification

See [API/database acceptance evidence](refinancing-accounting-e2e-2026-10-30.json). Synthetic acceptance used a separate registry/data clone of local default on HTTPS port 9443, with migrations/background workers disabled after applying only the new migration SQL to that clone. Original default was read-only checked: no new operation table or test loan tags were present.

API-to-database checks cover default payout, explicit-false linked savings, optional retention, zero remainder, upfront fees, VAT, committee fees, gross reduce-disbursal tax, insurance liability, consolidation, prior borrower-payment preservation, later-payment blockers, full/partial cash delivery and return, queue removal, duplicate cash/undo requests, short-to-long canonical accounts and refinance-chain reversal order. A late injected database constraint failure proved loan/schedule/journal rollback; an insufficient-remainder case also rolled back. All successful synthetic refinance operations were unwound, and every tracked original/counterentry pair was checked by account, amount, currency, loan, office and dimensions. The assembler also tests the exact mapped 400.00 source example and differing office attribution. Cross-office attribution is a unit check, not a live branch-transfer acceptance test.

All 30 focused Java tests passed; 15 Mifos action/navigation tests and Angular template compilation passed. Focused Java tests cover assembly, context cleanup/suppression, operation guards, ownership, cashier audit and retained repayment. Mifos tests cover omitted/default and explicit choices, movement retries, invalid/reversed submissions, reversal review/blockers and navigation refresh. Angular template compilation passed. Browser clicking and report-export rendering were not exercised.

A repeatable, reset-free API/GL check is available in [verify-refinancing-e2e.py](../scripts/verify-refinancing-e2e.py). It refuses non-loopback/non-9443 API targets and databases outside `refinance_test_data_*`. Prepare a disposable instance first and supply credentials through `FINERACT_TEST_USER`, `FINERACT_TEST_PASSWORD`, and `REFINANCE_TEST_PG_DSN`:

```bash
python scripts/verify-refinancing-e2e.py \
  --base-url https://127.0.0.1:9443/fineract-provider/api/v1 \
  --product-id TEST_PRODUCT_ID --output /tmp/refinance-acceptance.json
```

The test product must support the documented 4,000/6,000, 12-month, 1%-monthly synthetic profile. The script creates its own synthetic client/loans, checks postings, reverses both refinancings, and retains audit history. It never clones/resets a database or writes SQL.
