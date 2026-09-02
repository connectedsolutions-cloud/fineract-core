# Client staff assignment contract

## Identity and cardinality

- Owner source key: `AFI_SOCIO.NUMERO_AFILIACION`.
- Owner target key: `m_client.external_id`.
- Employee source key: `AFI_SOCIO.ID_EMPRESA:<role person ID>`.
- Employee target key: `m_staff.external_id`.
- Cardinality: zero or one employee in each of three roles per party, represented by exactly one extension row per synchronized client. An all-null source assignment creates an all-null relationship row so future changes and reconciliation remain unambiguous.

## Field map

| Arissto | Preserved legacy column | Staff foreign key |
|---|---|---|
| `ID_PROMOTOR` | `arissto_promoter_person_id` | `promoter_staff_id` |
| `ID_EJECUTIVO_CUENTA` | `arissto_account_executive_person_id` | `account_executive_staff_id` |
| `ID_GESTOR_COBRO` | `arissto_collections_manager_person_id` | `collections_manager_staff_id` |

`AFI_SOCIO.ID_EMPRESA` is preserved as `arissto_company_id` and participates in every employee lookup.

## Native loan-officer boundary

Arissto has no direct equivalent of Fineract's generic loan-officer role. The
service therefore preserves promoter, account executive, and collections
manager independently and leaves native loan-officer assignment and
`m_staff.is_loan_officer` unchanged.

## Ownership and safety

All extension columns are legacy-owned. Each plan hashes the normalized relationship values and the contract. Apply re-reads the source row and revalidates the client and staff identities before writing through the datatable API.

Missing clients, missing staff, invalid source identities, or duplicated source keys stop or quarantine work without guessing. Reconciliation compares all legacy IDs and all resolved staff external IDs. The service does not write native loan-officer or collection-manager client columns and never deletes target records.
