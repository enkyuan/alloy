"""Integration registry: discoverable, copyable integration manifests.

The registry under ``kaji/integrations/registry/`` is shadcn-style: each
entry ships a manifest + one or more source files. ``kaji add <name>``
copies the source into the user's project; the user owns the copies and
edits them freely. The SDK exposes the same modules for callers who want
to use them directly without copying.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from kaji.integrations.validation import (
    IndexValidationError,
    IntegrationValidationError as IntegrationValidationError,
    ManifestError,
    ManifestValidationError,
    json_pointer,
    validate_index_document,
    validate_manifest_document,
)
from kaji.runtime.tools.registry import ToolRisk


# Errors are deliberately specific so the CLI can produce useful messages.


class IntegrationNotFound(KeyError):
    """Raised when a name isn't in the registry index."""


@dataclass(frozen=True)
class ManifestTool:
    name: str
    description: str
    parameters: Mapping[str, object]
    risk: ToolRisk
    parallel_safe: bool
    timeout_ms: int | None = None


@dataclass(frozen=True, slots=True)
class ManifestAuth:
    kind: Literal["none", "env", "oauth"]
    env: str | None = None
    optional: bool = False
    docs: str | None = None
    provider: Literal["google"] | None = None
    client_id_env: str | None = None
    client_secret_env: str | None = None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegistryEntry:
    manifest: str
    stability: str
    runtimes: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    """Parsed integration manifest. Read-only; load via :func:`load_manifest`."""

    name: str
    version: str
    namespace: str
    description: str
    auth: ManifestAuth
    files: tuple[str, ...]
    tools: tuple[ManifestTool, ...]
    extras: tuple[str, ...]
    peer_deps: Mapping[str, str]
    stability: str
    runtimes: tuple[str, ...]
    # Absolute path to the manifest file on disk, so callers can resolve
    # ``files`` entries relative to it.
    path: Path

    @property
    def root(self) -> Path:
        """Directory holding the manifest and its `files`."""
        return self.path.parent


def _registry_root() -> Path:
    """Return the on-disk path of the bundled registry directory.

    Resolved relative to this module file. The SDK is installed as a normal
    filesystem package (no zipimport), so this is safe.
    """
    return Path(__file__).resolve().parent / "registry"


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _read_index() -> dict[str, RegistryEntry]:
    index_path = _registry_root() / "index.json"
    if not index_path.exists():
        raise IndexValidationError("/", "Registry index is missing")
    try:
        data = json.loads(index_path.read_text())
    except json.JSONDecodeError as e:
        raise IndexValidationError("/", "Registry index is not valid JSON") from e
    except (OSError, UnicodeError) as e:
        raise IndexValidationError("/", "Registry index is unreadable") from e
    validate_index_document(data)
    integrations = cast(dict[str, dict[str, Any]], data["integrations"])
    return {
        name: RegistryEntry(
            manifest=entry["manifest"],
            stability=entry["stability"],
            runtimes=tuple(entry["runtimes"]),
        )
        for name, entry in integrations.items()
    }


def list_integrations() -> list[str]:
    """Return the names of all integrations available in the registry."""
    return sorted(_read_index().keys())


def _contained_path(root: Path, relative: str, *, path: str, index: bool) -> Path:
    try:
        resolved_root = root.resolve()
        resolved = (root / relative).resolve()
    except (OSError, RuntimeError):
        message = f"Integration path cannot be resolved safely at {path}"
        if index:
            raise IndexValidationError(path, message) from None
        raise ManifestValidationError(path, message) from None
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        message = f"Integration path resolves outside its allowed root at {path}"
        if index:
            raise IndexValidationError(path, message) from None
        raise ManifestValidationError(path, message) from None
    return resolved


