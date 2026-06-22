"""Integration registry: discoverable, copyable integration manifests.

The registry under ``agentkit/integrations/registry/`` is shadcn-style: each
entry ships a manifest + one or more source files. ``agentkit add <name>``
copies the source into the user's project; the user owns the copies and
edits them freely. The SDK exposes the same modules for callers who want
to use them directly without copying.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


# Errors are deliberately specific so the CLI can produce useful messages.


class IntegrationNotFound(KeyError):
    """Raised when a name isn't in the registry index."""


class ManifestError(ValueError):
    """Raised when a manifest is malformed."""


@dataclass(frozen=True)
class ManifestTool:
    name: str
    description: str
    risk: Optional[str] = None


@dataclass(frozen=True)
class ManifestAuth:
    kind: str  # "env" | "oauth" | "none"
    env: Optional[str] = None
    docs: Optional[str] = None
    scopes: tuple[str, ...] = ()


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


def _read_index() -> dict[str, str]:
    index_path = _registry_root() / "index.json"
    if not index_path.exists():
        raise ManifestError(f"Registry index missing at {index_path}")
    try:
        data = json.loads(index_path.read_text())
    except json.JSONDecodeError as e:
        raise ManifestError(f"Registry index is not valid JSON: {e}") from e
    integrations = data.get("integrations")
    if not isinstance(integrations, dict):
        raise ManifestError("Registry index missing 'integrations' object.")
    return integrations


def list_integrations() -> list[str]:
    """Return the names of all integrations available in the registry."""
    return sorted(_read_index().keys())


def _validate_manifest(data: Any, path: Path) -> None:
    """Cheap structural validation. We don't pull in jsonschema; the
    schema.json file is the canonical reference and human-readable check."""
    if not isinstance(data, dict):
        raise ManifestError(f"{path}: manifest must be a JSON object.")
    required = {"name", "version", "namespace", "description", "auth", "files", "tools"}
    missing = required - data.keys()
    if missing:
        raise ManifestError(f"{path}: manifest missing keys: {sorted(missing)}")
    if not isinstance(data["files"], list) or not data["files"]:
        raise ManifestError(f"{path}: 'files' must be a non-empty list.")
    if not isinstance(data["tools"], list) or not data["tools"]:
        raise ManifestError(f"{path}: 'tools' must be a non-empty list.")
    auth = data["auth"]
    if not isinstance(auth, dict) or "kind" not in auth:
        raise ManifestError(f"{path}: 'auth.kind' is required.")
    if auth["kind"] not in ("env", "oauth", "none"):
        raise ManifestError(
            f"{path}: auth.kind must be one of env|oauth|none, got {auth['kind']!r}."
        )
    if auth["kind"] == "env" and not auth.get("env"):
        raise ManifestError(f"{path}: auth.kind=='env' requires 'auth.env'.")


def load_manifest(name: str) -> Manifest:
    """Load the manifest for an integration by name.

    Raises ``IntegrationNotFound`` if the name isn't in the index, or
    ``ManifestError`` if the manifest file itself is malformed.
    """
    index = _read_index()
    rel = index.get(name)
    if rel is None:
        raise IntegrationNotFound(f"Unknown integration: {name!r}")
    manifest_path = _registry_root() / rel
    if not manifest_path.exists():
        raise ManifestError(
            f"Integration {name!r} index points at {manifest_path} which does not exist."
        )
    try:
        data = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        raise ManifestError(f"{manifest_path}: invalid JSON: {e}") from e
    _validate_manifest(data, manifest_path)
    auth = data["auth"]
    return Manifest(
        name=data["name"],
        version=data["version"],
        namespace=data["namespace"],
        description=data["description"],
        auth=ManifestAuth(
            kind=auth["kind"],
            env=auth.get("env"),
            docs=auth.get("docs"),
            scopes=tuple(auth.get("scopes") or ()),
        ),
        files=tuple(data["files"]),
        tools=tuple(
            ManifestTool(
                name=t["name"],
                description=t["description"],
                risk=t.get("risk"),
            )
            for t in data["tools"]
        ),
        extras=tuple(data.get("extras") or ()),
        path=manifest_path,
    )


def install_integration(
    name: str,
    dest: Path,
    *,
    force: bool = False,
) -> list[Path]:
    """Copy an integration's files into ``dest``.

    Returns the list of paths written. Skips (without overwriting) any file
    already at the destination unless ``force=True``. Raises if the file
    exists and ``force`` is false; the caller (typically the CLI) is
    expected to surface a clear message.
    """
    manifest = load_manifest(name)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for rel in manifest.files:
        src = manifest.root / rel
        if not src.exists():
            raise ManifestError(f"Manifest {manifest.path} references missing file {src}")
        # Preserve any sub-directory structure declared in the manifest so an
        # integration can ship multiple files like ["foo.py", "lib/bar.py"].
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            raise FileExistsError(
                f"{target} already exists. Pass --force to overwrite."
            )
        shutil.copy2(src, target)
        written.append(target)
    return written
