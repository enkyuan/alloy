# Contributing

## Local checks

Run focused tests while developing, then the clean local Kaji checkpoint:

```bash
uv run --project kaji/sdk python kaji/scripts/check_beta_contract.py
uv run --project kaji/sdk python kaji/scripts/sync_beta_contracts.py --check
uv run --project kaji/sdk python kaji/scripts/check_sdk_parity.py
uv run --project kaji/sdk pytest -m "not integration"
cd kaji/ts && bun run build && bun run test
```

Do not use live keys in ordinary pull requests. Provider, publication,
signature, provenance, soak, and calibrated benchmark actions belong to the
protected release operator workflow.

## Compatibility boundaries

`kaji/contracts/feature-tiers-v1.json` is the authority for stable,
experimental, and deprecated features and exports. Stable contract changes
need cross-SDK fixtures and both consumers in the same change. Experimental
work must remain explicitly quarantined. Deprecated compatibility paths need a
documented replacement and removal horizon.

Keep prompts, tool arguments/results, metadata, credentials, and raw provider
causes out of fixtures, logs, issues, and review descriptions.
