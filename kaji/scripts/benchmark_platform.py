#!/usr/bin/env python3
"""Measure and validate the protected beta benchmark runner."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import stat
from typing import Any


MAX_MANIFEST_BYTES = 64 * 1024
MACOS_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){1,2}")
SHA256 = re.compile(r"[0-9a-f]{64}")
RUNNER_KEYS = {
    "os",
    "arch",
    "platformVersion",
    "bootstrapManifestSha256",
}


class BenchmarkPlatformError(RuntimeError):
    """Protected benchmark runner provenance is invalid."""


def validate_retained_runner(value: Any) -> dict[str, str]:
    """Validate the closed runner shape without inspecting the current host."""
    if not isinstance(value, dict) or set(value) != RUNNER_KEYS:
        raise BenchmarkPlatformError("runner fingerprint must use the closed shape")
    if value.get("os") != "Darwin" or value.get("arch") != "arm64":
        raise BenchmarkPlatformError("runner fingerprint must describe arm64 macOS")
    version = value.get("platformVersion")
    if not isinstance(version, str) or MACOS_VERSION.fullmatch(version) is None:
        raise BenchmarkPlatformError(
            "runner fingerprint must contain a numeric macOS version"
        )
    manifest_hash = value.get("bootstrapManifestSha256")
    if not isinstance(manifest_hash, str) or SHA256.fullmatch(manifest_hash) is None:
        raise BenchmarkPlatformError(
            "runner fingerprint must contain a bootstrap manifest hash"
        )
    return {
        "os": "Darwin",
        "arch": "arm64",
        "platformVersion": version,
        "bootstrapManifestSha256": manifest_hash,
    }


def _manifest_bytes(path: str) -> bytes:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise BenchmarkPlatformError(
            "protected evidence requires a readable bootstrap manifest"
        ) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise BenchmarkPlatformError(
                "protected evidence requires a regular bootstrap manifest"
            )
        if before.st_size > MAX_MANIFEST_BYTES:
            raise BenchmarkPlatformError(
                "protected evidence requires a bootstrap manifest no larger than 64 KiB"
            )
        chunks: list[bytes] = []
        remaining = MAX_MANIFEST_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 16 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        encoded = b"".join(chunks)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
        if any(getattr(before, name) != getattr(after, name) for name in stable_fields):
            raise BenchmarkPlatformError(
                "protected evidence requires a stable bootstrap manifest"
            )
        if len(encoded) != before.st_size or len(encoded) > MAX_MANIFEST_BYTES:
            raise BenchmarkPlatformError(
                "protected evidence requires a stable bootstrap manifest"
            )
        return encoded
    finally:
        os.close(descriptor)


def verify_bootstrap_manifest_from_environment() -> str:
    path = os.environ.get("KAJI_BENCHMARK_RUNNER_MANIFEST")
    expected = os.environ.get("KAJI_BENCHMARK_RUNNER_MANIFEST_SHA256")
    if not path:
        raise BenchmarkPlatformError(
            "protected evidence requires a bootstrap manifest path"
        )
    if not isinstance(expected, str) or SHA256.fullmatch(expected) is None:
        raise BenchmarkPlatformError(
            "protected evidence requires a lowercase bootstrap manifest hash"
        )
    measured = hashlib.sha256(_manifest_bytes(path)).hexdigest()
    if measured != expected:
        raise BenchmarkPlatformError("bootstrap manifest hash does not match")
    return measured


def require_protected_macos_arm64(
    *, protected: bool, calibrating: bool
) -> dict[str, str] | None:
    """Measure the runner only when the result may become protected evidence."""
    if not (protected or calibrating):
        return None
    if os.environ.get("KAJI_BENCHMARK_PINNED_RUNNER") != "1":
        raise BenchmarkPlatformError("protected evidence requires the pinned runner")
    if platform.system() != "Darwin" or platform.machine().lower() != "arm64":
        raise BenchmarkPlatformError("protected evidence requires arm64 macOS")
    version = platform.mac_ver()[0]
    if MACOS_VERSION.fullmatch(version) is None:
        raise BenchmarkPlatformError(
            "protected evidence requires a numeric macOS version"
        )
    return validate_retained_runner(
        {
            "os": "Darwin",
            "arch": "arm64",
            "platformVersion": version,
            "bootstrapManifestSha256": (verify_bootstrap_manifest_from_environment()),
        }
    )


def runner_fingerprint(*, protected: bool, calibrating: bool) -> dict[str, str]:
    measured = require_protected_macos_arm64(
        protected=protected, calibrating=calibrating
    )
    if measured is not None:
        return measured
    return {
        "os": platform.system(),
        "arch": platform.machine().lower(),
        "platformVersion": platform.mac_ver()[0] or platform.release(),
        "bootstrapManifestSha256": "local-unpinned",
    }