def load_manifest(name: str) -> Manifest:
    """Load the manifest for an integration by name.

    Raises ``IntegrationNotFound`` if the name isn't in the index, or
    ``ManifestError`` if the manifest file itself is malformed.
    """
    index = _read_index()
    entry = index.get(name)
    if entry is None:
        raise IntegrationNotFound(f"Unknown integration: {name!r}")
    manifest_pointer = json_pointer(("integrations", name, "manifest"))
    manifest_path = _contained_path(
        _registry_root(), entry.manifest, path=manifest_pointer, index=True
    )
    if not manifest_path.is_file():
        raise IndexValidationError(
            manifest_pointer, "Integration index references a missing manifest"
        )
    try:
        data = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        raise ManifestValidationError(
            "/", "Integration manifest is not valid JSON"
        ) from e
    except (OSError, UnicodeError) as e:
        raise ManifestValidationError("/", "Integration manifest is unreadable") from e
    validate_manifest_document(data)
    if data["name"] != name:
        raise IndexValidationError(
            "/name", "Integration index key does not match manifest name"
        )
    manifest_root = manifest_path.parent
    for file_index, relative in enumerate(data["files"]):
        pointer = f"/files/{file_index}"
        source = _contained_path(manifest_root, relative, path=pointer, index=False)
        if not source.is_file():
            raise ManifestValidationError(
                pointer, "Integration manifest references a missing file"
            )
    auth = data["auth"]
    return Manifest(
        name=data["name"],
        version=data["version"],
        namespace=data["namespace"],
        description=data["description"],
        auth=ManifestAuth(
            kind=auth["kind"],
            env=auth.get("env"),
            optional=auth.get("optional", False),
            docs=auth.get("docs"),
            provider=auth.get("provider"),
            client_id_env=auth.get("clientIdEnv"),
            client_secret_env=auth.get("clientSecretEnv"),
            scopes=tuple(auth.get("scopes") or ()),
        ),
        files=tuple(data["files"]),
        tools=tuple(
            ManifestTool(
                name=t["name"],
                description=t["description"],
                parameters=cast(Mapping[str, object], _freeze_json(t["parameters"])),
                risk=t["risk"],
                parallel_safe=t["parallel_safe"],
                timeout_ms=t.get("timeout_ms"),
            )
            for t in data["tools"]
        ),
        extras=tuple(data.get("extras") or ()),
        peer_deps=dict(data.get("peerDeps") or {}),
        stability=entry.stability,
        runtimes=entry.runtimes,
        path=manifest_path,
    )


def install_integration(
    name: str,
    dest: Path,
    *,
    force: bool = False,
    allow_experimental: bool = False,
) -> list[Path]:
    """Copy an integration's files into ``dest``.

    Returns the copied manifest paths. A current bundle is a safe no-op;
    ``force`` replaces only an unmodified same-provider outdated bundle.
    """
    manifest = load_manifest(name)
    if manifest.stability == "experimental" and not allow_experimental:
        raise ManifestError(
            f"Integration {name!r} is experimental; pass allow_experimental=True"
        )
    from kaji.integrations.copy import install_integration_bundle

    return list(
        install_integration_bundle(
            manifest, dest, runtime="python", force=force
        ).written
    )


# Internal adapters intentionally stay out of the top-level ``kaji`` API.
from kaji.integrations.errors import (  # noqa: E402
    IntegrationAuthError as _IntegrationAuthError,
    IntegrationAuthRequiredError as _IntegrationAuthRequiredError,
    IntegrationExecutionError as _IntegrationExecutionError,
    IntegrationPolicyError as _IntegrationPolicyError,
    IntegrationRateLimitedError as _IntegrationRateLimitedError,
    IntegrationTransientReadError as _IntegrationTransientReadError,
    IntegrationTransportError as _IntegrationTransportError,
)
from kaji.integrations.fixed_origin import (  # noqa: E402
    FixedOriginClient as _FixedOriginClient,
    IntegrationResponse as _IntegrationResponse,
)

_FIXED_ORIGIN_INTERNALS = (
    _IntegrationAuthError,
    _IntegrationAuthRequiredError,
    _IntegrationExecutionError,
    _IntegrationPolicyError,
    _IntegrationRateLimitedError,
    _IntegrationTransientReadError,
    _IntegrationTransportError,
    _FixedOriginClient,
    _IntegrationResponse,
)
