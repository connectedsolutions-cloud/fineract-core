# Loans

This executable proof block reconstructs the supported Arissto loan lifecycle in
native Fineract loans and loan transactions. It owns loan creation,
disbursement, repayment, reversal, charge, settlement, and closure behavior.

The block depends on synchronized clients and employees. Unsupported source
anomalies remain entity-scoped quarantines; they do not disable reviewed local
runs of the service.

Current full-run reconciliation gaps and the next-agent work order are tracked
in [loan-reconciliation.md](loan-reconciliation.md).

## Stable identity

```text
m_loan.external_id = ARISSTO:CRD:{CRD_CARTERA.ID_CREDITO}
m_loan_transaction.external_id =
    ARISSTO:CRD-MOV:{CRD_MOVIMIENTOS_CARTERA.ID_MOVIMIENTO_CARTERA}
```

The transaction identity is the downstream bridge used by mobile collections.
Neither service may fall back to matching by date and amount.

## Downstream ownership

`mobile-collections` runs only after this service. The loans service creates the
native repayment and assigns its stable source external ID. Mobile collections
may link operational route, batch, receipt, and capture metadata to that
transaction, but must never create the same repayment again.

## Status

- Registry status: `blocked`; executable only for reviewed, explicitly selected
  proof runs until renewed Gate 5 exact-schedule acceptance
- CLI block: `loans`, inspection and immutable target-specific planning
- Writer: product plus bounded native loan lifecycle for normal, adjusted,
  Cobro Movil, reversal, terminal, and supported single-predecessor refinance
  flows
- Historical repayments use the permission-gated `sourceExactRepayment`
  command. The writer supplies the four frozen components and blocks unless
  Fineract returns the exact total and allocation.
- The single proved zero-cash Arissto component reallocation uses the separately
  permission-gated `sourceExactComponentReallocation` command and retains all
  constituent source movement identities.
- Product policy: create required reviewed products from an empty business-data
  baseline; never bind unrelated native products by name or numeric ID
- Accounting segmentation: one portfolio GL per native product; preserve
  Arissto line type, credit type, and SLU through native fields/dimensions that
  propagate to journal entries
- Normal repayment allocation, periodic interest and insurance recognition,
  Cobro Movil clearing/reversal, and source reversal pairing: accepted for
  canary `2068`, reviewed local line `00010`, and the audited source reversal
  population; single-predecessor refinance uses Fineract native top-up
- Two duplicate/orphan repayment-reversal notes on source loan `83` are a
  mandatory whole-loan quarantine, not candidates for heuristic repair
- Fully reversed, net-zero refinance attempts are retained as reviewed
  provenance-only no-write actions and removed from the effective graph;
  partial signatures remain quarantined. Multi-predecessor consolidations use
  the dedicated atomic settlement contract. The same-client shape is
  canary-proved; cross-client predecessors remain quarantined pending an
  explicit authorization/participant contract
- The 6,603 schedule rows tagged with `ID_REESTRUCTURACION` are 174 archival
  snapshots with null `ID_CREDITO`; none belongs to a current portfolio loan.
  A future linked row is quarantined until a native same-loan reschedule proof
  is added.
- Line `00001` loans `24`, `435`, and `945` are reviewed non-blocking historical
  manual adjustments: native schedule differences are reported while source
  movements, component totals, cutover balances, and terminal status remain
  exact
- Line `00010` loans `1117`, `1484`, `1743`, `1748`, `2069`, `2241`, `2254`,
  and `2355` are independently classified under the same narrow policy. Their
  archived operator edits, non-monotonic final rows, and any negative interest
  adjustments are retained as source provenance, are not replayed as Fineract
  events, and do not broaden product schedule logic. Loan `2374` remains an
  explicit source quarantine because it has no adjustment history
- Closed line `00010` loans `23`, `90`, `317`, `340`, and `359` use the same
  reviewed historical-reference policy. Their archived edits are provenance,
  while movements, allocations, charges, balances, status, and accounting
  remain exact. Active loans `479`, `1738`, `1841`, and `1869` remain outside
  this extension pending an explicit future-servicing decision
- Loan `83` keeps its incomplete six-row Arissto schedule as historical
  reference only; it is not a manual-adjustment classification. Fineract uses
  its native schedule while movements, components, balances, status, and
  journals remain exact
- Closed loan `26` uses historical-reference-only scheduling only when its
  zero-principal stored plan and complete repayment/refinance lifecycle match
  the reviewed runtime signature. Any near-match remains quarantined, and the
  `26 -> 108` chain must still pass apply, reconcile, and unchanged replay

