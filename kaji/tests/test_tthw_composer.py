from __future__ import annotations

from contextlib import nullcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import textwrap
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "kaji" / "scripts"
COMPOSER = SCRIPTS / "compose_tthw_evidence.py"
PARTICIPANT_TEMPLATE = (
    REPO_ROOT / "kaji/contracts/release/tthw-participant.template.json"
)
TIMINGS_TEMPLATE = (
    REPO_ROOT / "kaji/contracts/release/tthw-automated-timings.template.json"
)
ARTIFACTS = {
    "kaji_sdk-0.2.0b1-py3-none-any.whl": ("python", "0.2.0b1"),
    "kaji_sdk-0.2.0b1.tar.gz": ("python", "0.2.0b1"),
    "kaji-sdk-0.2.0-beta.2.tgz": ("typescript", "0.2.0-beta.2"),
}


def _marked_snippet(path: Path, name: str, language: str) -> str:
    matches = re.findall(
        rf"<!-- {re.escape(name)}:start -->\s*```{language}\n(.*?)\n[ \t]*```\s*"
        rf"<!-- {re.escape(name)}:end -->",
        path.read_text(),
        flags=re.DOTALL,
    )
    assert len(matches) == 1, f"expected exactly one {name} block in {path}"
    return textwrap.dedent(matches[0])


def test_exact_python_tthw_echo_snippet_runs_offline(tmp_path: Path) -> None:
    source = _marked_snippet(
        REPO_ROOT / "docs/kaji/tthw-evidence.md", "tthw-echo:python", "python"
    )
    echo = tmp_path / "echo"
    echo.mkdir()
    shutil.copyfile(
        REPO_ROOT / "kaji/src/kaji/integrations/registry/echo/echo.py",
        echo / "echo.py",
    )
    script = tmp_path / "echo_loop.py"
    script.write_text(source)
    environment = os.environ.copy()
    for name in (
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        environment.pop(name, None)

    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == (
        "PASS: echo requested, started, completed, and observed"
    )


def _load_script(path: Path) -> ModuleType:
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[list[Path], Path, Path, Path]:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    commit = "a" * 40
    manifest_rows = []
    for index, (name, (package, version)) in enumerate(ARTIFACTS.items(), 1):
        artifact = artifacts_dir / name
        artifact.write_bytes(f"artifact-{index}".encode())
        manifest_rows.append(
            {
                "file": name,
                "package": package,
                "version": version,
                "size": artifact.stat().st_size,
                "sha256": _sha(artifact),
                "commit": commit,
            }
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"commit": commit, "artifacts": manifest_rows}))
    manifest_hash = _sha(manifest)
    artifacts_by_name = {row["file"]: row for row in manifest_rows}

    toolchain = {
        "python": "3.14.6",
        "uv": "0.11.25",
        "node": "24.4.1",
        "npm": "11.4.2",
        "bun": "1.3.14",
        "typescript": "5.7.3 and 6.0.3",
    }
    paths = ("python", "npm", "bun", "python", "npm")
    receipts = []
    for index, path_name in enumerate(paths, 1):
        artifact_name = (
            "kaji_sdk-0.2.0b1-py3-none-any.whl"
            if path_name == "python"
            else "kaji-sdk-0.2.0-beta.2.tgz"
        )
        artifact = artifacts_by_name[artifact_name]
        receipt = {
            "participantId": f"user-{index:03d}",
            "commit": commit,
            "releaseManifestSha256": manifest_hash,
            "artifact": {
                "name": artifact["file"],
                "package": artifact["package"],
                "version": artifact["version"],
                "sha256": artifact["sha256"],
            },
            "os": "macos",
            "architecture": "arm64",
            "platformVersion": "15.5",
            "path": path_name,
            "cleanEnvironment": True,
            "noSourceCheckout": True,
            "toolchain": toolchain,
            "steps": [
                {"name": name, "durationMs": index * 1_000}
                for name in (
                    "artifact-install",
                    "scaffold-init",
                    "no-key-run",
                    "echo-setup",
                    "echo-run",
                )
            ],
            "assertions": {
                "deterministicText": True,
                "nonEmptyTurnId": True,
                "positiveSequence": True,
                "echoToolRequested": True,
                "echoToolStarted": True,
                "echoToolCompleted": True,
                "echoResultObserved": True,
            },
            "confusion": [],
            "redacted": True,
            "owner": "kaji-maintainer",
            "reviewDate": "2026-07-14",
            "followUpDate": "2026-08-13",
        }
        receipt_path = tmp_path / f"participant-{index}.json"
        receipt_path.write_text(json.dumps(receipt))
        receipts.append(receipt_path)

    timings = tmp_path / "automated-timings.json"
    timings.write_text(
        json.dumps(
            {
                path_name: {
                    "coldSetupToOutputMs": 10_000,
                    "warmRunMs": 500,
                    "toolchain": toolchain,
                }
                for path_name in ("python", "npm", "bun")
            }
        )
    )
    return receipts, timings, manifest, artifacts_dir


