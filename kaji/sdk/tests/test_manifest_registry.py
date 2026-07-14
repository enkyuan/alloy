"""Shared integration contracts and registry loading."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from kaji.integrations import (
    IntegrationNotFound,
    IntegrationValidationError,
    Manifest,
    ManifestError,
    ManifestValidationError,
    install_integration,
    list_integrations,
    load_manifest,
)
from kaji.integrations.validation import (
    _schema_validator,
    validate_index_document,
    validate_manifest_document,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "kaji" / "contracts" / "integrations"
VALID_CASES = json.loads((CONTRACTS / "conformance-valid.json").read_text())["cases"]
INVALID_CASES = json.loads((CONTRACTS / "conformance-invalid.json").read_text())[
    "cases"
]


def _entry(
    manifest: str, *, stability: str = "experimental", runtimes: list[str] | None = None
) -> dict[str, Any]:
    return {
        "manifest": manifest,
        "stability": stability,
        "runtimes": runtimes or ["python"],
    }


def _index(integrations: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "./index.schema.json",
        "version": "0.1.0",
        "integrations": integrations,
    }


def _valid_manifest(name: str, files: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "version": "0.1.0",
        "namespace": name.replace("-", "_"),
        "description": name,
        "auth": {"kind": "none"},
        "files": files,
        "tools": [
            {
                "name": "run",
                "description": "Run.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "additionalProperties": False,
                },
                "risk": "read",
                "parallel_safe": False,
                "timeout_ms": 250,
            }
        ],
    }


def _write_registry_case(root: Path, case: dict[str, Any]) -> str:
    root.mkdir()
    (root / "index.json").write_text(json.dumps(case["index"]))
    for relative, manifest in case.get("manifests", {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest))
    for relative in case.get("files", []):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// fixture\n")
    return next(iter(case["index"]["integrations"]))


def test_list_integrations_includes_known_names() -> None:
    names = list_integrations()
    assert names == ["echo", "github"]


def test_load_manifest_returns_parsed_manifest() -> None:
    manifest = load_manifest("echo")
    assert isinstance(manifest, Manifest)
    assert manifest.name == "echo"
    assert manifest.namespace == "echo"
    assert manifest.auth.kind == "none"
    assert {"echo.py", "echo.ts"} <= set(manifest.files)
    assert manifest.peer_deps == {}
    assert manifest.stability == "beta"
    assert manifest.runtimes == ("python", "typescript")
    assert {tool.name for tool in manifest.tools} == {"say", "shout"}
    for tool in manifest.tools:
        assert isinstance(tool.parameters, MappingProxyType)
        assert tool.risk == "read"
        assert tool.parallel_safe is False
        assert tool.timeout_ms is None


def test_oauth_manifest_requires_google_provider_and_client_id_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kaji.integrations as integrations

    root = tmp_path / "registry"
    root.mkdir()
    (root / "index.json").write_text(
        json.dumps(_index({"mail": _entry("mail/manifest.json")}))
    )
    directory = root / "mail"
    directory.mkdir()
    manifest = _valid_manifest("mail", ["index.ts"])
    manifest["auth"] = {
        "kind": "oauth",
        "provider": "google",
        "clientIdEnv": "GOOGLE_CLIENT_ID",
        "clientSecretEnv": "GOOGLE_CLIENT_SECRET",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "index.ts").write_text("// fixture\n")
    monkeypatch.setattr(integrations, "_registry_root", lambda: root)

    loaded = load_manifest("mail")

    assert loaded.auth.provider == "google"
    assert loaded.auth.client_id_env == "GOOGLE_CLIENT_ID"
    assert loaded.auth.client_secret_env == "GOOGLE_CLIENT_SECRET"


@pytest.mark.parametrize("field", ["provider", "clientIdEnv"])
def test_oauth_manifest_rejects_missing_required_metadata(field: str) -> None:
    auth = {
        "kind": "oauth",
        "provider": "google",
        "clientIdEnv": "GOOGLE_CLIENT_ID",
        "scopes": ["scope"],
    }
    del auth[field]
    manifest = _valid_manifest("mail", ["index.ts"])
    manifest["auth"] = auth

    with pytest.raises(ManifestValidationError) as caught:
        validate_manifest_document(manifest)

    assert caught.value.path.startswith("/auth")


def test_load_manifest_freezes_nested_parameter_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kaji.integrations as integrations

    root = tmp_path / "registry"
    root.mkdir()
    (root / "index.json").write_text(
        json.dumps(_index({"frozen": _entry("frozen/manifest.json")}))
    )
    directory = root / "frozen"
    directory.mkdir()
    manifest = _valid_manifest("frozen", ["index.ts"])
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "index.ts").write_text("// fixture\n")
    monkeypatch.setattr(integrations, "_registry_root", lambda: root)

    loaded = load_manifest("frozen").tools[0]
    assert loaded.name == "run"
    assert loaded.description == "Run."
    assert loaded.risk == "read"
    assert loaded.parallel_safe is False
    assert loaded.timeout_ms == 250
    properties = loaded.parameters["properties"]
    assert isinstance(properties, MappingProxyType)
    mutable: Any = properties
    with pytest.raises(TypeError):
        mutable["other"] = {"type": "number"}


def test_packaged_schemas_match_canonical_contracts() -> None:
    for packaged in (
        REPO_ROOT / "kaji/sdk/src/kaji/integrations/registry/schema.json",
        REPO_ROOT / "kaji/ts/registry/schema.json",
    ):
        assert (
            packaged.read_bytes() == (CONTRACTS / "manifest.schema.json").read_bytes()
        )
    for packaged in (
        REPO_ROOT / "kaji/sdk/src/kaji/integrations/registry/index.schema.json",
        REPO_ROOT / "kaji/ts/registry/index.schema.json",
    ):
        assert packaged.read_bytes() == (CONTRACTS / "index.schema.json").read_bytes()


def test_copy_provenance_is_closed_and_supports_demotion_detection() -> None:
    schema = json.loads((CONTRACTS / "copy-provenance-v1.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    digest = "0" * 64
    provenance = {
        "schemaVersion": "1.0.0",
        "integration": "fs",
        "sdkVersion": "0.1.0",
        "runtime": "typescript",
        "stability": "experimental",
        "registryEntrySha256": digest,
        "abiSha256": None,
        "manifestSha256": digest,
        "license": {
            "identifier": "PolyForm-Noncommercial-1.0.0",
            "url": "https://polyformproject.org/licenses/noncommercial/1.0.0",
            "sha256": digest,
        },
        "files": {"index.ts": digest},
    }

    assert validator.is_valid(provenance)
    assert validator.is_valid(
        {**provenance, "integration": "echo", "abiSha256": digest}
    )
    assert not validator.is_valid(
        {key: value for key, value in provenance.items() if key != "stability"}
    )
    assert not validator.is_valid({**provenance, "registryEntrySha256": "short"})
    assert not validator.is_valid(
        {**provenance, "files": {".kaji-integration-provenance.json": digest}}
    )
    assert not validator.is_valid({**provenance, "unexpected": True})


def test_fixed_contract_validators_are_cached() -> None:
    assert _schema_validator("manifest") is _schema_validator("manifest")
    assert _schema_validator("index") is _schema_validator("index")


@pytest.mark.parametrize("case", VALID_CASES, ids=lambda case: case["name"])
def test_shared_valid_contract_cases(case: dict[str, Any]) -> None:
    if case["target"] == "manifest":
        validate_manifest_document(case["document"])
    else:
        validate_index_document(case["document"])


@pytest.mark.parametrize(
    "case",
    [case for case in INVALID_CASES if case["target"] != "registry"],
    ids=lambda case: case["name"],
)
def test_shared_invalid_schema_cases(case: dict[str, Any]) -> None:
    validator = (
        validate_manifest_document
        if case["target"] == "manifest"
        else validate_index_document
    )
    with pytest.raises(IntegrationValidationError) as caught:
        validator(case["document"])

    assert caught.value.normalized() == {
        "code": case["expectedCode"],
        "path": case["expectedPath"],
    }


@pytest.mark.parametrize(
    "case",
    [case for case in INVALID_CASES if case["target"] == "registry"],
    ids=lambda case: case["name"],
)
def test_shared_invalid_registry_cases(
    case: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kaji.integrations as integrations

    root = tmp_path / "registry"
    name = _write_registry_case(root, case)
    monkeypatch.setattr(integrations, "_registry_root", lambda: root)

    with pytest.raises(IntegrationValidationError) as caught:
        load_manifest(name)

    assert caught.value.normalized() == {
        "code": case["expectedCode"],
        "path": case["expectedPath"],
    }


def test_load_manifest_unknown_raises_integration_not_found() -> None:
    with pytest.raises(IntegrationNotFound):
        load_manifest("does-not-exist")


def test_install_integration_copies_files(tmp_path: Path) -> None:
    written = install_integration("echo", tmp_path)
    assert {path.name for path in written} == {"echo.py", "echo.ts"}
    target = tmp_path / "echo.py"
    assert "async def say" in target.read_text()
    assert "kaji.function_tool" in target.read_text()
    assert (tmp_path / ".kaji-integration-provenance.json").is_file()


def test_install_integration_current_bundle_is_a_safe_noop(tmp_path: Path) -> None:
    install_integration("echo", tmp_path)
    assert install_integration("echo", tmp_path) == []


def test_install_integration_force_rejects_local_modifications(tmp_path: Path) -> None:
    install_integration("echo", tmp_path)
    target = tmp_path / "echo.py"
    target.write_text("# modified by user\n")
    with pytest.raises(FileExistsError, match="modified"):
        install_integration("echo", tmp_path, force=True)
    assert target.read_text() == "# modified by user\n"


def test_copy_classification_detects_stability_demotion(tmp_path: Path) -> None:
    from kaji.integrations.copy import classify_integration_bundle

    install_integration("echo", tmp_path)
    demoted = replace(load_manifest("echo"), stability="experimental")

    status = classify_integration_bundle(demoted, tmp_path, runtime="python")
    assert (status.state, status.reason_code, status.exit_code) == (
        "demoted",
        "stability_demoted",
        6,
    )


def test_manifest_validation_catches_missing_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kaji.integrations as integrations

    root = tmp_path / "registry"
    root.mkdir()
    (root / "index.json").write_text(
        json.dumps(_index({"broken": _entry("broken/manifest.json")}))
    )
    (root / "broken").mkdir()
    manifest = _valid_manifest("broken", ["x.py"])
    del manifest["tools"]
    (root / "broken" / "manifest.json").write_text(json.dumps(manifest))
    (root / "broken" / "x.py").write_text("# fixture\n")

    monkeypatch.setattr(integrations, "_registry_root", lambda: root)
    with pytest.raises(ManifestError, match="required validation"):
        load_manifest("broken")


def test_load_manifest_parses_peer_deps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kaji.integrations as integrations

    root = tmp_path / "registry"
    root.mkdir()
    (root / "index.json").write_text(
        json.dumps(_index({"ts-deps": _entry("ts-deps/manifest.json")}))
    )
    directory = root / "ts-deps"
    directory.mkdir()
    manifest = _valid_manifest("ts-deps", ["index.ts"])
    manifest["peerDeps"] = {"better-sqlite3": "^9"}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "index.ts").write_text("// fixture\n")
    monkeypatch.setattr(integrations, "_registry_root", lambda: root)

    assert load_manifest("ts-deps").peer_deps == {"better-sqlite3": "^9"}


def test_load_manifest_rejects_source_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kaji.integrations as integrations

    root = tmp_path / "registry"
    directory = root / "escape"
    directory.mkdir(parents=True)
    (root / "index.json").write_text(
        json.dumps(_index({"escape": _entry("escape/manifest.json")}))
    )
    (directory / "manifest.json").write_text(
        json.dumps(_valid_manifest("escape", ["payload.py"]))
    )
    outside = tmp_path / "outside.py"
    outside.write_text("# outside\n")
    (directory / "payload.py").symlink_to(outside)
    monkeypatch.setattr(integrations, "_registry_root", lambda: root)

    with pytest.raises(IntegrationValidationError) as caught:
        load_manifest("escape")

    assert caught.value.normalized() == {
        "code": "INTEGRATION_SCHEMA_INVALID",
        "path": "/files/0",
    }


def test_load_manifest_normalizes_source_symlink_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kaji.integrations as integrations

    root = tmp_path / "registry"
    directory = root / "loop"
    directory.mkdir(parents=True)
    (root / "index.json").write_text(
        json.dumps(_index({"loop": _entry("loop/manifest.json")}))
    )
    (directory / "manifest.json").write_text(
        json.dumps(_valid_manifest("loop", ["payload.py"]))
    )
    (directory / "payload.py").symlink_to("payload.py")
    monkeypatch.setattr(integrations, "_registry_root", lambda: root)

    with pytest.raises(IntegrationValidationError) as caught:
        load_manifest("loop")

    assert caught.value.normalized() == {
        "code": "INTEGRATION_SCHEMA_INVALID",
        "path": "/files/0",
    }


def test_load_manifest_rejects_indexed_manifest_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kaji.integrations as integrations

    root = tmp_path / "registry"
    directory = root / "escape"
    directory.mkdir(parents=True)
    (root / "index.json").write_text(
        json.dumps(_index({"escape": _entry("escape/manifest.json")}))
    )
    outside = tmp_path / "outside-manifest.json"
    outside.write_text(json.dumps(_valid_manifest("escape", ["payload.py"])))
    (directory / "manifest.json").symlink_to(outside)
    monkeypatch.setattr(integrations, "_registry_root", lambda: root)

    with pytest.raises(IntegrationValidationError) as caught:
        load_manifest("escape")

    assert caught.value.normalized() == {
        "code": "INTEGRATION_SCHEMA_INVALID",
        "path": "/integrations/escape/manifest",
    }


def test_install_rejects_destination_symlink_escape(tmp_path: Path) -> None:
    destination = tmp_path / "destination"
    outside = tmp_path / "outside"
    destination.mkdir()
    outside.mkdir()
    (destination / "echo.py").symlink_to(outside / "echo.py")

    with pytest.raises(FileExistsError, match="modified"):
        install_integration("echo", destination, force=True)

    assert not (outside / "echo.py").exists()
