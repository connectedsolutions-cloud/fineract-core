# Collateral asset details

This extension keeps Fineract's native collateral chain as the system of record:

```text
m_collateral_management
  -> m_client_collateral_management
       -> m_client_collateral_asset
            -> m_client_collateral_vehicle (0..1)
            -> m_client_collateral_property (0..1)
            -> m_collateral_valuation (0..n)
            -> m_collateral_registration (0..n)
       -> m_loan_collateral_management
            -> selected m_collateral_valuation + immutable value snapshot
```

The schema is introduced by tenant migration `0341_add_collateral_details.xml`;
`0346_allow_collateral_valuation_without_date.xml` makes appraisal dates optional.

## Lifecycle rules

- A client-collateral row has at most one asset-detail row.
- An asset type is `VEHICLE`, `PROPERTY`, or `OTHER`. Vehicle and property subtype rows are mutually exclusive.
- Appraisals are `DRAFT`, `FINAL`, or `SUPERSEDED`. Only drafts may be edited in place.
- An appraisal requires a total value, but its appraisal date is optional. Zero
  and negative historical values are accepted and preserved without blocking a loan.
- A final appraisal is corrected by the `supersede` command, which creates a linked final reappraisal and preserves the prior record.
- Loan collateral may select a final appraisal. Fineract stores `valuation_id`, `pledged_value`, `eligible_value`, and `valuation_date` on the pledge so later reappraisals cannot change a historical approval or disbursement decision.
- A new loan pledge without `valuationId` continues to use collateral-product base price and eligibility percentage. When an older client updates an existing valued pledge without resending `valuationId`, Fineract preserves the stored snapshot and scales it only if quantity changes.
- A pledge may cover only part of the loan principal; collateral value is not a minimum-loan-amount constraint.
- Final appraisals and registration history do not have delete endpoints.

Migration `0341` also creates the administrator-managed code groups `Collateral vehicle type`, `Collateral asset quality`, and `Collateral property type`. Vehicle/property requests that supply code-value IDs must use values from the corresponding group; the migration deliberately does not invent business labels.

## Permissions

- `READ_COLLATERAL_DETAILS` reads assets, appraisals, and registrations.
- `MANAGE_COLLATERAL_DETAILS` includes read access and creates or changes the whole collateral-detail family.
- Attaching or releasing collateral remains protected by the existing loan permissions.

## API

All routes are below `/v1/clients/{clientId}/collaterals/{clientCollateralId}`:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/asset` | Read the asset and its vehicle/property subtype |
| `PUT` | `/asset` | Create or replace the asset details |
| `GET` | `/valuations` | List appraisal history, newest first |
| `POST` | `/valuations` | Add a draft or final appraisal |
| `GET` | `/valuations/{valuationId}` | Read one appraisal |
| `PUT` | `/valuations/{valuationId}` | Edit a draft appraisal |
| `POST` | `/valuations/{valuationId}?command=supersede` | Replace a final appraisal with a linked final reappraisal |
| `GET` | `/registrations` | List registration history |
| `POST` | `/registrations` | Add a registration record |
| `GET` | `/registrations/{registrationId}` | Read one registration record |
| `PUT` | `/registrations/{registrationId}` | Update a registration record |

`POST /v1/clients/{clientId}/collaterals` remains backward compatible and additionally accepts optional `asset` and `initialValuation` objects. When supplied, the native client collateral, asset subtype, and initial appraisal are created in one transaction.

A loan `collateral` item accepts:

```json
{
  "clientCollateralId": 10,
  "quantity": 1,
  "valuationId": 91
}
```

`valuationId` is optional. When present, it must identify a final appraisal belonging to that client collateral and its currency must match the loan currency.

## Frontend boundary

The existing Mifos client and loan collateral screens currently submit only collateral-product identity and quantity and calculate display values from product base price. They do not yet display asset details, appraisal history, registration history, or allow appraisal selection. This delivery is intentionally Fineract-only; a later Mifos slice must add those flows before staff can operate the feature through the UI.
