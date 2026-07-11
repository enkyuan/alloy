from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SDK_ROOT = REPO_ROOT / "kaji" / "sdk"
EXPORTER = SDK_ROOT / "scripts" / "export_parity.py"
SCENARIOS = REPO_ROOT / "kaji" / "contracts" / "parity" / "scenarios.json"
TOOLS = REPO_ROOT / "kaji" / "contracts" / "tools"
SNAPSHOT_KEYS = {
    "events",
    "operation_trace",
    "provider_requests",
    "provider_responses",
    "replay",
    "result",
}
PARITY_CHECK = REPO_ROOT / "kaji" / "scripts" / "check_sdk_parity.py"


def run_exporter(poison: str) -> bytes:
    environment = dict(os.environ)
    environment.update(
        {
            "OPENAI_API_KEY": poison,
            "ANTHROPIC_API_KEY": poison,
            "GOOGLE_API_KEY": poison,
            "TZ": "UTC",
        }
    )
    result = subprocess.run(
        [sys.executable, str(EXPORTER)],
        cwd=SDK_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def test_python_exporter_is_byte_stable_and_covers_every_scenario() -> None:
    first = run_exporter("must-not-be-read-a")
    second = run_exporter("must-not-be-read-b")

    assert first == second
    exported = json.loads(first)
    contract = json.loads(SCENARIOS.read_text())
    assert [row["id"] for row in exported["scenarios"]] == [
        row["id"] for row in contract["scenarios"]
    ]
    assert len(exported["scenarios"]) == 59
    assert all(set(row["snapshot"]) == SNAPSHOT_KEYS for row in exported["scenarios"])
    snapshots = {row["id"]: row["snapshot"] for row in exported["scenarios"]}
    for scenario_id, service, action, cost in (
        ("openai-non-stream", "openai", "request", 0.00001725),
        ("openai-stream", "openai", "stream", 0.00001725),
        ("anthropic-non-stream", "anthropic", "request", 0.00006),
        ("anthropic-stream", "anthropic", "stream", 0.00006),
    ):
        result = snapshots[scenario_id]["result"]
        assert result["cost_usd"] == cost
        assert result["provider_error"] == {
            "type": "network",
            "code": "PROVIDER_NETWORK_ERROR",
            "service": service,
            "action": action,
            "status": None,
            "retryable": True,
        }
    assert {
        scenario_id: snapshots[scenario_id]["result"]["tool_content"]
        for scenario_id in (
            "replay-json-boolean",
            "replay-json-null",
            "replay-json-number",
            "replay-json-integral-float",
            "replay-json-negative-zero",
            "replay-json-exponent-boundaries",
            "replay-json-numeric-keys",
            "replay-json-safe-integer-boundary",
            "replay-json-utf16-keys",
            "replay-json-string",
            "replay-json-array",
        )
    } == {
        "replay-json-boolean": "true",
        "replay-json-null": "null",
        "replay-json-number": "7.5",
        "replay-json-integral-float": "1",
        "replay-json-negative-zero": "0",
        "replay-json-exponent-boundaries": "[0.000001,1e-7,100000000000000000000,1e+21]",
        "replay-json-numeric-keys": '{"10":"ten","2":"two"}',
        "replay-json-safe-integer-boundary": "9007199254740991",
        "replay-json-utf16-keys": '{"\U00010000":"astral","\ue000":"bmp"}',
        "replay-json-string": '"café"',
        "replay-json-array": "[1,false,null]",
    }
    assert snapshots["replay-json-unrepresentable-integer"]["result"] == {
        "event_count": 3,
        "rejection": "integer_not_exactly_representable",
    }

    referenced = {
        (row["fixtureFile"], row["fixture"])
        for row in contract["scenarios"]
        if row["kind"] == "tool-schema"
    }
    canonical = {
        (filename, case["name"])
        for filename in ("conformance-valid.json", "conformance-invalid.json")
        for case in json.loads((TOOLS / filename).read_text())["cases"]
    }
    assert referenced == canonical


def test_python_exporter_has_no_environment_or_network_client_boundary() -> None:
    source = EXPORTER.read_text()

    for forbidden in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "os.environ",
        "os.getenv",
        "OpenAIProvider(",
        "AnthropicProvider(",
        "socket.",
        "httpx.",
    ):
        assert forbidden not in source
    assert "object.__new__(OpenAIProvider)" in source
    assert "object.__new__(AnthropicProvider)" in source
    assert "expected-normalized.json" not in source


def test_orchestrator_child_environment_is_a_minimal_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    poisoned = {
        "PYTHONPATH": "/poison/pythonpath",
        "PYTHONHOME": "/poison/pythonhome",
        "NODE_OPTIONS": "--require=/poison/node.js",
        "NODE_PATH": "/poison/node_modules",
        "BUN_OPTIONS": "--preload=/poison/bun.ts",
        "OPENAI_API_KEY": "poison-secret",
        "ANTHROPIC_API_KEY": "poison-secret",
    }
    for key, value in poisoned.items():
        monkeypatch.setenv(key, value)
    module = runpy.run_path(str(PARITY_CHECK), run_name="parity_check_test")

    environment = module["sanitized_environment"](
        bun="/fixture/bin/bun",
        home=tmp_path / "home",
        temporary=tmp_path / "tmp",
    )

    assert set(environment) == {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONHASHSEED",
        "PYTHONNOUSERSITE",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
    }
    assert not set(poisoned) & set(environment)
