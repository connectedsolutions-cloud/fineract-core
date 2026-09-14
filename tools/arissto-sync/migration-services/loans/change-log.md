# Loan sync change tracking

Loan-sync fixes are recorded in the durable local SQLite database at
`.arissto-sync/change-tracker.sqlite3`. This database is deliberately separate
from per-cycle workflow state and survives fresh/clean runs and local retention.
The tracker is an index of commits or PRs, decisions, and affected loan IDs; it
does not replace plans, runs, reconciliation output, Git, or the PR itself.

Per-cycle databases under `.arissto-sync/cycles/<cycle-id>/state.sqlite3` contain
only disposable operational state: plans, workflow runs and steps, mappings,
reconciliation results, failures, and events. Fresh-cycle retention may delete
those databases after their cycle is superseded.

## Tables

- `loan_sync_changes`: one row per commit or PR, with a stable
  `change_reference`, optional `commit_sha` and `pr_reference`, description, and status.
- `loan_sync_change_loans`: one row per source loan affected by a change, including
  the optional Fineract loan ID and a short result.
- `loan_sync_change_decisions`: decisions and rationale associated with a change.

The tables are created automatically when `arissto_sync.change_tracker.ChangeTracker`
opens the durable database. Creating a replacement cycle migrates legacy tracker
rows from surviving per-cycle or shared state databases before retention runs.

## How to register a change

1. Add a row to `loan_sync_changes` for the implemented change. Use the full
   commit SHA as `change_reference` and `commit_sha`; add the PR number or URL in
   `pr_reference` when one exists. Do not use a branch name.
2. Add each affected Arissto loan to `loan_sync_change_loans`. A loan appears
   once per change but may appear again under a later change.
3. Add significant policy or implementation choices to
   `loan_sync_change_decisions`, including the reason for the decision.
4. When the PR is resolved, update its status to `merged`, `superseded`, or
   `rejected` and set `closed_at`.

Keep entries brief and non-sensitive. Do not store borrower names, account
numbers, credentials, transaction payloads, or sampled source rows. Stable loan
IDs and links to existing plan, run, and reconciliation evidence are enough.