def test_checked_in_tthw_input_templates_have_exact_composer_shapes() -> None:
    participant = json.loads(PARTICIPANT_TEMPLATE.read_text())
    timings = json.loads(TIMINGS_TEMPLATE.read_text())

    assert [step["name"] for step in participant["steps"]] == [
        "artifact-install",
        "scaffold-init",
        "no-key-run",
        "echo-setup",
        "echo-run",
    ]
    assert "noKeyTotalMs" not in participant
    assert "echoTotalMs" not in participant
    assert all(step["durationMs"] == -1 for step in participant["steps"])
    assert participant["cleanEnvironment"] is True
    assert participant["noSourceCheckout"] is True
    assert participant["os"] == "macos"
    assert participant["architecture"] == "arm64"
    assert participant["commit"] == "replace-with-generated-commit"
    assert participant["releaseManifestSha256"] == (
        "replace-with-generated-release-manifest-sha256"
    )
    assert set(participant["artifact"]) == {"name", "package", "version", "sha256"}
    assert set(timings) == {"python", "npm", "bun"}
    assert all(timing["coldSetupToOutputMs"] == -1 for timing in timings.values())


def test_composer_derives_identity_totals_summary_and_deterministic_order(
    tmp_path: Path,
) -> None:
    module = _load_script(COMPOSER)
    receipts, timings, manifest, artifacts = _fixture(tmp_path)

    document = module.compose(
        participant_receipts=list(reversed(receipts)),
        automated_timings=timings,
        release_manifest=manifest,
        artifacts_dir=artifacts,
    )
    repeated = module.compose(
        participant_receipts=receipts,
        automated_timings=timings,
        release_manifest=manifest,
        artifacts_dir=artifacts,
    )

    assert document == repeated
    assert document["commit"] == "a" * 40
    assert document["releaseManifestSha256"] == _sha(manifest)
    assert [run["participantId"] for run in document["humanRuns"]] == [
        f"user-{index:03d}" for index in range(1, 6)
    ]
    assert document["humanRuns"][0]["noKeyTotalMs"] == 3_000
    assert document["humanRuns"][0]["echoTotalMs"] == 5_000
    assert document["humanRuns"][0]["artifact"]["name"] == (
        "kaji_sdk-0.2.0b1-py3-none-any.whl"
    )
    assert document["summary"] == {
        "noKeyMedianMs": 9_000,
        "noKeyMaxMs": 15_000,
        "echoMedianMs": 15_000,
        "echoMaxMs": 25_000,
    }


def test_atomic_writer_replaces_with_owner_only_secret_file(tmp_path: Path) -> None:
    module = _load_script(COMPOSER)
    output = tmp_path / "tthw.json"
    output.write_text("old")

    module.write_atomic(output, {"secretReady": True})

    assert json.loads(output.read_text()) == {"secretReady": True}
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert list(tmp_path.glob(".tthw.json.*.tmp")) == []


