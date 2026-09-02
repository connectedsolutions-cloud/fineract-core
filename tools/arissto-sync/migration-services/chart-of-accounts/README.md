# Credesal chart-of-accounts tenant bootstrap

## Status

- Service registry: intentionally not registered
- CLI block: none
- Source: approved local Fineract `default` tenant snapshot
- Fineract tenant migration: implemented in Liquibase `0310`

The Credesal chart of accounts is tenant configuration, not Arissto business
data. It is therefore a one-time, versioned Fineract bootstrap rather than an
`inspect -> plan -> apply` synchronization service.

Migration
[`0310_bootstrap_credesal_chart_of_accounts.xml`](../../../../fineract-provider/src/main/resources/db/changelog/tenant/parts/0310_bootstrap_credesal_chart_of_accounts.xml)
loads the canonical CSV under `parts/data/0310/` during normal tenant
Liquibase startup. The snapshot contains 2,523 accounts and uses `gl_code` and
`parent_gl_code` as stable identity; database IDs and hierarchy paths are
resolved inside each destination tenant.

## Why Liquibase instead of the API

- Every new tenant receives the exact reviewed snapshot automatically with its
  schema version.
- The standard GL API creates one account per request. A full clone would need
  2,523 ordered writes plus separate planning and reconciliation.
- Fineract's bulk workbook import is asynchronous and skips existing GL codes;
  it is useful for operator uploads but is a weaker source of truth for tenant
  bootstrap and drift detection.
- The migration is atomic and keeps IDs of the 19 accounts already seeded by
  migrations `0295` and `0297`, so existing product references remain valid.

The GL read API returned HTTP 500 for both collection and individual-account
requests during the 2026-08-30 audit. That defect reinforces the bootstrap
choice but is not required for the migration to work.

## Safety and convergence policy

The migration:

1. validates the snapshot row count and parent hierarchy;
2. no-ops when a tenant already matches the approved COA;
3. fills or normalizes an empty/bootstrap-only tenant while preserving existing
   account IDs;
4. refuses to change a divergent tenant after clients, loans, savings accounts,
   or journal entries exist; and
5. checks exact metadata and parent reconciliation before completing.

Do not paste or maintain a second ad-hoc SQL copy of the COA. Deliberate future
COA changes should use a new versioned migration rather than modifying the
released `0310` snapshot.
