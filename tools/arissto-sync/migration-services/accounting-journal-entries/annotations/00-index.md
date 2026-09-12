# Accounting cutoff implementation annotations

This directory is the ordered, durable implementation notebook for the
Fineract accounting cutoff and historical-journal migration boundary. It does
not replace the service contract, operating guide, or project-global
requirement.

## Ordered notes

1. [`10-implementation-map.md`](10-implementation-map.md) — code ownership,
   delivered slices, and remaining integration points.
2. [`20-decisions.md`](20-decisions.md) — accepted decisions and unresolved
   security/accounting choices.
3. [`30-validation-log.md`](30-validation-log.md) — commands and evidence from
   each validation cycle.
4. [`40-loan-cutoff-canary.md`](40-loan-cutoff-canary.md) — bounded local test
   procedure for the first disbursement/repayment slice.
5. [`50-loan-lifecycle-coverage.md`](50-loan-lifecycle-coverage.md) — command,
   permission, and accounting-bridge coverage for the remaining synced loan
   lifecycle.
6. [`60-sandbox-canary-results.md`](60-sandbox-canary-results.md) — seeded-client
   selection, execution, reconciliation, cutoff, and replay evidence from the
   first expanded loan-lifecycle canary.
7. [`70-fineract-native-table-map.md`](70-fineract-native-table-map.md) —
   authoritative native accounting tables, source-to-target field rules,
   report reconstruction, office handling, and implementation gaps.

Add future notes with the next available ten-based prefix. Keep current service
status and operator commands in the parent [`README.md`](../README.md), not in
these annotations.
