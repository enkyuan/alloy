"""Stdlib-only projection of canonical contracts for the TypeScript package."""

from __future__ import annotations

import json
from pathlib import Path


TYPESCRIPT_PROJECTED_CONTRACTS = {
    "events/v1/cases/valid.json",
    "events/v1/schema/new.json",
    "events/v1/schema/stored.json",
    "tiers/v1/features.json",
}


def typescript_contract_projection(relative: Path, source: Path) -> bytes:
    """Return the TypeScript package view of a canonical contract."""

    document = json.loads(source.read_text())
    del relative
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()
