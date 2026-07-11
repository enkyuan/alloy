# Kaji beta contracts

These files define the behavior shared by the Python and TypeScript SDK beta.

- `beta-core-v1.json` pins public defaults and stability boundaries.
- `feature-tiers-v1.json` is the machine-readable stable/experimental surface.
- `events/` separates event drafts from sequenced stored events.
- `tools/` contains the tool-spec schema and shared validation fixtures.
- `errors/error-codes.json` is the normalized public failure vocabulary;
  `errors/provider-normalization.json` pins cross-SDK status classification.

Canonical files live here. Package copies are generated and checked by
`kaji/scripts/sync_beta_contracts.py`; do not edit package copies directly.
