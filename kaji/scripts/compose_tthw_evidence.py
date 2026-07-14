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


def _participant_receipt(path: Path, index: int) -> dict[str, Any]:
    receipt = validation.load_json(path, f"participant receipt {index}")
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


def _artifact_rows(artifacts_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in sorted(validation.EXPECTED_ARTIFACTS):
        package, version = validation.EXPECTED_ARTIFACTS[name]
        artifact = artifacts_dir / name
        if not artifact.is_file() or artifact.is_symlink():
            validation.fail("/artifacts", "artifact file is missing or unsafe")
        rows.append(
            {
                "name": name,
                "package": package,
                "version": version,
                "size": artifact.stat().st_size,
                "sha256": validation.sha256(artifact),
            }
        )
    return rows


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

    manifest = validation.load_json(release_manifest, "release manifest")
    timings = validation.load_json(automated_timings, "automated timings")
    runs = [
        _participant_receipt(path, index)
        for index, path in enumerate(participant_receipts, 1)
    ]
    runs.sort(key=lambda run: str(run.get("participantId", "")))

    document = {
        "schemaVersion": "1.0.0",
        "commit": manifest.get("commit"),
        "releaseManifestSha256": validation.sha256(release_manifest),
        "artifacts": _artifact_rows(artifacts_dir),
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
    parser.add_argument(
        "--participant",
        type=Path,
        action="append",
        required=True,
        help="one redacted participant receipt; supply exactly five",
    )
    parser.add_argument("--automated-timings", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
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
    print(
        "PASS: secret-ready TTHW evidence written "
        f"sha256={validation.sha256(args.output)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
