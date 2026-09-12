# G9 statement-output acceptance environment

This environment closes the remaining difference between journal-derived
parity and the statements actually presented by Arissto. It is read-only on
both databases. It never resets a tenant, posts a journal, copies
`CNT_MAYOR`, or creates a synthetic opening.

## Fixed sandbox case

- target tenant: `sandbox` only;
- Arissto company: `001`;
- December period: `00053` (`2024-12-01` through `2024-12-31`);
- January continuity period: `00054`;
- agency mapping: `001 -> dimensions.office="1"`, `002 -> "2"`;
- control accounts: `314002%` and exact account `2220050501`.

Generated evidence is written under the ignored directory
`.arissto-sync/g9-evidence/`. Keep the accepted artifact hashes and exact
commands in `annotations/30-validation-log.md`; do not commit raw exports that
contain sensitive source detail.

## 1. Inspect readiness

PostgreSQL may be running while Fineract is stopped. The readiness command uses
only a read-only PostgreSQL transaction and verifies the frozen populated
sandbox counts, the three December closing journals, provenance-to-native line
coverage, agency dimensions, annual-close shape, zero imported opening flags,
and zero unprovenanced pre-cutoff lines.

```bash
cd fineract-core/tools/arissto-sync
.venv/bin/python -m arissto_sync.accounting_g9_acceptance readiness
```

Any count drift is a blocker. Restore and rerun the controlled migration cycle;
do not weaken the expected counts to fit an unknown tenant state.

## 2. Capture the two account traces

This command compares read-only source journal activity, December daily mayor,
December/January monthly mayor, and the corresponding imported native lines.
The named Tests B/C traces remain limited to their control-account families,
while the Test D continuity section covers every account used by an eligible
journal through December 31. It applies the frozen chart overrides and rebuilds
source materialized hierarchy nodes from native direct-account balances.

```bash
.venv/bin/python -m arissto_sync.accounting_g9_acceptance trace-controls
```

The output artifact is `control-account-trace.json`. Use it for Tests B, C,
and D. The trace is evidence for classification only: a mayor difference never
authorizes a synthetic journal.

## 3. Start Fineract and capture native statements

```bash
cd ../..
./scripts/local-fineract.sh start
cd tools/arissto-sync
./arissto-sync preflight --target local
.venv/bin/python -m arissto_sync.accounting_g9_acceptance capture-target
```

The capture contains all 12 December report/scope/closing-mode cases in
`target-statements.json`, including zero rows so selection differences cannot
disappear. Compare `case_content_sha256` between clean cycles; the whole-file
hash also includes the intentionally different capture timestamp.

## 4. Normalize the authoritative Arissto exports

The reviewed December 2024 exports are Excel workbooks split by agency. The
normalizer validates the workbook header instead of trusting the filename,
records every original SHA-256, maps `santiago` / `AGENCIA CENTRAL` to office
`1`, maps `USULUTAN` to office `2`, fills source-omitted zero rows from the
frozen presentation snapshot, and derives each consolidated case as office
`1 + 2`.

```bash
.venv/bin/python -m arissto_sync.accounting_g9_acceptance normalize-source \
  --input-dir /absolute/path/to/credesal-dec-2024-combined
```

The required direct statement cases are:

- `balance-comprobacion-pre-liquidacion` -> trial balance, `pre-closing`;
- `balance-comprobacion` -> trial balance, `post-closing`;
- `balance-gral` / `Estado de Situación Financiera` -> balance sheet,
  `post-closing`; and
- `estado de resultados-pre-liq` -> income statement, `pre-closing`.

The unqualified `estado de resultados` exports are supplemental annual-close
evidence. Fineract intentionally exposes the income statement before annual
closing, while the trial balance supplies both closing modes. A supplemental
workbook whose filename and internal agency disagree is retained as a warning
and is never substituted for a required case.

The generated `authoritative-arissto-statements.json` has the same case
identity as `target-statements.json`. For trial balance and balance sheet, the
export supplies the closing balance. For income statement it supplies both the
December monthly balance and the January-through-December accumulated balance.
The target capture therefore requests both date ranges for the income case.

```json
{
  "gl_code": "111001",
  "account_name": "SOURCE LABEL",
  "closing_balance": "0.00",
  "accumulated_balance": "0.00"
}
```

Each case includes independently calculated presentation controls for source
subtotals, grand totals, current-year result, and the accounting equation. The
comparator checks every supplied row, row order, measure, and control at
currency precision.

Do not call a legacy stored procedure an authoritative output merely because
it is available. The accounting owner must confirm that the export represents
the December 2024 statement used operationally.

## 5. Compare at currency precision

```bash
.venv/bin/python -m arissto_sync.accounting_g9_acceptance compare \
  --expected .arissto-sync/g9-evidence/authoritative-arissto-statements.json \
  --actual .arissto-sync/g9-evidence/target-statements.json
```

The comparison fails closed on missing cases, missing rows, label differences,
or any opening/debit/credit/closing difference at one cent. Named presentation
differences require durable accounting sign-off; an unexplained net-zero
offset does not pass.

## Test-list mapping

| G9 acceptance test | Harness evidence |
|---|---|
| A — December authoritative parity | `target-statements.json` plus `statement-comparison.json` |
| B — annual liquidation / `314002` | `control-account-trace.json`, pre/post-closing target cases, authoritative source row |
| C — `2220050501` two cents | daily/monthly/source-journal/native sections in `control-account-trace.json` |
| D — January continuity | All-account December `SALDO_FINAL`, January `SALDO_INICIAL`, and journal-derived native opening balances in the trace; no January UI export is required |
| E — cash flow | blocked; no approved source or target contract exists |

This populated-tenant run is diagnostic acceptance evidence. G11 must run the
same suite in both restored clean cycles and reproduce the accepted hashes.
