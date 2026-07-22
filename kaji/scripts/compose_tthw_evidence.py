#!/usr/bin/env python3
"""Compose validated, secret-ready Kaji TTHW evidence from retained receipts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import tempfile
from typing import Any

import validate_tthw_evidence as validation


ROOT = Path(__file__).resolve().parents[2]
PARTICIPANT_TEMPLATE = (
    ROOT / "kaji" / "contracts" / "release" / "tthw-participant.template.json"
)
PARTICIPANT_ARTIFACT_FIELDS = ("name", "package", "version", "sha256")


def _participant_receipt(
    path: Path,
    index: int,
    *,
    commit: str,
    manifest_hash: str,
    artifacts_by_name: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    receipt = validation.load_json(path, f"participant receipt {index}")
    location = f"/humanRuns/{index - 1}"
    path_name = receipt.get("path")
    if path_name not in validation.PATH_ARTIFACTS:
        validation.fail(f"{location}/path", "participant path is invalid")
    if receipt.get("commit") != commit:
        validation.fail(f"{location}/commit", "participant commit differs")
    if receipt.get("releaseManifestSha256") != manifest_hash:
        validation.fail(
            f"{location}/releaseManifestSha256",
            "participant release manifest differs",
        )
    artifact = receipt.get("artifact")
    if not isinstance(artifact, dict) or set(artifact) != set(
        PARTICIPANT_ARTIFACT_FIELDS
    ):
        validation.fail(f"{location}/artifact", "participant artifact is invalid")
    expected_artifact = artifacts_by_name[validation.PATH_ARTIFACTS[path_name]]
    for field in PARTICIPANT_ARTIFACT_FIELDS:
        if artifact[field] != expected_artifact[field]:
            validation.fail(
                f"{location}/artifact/{field}",
                "participant artifact binding differs",
            )
    steps = receipt.get("steps")
    if not isinstance(steps, list) or len(steps) != len(validation.STEP_ORDER):
        validation.fail(
            f"/humanRuns/{index - 1}/steps",
            "participant receipt must contain exactly five steps",
        )
    durations: list[int] = []
    for step_index, step in enumerate(steps):
        duration = step.get("durationMs") if isinstance(step, dict) else None
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            validation.fail(
                f"/humanRuns/{index - 1}/steps/{step_index}/durationMs",
                "must be a non-negative integer",
            )
        durations.append(duration)
    normalized = dict(receipt)
    normalized["noKeyTotalMs"] = sum(durations[:3])
    normalized["echoTotalMs"] = sum(durations)
    return normalized


def participant_template(
    *, path_name: str, release_manifest: Path, artifacts_dir: Path
) -> dict[str, Any]:
    if path_name not in validation.PATH_ARTIFACTS:
        validation.fail("/path", "participant path is invalid")
    commit, manifest_hash, artifacts = validation.release_identity(
        release_manifest, artifacts_dir
    )
    artifacts_by_name = {row["name"]: row for row in artifacts}
    artifact = artifacts_by_name[validation.PATH_ARTIFACTS[path_name]]
    template = validation.load_json(PARTICIPANT_TEMPLATE, "participant template")
    template.update(
        {
            "commit": commit,
            "releaseManifestSha256": manifest_hash,
            "artifact": {
                field: artifact[field] for field in PARTICIPANT_ARTIFACT_FIELDS
            },
            "path": path_name,
        }
    )
    return template


def _summary(runs: list[dict[str, Any]]) -> dict[str, int]:
    no_key_totals = [run["noKeyTotalMs"] for run in runs]
    echo_totals = [run["echoTotalMs"] for run in runs]
    return {
        "noKeyMedianMs": int(statistics.median(no_key_totals)),
        "noKeyMaxMs": max(no_key_totals),
        "echoMedianMs": int(statistics.median(echo_totals)),
        "echoMaxMs": max(echo_totals),
    }


def compose(
    *,
    participant_receipts: list[Path],
    automated_timings: Path,
    release_manifest: Path,
    artifacts_dir: Path,
) -> dict[str, Any]:
    if len(participant_receipts) != 5:
        validation.fail("/humanRuns", "exactly five participant receipts are required")

    commit, manifest_hash, artifacts = validation.release_identity(
        release_manifest, artifacts_dir
    )
    artifacts_by_name = {row["name"]: row for row in artifacts}
    timings = validation.load_json(automated_timings, "automated timings")
    runs = [
        _participant_receipt(
            path,
            index,
            commit=commit,
            manifest_hash=manifest_hash,
            artifacts_by_name=artifacts_by_name,
        )
        for index, path in enumerate(participant_receipts, 1)
    ]
    runs.sort(key=lambda run: str(run.get("participantId", "")))

    document = {
        "schemaVersion": "1.0.0",
        "commit": commit,
        "releaseManifestSha256": manifest_hash,
        "artifacts": artifacts,
        "automatedTimings": timings,
        "humanRuns": runs,
        "summary": _summary(runs),
    }
    validation.validate_document(document)
    validation.validate_bindings(document, release_manifest, artifacts_dir)
    return document


def write_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--participant",
        type=Path,
        action="append",
        help="one redacted participant receipt; supply exactly five",
    )
    mode.add_argument(
        "--generate-participant-template",
        choices=tuple(validation.PATH_ARTIFACTS),
        metavar="{python,npm,bun}",
        help="write a candidate-bound participant skeleton for this path",
    )
    parser.add_argument("--automated-timings", type=Path)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.participant is not None and args.automated_timings is None:
        parser.error("--automated-timings is required with --participant")
    if (
        args.generate_participant_template is not None
        and args.automated_timings is not None
    ):
        parser.error("--automated-timings is only valid with --participant")
    return args


def main() -> int:
    args = parse_args()
    try:
        path_name = getattr(args, "generate_participant_template", None)
        if path_name is not None:
            document = participant_template(
                path_name=path_name,
                release_manifest=args.release_manifest,
                artifacts_dir=args.artifacts_dir,
            )
        else:
            document = compose(
                participant_receipts=args.participant,
                automated_timings=args.automated_timings,
                release_manifest=args.release_manifest,
                artifacts_dir=args.artifacts_dir,
            )
        write_atomic(args.output, document)
    except validation.EvidenceError as error:
        print(f"FAIL: {error}")
        return 1
    except OSError:
        print("FAIL: TTHW evidence could not be read or written")
        return 1
    label = (
        "candidate-bound participant template"
        if path_name
        else "secret-ready TTHW evidence"
    )
    print(f"PASS: {label} written sha256={validation.sha256(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
