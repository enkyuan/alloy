"""Tests for the echo integration's Python registry entry."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
from kaji.integrations import install_integration, load_manifest


def test_echo_manifest_loads():
    m = load_manifest("echo")
    assert m.name == "echo"
    assert m.namespace == "echo"
    assert m.auth.kind == "none"
    assert m.files == ("echo.py",)
    assert {t.name for t in m.tools} == {"say", "shout"}


def test_echo_install_copies_python_file(tmp_path: Path):
    written = install_integration("echo", tmp_path)
    names = {p.name for p in written}
    assert names == {"echo.py"}
    assert (tmp_path / "echo.py").read_text().startswith('"""Echo integration')


def test_echo_py_template_sets_echo_namespace():
    """Both Python tools must declare namespace='echo' so they don't fall
    through to function_tool's default 'fn' namespace. That default would
    break the cross-language contract: the TS template registers under
    echo.say / echo.shout; the Python template must match."""
    from kaji.integrations.registry.echo import echo as echo_mod

    assert echo_mod.say.namespace == "echo"
    assert echo_mod.shout.namespace == "echo"
    assert echo_mod.say.spec.name == "say"
    assert echo_mod.shout.spec.name == "shout"


def test_echo_executable_specs_match_authoritative_abi() -> None:
    from kaji.integrations.registry.echo import echo as echo_mod

    root = Path(__file__).resolve().parents[2]
    contract = json.loads(
        (root / "kaji/contracts/integrations/echo-tool-abi-v1.json").read_text()
    )
    actual = []
    for tool in echo_mod.tools:
        spec = tool.spec
        actual.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
                "risk": spec.risk,
                "parallel_safe": spec.parallel_safe,
                **(
                    {"timeout_ms": spec.timeout_ms}
                    if spec.timeout_ms is not None
                    else {}
                ),
            }
        )

    assert {tool.namespace for tool in echo_mod.tools} == {contract["namespace"]}
    assert sorted(actual, key=lambda tool: tool["name"]) == contract["tools"]
    assert echo_mod.tools == (echo_mod.say, echo_mod.shout)


def test_echo_manifests_share_only_the_canonical_abi_fields() -> None:
    root = Path(__file__).resolve().parents[2]
    contract = json.loads(
        (root / "kaji/contracts/integrations/echo-tool-abi-v1.json").read_text()
    )
    python_manifest = json.loads(
        (root / "kaji/src/kaji/integrations/registry/echo/manifest.json").read_text()
    )
    typescript_manifest = json.loads(
        (root / "kaji/ts/registry/echo/manifest.json").read_text()
    )

    for manifest in (python_manifest, typescript_manifest):
        assert manifest["namespace"] == contract["namespace"]
        assert manifest["tools"] == contract["tools"]
    assert python_manifest["files"] == ["echo.py"]
    assert typescript_manifest["files"] == ["index.ts"]
    assert typescript_manifest["peerDeps"] == {}


def test_registry_sources_are_owned_by_their_runtime() -> None:
    root = Path(__file__).resolve().parents[2]
    python_registry = root / "kaji/src/kaji/integrations/registry"
    typescript_registry = root / "kaji/ts/registry"

    assert not [
        path
        for path in python_registry.rglob("*")
        if path.suffix in {".js", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
    ]
    assert not [
        path
        for path in typescript_registry.rglob("*")
        if path.suffix in {".py", ".pyi"}
    ]


def _load_repo_script(name: str, path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_integration_sync_detects_newline_byte_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    sync = _load_repo_script(
        "sync_integration_contracts_bytes",
        root / "kaji/scripts/sync_integration_contracts.py",
        monkeypatch,
    )
    source = tmp_path / "index.ts"
    copy = tmp_path / "copy.ts"
    source.write_bytes(b"export const value = 1;\n")
    copy.write_bytes(b"export const value = 1;\r\n")
    assert sync._diff_bytes(copy.read_bytes(), source.read_bytes(), copy, source), (
        "LF and CRLF sources must not compare as byte-identical"
    )
    assert sync._diff_bytes(b"\x80", b"\x81", copy, source)


@pytest.mark.parametrize(
    "relative",
    ["/absolute.json", "C:/absolute.json", "../escape.json", "missing.json"],
)
def test_abi_index_rejects_unsafe_or_missing_contract_paths(
    relative: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[2]
    checker = _load_repo_script(
        "check_integration_abi_index_paths",
        root / "kaji/scripts/check_integration_abi.py",
        monkeypatch,
    )
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    index = contracts / "abi-index-v1.json"
    index.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "integrations": {"echo": relative},
            }
        )
    )
    monkeypatch.setattr(checker, "CONTRACTS", contracts)
    monkeypatch.setattr(checker, "ABI_INDEX", index)

    with pytest.raises(checker.IntegrationAbiCheckError):
        checker._abi_contracts()


