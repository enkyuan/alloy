#!/usr/bin/env python3
"""Verify stable Echo manifests against both executable tool ABIs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from process_runner import CommandError, METADATA_BUDGET, run_checked


ROOT = Path(__file__).resolve().parents[2]
KAJI = ROOT / "kaji"
CONTRACT = KAJI / "contracts" / "integrations" / "echo-tool-abi-v1.json"
PYTHON_SDK = KAJI / "sdk"
TYPESCRIPT_SDK = KAJI / "ts"
MANIFESTS = (
    PYTHON_SDK / "src" / "integrations" / "registry" / "echo" / "manifest.json",
    TYPESCRIPT_SDK / "registry" / "echo" / "manifest.json",
)


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
    if value is None or isinstance(value, (bool, int, float)):
        return json.dumps(value)
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


def _runtime_documents() -> tuple[dict[str, Any], dict[str, Any]]:
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
            [sys.executable, str(Path(__file__).resolve()), "--python-json"],
            PYTHON_SDK,
            environment,
        )
        typescript = _run_exporter(
            "TypeScript",
            [bun, "run", "scripts/integration-abi.ts", "--json"],
            TYPESCRIPT_SDK,
            environment,
        )
    return python, typescript


def _python_document() -> dict[str, Any]:
    from kaji.integrations.registry.echo import echo  # noqa: PLC0415
    from kaji.runtime.integrations import BoundTool  # noqa: PLC0415

    declared = tuple(echo.tools)
    exports = sorted(
        (name, value)
        for name, value in vars(echo).items()
        if isinstance(value, BoundTool)
    )
    declared_ids = {id(tool) for tool in declared}
    for name, tool in exports:
        if id(tool) not in declared_ids:
            raise IntegrationAbiMismatchError(
                f"/exports/{_pointer_part(name)}",
                "listed in tools",
                "unlisted BoundTool export",
            )
    exported_ids = {id(tool) for _, tool in exports}
    for index, tool in enumerate(declared):
        if id(tool) not in exported_ids:
            raise IntegrationAbiMismatchError(
                f"/tools/{index}",
                "named BoundTool export",
                "unexported tool metadata",
            )
    namespaces = {tool.namespace for tool in declared}
    if len(namespaces) != 1:
        raise IntegrationAbiMismatchError(
            "/namespace", "one namespace", sorted(namespaces)
        )
    tools: list[dict[str, Any]] = []
    for tool in declared:
        spec = tool.spec
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
        "namespace": next(iter(namespaces)),
        "tools": sorted(tools, key=lambda tool: tool["name"]),
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
            "name": tool.get("name"),
            "description": tool.get("description"),
            "parameters": tool.get("parameters"),
            "risk": tool.get("risk"),
            "parallel_safe": tool.get("parallel_safe", False),
        }
        if tool.get("timeout_ms") is not None:
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


def check_integration_abi() -> None:
    canonical = _load_json(CONTRACT)
    expected = {
        "namespace": canonical.get("namespace"),
        "tools": _normalized_tools(canonical.get("tools"), str(CONTRACT)),
    }
    candidates: list[tuple[str, dict[str, Any]]] = []
    for manifest_path in MANIFESTS:
        manifest = _load_json(manifest_path)
        candidates.append(
            (
                str(manifest_path),
                {
                    "namespace": manifest.get("namespace"),
                    "tools": _normalized_tools(
                        manifest.get("tools"), str(manifest_path)
                    ),
                },
            )
        )
    python, typescript = _runtime_documents()
    candidates.extend((("Python Echo", python), ("TypeScript Echo", typescript)))
    for source, actual in candidates:
        normalized = {
            "namespace": actual.get("namespace"),
            "tools": _normalized_tools(actual.get("tools"), source),
        }
        mismatch = _first_mismatch(expected, normalized)
        if mismatch is not None:
            raise IntegrationAbiMismatchError(*mismatch)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--python-json", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.python_json:
        try:
            document = _python_document()
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
        check_integration_abi()
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
    print("OK: Echo manifests and Python/TypeScript executable tool ABIs match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
