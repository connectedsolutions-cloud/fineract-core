# Savings and fixed-term deposits source-to-target contract

## Contract boundary

The service migrates financial meaning, not only ending balances. Native
Fineract deposit records are authoritative after cutover. Arissto remains
strictly read-only, and no writer may insert directly into `m_savings_*`,
`m_account_transfer_*`, tax, or journal tables.

## Canonical identities

| Entity | Canonical source identity | Native identity |
|---|---|---|
| Product line | `AHO_LINEA_AHORRO|ID_EMPRESA|ID_LINEA_AHORRO` | Stable external ID in the reviewed Fineract savings/fixed-deposit product contract |
| Account | `AHO_CUENTA_AHORRO|ID_EMPRESA|ID_SUCURSAL|ID_CUENTA_AHORRO` | `m_savings_account.external_id` plus migration-account row |
| Owner | `AHO_PROPIETARIOS|ID_EMPRESA|ID_SUCURSAL|ID_CUENTA_AHORRO|ID_PROPIETARIO` | Native client plus migration-owner row |
| Movement | `AHO_MOVIMIENTOS|ID_AHO_MOVIMIENTO` | Native savings transaction plus event-map row; the separate business `ID_MOVIMIENTO_AHORRO` is retained for history/tax links |
| Cutoff accrual | `SAVINGS_CUTOFF_ACCRUAL|account-key|cutoff-date` | Migration-account cutoff snapshot plus native calculation diagnostic; never a fabricated transaction |

All identities are escaped and hashed with the versioned contract. Bare
`ID_SOCIO`, account number, or movement ID is never a cross-service identity.

## Product mapping

| Arissto type | Native Fineract resource | Decision |
|---|---|---|
| `001 VISTA` | Savings product/account | Migrate |
| `002 PROGRAMADO` | Recurring/scheduled product candidate | Inspect only until a source account exists and behavior is verified |
| `003 PLAZO` | Fixed-deposit product/account | Migrate by reviewed term/rate line |

Product creation is API-only. The contract must map currency, nominal annual
rate, calculation method, 365/366-day behavior, compounding/posting period,
minimum balance, dormancy, tax group, and all accounting roles. A source line
change after planning invalidates the plan.

## Account mapping

`AHO_CUENTA_AHORRO` supplies account number, line, state, opening date, agreed
rate, current balance, term/maturity, capitalization rule, linked destination,
last calculation/posting dates, holds/restrictions, and provision state.

Native account lifecycle mapping is intentionally command-based:

| Source state | Native target behavior |
|---|---|
| `APERTURADA` and zero funded balance | Apply/approve without inventing a deposit; activation behavior requires product validation |
| `ACTIVA` | Apply, approve, activate, and replay eligible financial history |
| `VENCIDA` | Reconstruct fixed-deposit maturity state through the supported lifecycle |
| `CERRADA` | Replay history and close only after principal reaches zero and the source closure movement reconciles |
| `INACTIVA` | Quarantine until a source-to-native dormancy/inactivity rule is approved |

Account creation order is `VISTA` first, then `PLAZO`, because every current
DPF capitalization destination resolves to a `VISTA`. The destination must be
active, same-client, and same-currency.

DPF principal funding is independent of that destination: a population audit
found no matching linked-VISTA principal withdrawal for 115 of the 119 source
DPFs (four have a reviewed possible match). The writer therefore activates a
funded DPF without `linkAccountId`, then calls the permissioned native
`migrationLink` command to attach the active same-client VISTA and enable
interest transfer without moving principal. Stock creation-time linking cannot
be used because it would collect the opening deposit from VISTA and invent a
source transaction.

Each source `AHO_LINEA_AHORRO` maps to one native product through
`credesal_savings_product_map`; product name alone is not durable identity.
The account's negotiated `PORCENTAJE_INTERES` is preserved as an account-level
rate override. It must not be replaced by the stale line default.

One source DPF is a position, not necessarily one native account. Every type-2
renewal boundary closes the predecessor term and creates a new native
fixed-deposit account through the maturity/reinvestment domain path.
`credesal_savings_migration_cycle` stores that one-to-many chain, and the
migration-account row points to the current native term.

## Ownership mapping

`AHO_PROPIETARIOS` is authoritative. Every owner must resolve through its
declared `AFI_SOCIO` FK to the reconciled client service. A native individual
deposit account has one client, while Arissto contains one jointly owned DPF.
For a joint account, the native client is the unique authoritative owner whose
`(ID_SUCURSAL_SOCIO, ID_SOCIO)` equals the same pair on the account master. The
reviewed joint DPF has exactly one such match. Zero or multiple matches are a
hard quarantine; all owners are still preserved in
`credesal_savings_migration_owner`. The engine must never duplicate principal
into one native account per owner.

