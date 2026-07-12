#!/usr/bin/env python3
"""Poll registries and verify the published beta bytes against the manifest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from process_runner import (
    METADATA_BUDGET,
    CommandError,
    run_checked,
)


PYPI_URL = "https://pypi.org/pypi/kaji/0.2.0b1/json"
NPM_SPEC = "@kaji/sdk@0.2.0-beta.1"
NPM_REGISTRY = "https://registry.npmjs.org/"
USER_AGENT = "kaji-beta-release-verifier/1"


class VerificationMismatch(RuntimeError):
    """The registry returned immutable metadata/bytes that do not match."""


def fail(message: str) -> NoReturn:
    raise SystemExit(f"FAIL: {message}")


def fetch(
    url: str, *, allowed_host: str | None = None, max_bytes: int = 2 * 1024 * 1024
) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        final = urllib.parse.urlparse(response.geturl())
        if allowed_host is not None and (
            final.scheme != "https" or final.hostname != allowed_host
        ):
            raise VerificationMismatch(
                "registry download redirected outside the expected host"
            )
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError as error:
                raise VerificationMismatch(
                    "registry response has an invalid content length"
                ) from error
            if declared_length < 0 or declared_length > max_bytes:
                raise VerificationMismatch(
                    "registry response exceeds the expected size cap"
                )
        payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise VerificationMismatch(
                "registry response exceeds the expected size cap"
            )
        return payload


def manifest_data(
    artifacts: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = json.loads((artifacts / "manifest.json").read_text())
    return manifest, {entry["file"]: entry for entry in manifest["artifacts"]}


def verify_pypi(entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    metadata = json.loads(fetch(PYPI_URL))
    expected_names = {
        name for name, entry in entries.items() if entry["package"] == "python"
    }
    urls = metadata.get("urls")
    if (
        not isinstance(urls, list)
        or {item.get("filename") for item in urls} != expected_names
    ):
        raise VerificationMismatch("PyPI published file set differs from manifest")
    for item in urls:
        entry = entries[item["filename"]]
        digest = item.get("digests", {}).get("sha256")
        if digest != entry["sha256"] or item.get("size") != entry["size"]:
            raise VerificationMismatch(
                f"PyPI digest/size mismatch for {item['filename']}"
            )
    return {
        "metadataUrl": PYPI_URL,
        "files": [
            {
                "filename": name,
                "sha256": entries[name]["sha256"],
                "size": entries[name]["size"],
            }
            for name in sorted(expected_names)
        ],
    }


def parse_integrity(integrity: str) -> tuple[str, bytes]:
    token = integrity.split()[0]
    algorithm, separator, encoded = token.partition("-")
    if not separator or algorithm not in hashlib.algorithms_available:
        raise VerificationMismatch("npm returned an unsupported integrity value")
    try:
        return algorithm, base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise VerificationMismatch(
            "npm returned malformed integrity metadata"
        ) from error


def verify_npm(entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    completed = run_checked(
        ["npm", "view", NPM_SPEC, "dist", "--json", f"--registry={NPM_REGISTRY}"],
        cwd=Path.cwd(),
        budget=METADATA_BUDGET,
        capture=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("npm metadata is not available yet")
    dist = json.loads(completed.stdout.decode("utf-8"))
    tarball_url = dist.get("tarball")
    integrity = dist.get("integrity")
    if not isinstance(tarball_url, str) or not isinstance(integrity, str):
        raise VerificationMismatch("npm dist metadata omits tarball or integrity")
    parsed = urllib.parse.urlparse(tarball_url)
    if parsed.scheme != "https" or parsed.hostname != "registry.npmjs.org":
        raise VerificationMismatch("npm tarball URL is outside the expected registry")
    entry = entries["kaji-sdk-0.2.0-beta.1.tgz"]
    payload = fetch(
        tarball_url,
        allowed_host="registry.npmjs.org",
        max_bytes=entry["size"],
    )
    if (
        len(payload) != entry["size"]
        or hashlib.sha256(payload).hexdigest() != entry["sha256"]
    ):
        raise VerificationMismatch("downloaded npm tarball differs from manifest")
    algorithm, expected_integrity = parse_integrity(integrity)
    if hashlib.new(algorithm, payload).digest() != expected_integrity:
        raise VerificationMismatch("downloaded npm tarball fails registry integrity")
    shasum = dist.get("shasum")
    if isinstance(shasum, str) and hashlib.sha1(payload).hexdigest() != shasum:  # noqa: S324
        raise VerificationMismatch("downloaded npm tarball fails registry shasum")
    return {
        "filename": entry["file"],
        "integrity": integrity,
        "tarball": tarball_url,
        "sha256": entry["sha256"],
        "size": entry["size"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--initial-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=20.0)
    args = parser.parse_args()
    if args.attempts < 1 or args.initial_delay < 0 or args.max_delay < 0:
        fail("polling bounds must be non-negative and attempts must be positive")
    manifest, entries = manifest_data(args.artifacts_dir)

    for attempt in range(1, args.attempts + 1):
        try:
            pypi = verify_pypi(entries)
            npm = verify_npm(entries)
        except (
            VerificationMismatch,
            OSError,
            RuntimeError,
            CommandError,
            urllib.error.URLError,
            json.JSONDecodeError,
        ) as error:
            if attempt == args.attempts:
                fail(
                    f"registry verification did not converge after {args.attempts} attempts: "
                    f"{type(error).__name__}: {error}"
                )
            delay = min(args.initial_delay * (2 ** (attempt - 1)), args.max_delay)
            print(
                f"Registry evidence unavailable (attempt {attempt}/{args.attempts}); retrying in {delay:g}s"
            )
            time.sleep(delay)
            continue
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "status": "verified",
                    "manifestCommit": manifest["commit"],
                    "packages": manifest["packages"],
                    "verifiedAt": datetime.now(UTC).isoformat(),
                    "attempt": attempt,
                    "attemptLimit": args.attempts,
                    "pypi": pypi,
                    "npm": npm,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        print(
            "PASS: published PyPI digests and npm tarball/integrity match the manifest"
        )
        return


if __name__ == "__main__":
    main()
