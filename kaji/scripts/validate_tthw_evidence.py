#!/usr/bin/env python3
"""Validate exact-commit Kaji TTHW evidence without exposing user content."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import statistics
from typing import Any, NoReturn

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "kaji" / "contracts" / "release" / "tthw-evidence-v1.schema.json"
EXPECTED_ARTIFACTS = {
    "kaji_sdk-0.2.0b1-py3-none-any.whl": ("python", "0.2.0b1"),
    "kaji_sdk-0.2.0b1.tar.gz": ("python", "0.2.0b1"),
    "kaji-sdk-0.2.0-beta.7.tgz": ("typescript", "0.2.0-beta.7"),
}
PATH_ARTIFACTS = {
    "python": "kaji_sdk-0.2.0b1-py3-none-any.whl",
    "npm": "kaji-sdk-0.2.0-beta.7.tgz",
    "bun": "kaji-sdk-0.2.0-beta.7.tgz",
}
COMPATIBILITY_RECEIPT_FIELDS = {
    "artifactSha256",
    "artifacts",
    "commit",
    "conclusion",
    "failureCode",
    "githubPackageProofs",
    "releaseManifestSha256",
    "runtime",
    "schemaVersion",
    "timings",
    "toolchain",
    "workflowRun",
    "workflowRunAttempt",
}
TOOLCHAIN_FIELDS = {"python", "uv", "node", "npm", "bun", "typescript"}
TIMING_FIELDS = {"coldSetupToOutputMs", "warmRunMs"}
MAX_SAFE_INTEGER = 9_007_199_254_740_991
WORKFLOW_RUN = re.compile(r"https?://.+/actions/runs/[1-9][0-9]*")
SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
)
MAX_RELEASE_MANIFEST_BYTES = 1024 * 1024
STEP_ORDER = (
    "artifact-install",
    "scaffold-init",
    "no-key-run",
    "echo-setup",
    "echo-run",
)
EXPECTED_PATH_COUNTS = Counter({"python": 2, "npm": 2, "bun": 1})
MAX_REVIEW_AGE_DAYS = 7
PLACEHOLDER_MARKERS = (
    "replace-with",
    "replace-me",
    "placeholder",
    "unknown",
    "not-used",
    "unset",
    "todo",
    "tbd",
)
SENSITIVE_TEXT = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{8,}|api[_-]?key\s*[:=]|authorization\s*[:=]|bearer\s+[A-Za-z0-9._-]{8,})",
    re.IGNORECASE,
)


class EvidenceError(RuntimeError):
    pass


def fail(location: str, message: str) -> NoReturn:
    raise EvidenceError(f"{location}: {message}")


def pointer(parts: Any) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(encoded: bytes, label: str) -> dict[str, Any]:
    try:
        document = json.loads(encoded)
    except (UnicodeError, json.JSONDecodeError):
        fail("/", f"invalid {label}")
    if not isinstance(document, dict):
        fail("/", f"{label} must be an object")
    return document


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        encoded = path.read_bytes()
    except OSError:
        fail("/", f"invalid {label}")
    return _json_object(encoded, label)


def _is_placeholder(value: str) -> bool:
    normalized = value.casefold()
    return any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def _same_file(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_mode,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_mode,
    )


def _release_manifest_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size > MAX_RELEASE_MANIFEST_BYTES
            ):
                raise OSError
            encoded = stream.read(MAX_RELEASE_MANIFEST_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(encoded) > MAX_RELEASE_MANIFEST_BYTES or not _same_file(before, after):
            raise OSError
        return encoded
    except OSError:
        fail("/", "invalid release manifest")


def _artifact_identity(path: Path) -> tuple[int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise OSError
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        if size != before.st_size or not _same_file(before, after):
            raise OSError
        return size, digest.hexdigest()
    except OSError:
        fail("/artifacts", "artifact file is missing or unsafe")


def release_identity(
    release_manifest: Path, artifacts_dir: Path
) -> tuple[str, str, list[dict[str, Any]]]:
    manifest_bytes = _release_manifest_bytes(release_manifest)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = _json_object(manifest_bytes, "release manifest")
    commit = manifest.get("commit")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        fail("/commit", "release manifest commit is invalid")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        fail("/artifacts", "release manifest artifact list is missing")
    manifest_by_name = {
        entry.get("file"): entry for entry in entries if isinstance(entry, dict)
    }
    if (
        len(entries) != len(EXPECTED_ARTIFACTS)
        or len(manifest_by_name) != len(entries)
        or set(manifest_by_name) != set(EXPECTED_ARTIFACTS)
    ):
        fail("/artifacts", "release manifest artifact names differ")

    rows: list[dict[str, Any]] = []
    for name in sorted(EXPECTED_ARTIFACTS):
        package, version = EXPECTED_ARTIFACTS[name]
        artifact = artifacts_dir / name
        size, artifact_hash = _artifact_identity(artifact)
        row = {
            "name": name,
            "package": package,
            "version": version,
            "size": size,
            "sha256": artifact_hash,
        }
        manifest_entry = manifest_by_name[name]
        if any(
            manifest_entry.get(key) != value
            for key, value in {
                "package": package,
                "version": version,
                "commit": commit,
            }.items()
        ):
            fail("/artifacts", "release manifest artifact binding differs")
        if any(manifest_entry.get(key) != row[key] for key in ("size", "sha256")):
            fail("/artifacts", "retained artifact size/hash differs")
        rows.append(row)
    return commit, manifest_hash, rows


def _compatibility_timing(value: Any, location: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != TIMING_FIELDS:
        fail(location, "compatibility timing shape is invalid")
    for field in TIMING_FIELDS:
        duration = value[field]
        if type(duration) is not int or duration < 0 or duration > MAX_SAFE_INTEGER:
            fail(f"{location}/{field}", "compatibility timing is invalid")
    return {
        "coldSetupToOutputMs": value["coldSetupToOutputMs"],
        "warmRunMs": value["warmRunMs"],
    }


def _compatibility_toolchain(
    value: Any,
    *,
    runtime: str,
    runtime_version: str,
    location: str,
) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != TOOLCHAIN_FIELDS:
        fail(location, "compatibility toolchain shape is invalid")
    if any(
        not isinstance(item, str) or not item or len(item) > 80
        for item in value.values()
    ):
        fail(location, "compatibility toolchain value is invalid")
    if runtime == "python":
        if (
            value["python"] != runtime_version
            or value["uv"] != "0.11.25"
            or any(
                value[field] != "not-used"
                for field in ("node", "npm", "bun", "typescript")
            )
        ):
            fail(location, "Python compatibility toolchain differs")
    else:
        typescript = value["typescript"]
        current_typescript = (
            typescript.removeprefix("5.7.3 and ")
            if typescript.startswith("5.7.3 and ")
            else ""
        )
        if (
            value["python"] != "not-used"
            or value["uv"] != "not-used"
            or value["node"] != runtime_version
            or SEMVER.fullmatch(value["npm"]) is None
            or value["bun"] != "1.3.11"
            or SEMVER.fullmatch(current_typescript) is None
            or current_typescript == "5.7.3"
        ):
            fail(location, "Node compatibility toolchain differs")
    return {field: value[field] for field in sorted(TOOLCHAIN_FIELDS)}


def validate_closed_compatibility_receipt(
    receipt: dict[str, Any],
    *,
    runtime: str,
    expected_runtime_version: str,
    commit: str,
    manifest_hash: str,
    artifacts_by_name: dict[str, dict[str, Any]],
    expected_workflow_run: str,
    expected_workflow_run_attempt: int,
) -> tuple[dict[str, dict[str, int]], dict[str, str]]:
    location = f"/compatibility/{runtime}"
    if set(receipt) != COMPATIBILITY_RECEIPT_FIELDS:
        fail(location, "compatibility receipt shape is invalid")
    if (
        type(receipt.get("schemaVersion")) is not int
        or receipt.get("schemaVersion") != 1
        or receipt.get("conclusion") != "passed"
        or receipt.get("failureCode") is not None
    ):
        fail(location, "compatibility receipt did not pass")
    if receipt.get("commit") != commit:
        fail(f"{location}/commit", "compatibility commit differs")
    if receipt.get("releaseManifestSha256") != manifest_hash:
        fail(
            f"{location}/releaseManifestSha256",
            "compatibility release manifest differs",
        )
    if (
        type(receipt.get("workflowRunAttempt")) is not int
        or receipt.get("workflowRunAttempt") != expected_workflow_run_attempt
    ):
        fail(
            f"{location}/workflowRunAttempt",
            "compatibility workflow run attempt differs",
        )
    if receipt.get("workflowRun") != expected_workflow_run:
        fail(f"{location}/workflowRun", "compatibility workflow run differs")
    runtime_value = receipt.get("runtime")
    artifact_paths = receipt.get("artifacts")
    proofs = receipt.get("githubPackageProofs")
    timings = receipt.get("timings")
    if not isinstance(proofs, dict):
        fail(f"{location}/githubPackageProofs", "compatibility proofs are invalid")

    if runtime == "python":
        expected_names = (
            "kaji_sdk-0.2.0b1-py3-none-any.whl",
            "kaji_sdk-0.2.0b1.tar.gz",
        )
        if (
            not isinstance(runtime_value, dict)
            or set(runtime_value) != {"implementation", "version", "executable"}
            or runtime_value.get("implementation") != "CPython"
            or not isinstance(runtime_value.get("version"), str)
            or re.fullmatch(
                rf"{re.escape(expected_runtime_version)}[.][0-9]+",
                runtime_value["version"],
            )
            is None
            or not isinstance(runtime_value.get("executable"), str)
            or not runtime_value["executable"]
        ):
            fail(
                f"{location}/runtime",
                f"Python {expected_runtime_version} runtime is required",
            )
        if (
            not isinstance(artifact_paths, dict)
            or set(artifact_paths) != {"wheel", "sdist"}
            or Path(str(artifact_paths["wheel"])).name != expected_names[0]
            or Path(str(artifact_paths["sdist"])).name != expected_names[1]
        ):
            fail(f"{location}/artifacts", "Python compatibility artifacts differ")
        if set(proofs) != {"wheel", "sdist"}:
            fail(
                f"{location}/githubPackageProofs",
                "Python compatibility proofs are invalid",
            )
        if not isinstance(timings, dict) or set(timings) != {"wheel", "sdist"}:
            fail(f"{location}/timings", "Python compatibility timings are invalid")
        selected_timings = {
            name: _compatibility_timing(timings[name], f"{location}/timings/{name}")
            for name in ("wheel", "sdist")
        }
    else:
        expected_names = ("kaji-sdk-0.2.0-beta.7.tgz",)
        if (
            not isinstance(runtime_value, dict)
            or set(runtime_value) != {"version"}
            or not isinstance(runtime_value.get("version"), str)
            or re.fullmatch(
                rf"v{re.escape(expected_runtime_version)}[.][0-9]+[.][0-9]+",
                runtime_value["version"],
            )
            is None
        ):
            fail(
                f"{location}/runtime",
                f"Node {expected_runtime_version} runtime is required",
            )
        if (
            not isinstance(artifact_paths, dict)
            or set(artifact_paths) != {"tarball", "package"}
            or Path(str(artifact_paths["tarball"])).name != expected_names[0]
            or not isinstance(artifact_paths["package"], str)
            or not artifact_paths["package"]
        ):
            fail(f"{location}/artifacts", "Node compatibility artifacts differ")
        if (
            set(proofs) != {"npm", "bun"}
            or not isinstance(proofs["npm"], dict)
            or proofs["npm"] != proofs["bun"]
        ):
            fail(
                f"{location}/githubPackageProofs",
                "Node compatibility proofs are invalid",
            )
        if not isinstance(timings, dict) or set(timings) != {"npm", "bun"}:
            fail(f"{location}/timings", "Node compatibility timings are invalid")
        selected_timings = {
            name: _compatibility_timing(timings[name], f"{location}/timings/{name}")
            for name in ("npm", "bun")
        }

    expected_hashes = {
        name: artifacts_by_name[name]["sha256"] for name in expected_names
    }
    if receipt.get("artifactSha256") != expected_hashes:
        fail(f"{location}/artifactSha256", "compatibility artifact hashes differ")
    runtime_version = runtime_value["version"]
    toolchain = _compatibility_toolchain(
        receipt.get("toolchain"),
        runtime=runtime,
        runtime_version=runtime_version,
        location=f"{location}/toolchain",
    )
    if runtime == "node":
        declarations = proofs["npm"].get("typescriptDeclarationChecks")
        typescript_57 = (
            declarations.get("typescript57") if isinstance(declarations, dict) else None
        )
        typescript_current = (
            declarations.get("typescriptCurrent")
            if isinstance(declarations, dict)
            else None
        )
        if (
            not isinstance(typescript_57, dict)
            or not isinstance(typescript_current, dict)
            or toolchain["typescript"]
            != (
                f"{typescript_57.get('version')} and "
                f"{typescript_current.get('version')}"
            )
        ):
            fail(
                f"{location}/toolchain/typescript",
                "TypeScript toolchain differs from installed proof",
            )
    return selected_timings, toolchain


def automated_timings_from_compatibility_receipts(
    python_receipt: dict[str, Any],
    node_receipt: dict[str, Any],
    *,
    commit: str,
    manifest_hash: str,
    artifacts: list[dict[str, Any]],
    expected_workflow_run: str,
    expected_workflow_run_attempt: int,
) -> dict[str, dict[str, Any]]:
    if WORKFLOW_RUN.fullmatch(expected_workflow_run) is None:
        fail("/compatibility/workflowRun", "expected workflow run is invalid")
    if (
        type(expected_workflow_run_attempt) is not int
        or expected_workflow_run_attempt < 1
        or expected_workflow_run_attempt > MAX_SAFE_INTEGER
    ):
        fail(
            "/compatibility/workflowRunAttempt",
            "expected workflow run attempt is invalid",
        )
    artifacts_by_name = {row["name"]: row for row in artifacts}
    python_timings, python_toolchain = validate_closed_compatibility_receipt(
        python_receipt,
        runtime="python",
        expected_runtime_version="3.14",
        commit=commit,
        manifest_hash=manifest_hash,
        artifacts_by_name=artifacts_by_name,
        expected_workflow_run=expected_workflow_run,
        expected_workflow_run_attempt=expected_workflow_run_attempt,
    )
    node_timings, node_toolchain = validate_closed_compatibility_receipt(
        node_receipt,
        runtime="node",
        expected_runtime_version="24",
        commit=commit,
        manifest_hash=manifest_hash,
        artifacts_by_name=artifacts_by_name,
        expected_workflow_run=expected_workflow_run,
        expected_workflow_run_attempt=expected_workflow_run_attempt,
    )
    return {
        "python": {**python_timings["wheel"], "toolchain": python_toolchain},
        "npm": {**node_timings["npm"], "toolchain": node_toolchain},
        "bun": {**node_timings["bun"], "toolchain": node_toolchain},
    }


def validate_compatibility_receipts(
    document: dict[str, Any],
    python_receipt: dict[str, Any],
    node_receipt: dict[str, Any],
    *,
    expected_workflow_run: str,
    expected_workflow_run_attempt: int,
) -> None:
    expected = automated_timings_from_compatibility_receipts(
        python_receipt,
        node_receipt,
        commit=document["commit"],
        manifest_hash=document["releaseManifestSha256"],
        artifacts=document["artifacts"],
        expected_workflow_run=expected_workflow_run,
        expected_workflow_run_attempt=expected_workflow_run_attempt,
    )
    if document.get("automatedTimings") != expected:
        fail(
            "/automatedTimings",
            "must be derived from canonical compatibility receipts",
        )


def validate_document(document: dict[str, Any]) -> dict[str, int]:
    schema = load_json(SCHEMA, "TTHW schema")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (list(error.absolute_path), list(error.absolute_schema_path)),
    )
    if errors:
        first_error = errors[0]
        if list(first_error.absolute_path) == ["humanRuns"] and "allOf" in list(
            first_error.absolute_schema_path
        ):
            fail("/humanRuns", "exactly 2 Python, 2 npm, and 1 Bun runs are required")
        fail(pointer(first_error.absolute_path), "schema validation failed")

    artifacts = document["artifacts"]
    by_name = {entry["name"]: entry for entry in artifacts}
    if set(by_name) != set(EXPECTED_ARTIFACTS):
        fail("/artifacts", "exact artifact names are required")
    for name, (package, version) in EXPECTED_ARTIFACTS.items():
        if (by_name[name]["package"], by_name[name]["version"]) != (
            package,
            version,
        ):
            fail("/artifacts", "artifact package/version binding differs")

    runs = document["humanRuns"]
    participant_ids = [run["participantId"] for run in runs]
    if len(participant_ids) != len(set(participant_ids)):
        fail("/humanRuns", "participant pseudonyms must be distinct")
    if any(run["os"] != "macos" or run["architecture"] != "arm64" for run in runs):
        fail("/humanRuns", "every beta TTHW run must use arm64 macOS")
    if Counter(run["path"] for run in runs) != EXPECTED_PATH_COUNTS:
        fail("/humanRuns", "exactly 2 Python, 2 npm, and 1 Bun runs are required")

    artifacts_by_name = {entry["name"]: entry for entry in artifacts}
    collected_date = date.fromisoformat(document["collectedDate"])
    no_key_totals: list[int] = []
    echo_totals: list[int] = []
    for index, run in enumerate(runs):
        if _is_placeholder(run["participantId"]):
            fail(f"/humanRuns/{index}/participantId", "placeholder is not allowed")
        if _is_placeholder(run["owner"]):
            fail(f"/humanRuns/{index}/owner", "placeholder is not allowed")
        for field, value in run["toolchain"].items():
            if _is_placeholder(value):
                fail(
                    f"/humanRuns/{index}/toolchain/{field}",
                    "placeholder is not allowed",
                )
        if run["commit"] != document["commit"]:
            fail(f"/humanRuns/{index}/commit", "participant commit differs")
        if run["releaseManifestSha256"] != document["releaseManifestSha256"]:
            fail(
                f"/humanRuns/{index}/releaseManifestSha256",
                "participant release manifest differs",
            )
        expected_artifact = artifacts_by_name[PATH_ARTIFACTS[run["path"]]]
        for field in ("name", "package", "version", "sha256"):
            if run["artifact"][field] != expected_artifact[field]:
                fail(
                    f"/humanRuns/{index}/artifact/{field}",
                    "participant artifact binding differs",
                )
        names = tuple(step["name"] for step in run["steps"])
        if names != STEP_ORDER:
            fail(f"/humanRuns/{index}/steps", "step order differs")
        durations = [step["durationMs"] for step in run["steps"]]
        if run["noKeyTotalMs"] != sum(durations[:3]):
            fail(f"/humanRuns/{index}/noKeyTotalMs", "total differs from steps")
        if run["echoTotalMs"] != sum(durations):
            fail(f"/humanRuns/{index}/echoTotalMs", "total differs from steps")
        review_date = date.fromisoformat(run["reviewDate"])
        follow_up_date = date.fromisoformat(run["followUpDate"])
        if review_date > collected_date:
            fail(f"/humanRuns/{index}/reviewDate", "must not follow collectedDate")
        if (collected_date - review_date).days > MAX_REVIEW_AGE_DAYS:
            fail(
                f"/humanRuns/{index}/reviewDate",
                f"must be within {MAX_REVIEW_AGE_DAYS} days of collectedDate",
            )
        if follow_up_date < review_date:
            fail(f"/humanRuns/{index}/followUpDate", "must not precede review date")
        for item in run["confusion"]:
            if SENSITIVE_TEXT.search(item["summary"]) or SENSITIVE_TEXT.search(
                item["remediation"]
            ):
                fail(f"/humanRuns/{index}/confusion", "sensitive text is not redacted")
        no_key_totals.append(run["noKeyTotalMs"])
        echo_totals.append(run["echoTotalMs"])

    computed = {
        "noKeyMedianMs": int(statistics.median(no_key_totals)),
        "noKeyMaxMs": max(no_key_totals),
        "echoMedianMs": int(statistics.median(echo_totals)),
        "echoMaxMs": max(echo_totals),
    }
    if document["summary"] != computed:
        fail("/summary", "summary differs from recomputed median/maximum")
    if computed["noKeyMedianMs"] >= 300_000:
        fail("/summary/noKeyMedianMs", "must be under 300000")
    if computed["noKeyMaxMs"] >= 600_000:
        fail("/summary/noKeyMaxMs", "every run must be under 600000")
    if computed["echoMedianMs"] >= 600_000:
        fail("/summary/echoMedianMs", "must be under 600000")
    if computed["echoMaxMs"] >= 1_200_000:
        fail("/summary/echoMaxMs", "every run must be under 1200000")
    return computed


def validate_release_freshness(
    document: dict[str, Any], *, today: date | None = None
) -> None:
    validation_date = today or date.today()
    collected_date = date.fromisoformat(document["collectedDate"])
    if collected_date > validation_date:
        fail("/collectedDate", "must not be in the future")
    if (validation_date - collected_date).days > MAX_REVIEW_AGE_DAYS:
        fail(
            "/collectedDate",
            f"must be at most {MAX_REVIEW_AGE_DAYS} days old",
        )


def validate_bindings(
    document: dict[str, Any], release_manifest: Path, artifacts_dir: Path
) -> None:
    commit, manifest_hash, canonical_artifacts = release_identity(
        release_manifest, artifacts_dir
    )
    if manifest_hash != document["releaseManifestSha256"]:
        fail("/releaseManifestSha256", "release manifest hash differs")
    if commit != document["commit"]:
        fail("/commit", "release manifest commit differs")
    evidence_by_name = {entry["name"]: entry for entry in document["artifacts"]}
    canonical_by_name = {entry["name"]: entry for entry in canonical_artifacts}
    if set(evidence_by_name) != set(canonical_by_name):
        fail("/artifacts", "exact artifact names are required")
    for name, evidence in evidence_by_name.items():
        canonical = canonical_by_name[name]
        if any(evidence[field] != canonical[field] for field in ("size", "sha256")):
            fail("/artifacts", "retained artifact size/hash differs")
        if any(evidence[field] != canonical[field] for field in ("package", "version")):
            fail("/artifacts", "artifact package/version binding differs")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--python-compatibility-receipt", type=Path, required=True)
    parser.add_argument("--node-compatibility-receipt", type=Path, required=True)
    parser.add_argument("--expected-workflow-run", required=True)
    parser.add_argument(
        "--expected-workflow-run-attempt",
        type=int,
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        document = load_json(args.evidence, "TTHW evidence")
        summary = validate_document(document)
        validate_release_freshness(document)
        validate_bindings(document, args.release_manifest, args.artifacts_dir)
        validate_compatibility_receipts(
            document,
            load_json(
                args.python_compatibility_receipt,
                "Python 3.14 compatibility receipt",
            ),
            load_json(
                args.node_compatibility_receipt,
                "Node 24 compatibility receipt",
            ),
            expected_workflow_run=args.expected_workflow_run,
            expected_workflow_run_attempt=args.expected_workflow_run_attempt,
        )
    except EvidenceError as error:
        print(f"FAIL: {error}")
        return 1
    print(
        "PASS: exact-commit five-user TTHW evidence validated "
        f"no_key_median_ms={summary['noKeyMedianMs']} "
        f"no_key_max_ms={summary['noKeyMaxMs']} "
        f"echo_median_ms={summary['echoMedianMs']} "
        f"echo_max_ms={summary['echoMaxMs']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
