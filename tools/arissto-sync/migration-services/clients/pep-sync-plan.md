# Client PEP implementation history

The original PEP implementation was proved locally as part of the broad
`clients` block on 2026-08-14. It has since been separated into the registered
`client-pep` service so ownership, plans, runs, retries, reconciliation, and
dependency order are explicit.

Current operator instructions and lifecycle status are maintained in:

- [`../client-pep/README.md`](../client-pep/README.md)
- [`../client-pep/contract.md`](../client-pep/contract.md)
- [`../registry.json`](../registry.json)

Historical acceptance evidence remains valid: 1,029 source parties reconciled,
with 3 true, 416 false, 610 unknown, and zero invalid values. The final
full-population replan classified all 1,029 clients as unchanged. No source keys
or customer values were recorded in documentation.

Do not use this historical file as an operating guide. In particular, PEP is
no longer owned by `config/clients.json` or the `clients` block.
