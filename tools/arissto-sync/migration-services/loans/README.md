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

- Registry status: `available`; Gate 5 was accepted from fresh/clean cycle
  `sandbox-2026-09-13-loans-b`, including dependency-complete recovery after an
  environmental disk-full interruption, a final durable ledger with no failed
  or blocked plan items, and strict reconciliation with zero blocking mismatches
- CLI block: `loans`, inspection and immutable target-specific planning
- Writer: product plus bounded native loan lifecycle for normal, adjusted,
  Cobro Movil, reversal, terminal, single-predecessor refinance, multi-loan
  consolidation, cross-client legacy settlement, and partial-paydown flows
- Historical repayments use the permission-gated `sourceExactRepayment`
  command. The writer supplies the four frozen components and blocks unless
  Fineract returns the exact total and allocation.
- Personal guarantors are resolved as existing synchronized clients and written
  through the permission-gated `sourceExactCreate` guarantor command. The
  writer preserves repeated source rows, supports historical attachment to
  closed loans, omits relationship/funding details, and reconciles exact active
  multiplicity without deleting target rows.
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
- Loan `83`'s two orphan reversal notes and later repayment are handled only by
  the proved source-exact component-reallocation signature; partial or changed
  signatures remain quarantined
- Fully reversed, net-zero refinance attempts are retained as reviewed
  provenance-only no-write actions and removed from the effective graph;
  partial signatures remain quarantined. Multi-predecessor consolidations use
  the dedicated atomic settlement contract. The same-client shape is
  canary-proved. Completed legacy cross-client settlements use a separate,
  permission-gated source-exact path with liquidation/payoff audit evidence;
  successor `2472` proves this path through strict reconciliation and unchanged
  replay
- The 6,603 schedule rows tagged with `ID_REESTRUCTURACION` are 174 archival
  snapshots with null `ID_CREDITO`; none belongs to a current portfolio loan.
  A future linked row is quarantined until a native same-loan reschedule proof
  is added.
- Line `00001` loans `24`, `435`, and `945` are reviewed non-blocking historical
  manual adjustments: native schedule differences are reported while source
  movements, component totals, cutover balances, and terminal status remain
  exact
- Line `00010` loans `301`, `1117`, `1182`, `1484`, `1743`, `1748`, `2069`,
  `2241`, `2254`, and `2355` are independently classified under the same narrow policy. Their
  archived operator edits, non-monotonic final rows, and any negative interest
  adjustments are retained as source provenance, are not replayed as Fineract
  events, and do not broaden product schedule logic. Active loan `2374` has a
  different, source-verified shape: its final two rows share one due date and
  the last row is principal-only. The engine preserves the original 100 rows as
  provenance, aggregates those two rows into one source-exact terminal period,
  and installs the resulting 99-period active schedule after disbursement. The
  rule fails closed unless the state, sequence, ordering, and zero-interest/
  zero-other terminal signature all match. If that loan later becomes a closed
  refinance predecessor, the same aggregation remains valid only when its
  lifecycle proves one disbursement, one final refinance payoff, full principal
  settlement, a named successor, and zero terminal source balances
- Loans `301`, `1117`, and `1182` have a stale higher header rate after an
  operator adjustment. Only these identities use the current approved portfolio rate
  to create an acceptable native staging schedule. Loan `1441` is not manual:
  it uses the reviewed `205.31` staging EMI to create the required 75 native
  periods. Immediately after the sole disbursement and before servicing, the
  identity-guarded active-schedule importer installs and verifies the exact
  75-row source schedule. The unchanged first source core installment `205.29`
  is a fail-closed precondition. Existing partial pending applications are
  recovered only when their immutable staging terms agree; active or
  completed loans are never silently modified
- Closed line `00010` loans `23`, `90`, `317`, `340`, and `359` use planner
  policy `reviewed-manual-adjustment`, with historical-reference-only behavior.
  Their archived edits are provenance,
  while movements, allocations, charges, balances, status, and accounting
  remain exact. Active loans `479`, `1738`, `1841`, and `1869` use the separately
  reviewed source-exact active-schedule import: the migration does not replay
  archived adjustment operations or infer a calculator rule, but installs the
  current Arissto schedule after disbursement and before servicing. Identity,
  active state, line, adjustment count, cardinality, ordering, and full-principal
  signatures all fail closed on drift
- Closed loans whose header has `SALDO_TOTAL=0`, zero principal, interest,
  mora, recargos, and CxC, but a positive `SALDO_SEGURO`, use the dynamic
  `closed-stale-source-insurance-residue` terminal policy. The plan preserves
  the exact source residue as reviewed evidence while the clean Fineract
  reconstruction replays every real event and finishes closed with zero native
  fee debt. The rule is signature-based rather than loan-ID-based; missing
  event history or any nonzero companion balance quarantines the loan
- Namespaced plan `fd0a0a5680bd4bdab3e0b78d6cb4aa27` expanded the four
  active adjusted loans to nine dependency-complete loans. Run
  `60fd47138e6a43ad90a03eb873d57a2b` succeeded and reconciled all nine with
  zero failures, quarantines, or mismatches; unchanged replay
  `2053e64c48254af9b040915a718cfdf8` recovered all nine and reconciled identically
