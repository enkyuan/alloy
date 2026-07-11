#!/usr/bin/env python3
"""Compare deterministic Python and TypeScript SDK behavior snapshots."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
KAJI = ROOT / "kaji"
SCENARIOS = KAJI / "contracts" / "parity" / "scenarios.json"
EXPECTED = KAJI / "contracts" / "parity" / "expected-normalized.json"
PYTHON_SDK = KAJI / "sdk"
TYPESCRIPT_SDK = KAJI / "ts"
PYTHON_EXPORTER = PYTHON_SDK / "scripts" / "export_parity.py"
TYPESCRIPT_EXPORTER = TYPESCRIPT_SDK / "scripts" / "export_parity.ts"
ARTIFACTS = ROOT / ".artifacts" / "kaji-parity"
TIMEOUT_SECONDS = 60


class ParityError(RuntimeError):
    """A deterministic parity gate failure."""


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r}")


def reject_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_json(data: bytes, source: str) -> dict[str, Any]:
    try:
        value = json.loads(
            data.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise ParityError(
            f"{source} did not emit one valid UTF-8 JSON document: {error}"
        ) from error
    if not isinstance(value, dict):
        raise ParityError(f"{source} emitted {json_kind(value)}, expected object")
    assert_json_value(value)
    return value


def assert_json_value(value: Any, path: str = "") -> None:
    kind = json_kind(value)
    if kind in {"null", "boolean", "string"}:
        return
    if kind == "number":
        if isinstance(value, float) and not math.isfinite(value):
            raise ParityError(f"non-finite number at {path or '/'}")
        return
    if kind == "array":
        for index, item in enumerate(value):
            assert_json_value(item, f"{path}/{index}")
        return
    if kind == "object":
        for key, item in value.items():
            if not isinstance(key, str):
                raise ParityError(f"non-string object key at {path or '/'}")
            assert_json_value(item, f"{path}/{escape_pointer(key)}")
        return
    raise ParityError(f"non-JSON {kind} at {path or '/'}")


def json_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def sanitized_environment(*, bun: str, home: Path, temporary: Path) -> dict[str, str]:
    """Build a closed child environment; do not inherit runtime configuration."""
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


def run_exporter(
    name: str,
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
) -> bytes:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ParityError(
            f"{name} exporter timed out after {TIMEOUT_SECONDS}s"
        ) from error
    except OSError as error:
        raise ParityError(f"could not start {name} exporter: {error}") from error
    if result.returncode != 0:
        diagnostics = result.stderr.decode("utf-8", errors="replace").strip()
        suffix = f"\nstderr:\n{diagnostics}" if diagnostics else ""
        raise ParityError(
            f"{name} exporter exited with status {result.returncode}{suffix}"
        )
    return result.stdout


def load_normalization() -> tuple[set[str], dict[str, Any]]:
    document = load_json(SCENARIOS.read_bytes(), str(SCENARIOS))
    normalization = document.get("normalization")
    if not isinstance(normalization, dict):
        raise ParityError(f"{SCENARIOS}: /normalization must be an object")
    strip_keys = normalization.get("stripKeys")
    replace_keys = normalization.get("replaceKeys")
    if not isinstance(strip_keys, list) or not all(
        isinstance(key, str) for key in strip_keys
    ):
        raise ParityError(f"{SCENARIOS}: /normalization/stripKeys must be strings")
    if not isinstance(replace_keys, dict) or not all(
        isinstance(key, str) for key in replace_keys
    ):
        raise ParityError(f"{SCENARIOS}: /normalization/replaceKeys must be an object")
    return set(strip_keys), replace_keys


def normalize(value: Any, strip_keys: set[str], replace_keys: dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [normalize(item, strip_keys, replace_keys) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value):
            if key in strip_keys:
                continue
            if key in replace_keys:
                result[key] = replace_keys[key]
            else:
                result[key] = normalize(value[key], strip_keys, replace_keys)
        return result
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def join_pointer(path: str, part: str) -> str:
    return f"{path}/{escape_pointer(part)}" if path else f"/{escape_pointer(part)}"


def first_diff(expected: Any, actual: Any, path: str = "") -> str | None:
    expected_kind = json_kind(expected)
    actual_kind = json_kind(actual)
    pointer = path or "/"
    if expected_kind != actual_kind:
        return (
            f"{pointer}: expected {expected_kind} {render_value(expected)}, "
            f"actual {actual_kind} {render_value(actual)}"
        )
    if expected_kind == "object":
        expected_keys = set(expected)
        actual_keys = set(actual)
        for key in sorted(expected_keys | actual_keys):
            child = join_pointer(path, key)
            if key not in expected:
                return f"{child}: unexpected {json_kind(actual[key])} {render_value(actual[key])}"
            if key not in actual:
                return f"{child}: missing expected {json_kind(expected[key])} {render_value(expected[key])}"
            difference = first_diff(expected[key], actual[key], child)
            if difference is not None:
                return difference
        return None
    if expected_kind == "array":
        common = min(len(expected), len(actual))
        for index in range(common):
            difference = first_diff(
                expected[index], actual[index], join_pointer(path, str(index))
            )
            if difference is not None:
                return difference
        if len(expected) != len(actual):
            return f"{pointer}: expected array length {len(expected)}, actual {len(actual)}"
        return None
    if expected_kind == "number":
        return (
            None
            if expected == actual
            else (
                f"{pointer}: expected number {render_value(expected)}, actual number {render_value(actual)}"
            )
        )
    if expected != actual:
        return (
            f"{pointer}: expected {expected_kind} {render_value(expected)}, "
            f"actual {actual_kind} {render_value(actual)}"
        )
    return None


def render_value(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    return rendered if len(rendered) <= 240 else rendered[:237] + "..."


def compare(label: str, expected: Any, actual: Any) -> None:
    difference = first_diff(expected, actual)
    if difference is not None:
        raise ParityError(f"{label} mismatch at {difference}")


def retain_failure(temporary: Path, difference: str) -> None:
    ARTIFACTS.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".kaji-parity-", dir=ARTIFACTS.parent))
    names = (
        "python-raw.json",
        "typescript-raw.json",
        "python-normalized.json",
        "typescript-normalized.json",
    )
    try:
        for name in names:
            source = temporary / name
            (staging / name).write_bytes(
                source.read_bytes() if source.exists() else b""
            )
        (staging / "diff.txt").write_text(difference + "\n", encoding="utf-8")
        if ARTIFACTS.exists():
            shutil.rmtree(ARTIFACTS)
        staging.replace(ARTIFACTS)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="kaji-parity-") as directory:
        temporary = Path(directory)
        try:
            strip_keys, replace_keys = load_normalization()
            bun = shutil.which("bun")
            if bun is None:
                raise ParityError("bun was not found on PATH")
            child_home = temporary / "home"
            child_tmp = temporary / "tmp"
            child_home.mkdir()
            child_tmp.mkdir()
            environment = sanitized_environment(
                bun=bun,
                home=child_home,
                temporary=child_tmp,
            )

            python_raw = run_exporter(
                "Python",
                [sys.executable, str(PYTHON_EXPORTER)],
                PYTHON_SDK,
                environment,
            )
            (temporary / "python-raw.json").write_bytes(python_raw)
            typescript_raw = run_exporter(
                "TypeScript",
                [bun, "run", str(TYPESCRIPT_EXPORTER)],
                TYPESCRIPT_SDK,
                environment,
            )
            (temporary / "typescript-raw.json").write_bytes(typescript_raw)

            python = load_json(python_raw, "Python exporter")
            typescript = load_json(typescript_raw, "TypeScript exporter")
            expected = load_json(EXPECTED.read_bytes(), str(EXPECTED))
            python_normalized = normalize(python, strip_keys, replace_keys)
            typescript_normalized = normalize(typescript, strip_keys, replace_keys)
            (temporary / "python-normalized.json").write_bytes(
                canonical_bytes(python_normalized)
            )
            (temporary / "typescript-normalized.json").write_bytes(
                canonical_bytes(typescript_normalized)
            )

            compare("Python -> expected", expected, python_normalized)
            compare("TypeScript -> expected", expected, typescript_normalized)
            compare("Python -> TypeScript", python_normalized, typescript_normalized)
        except (OSError, ParityError) as error:
            message = str(error)
            retain_failure(temporary, message)
            print(
                f"FAIL: SDK parity\n{message}\nArtifacts: {ARTIFACTS}", file=sys.stderr
            )
            return 1

    if ARTIFACTS.exists():
        shutil.rmtree(ARTIFACTS)
    print(
        "OK: Python and TypeScript SDK snapshots match "
        f"{len(expected['scenarios'])} parity scenarios"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
