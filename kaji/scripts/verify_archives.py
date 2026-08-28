#!/usr/bin/env python3
"""Verify wheel and sdist completeness, canonical contracts, and package hygiene."""

from __future__ import annotations

import argparse
import base64
import configparser
import csv
import hashlib
import io
import json
import os
import posixpath
import stat
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Callable
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

wheel = Path()
sdist = Path()
sdk_root = Path()
py_pkg_root = Path()
contracts_dir = Path()
license_bytes = b""
readme_bytes = b""
registry_root = "kaji/integrations/registry"
pyproject: dict[str, Any] = {}
project: dict[str, Any] = {}
project_name = ""
project_version = ""
wheel_distribution = ""
expected_dist_info = ""
expected_sdist_root = ""
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_MEMBER_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_GENERATED_METADATA_BYTES = 1024 * 1024


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_archives(dist_dir: Path) -> None:
    """Load source metadata and select the first wheel and sdist in dist_dir."""
    global contracts_dir
    global expected_dist_info
    global expected_sdist_root
    global license_bytes
    global project
    global project_name
    global project_version
    global py_pkg_root
    global pyproject
    global readme_bytes
    global sdk_root
    global sdist
    global wheel
    global wheel_distribution

    if not dist_dir.is_dir():
        fail(f"expected one wheel and one sdist under {dist_dir}")
    candidates = (path for path in dist_dir.iterdir() if path.is_file())
    wheel_candidate: Path | None = None
    sdist_candidate: Path | None = None
    for candidate in candidates:
        if wheel_candidate is None and candidate.name.endswith(".whl"):
            wheel_candidate = candidate
        if sdist_candidate is None and candidate.name.endswith((".tar.gz", ".zip")):
            sdist_candidate = candidate
    if wheel_candidate is None or sdist_candidate is None:
        fail(f"expected one wheel and one sdist under {dist_dir}")

    wheel = wheel_candidate
    sdist = sdist_candidate
    sdk_root = Path(__file__).resolve().parents[1]
    # Contracts stay at kaji/contracts (shared canonical spine).
    contracts_dir = sdk_root / "contracts"
    # The Python SDK package moved to kaji/packages/py; its packaging inputs
    # (LICENSE/README/pyproject/build-requirements/src) live there now.
    py_pkg_root = sdk_root / "packages" / "py"
    license_bytes = (py_pkg_root / "LICENSE").read_bytes()
    readme_bytes = (py_pkg_root / "README.md").read_bytes()
    pyproject = tomllib.loads((py_pkg_root / "pyproject.toml").read_text())
    project = pyproject["project"]
    project_name = project["name"]
    project_version = project["version"]
    wheel_distribution = project_name.replace("-", "_")
    expected_dist_info = f"{wheel_distribution}-{project_version}.dist-info"
    expected_sdist_root = f"{wheel_distribution}-{project_version}"


def manifest_declared_owner_fixture_paths(
    paths: set[str],
    read_bytes: Callable[[str], bytes],
    *,
    prefix: str = "",
    registry_root_path: str = registry_root,
) -> set[str]:
    """Return each packaged owner fixture that its integration manifest declares.

    Every registry integration may ship exactly one owner fixture, named
    `tests/test_<name>.py` after the integration. It is allowed in the
    wheel/sdist only when the integration's own `manifest.json` lists that exact
    relative path in its `files` array. Any other test file is forbidden even if
    the manifest declares it, so a stray test can never be smuggled in.
    """
    registry_prefix = f"{prefix}{registry_root_path}/"
    allowed: set[str] = set()
    for path in paths:
        if not path.startswith(registry_prefix) or not path.endswith("/manifest.json"):
            continue
        name = path[len(registry_prefix) : -len("/manifest.json")]
        if "/" in name:
            continue
        owner_relative = f"tests/test_{name}.py"
        fixture_path = f"{registry_prefix}{name}/{owner_relative}"
        if fixture_path not in paths:
            continue
        try:
            manifest = json.loads(read_bytes(path))
        except (json.JSONDecodeError, UnicodeDecodeError):
            fail(f"{name} registry manifest is not valid JSON")
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if isinstance(files, list) and owner_relative in files:
            allowed.add(fixture_path)
    return allowed