- Gate `G5-SCH-009` has a dedicated acceptance checker. It derives the nine
  expected members and their state-specific policies from the plan, rejects
  failures, quarantines, active-loan variances, unexpected closed-loan
  variances, or blocking reconciliation findings, and requires an independently
  reconciled unchanged same-plan replay:

  ```bash
  ./arissto-sync check-loan-adjusted-schedule-cohort \
    --target local \
    --cycle CYCLE \
    --plan PLAN_ID \
    --run RUN_ID \
    --replay-run REPLAY_RUN_ID
  ```

  Acceptance is `accepted=true`. The only permitted findings are
  `reviewed_manual_adjustment_schedule_variance` entries for the five closed
  loans; no separate closed-subgroup apply is required
- Fresh combined-cohort plan `cfd5f875dbae4ef4bf30aa7da04ea055`, run
  `7e471a3392ff47b6a6898e4d03352a49`, and unchanged replay
  `f7b7235a42684e96bfb5227a9348873a` prove complete execution, strict
  reconciliation, exact active schedules, and replay idempotency across all
  nine members plus their dependencies. The checker still returns
  `accepted=false` because each reconciliation contains 20 unexpected
  non-schedule balance variances. Resolve those component/cutover differences
  before marking `G5-SCH-009` complete
- Loan `83` keeps its incomplete six-row Arissto schedule as historical
  reference only; it is not a manual-adjustment classification. Fineract uses
  its native schedule while movements, components, balances, status, and
  journals remain exact
- Closed loan `26` uses historical-reference-only scheduling only when its
  zero-principal stored plan and complete repayment/refinance lifecycle match
  the reviewed runtime signature. Any near-match remains quarantined, and the
  `26 -> 108` chain must still pass apply, reconcile, and unchanged replay
- Closed refinance predecessors `281`, `283`-`286`, `315`, `331`, `632`,
  `634`-`636`, `639`-`641`, `648`, `971`, `983`, `992`, `995`, and `998`
  retain their stored schedules as historical reference only. This is not a
  manual-adjustment classification and does not replay or synthesize schedule
  rows. The exception applies only while each loan remains closed with one
  disbursement, one refinance payoff, full principal allocation, zero terminal
  balances, and an unchanged monotonic full-principal source schedule
- `G5-SCH-014` has a source-derived contractual-origin schedule classifier
  and generalized active source-exact writer. It excludes every loan with
  `CRD_REESTRUCTURACION` history. Month-end refinance-root canary `280` and its
  predecessor `135` completed and reconciled without a blocking mismatch in
  run `52a1ce1571fd489498d719d4d3d13ba5`. Full replay plan
  `9995d2e755894af897cfbe133888d0c3` subsequently recovered 30 active-writer
  contractual-anchor loans and 20 reviewed closed refinance roots; reviewed
  voided successor `638` remained an intentional no-write quarantine.

