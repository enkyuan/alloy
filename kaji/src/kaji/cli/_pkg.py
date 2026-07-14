"""Read kaji package metadata."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _version


TYPESCRIPT_SDK_CLI = "bun --no-install -e 'import(\"@kaji/sdk/cli\")' --"


def get_version() -> str:
    try:
        return _version("kaji-sdk")
    except PackageNotFoundError:
        return "0.0.0"