def forbidden_artifacts(
    paths: set[str],
    *,
    allowed_test_paths: set[str] | frozenset[str] = frozenset(),
) -> list[str]:
    forbidden: list[str] = []
    for path in sorted(paths):
        parts = path.split("/")
        if any(
            part in {"__pycache__", ".pytest_cache", ".ruff_cache", "logs"}
            for part in parts
        ):
            forbidden.append(path)
        elif path.endswith((".pyc", ".pyo", ".log")):
            forbidden.append(path)
        elif "tests" in parts and path not in allowed_test_paths:
            forbidden.append(path)
    return forbidden


def checked_archive_path(raw_name: str) -> str:
    """Return one normalized POSIX member path or fail closed."""
    if not raw_name or raw_name.startswith("/") or "\\" in raw_name:
        fail(f"archive contains unsafe member path: {raw_name!r}")
    name = raw_name.rstrip("/")
    parts = name.split("/")
    if not name or any(part in {"", ".", ".."} for part in parts):
        fail(f"archive contains unsafe member path: {raw_name!r}")
    normalized = posixpath.normpath(name)
    if normalized != name or normalized.startswith("../"):
        fail(f"archive contains unsafe member path: {raw_name!r}")
    return normalized


def checked_zip_members(zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    uncompressed_bytes = 0
    for info in zf.infolist():
        if len(members) >= MAX_ARCHIVE_MEMBERS:
            fail("wheel contains too many members")
        name = checked_archive_path(info.filename)
        if name in members:
            fail(f"wheel contains duplicate member path: {name}")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            fail(f"wheel contains symlink member: {name}")
        if not info.is_dir() and stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
            fail(f"wheel contains non-regular member: {name}")
        if not info.is_dir() and mode & 0o111:
            fail(f"wheel contains unexpected executable payload: {name}")
        if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            fail(f"wheel member exceeds uncompressed size limit: {name}")
        uncompressed_bytes += info.file_size
        if uncompressed_bytes > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            fail("wheel exceeds total uncompressed size limit")
        members[name] = info
    return members


def checked_tar_members(tf: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    uncompressed_bytes = 0
    for member in tf:
        if len(members) >= MAX_ARCHIVE_MEMBERS:
            fail("sdist contains too many members")
        name = checked_archive_path(member.name)
        if name in members:
            fail(f"sdist contains duplicate member path: {name}")
        if member.issym() or member.islnk():
            fail(f"sdist contains link member: {name}")
        if not (member.isfile() or member.isdir()):
            fail(f"sdist contains non-file member: {name}")
        if member.isfile() and member.mode & 0o111:
            fail(f"sdist contains unexpected executable payload: {name}")
        if member.size > MAX_ARCHIVE_MEMBER_BYTES:
            fail(f"sdist member exceeds uncompressed size limit: {name}")
        uncompressed_bytes += member.size
        if uncompressed_bytes > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            fail("sdist exceeds total uncompressed size limit")
        members[name] = member
    return members


def parent_directories(paths: set[str]) -> set[str]:
    parents: set[str] = set()
    for path in paths:
        parent = posixpath.dirname(path)
        while parent:
            parents.add(parent)
            parent = posixpath.dirname(parent)
    return parents


def registry_path(base: str, relative: str) -> str:
    if relative.startswith("/") or ".." in relative.split("/"):
        fail(f"manifest declares unsafe path: {relative}")
    path = posixpath.normpath(posixpath.join(base, relative))
    if not path.startswith(f"{registry_root}/"):
        fail(f"manifest path escapes registry root: {relative}")
    return path


def canonical_specifier_list(value: str) -> str:
    """Canonicalize the simple comma-separated specifiers declared by this project."""
    specifiers = [item.strip() for item in value.split(",")]
    if not specifiers or any(not item for item in specifiers):
        fail(f"invalid declared version specifier: {value!r}")
    return ",".join(sorted(specifiers))


def canonical_requirement(value: str) -> str:
    """Mirror the pinned backend's canonical ordering without trusting artifact metadata."""
    if ";" in value:
        fail(f"unexpected marker in declared dependency: {value!r}")
    operator_positions = [
        index for operator in "<>=!~" if (index := value.find(operator)) >= 0
    ]
    if not operator_positions:
        return value.strip()
    split_at = min(operator_positions)
    name = value[:split_at].strip()
    if not name:
        fail(f"invalid declared dependency: {value!r}")
    return name + canonical_specifier_list(value[split_at:])


def expected_requires_dist() -> list[str]:
    requirements = [canonical_requirement(item) for item in project["dependencies"]]
    for extra, dependencies in project.get("optional-dependencies", {}).items():
        requirements.extend(
            f'{canonical_requirement(item)}; extra == "{extra}"'
            for item in dependencies
        )
    return requirements


def validate_core_metadata(data: bytes, label: str) -> None:
    """Validate all generated core metadata against pyproject and checkout bytes."""
    try:
        message = BytesParser(policy=policy.compat32).parsebytes(data)
    except Exception as error:
        fail(f"{label} is not valid core metadata: {type(error).__name__}")
    allowed_fields = {
        "Metadata-Version",
        "Name",
        "Version",
        "Summary",
        "Author-email",
        "License-Expression",
        "Project-URL",
        "Requires-Python",
        "Description-Content-Type",
        "License-File",
        "Requires-Dist",
        "Provides-Extra",
        "Dynamic",
    }
    actual_fields = set(message.keys())
    if actual_fields != allowed_fields:
        fail(
            f"{label} metadata fields differ; "
            f"missing={sorted(allowed_fields - actual_fields)}, "
            f"extra={sorted(actual_fields - allowed_fields)}"
        )

    authors = project.get("authors") or []
    expected_author_email = ", ".join(
        f"{author['name']} <{author['email']}>" for author in authors
    )
    expected_single = {
        "Metadata-Version": "2.4",
        "Name": project_name,
        "Version": project_version,
        "Summary": project["description"],
        "Author-email": expected_author_email,
        "License-Expression": project["license"],
        "Requires-Python": canonical_specifier_list(project["requires-python"]),
        "Description-Content-Type": "text/markdown",
        "License-File": "LICENSE",
        "Dynamic": "license-file",
    }
    for field, expected in expected_single.items():
        actual = message.get_all(field) or []
        if actual != [expected]:
            fail(f"{label} {field} differs from pyproject: {actual!r}")
    if (message.get_all("Provides-Extra") or []) != list(
        project.get("optional-dependencies", {})
    ):
        fail(f"{label} Provides-Extra differs from pyproject")
    if (message.get_all("Requires-Dist") or []) != expected_requires_dist():
        fail(f"{label} Requires-Dist differs from pyproject")
    expected_project_urls = [
        f"{name}, {url}" for name, url in project.get("urls", {}).items()
    ]
    if (message.get_all("Project-URL") or []) != expected_project_urls:
        fail(f"{label} Project-URL differs from pyproject")
    _header, separator, body = data.partition(b"\n\n")
    if not separator or body != readme_bytes:
        fail(f"{label} description body differs from checkout README.md")


def parse_ini(data: bytes, label: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read_string(data.decode("utf-8"))
    except (UnicodeDecodeError, configparser.Error) as error:
        fail(f"{label} is invalid: {type(error).__name__}")
    return parser


def validate_entry_points(data: bytes, label: str) -> None:
    parser = parse_ini(data, label)
    expected = dict(project.get("scripts", {}))
    if parser.sections() != ["console_scripts"]:
        fail(f"{label} must contain only [console_scripts]")
    if dict(parser.items("console_scripts")) != expected:
        fail(f"{label} console scripts differ from pyproject")


def validate_wheel_metadata(data: bytes, label: str) -> None:
    message = BytesParser(policy=policy.compat32).parsebytes(data)
    build_requires = pyproject["build-system"]["requires"]
    setuptools_pin = next(
        (
            item.split("==", 1)[1]
            for item in build_requires
            if item.startswith("setuptools==")
        ),
        None,
    )
    expected = {
        "Wheel-Version": ["1.0"],
        "Generator": [f"setuptools ({setuptools_pin})"],
        "Root-Is-Purelib": ["true"],
        "Tag": ["py3-none-any"],
    }
    if set(message.keys()) != set(expected):
        fail(f"{label} contains unexpected or missing wheel metadata fields")
    for field, values in expected.items():
        if (message.get_all(field) or []) != values:
            fail(f"{label} {field} is not canonical")


def validate_record(
    zf: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    file_names: set[str],
    record_path: str,
) -> None:
    try:
        rows = list(csv.reader(io.StringIO(zf.read(record_path).decode("utf-8"))))
    except (UnicodeDecodeError, csv.Error) as error:
        fail(f"wheel RECORD is invalid: {type(error).__name__}")
    records: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3:
            fail("wheel RECORD row does not have exactly three columns")
        path, digest, size = row
        if checked_archive_path(path) != path:
            fail(f"wheel RECORD contains unsafe path: {path!r}")
        if path in records:
            fail(f"wheel RECORD contains duplicate path: {path}")
        records[path] = (digest, size)
    if set(records) != file_names:
        fail(
            "wheel RECORD member set differs from archive; "
            f"missing={sorted(file_names - set(records))[:10]}, "
            f"extra={sorted(set(records) - file_names)[:10]}"
        )
    for path, (digest, size) in records.items():
        if path == record_path:
            if digest or size:
                fail("wheel RECORD must leave its own hash and size empty")
            continue
        payload = zf.read(members[path])
        if size != str(len(payload)):
            fail(f"wheel RECORD size mismatch: {path}")
        if not digest.startswith("sha256=") or "=" in digest.removeprefix("sha256="):
            fail(f"wheel RECORD uses a non-canonical digest: {path}")
        encoded = digest.removeprefix("sha256=")
        try:
            recorded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except (ValueError, base64.binascii.Error):
            fail(f"wheel RECORD contains invalid base64 digest: {path}")
        if recorded != hashlib.sha256(payload).digest():
            fail(f"wheel RECORD hash mismatch: {path}")


def validate_requires_txt(data: bytes, label: str) -> None:
    sections: dict[str, list[str]] = {"": []}
    current = ""
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        fail(f"{label} is not UTF-8")
    for line in lines:
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            if not current or current in sections:
                fail(f"{label} contains an invalid or duplicate section")
            sections[current] = []
            continue
        sections[current].append(line)
    expected = {"": [canonical_requirement(item) for item in project["dependencies"]]}
    expected.update(
        {
            extra: [canonical_requirement(item) for item in dependencies]
            for extra, dependencies in project.get("optional-dependencies", {}).items()
        }
    )
    if sections != expected:
        fail(f"{label} dependencies differ from pyproject")


def verify_archives() -> None:
    if project_name != "kaji":
        fail(f"unexpected Python project name: {project_name}")
    egg_info = f"{wheel_distribution}.egg-info"
    package_root = py_pkg_root / "src"
    expected_source_bytes = {
        f"kaji/{path.relative_to(package_root).as_posix()}": path.read_bytes()
        for path in package_root.rglob("*")
        if path.is_file()
        and path.name != ".DS_Store"
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    }
    canonical_contracts = {
        path.relative_to(contracts_dir).as_posix(): path.read_bytes()
        for path in contracts_dir.rglob("*")
        if path.is_file() and path.suffix in {".json", ".md"}
    }
    wheel_metadata_bytes: bytes | None = None

    if wheel.name != f"{wheel_distribution}-{project_version}-py3-none-any.whl":
        fail(f"wheel filename is not canonical: {wheel.name}")
    if sdist.name != f"{wheel_distribution}-{project_version}.tar.gz":
        fail(f"sdist filename is not canonical: {sdist.name}")

    with zipfile.ZipFile(wheel) as zf:
        members = checked_zip_members(zf)
        names = {name for name, info in members.items() if not info.is_dir()}
        allowed_test_paths = manifest_declared_owner_fixture_paths(
            names,
            lambda path: zf.read(members[path]),
        )
        forbidden = forbidden_artifacts(
            names,
            allowed_test_paths=allowed_test_paths,
        )
        if forbidden:
            fail(f"forbidden artifacts in wheel: {forbidden[:5]}")

        missing_sources = sorted(set(expected_source_bytes) - names)
        if missing_sources:
            fail(f"runtime source files missing from wheel: {missing_sources[:10]}")
        for path, expected in sorted(expected_source_bytes.items()):
            if members[path].file_size != len(expected):
                fail(f"wheel runtime source size differs from checkout: {path}")
            if zf.read(members[path]) != expected:
                fail(f"wheel runtime source differs from checkout: {path}")

        dist_info_roots = {
            name.split("/", 1)[0] for name in names if ".dist-info/" in name
        }
        if len(dist_info_roots) != 1:
            fail(
                f"wheel must contain one dist-info directory, found {sorted(dist_info_roots)}"
            )
        dist_info = next(iter(dist_info_roots))
        if dist_info != expected_dist_info:
            fail(f"wheel dist-info directory is not canonical: {dist_info}")
        generated_metadata = {
            f"{dist_info}/METADATA",
            f"{dist_info}/WHEEL",
            f"{dist_info}/entry_points.txt",
            f"{dist_info}/top_level.txt",
            f"{dist_info}/RECORD",
            f"{dist_info}/licenses/LICENSE",
        }
        allowed_wheel_files = set(expected_source_bytes) | generated_metadata
        unexpected = sorted(names - allowed_wheel_files)
        if unexpected:
            fail(f"unexpected payloads in wheel: {unexpected[:10]}")
        missing_metadata = sorted(generated_metadata - names)
        if missing_metadata:
            fail(f"wheel generated metadata missing: {missing_metadata}")
        for path in generated_metadata:
            if members[path].file_size > MAX_GENERATED_METADATA_BYTES:
                fail(f"wheel generated metadata exceeds size limit: {path}")

        wheel_metadata_bytes = zf.read(f"{dist_info}/METADATA")
        validate_core_metadata(wheel_metadata_bytes, "wheel METADATA")
        validate_wheel_metadata(zf.read(f"{dist_info}/WHEEL"), "wheel WHEEL")
        validate_entry_points(
            zf.read(f"{dist_info}/entry_points.txt"),
            "wheel entry_points.txt",
        )
        if zf.read(f"{dist_info}/top_level.txt") != b"kaji\n":
            fail("wheel top_level.txt is not canonical")
        validate_record(zf, members, names, f"{dist_info}/RECORD")

        expected_wheel_dirs = parent_directories(allowed_wheel_files)
        actual_wheel_dirs = {name for name, info in members.items() if info.is_dir()}
        unexpected_dirs = sorted(actual_wheel_dirs - expected_wheel_dirs)
        if unexpected_dirs:
            fail(f"unexpected directories in wheel: {unexpected_dirs[:10]}")

        license_paths = sorted(
            path for path in names if path.endswith("/LICENSE") or path == "LICENSE"
        )
        if not license_paths:
            fail("LICENSE missing from wheel")
        for path in license_paths:
            if zf.read(path) != license_bytes:
                fail(f"{path} differs from package LICENSE")

        packaged_contracts = {
            path.removeprefix("kaji/contracts/")
            for path in names
            if path.startswith("kaji/contracts/")
            and Path(path).suffix in {".json", ".md"}
        }
        if packaged_contracts != set(canonical_contracts):
            missing = sorted(set(canonical_contracts) - packaged_contracts)
            extra = sorted(packaged_contracts - set(canonical_contracts))
            fail(f"wheel contract set mismatch; missing={missing}, extra={extra}")
        for relative, expected in sorted(canonical_contracts.items()):
            if zf.read(f"kaji/contracts/{relative}") != expected:
                fail(f"kaji/contracts/{relative} differs from canonical bytes")

        index_path = f"{registry_root}/index.json"
        schema_path = f"{registry_root}/schema.json"
        for required in (index_path, schema_path, "kaji/__init__.py", "kaji/py.typed"):
            if required not in names:
                fail(f"{required} missing from wheel")

        integrations = json.loads(zf.read(index_path)).get("integrations") or {}
        if not integrations:
            fail("registry index declares no integrations")
        for name, entry in sorted(integrations.items()):
            manifest_rel = entry.get("manifest") if isinstance(entry, dict) else entry
            if not isinstance(manifest_rel, str) or not manifest_rel:
                fail(f"{name}: registry entry has no manifest path")
            manifest_path = registry_path(registry_root, manifest_rel)
            if manifest_path not in names:
                fail(f"{name}: manifest {manifest_rel} missing from wheel")
            manifest = json.loads(zf.read(manifest_path))
            for relative in manifest.get("files") or []:
                path = registry_path(posixpath.dirname(manifest_path), relative)
                if path not in names:
                    fail(f"{name}: manifest file {relative} missing from wheel")

    with tarfile.open(sdist, "r:*") as tf:
        all_members = checked_tar_members(tf)
        members = {
            name: member for name, member in all_members.items() if member.isfile()
        }
        names = set(members)
        roots = {path.split("/", 1)[0] for path in names}
        if len(roots) != 1:
            fail(f"sdist must have one root directory, found {sorted(roots)}")
        root = next(iter(roots))
        if root != expected_sdist_root:
            fail(f"sdist root directory is not canonical: {root}")
        relative_names = {path.removeprefix(f"{root}/") for path in names}

        def sdist_bytes(relative: str) -> bytes:
            extracted = tf.extractfile(members[f"{root}/{relative}"])
            if extracted is None:
                fail(f"sdist file cannot be read: {relative}")
            return extracted.read()

        allowed_test_paths = manifest_declared_owner_fixture_paths(
            relative_names,
            sdist_bytes,
            prefix="src/",
            registry_root_path="integrations/registry",
        )
        forbidden = forbidden_artifacts(
            relative_names,
            allowed_test_paths=allowed_test_paths,
        )
        if forbidden:
            fail(f"forbidden artifacts in sdist: {forbidden[:5]}")

        expected_sdist_source_bytes = {
            f"src/{path.removeprefix('kaji/')}": expected
            for path, expected in expected_source_bytes.items()
        }
        missing_sources = sorted(set(expected_sdist_source_bytes) - relative_names)
        if missing_sources:
            fail(f"runtime source files missing from sdist: {missing_sources[:10]}")
        for relative, expected in sorted(expected_sdist_source_bytes.items()):
            member = members[f"{root}/{relative}"]
            if member.size != len(expected):
                fail(f"sdist runtime source size differs from checkout: {relative}")
            extracted = tf.extractfile(member)
            if extracted is None or extracted.read() != expected:
                fail(f"sdist runtime source differs from checkout: {relative}")

        # Setuptools generates these metadata files. They are deliberately allowed
        # but excluded from byte comparison because their contents are build output.
        generated_sdist_metadata = {
            "PKG-INFO",
            "setup.cfg",
            f"{egg_info}/PKG-INFO",
            f"{egg_info}/SOURCES.txt",
            f"{egg_info}/dependency_links.txt",
            f"{egg_info}/entry_points.txt",
            f"{egg_info}/requires.txt",
            f"{egg_info}/top_level.txt",
        }
        checkout_metadata = {
            "LICENSE",
            "MANIFEST.in",
            "README.md",
            "build-requirements.txt",
            "pyproject.toml",
        }
        allowed_sdist_files = (
            set(expected_sdist_source_bytes)
            | generated_sdist_metadata
            | checkout_metadata
        )
        unexpected = sorted(relative_names - allowed_sdist_files)
        if unexpected:
            fail(f"unexpected payloads in sdist: {unexpected[:10]}")
        missing_allowed = sorted(allowed_sdist_files - relative_names)
        if missing_allowed:
            fail(f"sdist expected content missing: {missing_allowed[:10]}")
        for relative in generated_sdist_metadata:
            if members[f"{root}/{relative}"].size > MAX_GENERATED_METADATA_BYTES:
                fail(f"sdist generated metadata exceeds size limit: {relative}")

        root_pkg_info = sdist_bytes("PKG-INFO")
        egg_pkg_info = sdist_bytes(f"{egg_info}/PKG-INFO")
        validate_core_metadata(root_pkg_info, "sdist PKG-INFO")
        if wheel_metadata_bytes is None or root_pkg_info != wheel_metadata_bytes:
            fail("sdist PKG-INFO differs from wheel METADATA")
        if egg_pkg_info != root_pkg_info:
            fail("sdist egg-info PKG-INFO differs from root PKG-INFO")

        setup = parse_ini(sdist_bytes("setup.cfg"), "sdist setup.cfg")
        if setup.sections() != ["egg_info"] or dict(setup.items("egg_info")) != {
            "tag_build": "",
            "tag_date": "0",
        }:
            fail("sdist setup.cfg is not the canonical setuptools egg_info file")
        validate_entry_points(
            sdist_bytes(f"{egg_info}/entry_points.txt"),
            "sdist egg-info entry_points.txt",
        )
        validate_requires_txt(
            sdist_bytes(f"{egg_info}/requires.txt"),
            "sdist egg-info requires.txt",
        )
        if sdist_bytes(f"{egg_info}/dependency_links.txt") != b"\n":
            fail("sdist egg-info dependency_links.txt is not canonical")
        if sdist_bytes(f"{egg_info}/top_level.txt") != b"kaji\n":
            fail("sdist egg-info top_level.txt is not canonical")

        try:
            source_lines = (
                sdist_bytes(f"{egg_info}/SOURCES.txt").decode("utf-8").splitlines()
            )
        except UnicodeDecodeError:
            fail("sdist egg-info SOURCES.txt is not UTF-8")
        if len(source_lines) != len(set(source_lines)):
            fail("sdist egg-info SOURCES.txt contains duplicate paths")
        for source_path in source_lines:
            if checked_archive_path(source_path) != source_path:
                fail(
                    f"sdist egg-info SOURCES.txt contains unsafe path: {source_path!r}"
                )
        expected_source_listing = (
            set(expected_sdist_source_bytes)
            | checkout_metadata
            | {
                f"{egg_info}/PKG-INFO",
                f"{egg_info}/SOURCES.txt",
                f"{egg_info}/dependency_links.txt",
                f"{egg_info}/entry_points.txt",
                f"{egg_info}/requires.txt",
                f"{egg_info}/top_level.txt",
            }
        )
        if set(source_lines) != expected_source_listing:
            fail(
                "sdist egg-info SOURCES.txt differs from expected source manifest; "
                f"missing={sorted(expected_source_listing - set(source_lines))[:10]}, "
                f"extra={sorted(set(source_lines) - expected_source_listing)[:10]}"
            )

        expected_dirs = {root} | {
            f"{root}/{path}" for path in parent_directories(allowed_sdist_files)
        }
        actual_dirs = {name for name, member in all_members.items() if member.isdir()}
        unexpected_dirs = sorted(actual_dirs - expected_dirs)
        if unexpected_dirs:
            fail(f"unexpected directories in sdist: {unexpected_dirs[:10]}")

        for relative in checkout_metadata:
            if sdist_bytes(relative) != (py_pkg_root / relative).read_bytes():
                fail(f"sdist checkout metadata differs from source: {relative}")

        packaged_contracts = {
            path.removeprefix("src/contracts/")
            for path in relative_names
            if path.startswith("src/contracts/")
            and Path(path).suffix in {".json", ".md"}
        }
        if packaged_contracts != set(canonical_contracts):
            missing = sorted(set(canonical_contracts) - packaged_contracts)
            extra = sorted(packaged_contracts - set(canonical_contracts))
            fail(f"sdist contract set mismatch; missing={missing}, extra={extra}")
        for relative, expected in sorted(canonical_contracts.items()):
            path = f"{root}/src/contracts/{relative}"
            member = members[path]
            extracted = tf.extractfile(member)
            if extracted is None or extracted.read() != expected:
                fail(f"src/contracts/{relative} differs from canonical bytes")

        license_path = f"{root}/LICENSE"
        member = members.get(license_path)
        if member is None:
            fail("LICENSE missing from sdist")
        extracted = tf.extractfile(member)
        if extracted is None or extracted.read() != license_bytes:
            fail("sdist LICENSE differs from package LICENSE")

    print(f"PASS: verified {wheel.name} and {sdist.name}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dist_dir",
        nargs="?",
        type=Path,
        default=Path(os.environ.get("DIST_DIR") or "dist"),
        help="directory containing one wheel and one sdist (default: DIST_DIR or dist)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_archives(args.dist_dir)
    verify_archives()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