As of 2026-09-13, source-exact repayment allocation and the supported
single-predecessor outstanding/payoff refinance boundaries are implemented and
canary-proved. Multi-predecessor consolidation is implemented across Fineract,
the sync engine, and Mifos. A same-client consolidation and unchanged replay
are canary-proved. The migration-only cross-client evidence path is implemented
without weakening ordinary ownership validation. Full plan
`0065dc7d540f42c89b5cbe0fe18ec568` admits all 14 direct cross-client
settlements and removes their 75 graph-propagated quarantines; canary plan
`3aa9523256434f1eaf4d974b946b205a` and unchanged replay run
`709cd5eda5bb463caf5e62ab299847ad` prove the path. Fresh/clean cycle
`sandbox-2026-09-13-loans-b` supersedes the earlier assembled evidence.
Workflow run `dfcff1a3246e46828a90972b6630fbde` completed the frozen
dependency-closed plan after the host disk was recovered and retry closure was
corrected. Its durable plan ledger contains 2,509 succeeded loans, 19 recovered
loans, the same 19 reviewed no-write quarantines, two succeeded products, and
no failed or dependency-blocked item. Recovery child run
`a34a602cb5ec413eaf6c6023e0d56b74` safely reprocessed its complete affected
graph and reconciled with zero blocking mismatches. This same-plan recovery,
together with the established unchanged canary replays for specialized
lifecycle classes, is the accepted Gate 5 idempotency proof. A future
portfolio-wide zero-write replay remains useful regression hardening but is no
longer a registry-promotion blocker. Partial or non-zero reversed-refinance
signatures remain intentionally quarantined. See the current checklist in
[implementation-sequence.md](implementation-sequence.md#current-status--2026-09-13).

For the closed-refinance historical-schedule regression, build a fresh
namespaced plan from all 20 reviewed roots. The planner expands their refinance
components and immediately checks for the exact 57 descendants. This command
does not represent the separate 36-loan `G5-SCH-014` contractual-anchor cohort:

```bash
./arissto-sync plan-loan-reference-canary --target local \
  --proof-namespace g5-closed-ref-v1
```

Validate the frozen plan again before applying it:

```bash
./arissto-sync check-loan-reference-canary --target local --plan PLAN_ID
```

After apply, run the same command with `--run RUN_ID`. It performs strict loan
reconciliation and fails unless all 77 affected loans completed without a
quarantine or blocking finding. Run the command again against the unchanged
replay run. Canary execution belongs only on the disposable `sandbox` tenant;
never use the local `default` tenant for this proof.

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
./arissto-sync plan --block loans --target local --source-key ID_CREDITO --cutoff-date YYYY-MM-DD
```

The plan freezes the complete Fineract product payload for only the credit
lines required by the selected loans. Product actions use keys such as
`product:00001`; loan actions use keys such as `loan:24`, appear after their
product, and declare that product action in `depends_on`. An exact existing
product is `unchanged-product`; a missing product is `create-product`; any
external-ID or crosswalk contract drift makes the plan non-applicable.

The loan writer can apply one reviewed plan with bounded account-level concurrency:

```bash
./arissto-sync apply --plan PLAN_ID --target local
./arissto-sync apply --plan PLAN_ID --target local --loan-workers 4 \
  --fineract-pause-seconds 45 --fineract-recovery-attempts 5
./arissto-sync retry --run RUN_ID --failed-only --target local
./arissto-sync status --block loans --target local
```

The default is two workers, a shared 30-second recovery pause, and three
whole-loan attempts for transient connection/time-out or HTTP 429/5xx failures.
At most four workers are accepted. Commands inside one loan remain strictly
sequential, and a refinance successor waits for every selected predecessor to
finish successfully. After a transient failure, all workers pause; when the
delay expires, exactly one lifecycle acts as the recovery probe. Other workers
resume only after that probe reaches Fineract successfully. Each worker owns
its HTTP session, while only the main thread writes the SQLite run journal.
Validation and other non-transient failures are recorded immediately without
automatic retry. The same controls are available on `retry`. Composed workflows
accept them on `workflow plan` and freeze the resolved values into the parent
plan so detached start and resume retain the same policy.

Inspect every frozen Arissto lifecycle event beside the matching Fineract loan
transaction without writing to either system:

```bash
./arissto-sync debug-loans --run RUN_ID --target local --report /tmp/loan-events.json
./arissto-sync debug-loans --run RUN_ID --target local --source-key ID_CREDITO
```

The report includes target status and balances, every planned movement, every
Fineract transaction with component allocation, refinance successor context,
strict mismatch classifications, and a bounded recovery-or-quarantine
disposition. `--include-clean` retains fully reconciled loans for complete
event-ledger review.

Apply revalidates the frozen source, schema, target resources, product
contract, active client, and all referenced employee identities. It creates or
recovers the product first, then runs a non-posting native schedule calculation
for every new regular loan. Independent loan lifecycles may run concurrently,
but each loan submits, approves, disburses, and replays in strict order and only
when every frozen installment matches. A recovered partial loan must also pass
the same schedule comparison before another lifecycle write. A failed movement
stops the rest of that loan.
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
applicable lifecycle class. Every later target migration still requires its own
fresh full-scope plan, apply, and reconciliation on that exact target; registry
availability does not reuse the accepted sandbox plan.

Reconciliation treats source transaction identity, date, amount,
principal/interest/penalty/fee allocation, reversal state, terminal status,
every installment number/date/principal/interest amount, aggregate schedule
totals, and journal balance as blocking. Reviewed point-in-time balance
interpretations and the explicit line `00001` and line `00010` manual schedule
exceptions remain visible variances; they do not broaden the rule for another
loan.

The stricter rule reopened Gate 5 and remains the accepted reconciliation
boundary. The dedicated interest strategy makes the
actual historical repayment allocation for canary `2068` exact. The writer now
uses native pending-application term variations to impose the historical
schedule before approval, and blocks unless both the preview and persisted
schedule are exact. The complete strict canary matrix and accepted fresh/clean
workflow now support registry availability.

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
and canary-proved; they are not the current remaining defect count. The later
clean cycle populated all 2,493 supported loans and reduced the quarantine set
to the 19 reviewed no-write cases. Fresh/clean cycle
`sandbox-2026-09-13-loans-b` then closed Gate 5 under the accepted durable
same-plan recovery policy. Mobile Collections may consume those accepted
loan/repayment identities after its own dependencies and reconciliation pass.

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
historical/future charge contract. A `source_insurance_cutover_outstanding`
amount is a snapshot balance, so retry convergence compares the persisted
charge's `amountOutstanding`; its immutable original amount may be higher when
a later source insurance movement has already been replayed separately.
Historical insurance movement charges still require their original amounts to
match exactly. Savings and contribution components are
currently unpopulated in the reviewed credit flow; any future non-zero value
requires an explicit cross-product contract rather than being absorbed into a
loan charge.

See [contract.md](contract.md) for the source-to-native contract and
[implementation-sequence.md](implementation-sequence.md) for the gated build
order and production acceptance boundary. The canonical cross-service run
order is in
[orchestration.md](../orchestration.md#current-manual-loans-to-mobile-collections-flow).
