# Loan sync change tracking

Loan-sync fixes are recorded in the local per-cycle SQLite state database. The
tracker is an operational index of PRs, decisions, and affected loan IDs; it
does not replace plans, runs, reconciliation output, or the PR itself.

## Tables

- `loan_sync_changes`: one row per PR, with a brief description and status.
- `loan_sync_change_loans`: one row per source loan affected by a PR, including
  the optional Fineract loan ID and a short result.
- `loan_sync_change_decisions`: decisions and rationale associated with a PR.

The tables are created automatically when `arissto_sync.state.State` opens an
existing or new cycle database.

## How to register a change

1. Add a row to `loan_sync_changes` when the PR is opened. Use the PR number or
   URL as `pr_reference`, not a branch name.
2. Add each affected Arissto loan to `loan_sync_change_loans`. A loan appears
   once per PR but may appear again under a later PR.
3. Add significant policy or implementation choices to
   `loan_sync_change_decisions`, including the reason for the decision.
4. When the PR is resolved, update its status to `merged`, `superseded`, or
   `rejected` and set `closed_at`.

Keep entries brief and non-sensitive. Do not store borrower names, account
numbers, credentials, transaction payloads, or sampled source rows. Stable loan
IDs and links to existing plan, run, and reconciliation evidence are enough.