Beneficiaries and authorized users are a later subphase. They must be inspected
and mapped separately; they do not change financial account ownership.

## Movement classification

| Reviewed source label | Native role |
|---|---|
| `APERTURA DE DPF` | Fixed-deposit funding/activation |
| `CANCELACIÓN DE DPF` | Principal withdrawal followed by eligible close workflow |
| `DEPOSITO DE AHORRO` | Deposit |
| `RETIRO DE AHORRO` | Withdrawal |
| `CAP. INT. PLAZO FIJO` | Native DPF interest transfer to linked `VISTA` |
| `CAPITALIZACION INTERES` | Native VISTA interest posting |
| `RETENCIÓN DE RENTA-ISR (10%)` | Native withholding-tax result linked to the gross interest event |
| `NOTA DE ABONO (REVERSION)` | Reversal/credit counterpart; original event link required |
| `NOTA DE CARGO (REVERSION)` | Reversal/debit counterpart; original event link required |

Classification uses stable transaction catalog identity plus a reviewed label
check. Any new or renamed source type blocks inspection. A movement's direction,
amount, date, account type, reversal marker, and running balance must agree with
the selected native command.

A reversed opening immediately paired with its reviewed debit correction does
not create a second native funding/withdrawal pair. Both source rows are kept in
the native event map as `SKIPPED_CORRECTION`; the one non-reversed opening is
the authoritative native funding event.

## Interest, accrual, and cutoff

- `AHO_HISTORICO_PLAZOS.TIPO_HISTORICO=1` is a posted interest event and must
  reconcile to its linked customer movement.
- Type `2` is an initial catch-up accrual increment. It is not migrated as a
  deposit or a second interest payment.
- `FNC_PROVISIONES` and `AHO_HISTORICO_DIARIO` are accrual/reconciliation
  evidence. Historical daily rows are not copied into an extension ledger.
- At cutoff, inspection selects the latest completed `CIERRE_DIARIO` date and
  requires exactly one `AHO_HISTORICO_DIARIO` row per account.
- `INTERESES_PROVISIONADOS` is retained as both the operational and accounting
  opening-accrual amount. It reconciles all active DPFs to an independent
  Actual/Actual calculation within one cent; `INT_PROV` is a daily increment
  and the other candidate balances are incomplete or stale.
- When no historical posting precedes the cutoff, native event replay must
  reproduce the source cutoff exactly at currency precision.
- When explicit historical postings precede the cutoff, the exact Arissto
  amount is retained in `credesal_savings_migration_account` as the migration
  opening snapshot. Fineract's independently derived amount is retained as a
  diagnostic and can differ by cents at the posting boundary. The engine must
  not manufacture a transaction or journal to force those two calculations to
  agree.

### Historical posted interest

Historical `CAPITALIZACION INTERES` amounts are ledger facts. Arissto's daily
calculation evidence can differ by a cent from the amount it actually posted;
therefore the migration must not silently replace the source transaction with a
fresh calculation or represent the difference as a deposit. The local fork
uses:

```text
POST /savingsaccounts/{vistaId}/transactions?command=explicitInterestPosting
```

with source date, amount, and canonical movement key as
`transactionReference`. It creates native transaction type `3`
(`INTEREST_POSTING`) and normal savings journals. The referenced manual posting
remains authoritative when later backdated events cause interest recalculation.
This command is historical-import behavior only: unposted and future interest
continues through the native Actual/Actual calculator and period schedule.

Retries reuse both the stable source reference and an account-scoped Fineract
idempotency key. An existing reference is recoverable only when account, native
type, date, and amount all agree; any collision blocks the account.

## ISR

Historical tax outcome is event-specific. `AFECTA_ISR` means a product can be
taxed; it does not prove that every event is taxable. `APLICA_RENTA=1` is the
authoritative event gate. Only then must `MONTO_RENTA` equal 10% after source
cent rounding and `ID_MOV_AHO_RENTA` resolve through
`AHO_MOVIMIENTOS.ID_MOVIMIENTO_AHORRO` to the matching ISR debit. A non-zero
link on an untaxed row is ignored; 273 such rows exist with zero tax.