As of 2026-09-01, source-exact repayment allocation and the supported
single-predecessor outstanding/payoff refinance boundaries are implemented and
canary-proved. Multi-predecessor consolidation is implemented across Fineract,
the sync engine, and Mifos. A same-client consolidation and unchanged replay
are canary-proved, but the full cohort remains pending because nine of the 12
successors settle one loan owned by another client. This does **not** close the service:
remaining schedule/API edge cases, a clean full supported-population
reconciliation, and a zero-write second plan are still missing. Partial or
non-zero reversed-refinance signatures remain intentionally quarantined. See
the current checklist in
[implementation-sequence.md](implementation-sequence.md#current-status--2026-08-31).

Run a source-only portfolio inspection or one exact canary without loading a
Fineract target profile:

```bash
./arissto-sync inspect --block loans
./arissto-sync inspect --block loans --source-key ID_CREDITO
./arissto-sync inspect --block loans --target local
```

Passing `--target` adds a read-only audit of native loan/product/accounting
columns and the `credesal_loan_product_map` migration. Omitting it remains a
strictly source-only inspection.

Build a reviewable plan for the full portfolio or a bounded loan selection:

```bash
./arissto-sync plan --block loans --target local
./arissto-sync plan --block loans --target local --source-key ID_CREDITO
```

The plan freezes the complete Fineract product payload for only the credit
lines required by the selected loans. Product actions use keys such as
`product:00001`; loan actions use keys such as `loan:24`, appear after their
product, and declare that product action in `depends_on`. An exact existing
product is `unchanged-product`; a missing product is `create-product`; any
external-ID or crosswalk contract drift makes the plan non-applicable.

The Gate 4 sequential writer can apply one reviewed plan:

```bash
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync retry --run RUN_ID --failed-only --target local
./arissto-sync status --block loans --target local
```

Apply revalidates the frozen source, schema, target resources, product
contract, active client, and all referenced employee identities. It creates or
recovers the product first, then runs a non-posting native schedule calculation
for every new regular loan. It submits, approves, disburses, and replays the
loan only when every frozen installment matches. A recovered partial loan must
also pass the same schedule comparison before another lifecycle write. A
failed movement stops the rest of that loan.
Retries resolve the loan and every transaction by external ID before writing;
each run uses a new bounded API idempotency key so a cached failed command does
not prevent a reviewed retry. Production retains the standard exact-fingerprint
confirmation guard.

The controlled local Gate 4 canary used plan
`9dbddd1712b54ef4bfd131e56db9d925`. Recovery run
`1836284067904252ac7be797213203a1` created/recovered native loan `31`, replayed
one disbursement and four Cobro Movil repayments, and reconciled with no
blocking mismatch or unbalanced journal. Reapplying the same plan produced run
`bccea81db7f547c3b32c648297c179ce`, recovered the same loan, retained exactly
the same five source-identified transactions, and produced no duplicate.

Earlier Gate 5 evidence from 2026-08-29, now superseded by the stricter
source-exact contract, covered active, fully
paid, approved-undisbursed, normal and Cobro Movil repayment, repayment
reversal, disbursement reversal, debt-insurance, terminal closure, and native
refinance paths. Closed refinance plan
`c1b0bd0b1fda40abbf8acf6338f82ebe` migrated predecessor `1245` and successor
`1375`. Run `a148848aaea34a47aa599de629b285cf` reconciled with zero blocking
mismatches; the exact native top-up transfer and source payment totals were
retained, both loans closed, and all journals balanced. Replaying the same
frozen plan in run `ed15965531e04f5aa9f0c1f3a3ddb149` produced the same clean
reconciliation with no duplicate financial entries.

That earlier Gate 5 result is implementation acceptance, not evidence that the
entire inspected 2,490-loan source portfolio has already been applied to every target. The local
acceptance used controlled loans and refinance chains covering every currently
applicable lifecycle class. A full target migration still requires a fresh
full-scope plan, apply, reconciliation, and unchanged second plan on that exact
target.

Reconciliation treats source transaction identity, date, amount,
principal/interest/penalty/fee allocation, reversal state, terminal status,
every installment number/date/principal/interest amount, aggregate schedule
totals, and journal balance as blocking. Reviewed point-in-time balance
interpretations and the explicit line `00001` and line `00010` manual schedule
exceptions remain visible variances; they do not broaden the rule for another
loan.

The stricter rule keeps Gate 5 open. The dedicated interest strategy makes the
actual historical repayment allocation for canary `2068` exact. The writer now
uses native pending-application term variations to impose the historical
schedule before approval, and blocks unless both the preview and persisted
schedule are exact. The service remains executable for controlled proof work,
not production portfolio promotion, until the complete strict canary matrix
reconciles exactly and idempotently.

Fresh local proof plan `9da30c11808f4b6d8e32857e66ee1b78` expanded canary
`2068` to its required predecessor `1779`. Run
`82864df368814b459605ff06b3073bff` failed the stricter reconciliation as
intended: predecessor dates matched, but multiple installment principal and
interest values differed, aggregate interest was `$49.75` in Arissto versus
`$51.81` in Fineract, and several historical payment allocations differed.
The run predates the new pre-create guard and left local proof loan `1779`
partially replayed; it is test evidence, not an accepted migration result.
Guard-verification retry `6bf94a43880d4033a02c99bac44e3170`
then stopped recovered loan `1779` with
`existing_loan_schedule_mismatch_before_continue` and blocked dependent loan
`2068` before another financial write.

Source-exact writer proof (2026-08-30): local product `4` was updated through a
reviewed product action to `allowVariableInstallments=true`, `minimumGap=1`,
and `maximumGap=366`. Isolated pending application `44` reproduced source loan
`1082`: the base schedule had four installment-level differences and the stored
varied schedule had zero. Decisive pending application `45` reproduced source
loan `2068`: the base mixed 360/365 schedule had 22 installment/aggregate
differences and the stored varied schedule had zero. Both applications remained
status `100`, had zero transactions, and therefore made no accounting posting.
An identical replay recovered each exact schedule without adding duplicate
variations. These proofs clear the schedule-writing mechanism only; they do not
replace the posted lifecycle and accounting matrix.

Full default-tenant exercise (2026-08-30): preflight confirmed local tenant
`default` and target fingerprint `264d304e2927f694`. Full planning initially
exposed SQL Server's 2,100-parameter limit while freezing 2,490 loan
lifecycles; deterministic 900-loan extraction batches now cover the portfolio
and deduplicate refinance links across batch boundaries. Plan
`b86804017fec4c72a1fabd82e77754c2` then completed and its run
`192f2d3598714d0b86e8688cd64c0672` safely exercised the writer against a
non-empty target. It also exposed that 82 historical line `00010` loans use a
20.833333% periodic rate while the reviewed product ceiling was 20%, and that
failed-only retry incorrectly expanded a healthy product prerequisite to all
of that product's sibling loans.

The reviewed line `00010` historical envelope is now 30%, matching the maximum
frozen loan rate without repricing any account. Existing migration products
may widen only this maximum as a reviewed safe update. Retry now selects
explicit failures or crash gaps plus only their blocked descendants; adding a
healthy product as a failed loan's prerequisite no longer selects its siblings.
Failed Fineract diagnostics retain a bounded 4,000-character safe response so
validation codes remain operable.

Historical plan `1eeadbdec4a04d76b02cef67c7dddeee` widened the product and run
`e8bbff21f3bf42e2abdaf1496eb73c7b` synchronized 138 loans, recovered 27, and
recorded the remaining rows as 987 direct quarantines, 1,238 dependency blocks,
and 100 root failures. The former 82 rate-ceiling failures fell to zero. Strict
reconciliation still rejected the run: 2,101 historical repayment-allocation
mismatches affected the executed population, alongside 58 cutover/terminal
mismatches and only five schedule mismatches. Those historical counts motivated
the source-exact repayment and refinance mechanisms that are now implemented
and canary-proved; they are not the current remaining defect count. Gate 5 now
requires resolution of the remaining schedule/API edge cases, prerequisite
coverage, a fresh clean full supported-population reconciliation, and an
unchanged replay. Mobile Collections must not be promoted past loan/repayment
linking on this target until that loan reconciliation passes.

The Gate 3 schedule calculator is also non-posting and is restricted to the
local target:

```bash
./arissto-sync prove-loan-schedule --target local --source-key ID_CREDITO \
  --product-id FINERACT_PRODUCT_ID --client-id ELIGIBLE_LOCAL_CLIENT_ID
```

It calls Fineract's `calculateLoanSchedule` command, compares every installment
date, principal, and interest plus the aggregate totals, and never submits a
loan application. A schedule is accepted only when those core fields are exact;
equal totals do not excuse installment redistribution. `MONTO_OTROS` is a
resolved legacy aggregate: when it
duplicates `MONTO_SEGURO`, it is not added again. Debt insurance follows the
historical/future charge contract. Savings and contribution components are
currently unpopulated in the reviewed credit flow; any future non-zero value
requires an explicit cross-product contract rather than being absorbed into a
loan charge.

See [contract.md](contract.md) for the source-to-native contract and
[implementation-sequence.md](implementation-sequence.md) for the gated build
order and production acceptance boundary. The canonical cross-service run
order is in
[orchestration.md](../orchestration.md#current-manual-loans-to-mobile-collections-flow).