def test_composer_fails_before_replacing_output_on_invalid_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script(COMPOSER)
    receipts, timings, manifest, artifacts = _fixture(tmp_path)
    invalid = json.loads(receipts[0].read_text())
    invalid["confusion"] = [
        {"summary": "API_KEY=not-redacted", "remediation": "redact it"}
    ]
    receipts[0].write_text(json.dumps(invalid))
    output = tmp_path / "secret.json"
    output.write_text("preserve-me")
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: module.argparse.Namespace(
            participant=receipts,
            automated_timings=timings,
            release_manifest=manifest,
            artifacts_dir=artifacts,
            output=output,
        ),
    )

    assert module.main() == 1
    assert output.read_text() == "preserve-me"


@pytest.mark.parametrize(
    ("path_name", "artifact_name"),
    [
        ("python", "kaji_sdk-0.2.0b1-py3-none-any.whl"),
        ("npm", "kaji-sdk-0.2.0-beta.2.tgz"),
        ("bun", "kaji-sdk-0.2.0-beta.2.tgz"),
    ],
)
def test_template_generation_binds_selected_candidate_artifact(
    tmp_path: Path, path_name: str, artifact_name: str
) -> None:
    module = _load_script(COMPOSER)
    _receipts, _timings, manifest, artifacts = _fixture(tmp_path)

    participant = module.participant_template(
        path_name=path_name,
        release_manifest=manifest,
        artifacts_dir=artifacts,
    )

    assert participant["commit"] == "a" * 40
    assert participant["releaseManifestSha256"] == _sha(manifest)
    assert participant["path"] == path_name
    assert participant["artifact"]["name"] == artifact_name
    assert participant["artifact"]["sha256"] == _sha(artifacts / artifact_name)
    assert participant["os"] == "macos"
    assert participant["architecture"] == "arm64"


def test_template_generation_cli_writes_candidate_bound_skeleton(
    tmp_path: Path,
) -> None:
    _receipts, _timings, manifest, artifacts = _fixture(tmp_path)
    output = tmp_path / "participant.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(COMPOSER),
            "--generate-participant-template",
            "python",
            "--release-manifest",
            str(manifest),
            "--artifacts-dir",
            str(artifacts),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("PASS: candidate-bound participant template")
    assert json.loads(output.read_text())["commit"] == "a" * 40
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_composer_rejects_stale_receipt_instead_of_injecting_candidate_identity(
    tmp_path: Path,
) -> None:
    module = _load_script(COMPOSER)
    receipts, timings, manifest, artifacts = _fixture(tmp_path)
    stale = json.loads(receipts[0].read_text())
    stale["commit"] = "b" * 40
    receipts[0].write_text(json.dumps(stale))

    with pytest.raises(module.validation.EvidenceError, match="/humanRuns/0/commit"):
        module.compose(
            participant_receipts=receipts,
            automated_timings=timings,
            release_manifest=manifest,
            artifacts_dir=artifacts,
        )


def test_composer_rejects_python_receipt_bound_to_sdist(tmp_path: Path) -> None:
    module = _load_script(COMPOSER)
    receipts, timings, manifest, artifacts = _fixture(tmp_path)
    receipt = json.loads(receipts[0].read_text())
    sdist = artifacts / "kaji_sdk-0.2.0b1.tar.gz"
    receipt["artifact"] = {
        "name": sdist.name,
        "package": "python",
        "version": "0.2.0b1",
        "sha256": _sha(sdist),
    }
    receipts[0].write_text(json.dumps(receipt))

    with pytest.raises(
        module.validation.EvidenceError, match="/humanRuns/0/artifact/name"
    ):
        module.compose(
            participant_receipts=receipts,
            automated_timings=timings,
            release_manifest=manifest,
            artifacts_dir=artifacts,
        )


def test_composer_rechecks_retained_artifacts_after_participant_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script(COMPOSER)
    receipts, timings, manifest, artifacts = _fixture(tmp_path)
    original = module._participant_receipt
    mutated = False

    def mutate_then_read(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal mutated
        if not mutated:
            (artifacts / "kaji-sdk-0.2.0-beta.2.tgz").write_bytes(b"mutated")
            mutated = True
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "_participant_receipt", mutate_then_read)

    with pytest.raises(
        module.validation.EvidenceError, match="retained artifact size/hash differs"
    ):
        module.compose(
            participant_receipts=receipts,
            automated_timings=timings,
            release_manifest=manifest,
            artifacts_dir=artifacts,
        )