Historical DPF interest is transferred gross to the linked VISTA and the tax
is a separate debit on that VISTA. Standard Fineract withholding is generated
only from an ordinary savings account's own interest posting; the DPF transfer
job moves the gross DPF posting and cannot create this event-specific linked-
account tax. The local Fineract fork therefore implements
`command=explicitWithholdTax`, which creates native transaction type `18`
(`WITHHOLD_TAX`) on the linked VISTA with native tax-component detail, source
date/gross/tax validation, balance and journal processing, reversal support,
and a durable `transactionReference`. The VISTA product and account retain an
ISR tax-group link while `withHoldTax=false`: the tax group supplies the native
10% calculation and accounting destination, while the explicit command—not
ordinary VISTA interest posting—decides which historical events are taxed.
Future tax eligibility is a separate business-policy decision and must not be
inferred from historical event outcomes.

The writer uses:

```text
POST /savingsaccounts/{linkedVistaId}/transactions?command=explicitWithholdTax
```

with `transactionDate`, source `MONTO_RENTA` as `transactionAmount`, source
`MONTO_INTERES` as `grossInterestAmount`, and a stable source-event key as
`transactionReference`. Retries must also reuse the same Fineract idempotency
key. A reused reference is accepted only when the existing non-reversed type-18
transaction has the same account, date, and amount; otherwise it is a collision.

The controlled local acceptance run on 2026-08-26 created native type-18
transaction `483` for 10.00 on a 100.00 gross event. Both a same-idempotency-key
retry and a different-key retry using the same `transactionReference` recovered
that transaction. Its native tax detail referenced the 10% ISR component; its
journals credited ISR payable `2230000100` and debited the linked savings control
account. Native reversal preserved the tax-component detail and produced the
opposite journal pair. These IDs are local acceptance evidence, not production
mapping identifiers.

## Fixed-deposit lifecycle replay

Historical DPF interest is posted as native type `3` on the term account, then
transferred gross through the linked-account transfer service. Event-level ISR
is posted separately as native type `18` on the linked VISTA. Each command uses
an account-scoped idempotency key and a stable source reference.

Historical renewals use the targeted fixed-deposit maturity command with
principal-only reinvestment and `postMaturityInterest=false`. This prevents a
second native full-term interest posting after the authoritative Arissto events
have already been replayed. The new term preserves rate, linked VISTA,
transfer-interest behavior, and a unique native external identity; the
predecessor closes.

Historical cancellation uses normal fixed-deposit close behavior with the same
optional `postMaturityInterest=false` contract. The default is `true`, so
ordinary Fineract closures are unchanged. The migration path withdraws the
remaining source principal without reversing or replacing an exact source
interest posting.

The controlled matrix passed on 2026-08-28:

- four monthly terms renewed and matured with four 202.00 gross transfers and
  four 20.20 ISR debits; linked VISTA net 727.20;
- one cancellation retained 127.40 source interest and 12.74 ISR, closed the
  DPF at zero, and left 114.66 in VISTA;
- the joint active DPF preserved two source owners, selected one native owner,
  transferred 126.25, and retained its 15.78 source cutoff snapshot; and
- an at-maturity active DPF reproduced its 473.21 cutoff exactly.

Every native journal transaction in those proofs balances.

## Native write policy

- Products, accounts, deposits, withdrawals, reversals, closures, transfers,
  calculated or explicit historical interest posting, tax, and accounting use
  supported Fineract APIs/jobs/domain commands.
- Controlled SQL is limited to the versioned Credesal migration-support and
  product/cycle crosswalk tables created by migrations 0288, 0290, and 0300.
- The engine never updates derived balances, native transactions, or journals
  directly.
- Every source event is source-hash checked immediately before its command.

## Quarantine and blockers

Block an account when any of these applies:

- missing/duplicate client, product, account, owner, or linked destination;
- joint account has zero or multiple authoritative owners matching the
  account-master socio pair;
- unsupported source state, movement type, reversal, date, or negative amount;
- source running balance does not reconcile chronologically;
- posted interest/history/movement/ISR links disagree;
- cutoff accrual source is absent or ambiguous;
- backdating or closed-period rules reject the history;
- native target contains an identity collision or unexplained transaction; or
- accounting entries differ from the approved mapping.

Quarantine is account-atomic. No later event for that account may run.

## Reconciliation contract

For each account compare:

- identity, client, product, deposit type, status, dates, term, rate, and linked
  savings destination;
- source movement/event map completeness and native transaction type/date/
  amount/reversal;
- source final balance versus native running/account balance;
- gross interest, tax, net customer effect, current accrued interest, and next
  posting date; and
- native journal debits/credits against the reviewed source GL roles.

Institution totals must reconcile without double-counting the joint DPF. Owner
reporting may show the account for both people but must identify that it is one
financial account.
