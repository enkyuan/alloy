"""Read agentkit package metadata."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _version


def get_version() -> str:
    try:
        return _version("agentkit")
    except PackageNotFoundError:
        return "0.0.0"
