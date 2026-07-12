#!/usr/bin/env python3
"""Idempotently attach an exact, digest-verified GitHub prerelease asset set."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, NoReturn

from process_runner import (
    CommandBudget,
    CommandError,
    CommandExitError,
    CompletedCommand,
    run_checked,
)


RELEASE_NETWORK_BUDGET = CommandBudget(timeout_seconds=900)


def fail(message: str) -> NoReturn:
    raise SystemExit(f"FAIL: {message}")


def run(*command: str, check: bool = True) -> CompletedCommand:
    try:
        return run_checked(
            command,
            cwd=Path.cwd(),
            budget=RELEASE_NETWORK_BUDGET,
            capture=True,
            check=check,
        )
    except CommandExitError as error:
        fail(f"GitHub command failed with status {error.returncode}")
    except CommandError as error:
        fail(f"GitHub command failed: {error}")


def output(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def release(repo: str, tag: str) -> dict[str, Any] | None:
    completed = run("gh", "api", f"repos/{repo}/releases/tags/{tag}", check=False)
    if completed.returncode == 0:
        return json.loads(output(completed.stdout))
    if "HTTP 404" in output(completed.stderr):
        return None
    fail(f"could not read GitHub release: {output(completed.stderr).strip()}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def asset_map(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = metadata.get("assets")
    if not isinstance(assets, list) or any(
        not isinstance(item, dict) for item in assets
    ):
        fail("GitHub release returned malformed assets")
    names = [item.get("name") for item in assets]
    if any(not isinstance(name, str) for name in names) or len(names) != len(
        set(names)
    ):
        fail("GitHub release contains duplicate or malformed asset names")
    return {item["name"]: item for item in assets}


def verify_remote_asset(
    *, repo: str, tag: str, local: Path, remote: dict[str, Any], download_dir: Path
) -> None:
    expected = sha256(local)
    digest = remote.get("digest")
    if isinstance(digest, str) and digest:
        if digest != f"sha256:{expected}":
            fail(f"release asset digest mismatch for {local.name}")
        return
    destination = download_dir / local.name
    destination.unlink(missing_ok=True)
    completed = run(
        "gh",
        "release",
        "download",
        tag,
        "--repo",
        repo,
        "--pattern",
        local.name,
        "--dir",
        str(download_dir),
        check=False,
    )
    if completed.returncode != 0 or not destination.is_file():
        fail(f"could not download existing release asset {local.name}")
    if sha256(destination) != expected:
        fail(f"downloaded release asset digest mismatch for {local.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("asset", type=Path, nargs="+")
    args = parser.parse_args()

    desired: dict[str, Path] = {}
    for path in args.asset:
        if not path.is_file() or path.is_symlink():
            fail(f"release asset is not a regular file: {path}")
        if path.name in desired:
            fail(f"duplicate desired release asset name: {path.name}")
        desired[path.name] = path

    metadata = release(args.repo, args.tag)
    if metadata is None:
        completed = run(
            "gh",
            "release",
            "create",
            args.tag,
            "--repo",
            args.repo,
            "--prerelease",
            "--verify-tag",
            "--generate-notes",
            "--title",
            args.title,
            check=False,
        )
        if completed.returncode != 0:
            fail(
                f"could not create GitHub prerelease: {output(completed.stderr).strip()}"
            )
        metadata = release(args.repo, args.tag)
        if metadata is None:
            fail("created GitHub prerelease could not be read back")

    if (
        metadata.get("tag_name") != args.tag
        or metadata.get("prerelease") is not True
        or metadata.get("draft") is not False
        or metadata.get("name") != args.title
    ):
        fail("existing GitHub release is not the expected published prerelease")

    existing = asset_map(metadata)
    unexpected = set(existing) - set(desired)
    if unexpected:
        fail(f"GitHub release contains unexpected assets: {sorted(unexpected)}")

    with tempfile.TemporaryDirectory(prefix="kaji-release-assets-") as temporary:
        download_dir = Path(temporary)
        for name, path in desired.items():
            remote = existing.get(name)
            if remote is not None:
                verify_remote_asset(
                    repo=args.repo,
                    tag=args.tag,
                    local=path,
                    remote=remote,
                    download_dir=download_dir,
                )
                continue
            completed = run(
                "gh",
                "release",
                "upload",
                args.tag,
                "--repo",
                args.repo,
                str(path),
                check=False,
            )
            if completed.returncode != 0:
                fail(
                    f"could not upload missing release asset {name}: "
                    f"{output(completed.stderr).strip()}"
                )
            metadata = release(args.repo, args.tag)
            if metadata is None:
                fail("GitHub prerelease disappeared after asset upload")
            remote = asset_map(metadata).get(name)
            if remote is None:
                fail(f"uploaded release asset is missing: {name}")
            verify_remote_asset(
                repo=args.repo,
                tag=args.tag,
                local=path,
                remote=remote,
                download_dir=download_dir,
            )

    final = release(args.repo, args.tag)
    if final is None:
        fail("GitHub prerelease disappeared before final verification")
    final_assets = asset_map(final)
    if set(final_assets) != set(desired):
        fail("final GitHub release asset-name set differs from the desired set")
    with tempfile.TemporaryDirectory(prefix="kaji-release-final-") as temporary:
        download_dir = Path(temporary)
        for name, path in desired.items():
            verify_remote_asset(
                repo=args.repo,
                tag=args.tag,
                local=path,
                remote=final_assets[name],
                download_dir=download_dir,
            )
    print("PASS: GitHub prerelease contains exactly the digest-matched desired assets")


if __name__ == "__main__":
    main()