def test_python_abi_inspector_is_required_and_redacts_top_level_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    checker = _load_repo_script(
        "check_integration_abi_inspector_errors",
        root / "kaji/scripts/check_integration_abi.py",
        monkeypatch,
    )
    monkeypatch.setattr(
        checker.importlib,
        "import_module",
        lambda _name: SimpleNamespace(),
    )
    with pytest.raises(checker.IntegrationAbiMismatchError) as missing:
        checker._python_document("echo")
    assert missing.value.pointer == "/inspect_integration"

    def inspect_integration():
        raise RuntimeError("secret inspector failure")

    monkeypatch.setattr(
        checker.importlib,
        "import_module",
        lambda _name: SimpleNamespace(inspect_integration=inspect_integration),
    )
    with pytest.raises(checker.IntegrationAbiMismatchError) as failed:
        checker._python_document("echo")
    assert failed.value.pointer == "/inspect_integration"
    assert "secret inspector failure" not in str(failed.value)


def test_abi_normalization_rejects_duplicate_manifest_tool_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    checker = _load_repo_script(
        "check_integration_abi_duplicate_names",
        root / "kaji/scripts/check_integration_abi.py",
        monkeypatch,
    )
    tool = {
        "name": "say",
        "description": "Say.",
        "parameters": {},
        "risk": "read",
        "parallel_safe": False,
    }

    with pytest.raises(checker.IntegrationAbiMismatchError) as caught:
        checker._normalized_tools([tool, dict(tool)], "manifest")
    assert caught.value.pointer == "/tools/1/name"


def test_typescript_cli_mismatch_reaches_python_explain_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[2]
    source_ts = root / "kaji/ts"
    temporary_ts = tmp_path / "ts"
    shutil.copytree(source_ts / "src", temporary_ts / "src")
    shutil.copytree(source_ts / "contracts", temporary_ts / "contracts")
    (temporary_ts / "scripts").mkdir(parents=True)
    (temporary_ts / "registry/echo").mkdir(parents=True)
    shutil.copy2(source_ts / "scripts/integration-abi.ts", temporary_ts / "scripts")
    shutil.copy2(source_ts / "package.json", temporary_ts)
    shutil.copy2(source_ts / "tsconfig.json", temporary_ts)
    (temporary_ts / "node_modules").symlink_to(
        source_ts / "node_modules", target_is_directory=True
    )
    echo_source = (source_ts / "registry/echo/index.ts").read_text()
    drifted = echo_source.replace(
        "Object.freeze([say, shout] as const)",
        "Object.freeze([say] as const)",
    )
    assert drifted != echo_source
    (temporary_ts / "registry/echo/index.ts").write_text(drifted)

    checker = _load_repo_script(
        "check_integration_abi_explain",
        root / "kaji/scripts/check_integration_abi.py",
        monkeypatch,
    )
    monkeypatch.setattr(checker, "TYPESCRIPT_SDK", temporary_ts)
    bun = shutil.which("bun") or "/opt/homebrew/bin/bun"
    monkeypatch.setenv(
        "PATH", f"{Path(bun).parent}:{Path(sys.executable).parent}:/usr/bin:/bin"
    )

    assert checker.main(["--explain"]) == 1
    captured = capsys.readouterr()
    assert "INTEGRATION_ABI_MISMATCH at /tools/1" in captured.err


def test_echo_py_tools_register_without_collision(tmp_path: Path):
    """The two bound tools must both register cleanly into a fresh registry."""
    from kaji.integrations.registry.echo import echo as echo_mod
    from kaji.runtime.tools.registry import ToolRegistry

    registry = ToolRegistry()
    echo_mod.say.register(registry)
    echo_mod.shout.register(registry)
    specs = {s.name for s in registry.list_specs()}
    assert {"echo_say", "echo_shout"} <= specs or {"say", "shout"} <= specs


def test_every_registry_manifest_file_exists_on_disk():
    """Catch packaging drift: every file declared by a manifest must actually
    ship with the wheel. A manifest that lists a file outside the package-data
    globs would silently break install_integration on installed wheels.
    """
    from kaji.integrations import list_integrations, load_manifest

    for name in list_integrations():
        m = load_manifest(name)
        for rel in m.files:
            assert (m.root / rel).exists(), f"{name}: missing {rel}"
