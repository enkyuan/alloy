#!/usr/bin/env python3
"""Measure and validate the protected beta benchmark runner."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
from typing import Any


MAX_IMAGE_DATA_BYTES = 8 * 1024
IMAGE_DATA_PATH = Path.home() / "imagedata.json"
EXPECTED_IMAGE_OS = "macos15"
EXPECTED_IMAGE_LABEL = "macos-15-arm64"
MACOS_VERSION = re.compile(r"15\.[0-9]+(?:\.[0-9]+)?")
MACOS_BUILD = re.compile(r"[0-9]{2}[A-Z][0-9A-Z]+")
IMAGE_VERSION = re.compile(r"[0-9]{8}\.[0-9]+(?:\.[0-9]+)?")
SHA256 = re.compile(r"[0-9a-f]{64}")
RUNNER_KEYS = {
    "environment",
    "os",
    "arch",
    "platformVersion",
    "imageOS",
    "imageLabel",
    "imageVersion",
    "imageDataSha256",
}


class BenchmarkPlatformError(RuntimeError):
    """Protected benchmark runner provenance is invalid."""


def validate_retained_runner(value: Any) -> dict[str, str]:
    """Validate the closed hosted-runner shape without inspecting the host."""
    if type(value) is not dict or set(value) != RUNNER_KEYS:
        raise BenchmarkPlatformError("runner fingerprint must use the closed shape")
    if value.get("environment") != "github-hosted":
        raise BenchmarkPlatformError(
            "runner fingerprint must describe a GitHub-hosted runner"
        )
    if value.get("os") != "Darwin" or value.get("arch") != "arm64":
        raise BenchmarkPlatformError("runner fingerprint must describe arm64 macOS")
    version = value.get("platformVersion")
    if not isinstance(version, str) or MACOS_VERSION.fullmatch(version) is None:
        raise BenchmarkPlatformError(
            "runner fingerprint must contain a macOS 15 version"
        )
    if value.get("imageOS") != EXPECTED_IMAGE_OS:
        raise BenchmarkPlatformError(
            f"runner fingerprint ImageOS must be {EXPECTED_IMAGE_OS}"
        )
    if value.get("imageLabel") != EXPECTED_IMAGE_LABEL:
        raise BenchmarkPlatformError(
            f"runner fingerprint image label must be {EXPECTED_IMAGE_LABEL}"
        )
    image_version = value.get("imageVersion")
    if (
        not isinstance(image_version, str)
        or IMAGE_VERSION.fullmatch(image_version) is None
    ):
        raise BenchmarkPlatformError(
            "runner fingerprint must contain a GitHub image version"
        )
    image_data_hash = value.get("imageDataSha256")
    if (
        not isinstance(image_data_hash, str)
        or SHA256.fullmatch(image_data_hash) is None
    ):
        raise BenchmarkPlatformError(
            "runner fingerprint must contain an image data hash"
        )
    return {
        "environment": "github-hosted",
        "os": "Darwin",
        "arch": "arm64",
        "platformVersion": version,
        "imageOS": EXPECTED_IMAGE_OS,
        "imageLabel": EXPECTED_IMAGE_LABEL,
        "imageVersion": image_version,
        "imageDataSha256": image_data_hash,
    }


def _stable_regular_file_bytes(path: Path) -> bytes:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise BenchmarkPlatformError(
            "protected evidence cannot safely read GitHub runner image data"
        )
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | no_follow
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise BenchmarkPlatformError(
            "protected evidence requires readable GitHub runner image data"
        ) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise BenchmarkPlatformError(
                "protected evidence requires regular GitHub runner image data"
            )
        if before.st_size > MAX_IMAGE_DATA_BYTES:
            raise BenchmarkPlatformError(
                "protected evidence requires GitHub runner image data no larger "
                "than 8 KiB"
            )
        chunks: list[bytes] = []
        remaining = MAX_IMAGE_DATA_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        encoded = b"".join(chunks)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
        if any(getattr(before, name) != getattr(after, name) for name in stable_fields):
            raise BenchmarkPlatformError(
                "protected evidence requires stable GitHub runner image data"
            )
        if len(encoded) != before.st_size or len(encoded) > MAX_IMAGE_DATA_BYTES:
            raise BenchmarkPlatformError(
                "protected evidence requires stable GitHub runner image data"
            )
        return encoded
    finally:
        os.close(descriptor)


def _reject_json_constant(_value: str) -> None:
    raise BenchmarkPlatformError(
        "GitHub runner image data contains a non-finite number"
    )


def _reject_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise BenchmarkPlatformError(
                "GitHub runner image data contains a duplicate key"
            )
        result[key] = value
    return result


def _decode_image_data(encoded: bytes) -> list[dict[str, str]]:
    try:
        value = json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BenchmarkPlatformError(
            "GitHub runner image data is malformed JSON"
        ) from error
    if type(value) is not list or len(value) != 2:
        raise BenchmarkPlatformError(
            "GitHub runner image data must contain exactly two rows"
        )
    rows: list[dict[str, str]] = []
    for row in value:
        if (
            type(row) is not dict
            or set(row) != {"group", "detail"}
            or not all(isinstance(item, str) for item in row.values())
        ):
            raise BenchmarkPlatformError(
                "GitHub runner image data rows must use the closed string shape"
            )
        rows.append(row)
    if [row["group"] for row in rows] != ["Operating System", "Runner Image"]:
        raise BenchmarkPlatformError("GitHub runner image data groups are invalid")
    return rows


def _prefixed_line(line: str, prefix: str) -> str:
    if not line.startswith(prefix):
        raise BenchmarkPlatformError("GitHub runner image data detail is invalid")
    value = line[len(prefix) :]
    if not value:
        raise BenchmarkPlatformError("GitHub runner image data detail is invalid")
    return value


def _validated_image_data(
    image_data_path: Path | None = None,
) -> tuple[dict[str, str], bytes]:
    path = IMAGE_DATA_PATH if image_data_path is None else image_data_path
    if not path.is_absolute():
        raise BenchmarkPlatformError("GitHub runner image data path must be absolute")
    encoded = _stable_regular_file_bytes(path)
    operating_system, runner_image = _decode_image_data(encoded)
    os_detail = operating_system["detail"].splitlines()
    if (
        len(os_detail) != 3
        or os_detail[0] != "macOS"
        or MACOS_VERSION.fullmatch(os_detail[1]) is None
        or MACOS_BUILD.fullmatch(os_detail[2]) is None
    ):
        raise BenchmarkPlatformError(
            "GitHub runner image data operating system detail is invalid"
        )

    image_detail = runner_image["detail"].splitlines()
    if len(image_detail) != 4:
        raise BenchmarkPlatformError(
            "GitHub runner image data runner detail is invalid"
        )
    image_label = _prefixed_line(image_detail[0], "Image: ")
    image_version = _prefixed_line(image_detail[1], "Version: ")
    included_software = _prefixed_line(image_detail[2], "Included Software: ")
    image_release = _prefixed_line(image_detail[3], "Image Release: ")
    if image_label != EXPECTED_IMAGE_LABEL:
        raise BenchmarkPlatformError(
            f"GitHub runner image data label must be {EXPECTED_IMAGE_LABEL}"
        )
    if IMAGE_VERSION.fullmatch(image_version) is None:
        raise BenchmarkPlatformError("GitHub runner image data version is invalid")
    release_version = ".".join(image_version.split(".")[:2])
    expected_software = (
        "https://github.com/actions/runner-images/blob/"
        f"{image_label}/{release_version}/images/macos/{image_label}-Readme.md"
    )
    expected_release = (
        "https://github.com/actions/runner-images/releases/tag/"
        f"{image_label}%2F{release_version}"
    )
    if included_software != expected_software or image_release != expected_release:
        raise BenchmarkPlatformError("GitHub runner image data URLs are invalid")
    image_os_environment = os.environ.get("ImageOS")
    if image_os_environment is not None and image_os_environment != EXPECTED_IMAGE_OS:
        raise BenchmarkPlatformError(
            f"protected evidence requires ImageOS={EXPECTED_IMAGE_OS}"
        )
    image_version_environment = os.environ.get("ImageVersion")
    if (
        image_version_environment is not None
        and image_version_environment != image_version
    ):
        raise BenchmarkPlatformError(
            "protected evidence requires ImageVersion to match image data"
        )
    return (
        {
            "environment": "github-hosted",
            "os": "Darwin",
            "arch": "arm64",
            "platformVersion": os_detail[1],
            "imageOS": EXPECTED_IMAGE_OS,
            "imageLabel": image_label,
            "imageVersion": image_version,
            "imageDataSha256": hashlib.sha256(encoded).hexdigest(),
        },
        encoded,
    )


def require_github_hosted_macos_arm64(
    *,
    protected: bool,
    calibrating: bool,
    image_data_path: Path | None = None,
) -> dict[str, str] | None:
    """Measure GitHub-hosted provenance only for protected evidence."""
    if not (protected or calibrating):
        return None
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise BenchmarkPlatformError("protected evidence requires GitHub Actions")
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise BenchmarkPlatformError(
            "protected evidence requires a GitHub-hosted runner"
        )
    if os.environ.get("RUNNER_OS") != "macOS":
        raise BenchmarkPlatformError("protected evidence requires runner OS macOS")
    if os.environ.get("RUNNER_ARCH") != "ARM64":
        raise BenchmarkPlatformError(
            "protected evidence requires runner architecture ARM64"
        )
    if platform.system() != "Darwin" or platform.machine().lower() != "arm64":
        raise BenchmarkPlatformError("protected evidence requires arm64 macOS")
    version = platform.mac_ver()[0]
    if MACOS_VERSION.fullmatch(version) is None:
        raise BenchmarkPlatformError("protected evidence requires a macOS 15 version")
    measured, _encoded = _validated_image_data(image_data_path)
    if measured["platformVersion"] != version:
        raise BenchmarkPlatformError(
            "GitHub runner image data macOS version does not match the host"
        )
    return validate_retained_runner(measured)


def _write_new_regular_file(path: Path, encoded: bytes) -> None:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory is None:
        raise BenchmarkPlatformError(
            "protected evidence cannot safely retain GitHub runner image data"
        )
    parent_flags = os.O_RDONLY | directory | no_follow | getattr(os, "O_CLOEXEC", 0)
    try:
        parent_descriptor = os.open(path.parent, parent_flags)
    except OSError as error:
        raise BenchmarkPlatformError(
            "protected evidence could not retain GitHub runner image data"
        ) from error
    descriptor: int | None = None
    try:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | no_follow
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            descriptor = os.open(
                path.name,
                flags,
                0o600,
                dir_fd=parent_descriptor,
            )
        except OSError as error:
            raise BenchmarkPlatformError(
                "protected evidence could not retain GitHub runner image data"
            ) from error
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size != 0:
            raise BenchmarkPlatformError(
                "protected evidence requires a new regular retained image data file"
            )
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written <= 0:
                raise BenchmarkPlatformError(
                    "protected evidence could not retain complete image data"
                )
            offset += written
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size != len(encoded)
        ):
            raise BenchmarkPlatformError(
                "protected evidence could not retain stable image data"
            )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_descriptor)


def retain_github_image_data(destination: Path, *, image_data_sha256: str) -> str:
    """Retain exact validated image metadata without overwriting any path."""
    if SHA256.fullmatch(image_data_sha256) is None:
        raise BenchmarkPlatformError(
            "retained image data hash must be 64 lowercase hex characters"
        )
    measured, encoded = _validated_image_data()
    if measured["imageDataSha256"] != image_data_sha256:
        raise BenchmarkPlatformError(
            "GitHub runner image data hash does not match the runner fingerprint"
        )
    _write_new_regular_file(destination, encoded)
    retained = _stable_regular_file_bytes(destination)
    if retained != encoded or hashlib.sha256(retained).hexdigest() != image_data_sha256:
        raise BenchmarkPlatformError(
            "retained GitHub runner image data does not match its fingerprint"
        )
    return image_data_sha256


def retain_reported_github_image_data(report: Path) -> Path:
    """Retain image metadata beside a report using its closed runner fingerprint."""
    try:
        value = json.loads(
            report.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
        runner = value["fingerprint"]["runner"]
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as error:
        raise BenchmarkPlatformError(
            "performance report has no valid runner fingerprint"
        ) from error
    measured = validate_retained_runner(runner)
    destination = report.with_name("imagedata.json")
    retain_github_image_data(
        destination,
        image_data_sha256=measured["imageDataSha256"],
    )
    return destination


def runner_fingerprint(
    *,
    protected: bool,
    calibrating: bool,
    image_data_path: Path | None = None,
) -> dict[str, str]:
    measured = require_github_hosted_macos_arm64(
        protected=protected,
        calibrating=calibrating,
        image_data_path=image_data_path,
    )
    if measured is not None:
        return measured
    return {
        "environment": "local",
        "os": platform.system(),
        "arch": platform.machine().lower(),
        "platformVersion": platform.mac_ver()[0] or platform.release(),
        "imageOS": "local-unpinned",
        "imageLabel": "local-unpinned",
        "imageVersion": "local-unpinned",
        "imageDataSha256": "local-unpinned",
    }
