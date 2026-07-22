from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
from types import ModuleType

import pytest
from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "kaji/contracts/release/tthw-evidence-v1.schema.json"
VALIDATOR = REPO_ROOT / "kaji/scripts/validate_tthw_evidence.py"
ARTIFACTS = {
    "kaji_sdk-0.2.0b1-py3-none-any.whl": ("python", "0.2.0b1"),
    "kaji_sdk-0.2.0b1.tar.gz": ("python", "0.2.0b1"),
    "kaji-sdk-0.2.0-beta.2.tgz": ("typescript", "0.2.0-beta.2"),
}


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_tthw_evidence", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[dict, Path, Path]:
    commit = "a" * 40
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    artifact_rows = []
    manifest_rows = []
    for index, (name, (package, version)) in enumerate(ARTIFACTS.items(), 1):
        path = artifacts_dir / name
        path.write_bytes(f"synthetic-artifact-{index}".encode())
        row = {
            "name": name,
            "package": package,
            "version": version,
            "size": path.stat().st_size,
            "sha256": _sha(path),
        }
        artifact_rows.append(row)
        manifest_rows.append(
            {
                "file": name,
                "package": package,
                "version": version,
                "size": row["size"],
                "sha256": row["sha256"],
                "commit": commit,
            }
        )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"commit": commit, "artifacts": manifest_rows}))
    manifest_hash = _sha(manifest_path)
    artifacts_by_name = {row["name"]: row for row in artifact_rows}

    toolchain = {
        "python": "3.14.6",
        "uv": "0.11.25",
        "node": "24.4.1",
        "npm": "11.4.2",
        "bun": "1.3.14",
        "typescript": "5.7.3 and 6.0.3",
    }
    paths = ["python", "npm", "bun", "python", "npm"]
    no_key_totals = [100_000, 110_000, 120_000, 130_000, 140_000]
    echo_totals = [400_000, 420_000, 440_000, 460_000, 480_000]
    runs = []
    for index, (path, no_key, echo) in enumerate(
        zip(paths, no_key_totals, echo_totals, strict=True), 1
    ):
        first = [no_key // 5, no_key // 5, no_key - 2 * (no_key // 5)]
        remaining = echo - no_key
        durations = [*first, remaining // 2, remaining - remaining // 2]
        artifact_name = (
            "kaji_sdk-0.2.0b1-py3-none-any.whl"
            if path == "python"
            else "kaji-sdk-0.2.0-beta.2.tgz"
        )
        artifact = artifacts_by_name[artifact_name]
        runs.append(
            {
                "participantId": f"user-{index:03d}",
                "commit": commit,
                "releaseManifestSha256": manifest_hash,
                "artifact": {
                    key: artifact[key]
                    for key in ("name", "package", "version", "sha256")
                },
                "os": "macos",
                "architecture": "arm64",
                "platformVersion": "15.5",
                "path": path,
                "cleanEnvironment": True,
                "noSourceCheckout": True,
                "toolchain": toolchain,
                "steps": [
                    {"name": name, "durationMs": duration}
                    for name, duration in zip(
                        (
                            "artifact-install",
                            "scaffold-init",
                            "no-key-run",
                            "echo-setup",
                            "echo-run",
                        ),
                        durations,
                        strict=True,
                    )
                ],
                "noKeyTotalMs": no_key,
                "echoTotalMs": echo,
                "assertions": {
                    "deterministicText": True,
                    "nonEmptyTurnId": True,
                    "positiveSequence": True,
                    "echoToolRequested": True,
                    "echoToolStarted": True,
                    "echoToolCompleted": True,
                    "echoResultObserved": True,
                },
                "confusion": [
                    {
                        "summary": "A redacted synthetic usability note.",
                        "remediation": "A redacted synthetic docs change.",
                    }
                ],
                "redacted": True,
                "owner": "kaji-maintainer",
                "reviewDate": "2026-07-12",
                "followUpDate": "2026-08-11",
            }
        )
    document = {
        "schemaVersion": "1.0.0",
        "commit": commit,
        "releaseManifestSha256": manifest_hash,
        "artifacts": artifact_rows,
        "automatedTimings": {
            name: {
                "coldSetupToOutputMs": 10_000,
                "warmRunMs": 500,
                "toolchain": toolchain,
            }
            for name in ("python", "npm", "bun")
        },
        "humanRuns": runs,
        "summary": {
            "noKeyMedianMs": int(statistics.median(no_key_totals)),
            "noKeyMaxMs": max(no_key_totals),
            "echoMedianMs": int(statistics.median(echo_totals)),
            "echoMaxMs": max(echo_totals),
        },
    }
    return document, manifest_path, artifacts_dir


def test_synthetic_exact_commit_evidence_validates(tmp_path: Path) -> None:
    module = _module()
    document, manifest, artifacts = _fixture(tmp_path)

    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text()))
    assert module.validate_document(document) == document["summary"]
    module.validate_bindings(document, manifest, artifacts)


def test_validator_requires_five_distinct_pseudonyms(tmp_path: Path) -> None:
    module = _module()
    document, _manifest, _artifacts = _fixture(tmp_path)
    document["humanRuns"][1]["participantId"] = document["humanRuns"][0][
        "participantId"
    ]

    with pytest.raises(module.EvidenceError, match="pseudonyms must be distinct"):
        module.validate_document(document)


