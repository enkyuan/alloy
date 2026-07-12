"""Rollback-safe copied integration bundle provenance and publication."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, distribution, version
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from kaji.integrations.validation import ManifestError

if TYPE_CHECKING:
    from kaji.integrations import Manifest


BundleState = Literal["current", "absent", "outdated", "modified", "demoted"]
_LEGACY_NULL_ABI = frozenset({"fs", "http", "sqlite", "web"})
_SIDECAR = ".kaji-integration-provenance.json"
_LICENSE_IDENTIFIER = "PolyForm-Noncommercial-1.0.0"
_LICENSE_URL = "https://polyformproject.org/licenses/noncommercial/1.0.0"


@dataclass(frozen=True, slots=True)
class BundleStatus:
    state: BundleState
    reason_code: str
    destination: Path
    written: tuple[Path, ...] = ()
    _observed: str = ""

    @property
    def exit_code(self) -> int:
        return {
            "current": 0,
            "absent": 3,
            "outdated": 4,
            "modified": 5,
            "demoted": 6,
        }[self.state]


class BundleTransitionError(FileExistsError):
    def __init__(self, status: BundleStatus) -> None:
        self.status = status
        super().__init__(f"Integration bundle is {status.state}: {status.reason_code}")


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _contracts_root() -> Path:
    return Path(__file__).resolve().parent.parent / "contracts" / "integrations"


@lru_cache(maxsize=1)
def _provenance_validator() -> Draft202012Validator:
    schema = json.loads(
        (_contracts_root() / "copy-provenance-v1.schema.json").read_text()
    )
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _package_version() -> str:
    try:
        return version("kaji")
    except PackageNotFoundError:
        return "0.0.0"


def _package_license() -> Path:
    checkout = Path(__file__).resolve().parents[2] / "LICENSE"
    if checkout.is_file():
        return checkout
    try:
        installed = distribution("kaji")
    except PackageNotFoundError:
        raise ManifestError("Installed package license is unavailable") from None
    for relative in installed.files or ():
        if relative.name == "LICENSE":
            candidate = Path(installed.locate_file(relative))
            if candidate.is_file():
                return candidate
    raise ManifestError("Installed package license is unavailable")


def _abi_digest(name: str) -> str | None:
    index = json.loads((_contracts_root() / "abi-index-v1.json").read_text())
    relative = index["integrations"].get(name)
    if relative is None:
        if name in _LEGACY_NULL_ABI:
            return None
        raise ManifestError(f"Integration {name!r} has no canonical ABI contract")
    path = (_contracts_root() / relative).resolve()
    try:
        path.relative_to(_contracts_root().resolve())
    except ValueError:
        raise ManifestError("Canonical ABI path is unsafe") from None
    if not path.is_file():
        raise ManifestError("Canonical ABI contract is missing")
    return _digest(path.read_bytes())


def _entry(manifest: Manifest) -> dict[str, object]:
    return {
        "manifest": str(manifest.path.relative_to(manifest.root.parent)).replace(
            os.sep, "/"
        ),
        "runtimes": list(manifest.runtimes),
        "stability": manifest.stability,
    }


def _safe_source(manifest: Manifest, relative: str) -> Path:
    source = manifest.root / relative
    try:
        if source.is_symlink():
            raise ManifestError("Integration source assets cannot be symlinks")
        resolved = source.resolve(strict=True)
        resolved.relative_to(manifest.root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        raise ManifestError("Integration source asset is unsafe") from None
    if not resolved.is_file():
        raise ManifestError("Integration source asset is missing")
    return resolved


def _expected_provenance(manifest: Manifest, runtime: str) -> dict[str, object]:
    if runtime not in manifest.runtimes:
        raise ManifestError(f"Integration {manifest.name!r} does not support {runtime}")
    sources = {
        relative: _safe_source(manifest, relative) for relative in manifest.files
    }
    license_path = sources.get("LICENSE", _package_license())
    provenance = {
        "schemaVersion": "1.0.0",
        "integration": manifest.name,
        "sdkVersion": _package_version(),
        "runtime": runtime,
        "stability": manifest.stability,
        "registryEntrySha256": _digest(_canonical_bytes(_entry(manifest))),
        "abiSha256": _abi_digest(manifest.name),
        "manifestSha256": _digest(manifest.path.read_bytes()),
        "license": {
            "identifier": _LICENSE_IDENTIFIER,
            "url": _LICENSE_URL,
            "sha256": _digest(license_path.read_bytes()),
        },
        "files": {
            relative: _digest(source.read_bytes())
            for relative, source in sorted(sources.items())
        },
    }
    _provenance_validator().validate(provenance)
    return provenance


def _read_provenance(path: Path) -> tuple[dict[str, object] | None, str]:
    if not path.is_file() or path.is_symlink():
        return None, "missing_provenance"
    try:
        if path.stat().st_size > 64 * 1024:
            return None, "invalid_provenance"
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None, "invalid_provenance"
        _provenance_validator().validate(value)
        return value, ""
    except (OSError, UnicodeError, ValueError, ValidationError):
        return None, "invalid_provenance"


def _observed_token(provenance: dict[str, object], destination: Path) -> str:
    files = provenance["files"]
    assert isinstance(files, dict)
    snapshot: dict[str, str] = {}
    for relative in sorted(files):
        path = destination / relative
        if not path.is_file() or path.is_symlink():
            return "changed"
        snapshot[relative] = _digest(path.read_bytes())
    return _digest(_canonical_bytes({"provenance": provenance, "files": snapshot}))


def classify_integration_bundle(
    manifest: Manifest,
    destination: Path,
    *,
    runtime: Literal["python", "typescript"],
) -> BundleStatus:
    destination = destination.resolve()
    if not os.path.lexists(destination):
        return BundleStatus("absent", "not_installed", destination, _observed="absent")
    if destination.is_symlink() or not destination.is_dir():
        return BundleStatus(
            "modified", "unsafe_destination", destination, _observed="unsafe"
        )
    try:
        if not any(destination.iterdir()):
            return BundleStatus(
                "absent", "not_installed", destination, _observed="empty"
            )
    except OSError:
        return BundleStatus(
            "modified", "unsafe_destination", destination, _observed="unreadable"
        )

    provenance, failure = _read_provenance(destination / _SIDECAR)
    if provenance is None:
        return BundleStatus("modified", failure, destination, _observed=failure)
    if provenance["integration"] != manifest.name:
        return BundleStatus(
            "modified", "cross_provider", destination, _observed="cross_provider"
        )
    if provenance["runtime"] != runtime:
        return BundleStatus(
            "modified", "runtime_mismatch", destination, _observed="runtime_mismatch"
        )

    tracked = provenance["files"]
    assert isinstance(tracked, dict)
    actual: set[str] = set()
    try:
        for path in destination.rglob("*"):
            if path.is_symlink():
                return BundleStatus(
                    "modified", "local_changes", destination, _observed="symlink"
                )
            if path.is_file() and path.name != _SIDECAR:
                actual.add(path.relative_to(destination).as_posix())
        if actual != set(tracked):
            return BundleStatus(
                "modified", "local_changes", destination, _observed="files"
            )
        observed = _observed_token(provenance, destination)
    except (OSError, RuntimeError):
        return BundleStatus(
            "modified", "local_changes", destination, _observed="unreadable"
        )
    if observed == "changed":
        return BundleStatus(
            "modified", "local_changes", destination, _observed=observed
        )
    for relative, expected in tracked.items():
        if _digest((destination / relative).read_bytes()) != expected:
            return BundleStatus(
                "modified", "local_changes", destination, _observed=observed
            )

    expected = _expected_provenance(manifest, runtime)
    if provenance["stability"] == "beta" and manifest.stability == "experimental":
        return BundleStatus(
            "demoted", "stability_demoted", destination, _observed=observed
        )
    if provenance == expected:
        return BundleStatus("current", "up_to_date", destination, _observed=observed)
    return BundleStatus("outdated", "upstream_changed", destination, _observed=observed)


def _safe_parent(destination: Path) -> Path:
    parent = destination.parent
    probe = parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if probe.is_symlink():
        raise ManifestError("Destination parent cannot be a symlink")
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink() or not parent.is_dir():
        raise ManifestError("Destination parent is unsafe")
    return parent


def install_integration_bundle(
    manifest: Manifest,
    destination: Path,
    *,
    runtime: Literal["python", "typescript"],
    force: bool = False,
) -> BundleStatus:
    destination = destination.resolve()
    initial = classify_integration_bundle(manifest, destination, runtime=runtime)
    if initial.state == "current":
        return initial
    if initial.state == "outdated" and not force:
        raise BundleTransitionError(initial)
    if initial.state in {"modified", "demoted"}:
        raise BundleTransitionError(initial)

    provenance = _expected_provenance(manifest, runtime)
    parent = _safe_parent(destination)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.kaji-stage-", dir=parent)
    )
    backup = parent / f".{destination.name}.kaji-backup-{uuid4().hex}"
    wrote_backup = False
    try:
        for relative in manifest.files:
            source = _safe_source(manifest, relative)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
        sidecar = staging / _SIDECAR
        sidecar.write_bytes(_canonical_bytes(provenance) + b"\n")
        staged = classify_integration_bundle(manifest, staging, runtime=runtime)
        if staged.state != "current":
            raise ManifestError("Staged integration bundle failed validation")

        live = classify_integration_bundle(manifest, destination, runtime=runtime)
        if (live.state, live.reason_code, live._observed) != (
            initial.state,
            initial.reason_code,
            initial._observed,
        ):
            raise ManifestError("Destination changed during integration copy")
        if initial.state == "outdated" or initial._observed == "empty":
            destination.rename(backup)
            wrote_backup = True
        try:
            staging.rename(destination)
        except Exception:
            if wrote_backup and backup.exists() and not destination.exists():
                backup.rename(destination)
                wrote_backup = False
            raise
        if wrote_backup:
            shutil.rmtree(backup)
            wrote_backup = False
        return BundleStatus(
            "current",
            "installed" if initial.state == "absent" else "updated",
            destination,
            tuple(destination / relative for relative in manifest.files),
            _observed_token(provenance, destination),
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if wrote_backup and backup.exists() and not destination.exists():
            backup.rename(destination)
