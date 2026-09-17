# Arissto sync agent rules

Read `README.md`, `migration-services/orchestration.md`, the selected workflow
definition, and `../../../docs/ARISSTO_SYNC_RUN_MODES.md` before planning or
operating a composed sync. Treat the executable CLI and those documents as the
runtime sources of truth.

## Accounting dates: never collapse these concepts

The operator-facing date is the inclusive Arissto `source_through_date` (`S`).
The internal Fineract accounting cutoff (`T`) is exclusive and is always
derived as `T = S + 1 calendar day` in `America/El_Salvador`.

- Use `--source-through-date` for normal inspect and plan operations.
- Treat `--cutoff-date` as an advanced option that directly supplies `T`, the
  first Fineract-owned accounting date.
- Always display both values before a financial plan is approved: **Arissto
  through** (`S`) and **Fineract starts** (`T`).
- Example: `S=2026-09-17` includes all eligible September 17 accounting;
  `T=2026-09-18` allows native Fineract accruals dated September 18.
- Never propose restricting import to the last closed source period. Use the
  latest closed period for `CNT_MAYOR` control and reconcile later open-period
  journals individually.
- Once `T` is active, resumed and full re-sync workflows inherit it. They do not
  advance it. Arissto GL dated on or after `T` is comparison evidence and must
  not be imported over Fineract-owned accounting.
- A source read cannot include records committed afterward. To promise a whole
  calendar day, run after Arissto day close or use an approved source watermark.

Do not modify Arissto. Select exactly one explicit Fineract target, distinguish
fresh/clean, resumed, and full re-sync modes, and surface the immutable plan for
review before a state-changing workflow action.