def test_validator_requires_arm64_macos_and_package_manager_coverage(
    tmp_path: Path,
) -> None:
    module = _module()
    valid, _manifest, _artifacts = _fixture(tmp_path)
    document = deepcopy(valid)
    document["humanRuns"][0]["os"] = "linux"

    with pytest.raises(module.EvidenceError, match="/humanRuns/0/os"):
        module.validate_document(document)

    document = deepcopy(valid)
    document["humanRuns"][0]["architecture"] = "x86_64"
    with pytest.raises(module.EvidenceError, match="/humanRuns/0/architecture"):
        module.validate_document(document)

    document = deepcopy(valid)
    for run in document["humanRuns"]:
        if run["path"] == "bun":
            run["path"] = "npm"
    with pytest.raises(module.EvidenceError, match="Python, npm, and Bun"):
        module.validate_document(document)


@pytest.mark.parametrize(
    ("field", "value", "pointer"),
    [
        ("architecture", None, "/humanRuns/0"),
        ("platformVersion", None, "/humanRuns/0"),
        ("platformVersion", "Sonoma", "/humanRuns/0/platformVersion"),
    ],
)
def test_validator_requires_measured_macos_platform_identity(
    tmp_path: Path, field: str, value: str | None, pointer: str
) -> None:
    module = _module()
    document, _manifest, _artifacts = _fixture(tmp_path)
    if value is None:
        del document["humanRuns"][0][field]
    else:
        document["humanRuns"][0][field] = value

    with pytest.raises(module.EvidenceError, match=pointer):
        module.validate_document(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "kaji_sdk-0.2.0b1.tar.gz"),
        ("package", "typescript"),
        ("version", "0.2.0-beta.2"),
        ("sha256", "f" * 64),
    ],
)
def test_validator_rejects_wrong_participant_artifact_binding(
    tmp_path: Path, field: str, value: str
) -> None:
    module = _module()
    document, _manifest, _artifacts = _fixture(tmp_path)
    document["humanRuns"][0]["artifact"][field] = value

    with pytest.raises(module.EvidenceError, match=f"/humanRuns/0/artifact/{field}"):
        module.validate_document(document)


def test_validator_rejects_stale_participant_candidate_identity(tmp_path: Path) -> None:
    module = _module()
    document, _manifest, _artifacts = _fixture(tmp_path)
    stale = deepcopy(document)
    stale["humanRuns"][0]["commit"] = "b" * 40
    with pytest.raises(module.EvidenceError, match="/humanRuns/0/commit"):
        module.validate_document(stale)

    foreign = deepcopy(document)
    foreign["humanRuns"][0]["releaseManifestSha256"] = "c" * 64
    with pytest.raises(
        module.EvidenceError, match="/humanRuns/0/releaseManifestSha256"
    ):
        module.validate_document(foreign)


def test_validator_recomputes_totals_and_thresholds(tmp_path: Path) -> None:
    module = _module()
    document, _manifest, _artifacts = _fixture(tmp_path)
    mismatched = deepcopy(document)
    mismatched["humanRuns"][0]["noKeyTotalMs"] += 1
    with pytest.raises(module.EvidenceError, match="total differs from steps"):
        module.validate_document(mismatched)

    too_slow = deepcopy(document)
    for run in too_slow["humanRuns"]:
        extra = 300_000 - run["noKeyTotalMs"]
        run["steps"][2]["durationMs"] += extra
        run["noKeyTotalMs"] += extra
        run["echoTotalMs"] += extra
    too_slow["summary"] = {
        "noKeyMedianMs": 300_000,
        "noKeyMaxMs": 300_000,
        "echoMedianMs": 620_000,
        "echoMaxMs": 640_000,
    }
    with pytest.raises(module.EvidenceError, match="must be under 300000"):
        module.validate_document(too_slow)


def test_validator_rejects_sensitive_confusion_text(tmp_path: Path) -> None:
    module = _module()
    document, _manifest, _artifacts = _fixture(tmp_path)
    document["humanRuns"][0]["confusion"][0]["summary"] = (
        "API_KEY=should-have-been-redacted"
    )

    with pytest.raises(module.EvidenceError, match="sensitive text"):
        module.validate_document(document)


def test_validator_recomputes_retained_artifact_hashes(tmp_path: Path) -> None:
    module = _module()
    document, manifest, artifacts = _fixture(tmp_path)
    (artifacts / "kaji-sdk-0.2.0-beta.2.tgz").write_bytes(b"tampered")

    with pytest.raises(module.EvidenceError, match="retained artifact size/hash"):
        module.validate_bindings(document, manifest, artifacts)


def test_release_identity_hashes_and_parses_one_manifest_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _document, manifest, artifacts = _fixture(tmp_path)
    original_hash = _sha(manifest)
    original_sha256 = module.sha256

    def mutate_after_hash(path: Path) -> str:
        digest = original_sha256(path)
        if path == manifest:
            changed = json.loads(manifest.read_text())
            changed["commit"] = "b" * 40
            for entry in changed["artifacts"]:
                entry["commit"] = "b" * 40
            manifest.write_text(json.dumps(changed))
        return digest

    monkeypatch.setattr(module, "sha256", mutate_after_hash)

    commit, manifest_hash, _artifacts = module.release_identity(manifest, artifacts)

    assert commit == "a" * 40
    assert manifest_hash == original_hash
