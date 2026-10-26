# Interest recalculation activation

## Approved scope — 2026-10-26

Enable native interest recalculation for every newly created sync product and
loan, including historical loans and repayment replay. Keep debt insurance.
This feature does not promise equality of Arissto and Fineract loan metrics.
The user explicitly separated future metric reconciliation/alignment tools and
their sync step from this activation. Manual historical differences do not
create an activation prerequisite or justify synthetic balance adjustments.

## Frozen settings and next-cycle behavior

`config/loans.json` freezes daily rest frequency (2, interval 1), no compounding
(0), reschedule-next-repayments (1), preclosure interest through the preclosure
date (1), and arrears based on the original schedule. Product creation uses
`isInterestRecalculationEnabled=true`; native loan applications inherit it.
Products are compared against the actual nested `interestRecalculationData`
response, including every frozen setting. Existing loans must report the flag
as enabled. An old product/loan is not silently converted after posting.

The next cycle needs a newly reviewed plan: revision 8 and the changed contract
hash invalidate earlier plans. No fresh/clean cycle, reset, or composed workflow
was launched for this feature. The normal guarded workflow builds/starts the
updated backend before replay. Existing workflow run-mode and target controls
continue to apply.

Keep the original source schedule installation before servicing. Once repayment
replay has regenerated a native schedule, retries preserve that schedule across
all three schedule-writer paths. Transaction identities, dates and explicit
source allocation checks remain in force. These are replay-integrity controls,
not a requirement to match every source metric.

Remove the blanket `cutover_exact_component_alignment_unproved` active-loan
quarantine and stop calling the opening-interest alignment/waiver helper.
The native policy skips the legacy exact component gate. Dated interest,
due-principal and derived-schedule differences remain visible as named native
variances. Existing independent history, principal-conservation, mora, accounting
and extraction checks remain; they are not evidence that all loan metrics align.
No general balance-adjustment or reconciliation tool is introduced here.

## Insurance compatibility

`LoanChargeApiJsonValidator` previously grouped opening-outstanding-principal
insurance (calculation type 8) with percentage-of-disbursed-principal charges.
The loan-application path rejected the former for recalculating installment
products, although its calculation and separate add-charge validation already
supported it. Remove only the obsolete type-8 rejection. Keep the other
percentage-charge restrictions.

Insurance remains 0.06% of scheduled opening principal per ordinary installment,
rounded in the loan currency. A recalculated schedule supplies the updated
opening principal. Extra recalculated-interest components do not add insurance.
Historical insurance stays on the existing exact-charge replay path; recurring
insurance starts on `Fineract starts` and is not retroactively imposed on source
history. No rate or accounting mapping is changed.

## Technical verification

- Loan-sync suite: 229 tests passed, including product setting drift, active-loan
  eligibility, observational interest/schedule differences, and retry behavior.
- Java: 52 tests passed. Application validation permits type 8 with recalculation and retains the
  other restrictions. Opening-principal charge calculation and source-exact
  recalculation replay regression suites pass.
- Local sandbox proof: product 5 enables recalculation with insurance. Loan 2764
  (source 2612) proves application creation with both enabled. Loan 2765 (source
  2647) uses the real cutover-scoped recurring charge path and replays all seven
  historical principal/interest allocations. Every insurance installment matches
  independently calculated opening principal; retry adds no duplicate charge.
  Reversing and replaying the last payment preserves both the allocation and
  insurance schedule. There are zero linked GL rows.
- Proof boundary: **Arissto through 2026-10-19**, **Fineract starts 2026-10-20**;
  disposable local sandbox fingerprint `b9f6834b66790744`. Main proof plan
  `630a69999254824181e054173c675595d3829138ef9d5e047906e6213753e05e`;
  reversal/replay continuation
  `cf709143b80610c0d6219f9e13c7bee57886fd58090e86439bcc83b76a424e16`.
  Private artifacts reside under `.arissto-sync/loan-recalculation-insurance/`.

A deliberately different trial attached insurance from origination to 2612,
then attempted the unchanged historical source allocations. It rejected an
unrepresentable $0.10 interest remainder. That loan is creation-validation
coverage only, not a completed replay. The real migration attaches recurring
insurance at cutover; the successful 2647 proof exercises that path. These tests
establish bounded feature compatibility, not portfolio-wide metric parity.
See [sanitized checks](interest-recalculation-default-checks.json) and the
[earlier five-loan paired replay evidence](interest-recalculation-canary.md).

The broader 843-test sync run also found four unrelated expectation failures
in the existing native-creation override list, Vista minimum balance, workflow
service count and share-workflow dependencies. The focused commit snapshot independently passes 228 tests. The two affected loan modules
pass all 244 tests after completing their stale writer fixtures. These unrelated
failures are not repaired or used as a metric-parity gate by this feature.

## Mifos inspection

The product settings form and summary already own/display the recalculation
settings. Product and loan charge forms display the API calculation/time types;
`ChargesFilterPipe` filters currency/duplicates, not recalculation, and retains
type-8 insurance. Two focused frontend tests pass, verifying selection and submission
with recalculation enabled plus the existing currency/duplicate restrictions.
Existing English/Spanish recalculation labels remain applicable. No new field,
search criterion, sorting, export behavior or frontend production change is
needed for this server-side compatibility correction.

See the [project-global decision](../../../../../docs/ARISSTO_LOAN_ALIGNMENT.md)
for the separate future alignment scope.