def _complete_baseline(module: ModuleType) -> dict[str, Any]:
    cases = module.CASES
    return {
        "schemaVersion": 1,
        "status": "calibrated",
        "calibrationCommit": "a" * 40,
        "commit": "a" * 40,
        "releaseManifestSha256": "b" * 64,
        "artifacts": {"python": {"sha256": "c" * 64}},
        "runner": {
            "environment": "github-hosted",
            "os": "Darwin",
            "arch": "arm64",
            "platformVersion": "15.7.7",
            "imageOS": "macos15",
            "imageLabel": "macos-15-arm64",
            "imageVersion": "20260715.0234.1",
            "imageDataSha256": "c" * 64,
        },
        "versions": {"python": "3.14", "node": "24", "bun": "1.3"},
        "dependencyLockHash": "d" * 64,
        "sourceHash": "e" * 64,
        "medians": {
            runtime: {case: 10.0 for case in cases}
            for runtime in ("python", "typescript")
        },
        "rawSamples": {
            runtime: {case: [10.0] * 5 for case in cases}
            for runtime in ("python", "typescript")
        },
        "maxPeakMiB": {
            runtime: {case: 100.0 for case in cases}
            for runtime in ("python", "typescript")
        },
        "rawPeakMiB": {
            runtime: {case: [100.0] * 5 for case in cases}
            for runtime in ("python", "typescript")
        },
    }


def test_calibration_artifact_a_is_auditable_but_applicability_uses_fingerprint() -> (
    None
):
    module = _load_script(SCRIPTS / "beta_benchmark_gate.py")
    baseline = _complete_baseline(module)
    candidate_b_fingerprint = module._baseline_fingerprint(baseline)

    module._validate_baseline(baseline, candidate_b_fingerprint)

    assert baseline["calibrationCommit"] == "a" * 40
    assert baseline["releaseManifestSha256"] == "b" * 64
    assert "commit" not in candidate_b_fingerprint
    assert "releaseManifestSha256" not in candidate_b_fingerprint


def test_full_candidate_b_report_uses_b_artifacts_not_calibration_a(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script(SCRIPTS / "beta_benchmark_gate.py")
    baseline_a = _complete_baseline(module)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline_a))
    output = tmp_path / "full.json"
    commit_b = "f" * 40
    manifest_b = "1" * 64
    identity_b = {
        "commit": commit_b,
        "releaseManifestSha256": manifest_b,
        "artifacts": {
            "python": {"sha256": "2" * 64},
            "typescript": {"sha256": "3" * 64},
        },
        "resolvedPackages": {
            "python": "/candidate-b/python",
            "typescript": "/candidate-b/typescript",
        },
        "typescriptConsumerLock": {
            "templateSha256": "4" * 64,
            "renderedSha256": "5" * 64,
        },
    }
    current = module._baseline_fingerprint(baseline_a)
    result = {
        "medianMs": 3.0,
        "maxPeakMiB": 95.0,
        "sampleResults": [
            {"durationMs": float(index), "peakMiB": 90.0 + index}
            for index in range(1, 6)
        ],
    }
    installed = SimpleNamespace(identity=lambda: identity_b)
    monkeypatch.setattr(module, "BASELINE_PATH", baseline_path)
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            mode="full",
            output=output,
            candidate_baseline=None,
            protected=True,
            artifacts_dir=tmp_path / "candidate-b",
            expected_commit=commit_b,
        ),
    )
    monkeypatch.setattr(
        module,
        "performance_provenance",
        lambda **_kwargs: {
            "commit": commit_b,
            "fingerprint": current,
            "protected": True,
        },
    )
    monkeypatch.setattr(
        module, "_installed_context", lambda _args: nullcontext(installed)
    )
    monkeypatch.setattr(module, "_run_case", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(module, "_absolute_failures", lambda *_args, **_kwargs: [])

    assert module.main() == 0

    report = json.loads(output.read_text())
    assert report["commit"] == commit_b
    assert report["releaseManifestSha256"] == manifest_b
    assert report["artifacts"] == identity_b["artifacts"]
    assert report["releaseManifestSha256"] != baseline_a["releaseManifestSha256"]
