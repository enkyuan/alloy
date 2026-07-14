#!/usr/bin/env python3
"""Verify indexed integration manifests against both executable tool ABIs."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
from typing import Any

from process_runner import CommandError, METADATA_BUDGET, run_checked


ROOT = Path(__file__).resolve().parents[2]
KAJI = ROOT / "kaji"
CONTRACTS = KAJI / "contracts" / "integrations"
ABI_INDEX = CONTRACTS / "abi-index-v1.json"
PYTHON_SDK = KAJI / "sdk"
TYPESCRIPT_SDK = KAJI / "ts"
PYTHON_REGISTRY = PYTHON_SDK / "src" / "kaji" / "integrations" / "registry"
TYPESCRIPT_REGISTRY = TYPESCRIPT_SDK / "registry"
_INTEGRATION_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")


class IntegrationAbiCheckError(RuntimeError):
    """A redaction-safe ABI gate failure."""


class IntegrationAbiMismatchError(IntegrationAbiCheckError):
    code = "INTEGRATION_ABI_MISMATCH"

    def __init__(self, pointer: str, expected: object, actual: object) -> None:
        self.pointer = pointer
        self.expected = expected
        self.actual = actual
        super().__init__(f"Integration ABI mismatch at {pointer}")


_MISSING = object()


def _pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _display(value: object) -> str:
    if value is _MISSING:
        return "<missing>"
    if value is None:
        return "<null>"
    if isinstance(value, bool):
        return "<boolean>"
    if isinstance(value, (int, float)):
        return "<number>"
    if isinstance(value, str):
        return f"<string length={len(value)}>"
    if isinstance(value, list):
        return f"<array length={len(value)}>"
    if isinstance(value, dict):
        return f"<object keys={len(value)}>"
    return f"<{type(value).__name__}>"


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number {value}")


def _load_json_bytes(data: bytes, source: str) -> dict[str, Any]:
    try:
        value = json.loads(
            data.decode("utf-8"),
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise IntegrationAbiCheckError(
            f"{source} did not emit one valid UTF-8 JSON document"
        ) from error
    if not isinstance(value, dict):
        raise IntegrationAbiCheckError(f"{source} did not emit a JSON object")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return _load_json_bytes(path.read_bytes(), str(path))
    except OSError as error:
        raise IntegrationAbiCheckError(f"{path} could not be read") from error


def _abi_contracts() -> dict[str, Path]:
    document = _load_json(ABI_INDEX)
    if set(document) != {"schemaVersion", "integrations"}:
        raise IntegrationAbiCheckError("ABI index: / must be a closed object")
    if document.get("schemaVersion") != "1.0.0":
        raise IntegrationAbiCheckError(
            "ABI index: /schemaVersion must be version 1.0.0"
        )
    integrations = document.get("integrations")
    if not isinstance(integrations, dict) or not integrations:
        raise IntegrationAbiCheckError(
            "ABI index: /integrations must be a non-empty object"
        )

    contracts: dict[str, Path] = {}
    root = CONTRACTS.resolve()
    for name, relative in sorted(integrations.items()):
        pointer = f"/integrations/{_pointer_part(str(name))}"
        if not isinstance(name, str) or _INTEGRATION_NAME.fullmatch(name) is None:
            raise IntegrationAbiCheckError(
                f"ABI index: {pointer} has an invalid integration name"
            )
        if not isinstance(relative, str):
            raise IntegrationAbiCheckError(
                f"ABI index: {pointer} must be a relative path"
            )
        parts = relative.split("/")
        path = PurePosixPath(relative)
        if (
            not relative
            or "\\" in relative
            or path.is_absolute()
            or re.match(r"^[A-Za-z]:", relative) is not None
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise IntegrationAbiCheckError(
                f"ABI index: {pointer} must be a safe relative path"
            )
        candidate = (CONTRACTS / path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise IntegrationAbiCheckError(
                f"ABI index: {pointer} resolves outside the contract root"
            ) from None
        if not candidate.is_file():
            raise IntegrationAbiCheckError(
                f"ABI index: {pointer} references a missing file"
            )
        contracts[name] = candidate
    return contracts


def _environment(*, bun: str, home: Path, temporary: Path) -> dict[str, str]:
    path = os.pathsep.join(
        dict.fromkeys(
            [
                str(Path(sys.executable).parent),
                str(Path(bun).parent),
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            ]
        )
    )
    return {
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": path,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "TEMP": str(temporary),
        "TMP": str(temporary),
        "TMPDIR": str(temporary),
        "TZ": "UTC",
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }


def _run_exporter(
    name: str,
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
) -> dict[str, Any]:
    try:
        result = run_checked(
            command,
            cwd=cwd,
            budget=METADATA_BUDGET,
            capture=True,
            env=environment,
        )
    except CommandError as error:
        raise IntegrationAbiCheckError(
            f"{name} metadata exporter failed: {error}"
        ) from None
    document = _load_json_bytes(result.stdout, f"{name} metadata exporter")
    nested_error = document.get("error")
    if isinstance(nested_error, dict):
        if nested_error.get("code") != IntegrationAbiMismatchError.code:
            raise IntegrationAbiCheckError(
                f"{name} metadata exporter emitted an unknown error envelope"
            )
        raise IntegrationAbiMismatchError(
            str(nested_error.get("pointer", "/")),
            nested_error.get("expected", _MISSING),
            nested_error.get("actual", _MISSING),
        )
    return document


def _runtime_documents(integration_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    bun = shutil.which("bun")
    if bun is None:
        raise IntegrationAbiCheckError("bun was not found on PATH")
    with tempfile.TemporaryDirectory(prefix="kaji-integration-abi-") as temporary_name:
        temporary = Path(temporary_name)
        home = temporary / "home"
        home.mkdir()
        environment = _environment(bun=bun, home=home, temporary=temporary)
        python = _run_exporter(
            "Python",
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--python-json",
                integration_name,
            ],
            PYTHON_SDK,
            environment,
        )
        typescript = _run_exporter(
            "TypeScript",
            [bun, "run", "scripts/integration-abi.ts", "--json", integration_name],
            TYPESCRIPT_SDK,
            environment,
        )
    return python, typescript


def _python_document(integration_name: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(
            f"kaji.integrations.registry.{integration_name}.{integration_name}"
        )
    except Exception as error:
        raise IntegrationAbiMismatchError(
            "/inspect_integration", "importable integration module", error
        ) from None
    inspector = getattr(module, "inspect_integration", _MISSING)
    if not callable(inspector):
        raise IntegrationAbiMismatchError(
            "/inspect_integration", "side-effect-free inspector function", inspector
        )
    try:
        integration = inspector()
    except Exception as error:
        raise IntegrationAbiMismatchError(
            "/inspect_integration", "side-effect-free inspector result", error
        ) from None

    namespace = getattr(integration, "namespace", _MISSING)
    if not isinstance(namespace, str) or not namespace:
        raise IntegrationAbiMismatchError(
            "/namespace", "non-empty namespace", namespace
        )
    tools_method = getattr(integration, "tools", _MISSING)
    if not callable(tools_method):
        raise IntegrationAbiMismatchError("/tools", "metadata method", tools_method)
    try:
        declared = tools_method()
    except Exception as error:
        raise IntegrationAbiMismatchError(
            "/tools", "side-effect-free metadata", error
        ) from None
    if not isinstance(declared, (list, tuple)):
        raise IntegrationAbiMismatchError("/tools", "array of tool pairs", declared)

    tools: list[dict[str, Any]] = []
    for index, pair in enumerate(declared):
        if not isinstance(pair, (list, tuple)) or not pair:
            raise IntegrationAbiMismatchError(
                f"/tools/{index}", "tool metadata pair", pair
            )
        spec = pair[0]
        if not all(
            hasattr(spec, field)
            for field in (
                "name",
                "description",
                "parameters",
                "risk",
                "parallel_safe",
                "timeout_ms",
            )
        ):
            raise IntegrationAbiMismatchError(
                f"/tools/{index}", "complete tool metadata", spec
            )
        normalized = {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
            "risk": spec.risk,
            "parallel_safe": spec.parallel_safe,
        }
        if spec.timeout_ms is not None:
            normalized["timeout_ms"] = spec.timeout_ms
        tools.append(normalized)
    return {
        "namespace": namespace,
        "tools": sorted(tools, key=lambda tool: str(tool["name"])),
    }


def _normalized_tools(tools: object, source: str) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        raise IntegrationAbiCheckError(f"{source}: /tools must be an array")
    normalized: list[dict[str, Any]] = []
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            raise IntegrationAbiCheckError(
                f"{source}: /tools/{index} must be an object"
            )
        item = {
            "name": tool.get("name", _MISSING),
            "description": tool.get("description", _MISSING),
            "parameters": tool.get("parameters", _MISSING),
            "risk": tool.get("risk", _MISSING),
            "parallel_safe": tool.get("parallel_safe", _MISSING),
        }
        if "timeout_ms" in tool:
            item["timeout_ms"] = tool["timeout_ms"]
        normalized.append(item)
    normalized.sort(key=lambda tool: str(tool["name"]))
    for index in range(1, len(normalized)):
        if normalized[index - 1]["name"] == normalized[index]["name"]:
            raise IntegrationAbiMismatchError(
                f"/tools/{index}/name",
                "unique normalized tool name",
                normalized[index]["name"],
            )
    return normalized


def _first_mismatch(
    expected: object,
    actual: object,
    pointer: str = "",
) -> tuple[str, object, object] | None:
    if expected is _MISSING or actual is _MISSING:
        return (pointer or "/", expected, actual)
    if type(expected) is not type(actual):
        return (pointer or "/", expected, actual)
    if isinstance(expected, list):
        assert isinstance(actual, list)
        for index in range(max(len(expected), len(actual))):
            mismatch = _first_mismatch(
                expected[index] if index < len(expected) else _MISSING,
                actual[index] if index < len(actual) else _MISSING,
                f"{pointer}/{index}",
            )
            if mismatch is not None:
                return mismatch
        return None
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key in sorted(set(expected) | set(actual)):
            mismatch = _first_mismatch(
                expected.get(key, _MISSING),
                actual.get(key, _MISSING),
                f"{pointer}/{_pointer_part(key)}",
            )
            if mismatch is not None:
                return mismatch
        return None
    return None if expected == actual else (pointer or "/", expected, actual)


def _canonical_abi(integration_name: str, path: Path) -> dict[str, Any]:
    canonical = _load_json(path)
    if set(canonical) != {"$schema", "version", "namespace", "tools"}:
        raise IntegrationAbiCheckError(f"{path}: / must be a closed ABI object")
    if canonical.get("version") != "1.0.0":
        raise IntegrationAbiCheckError(f"{path}: /version must be version 1.0.0")
    if canonical.get("namespace") != integration_name:
        raise IntegrationAbiCheckError(
            f"{path}: /namespace must match the ABI index key"
        )
    return {
        "namespace": canonical.get("namespace", _MISSING),
        "tools": _normalized_tools(canonical.get("tools", _MISSING), str(path)),
    }


def check_integration_abi(integration_name: str | None = None) -> tuple[str, ...]:
    contracts = _abi_contracts()
    if integration_name is not None:
        if integration_name not in contracts:
            raise IntegrationAbiCheckError(
                "ABI index: /integrations has no requested entry"
            )
        contracts = {integration_name: contracts[integration_name]}

    for name, contract_path in contracts.items():
        expected = _canonical_abi(name, contract_path)
        manifest_paths = (
            PYTHON_REGISTRY / name / "manifest.json",
            TYPESCRIPT_REGISTRY / name / "manifest.json",
        )
        candidates: list[tuple[str, dict[str, Any]]] = []
        for manifest_path in manifest_paths:
            manifest = _load_json(manifest_path)
            candidates.append(
                (
                    str(manifest_path),
                    {
                        "namespace": manifest.get("namespace", _MISSING),
                        "tools": _normalized_tools(
                            manifest.get("tools", _MISSING), str(manifest_path)
                        ),
                    },
                )
            )
        python, typescript = _runtime_documents(name)
        candidates.extend(
            (("Python inspector", python), ("TypeScript inspector", typescript))
        )
        for source, actual in candidates:
            normalized = {
                "namespace": actual.get("namespace", _MISSING),
                "tools": _normalized_tools(actual.get("tools", _MISSING), source),
            }
            mismatch = _first_mismatch(expected, normalized)
            if mismatch is not None:
                raise IntegrationAbiMismatchError(*mismatch)
    return tuple(contracts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--integration")
    parser.add_argument("--python-json", metavar="NAME", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.python_json is not None:
        try:
            document = _python_document(args.python_json)
        except IntegrationAbiMismatchError as error:
            document = {
                "error": {
                    "code": error.code,
                    "pointer": error.pointer,
                    "expected": _display(error.expected),
                    "actual": _display(error.actual),
                }
            }
        print(json.dumps(document, sort_keys=True))
        return 0
    try:
        checked = check_integration_abi(args.integration)
    except IntegrationAbiMismatchError as error:
        detail = ""
        if args.explain:
            detail = (
                f": expected={_display(error.expected)} actual={_display(error.actual)}"
            )
        print(
            f"FAIL: {error.code} at {error.pointer}{detail}\n"
            "Run check_integration_abi.py --explain after updating the canonical ABI or executable metadata.",
            file=sys.stderr,
        )
        return 1
    except IntegrationAbiCheckError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"OK: indexed integration ABIs match: {', '.join(checked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
