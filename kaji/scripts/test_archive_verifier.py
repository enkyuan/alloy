#!/usr/bin/env python3
"""Prove the release archive verifier rejects forged generated metadata."""

from __future__ import annotations

import argparse
import base64
import copy
import csv
import hashlib
import io
import shutil
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from process_runner import PACKAGE_COMMAND_BUDGET, run_checked  # noqa: E402


WheelFiles = dict[str, tuple[zipfile.ZipInfo, bytes]]
TarFiles = list[tuple[tarfile.TarInfo, bytes | None]]


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def find_one(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        fail(f"expected exactly one {pattern} under {directory}, found {len(matches)}")
    return matches[0]


def read_wheel(path: Path) -> WheelFiles:
    with zipfile.ZipFile(path) as archive:
        return {
            info.filename: (
                copy.copy(info),
                b"" if info.is_dir() else archive.read(info),
            )
            for info in archive.infolist()
        }


def rewrite_record(files: WheelFiles) -> None:
    record_path = next(name for name in files if name.endswith(".dist-info/RECORD"))
    rows: list[list[str]] = []
    for name, (info, payload) in files.items():
        if info.is_dir() or name == record_path:
            continue
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
            .rstrip(b"=")
            .decode()
        )
        rows.append([name, f"sha256={digest}", str(len(payload))])
    rows.append([record_path, "", ""])
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    info, _payload = files[record_path]
    files[record_path] = (info, output.getvalue().encode())


def write_wheel(path: Path, files: WheelFiles) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for info, payload in files.values():
            archive.writestr(info, payload)


def read_sdist(path: Path) -> TarFiles:
    files: TarFiles = []
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            stream = archive.extractfile(member) if member.isfile() else None
            files.append((copy.copy(member), None if stream is None else stream.read()))
    return files


def write_sdist(path: Path, files: TarFiles) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for member, payload in files:
            archive.addfile(member, None if payload is None else io.BytesIO(payload))


def replace_wheel_file(files: WheelFiles, suffix: str, payload: bytes) -> None:
    path = next(name for name in files if name.endswith(suffix))
    info, _old = files[path]
    info.file_size = len(payload)
    files[path] = (info, payload)


def mutate_metadata(files: WheelFiles) -> None:
    path = next(name for name in files if name.endswith(".dist-info/METADATA"))
    _info, payload = files[path]
    headers, body = payload.split(b"\n\n", 1)
    replace_wheel_file(
        files,
        ".dist-info/METADATA",
        headers + b'\nRequires-Dist: attacker-package; extra == "hidden"\n\n' + body,
    )
    rewrite_record(files)


def mutate_wheel_project_url_extra(files: WheelFiles) -> None:
    path = next(name for name in files if name.endswith(".dist-info/METADATA"))
    _info, payload = files[path]
    headers, body = payload.split(b"\n\n", 1)
    replace_wheel_file(
        files,
        ".dist-info/METADATA",
        headers + b"\nProject-URL: Attacker, https://attacker.invalid/kaji\n\n" + body,
    )
    rewrite_record(files)


def mutate_entry_point(files: WheelFiles) -> None:
    replace_wheel_file(
        files,
        ".dist-info/entry_points.txt",
        b"[console_scripts]\nkaji = os:system\n",
    )
    rewrite_record(files)


def mutate_recorded_payload(files: WheelFiles) -> None:
    path = next(name for name in files if name.endswith(".dist-info/licenses/LICENSE"))
    info, payload = files[path]
    replacement = bytes([payload[0] ^ 1]) + payload[1:]
    files[path] = (info, replacement)


def mutate_oversized_metadata(files: WheelFiles) -> None:
    replace_wheel_file(
        files,
        ".dist-info/METADATA",
        b"X" * (1024 * 1024 + 1),
    )
    rewrite_record(files)


def mutate_wheel_package_test(files: WheelFiles) -> None:
    source = next(name for name in files if name.endswith("/tests/test_github.py"))
    source_info, _payload = files[source]
    path = "kaji/integrations/registry/github/tests/test_extra.py"
    info = copy.copy(source_info)
    info.filename = path
    payload = b"def test_unexpected_package_payload():\n    pass\n"
    info.file_size = len(payload)
    files[path] = (info, payload)
    rewrite_record(files)


def replace_sdist_file(files: TarFiles, suffix: str, payload: bytes) -> None:
    for index, (member, _old) in enumerate(files):
        if member.name.endswith(suffix):
            member.size = len(payload)
            files[index] = (member, payload)
            return
    fail(f"sdist mutation target missing: {suffix}")


def mutate_setup_cfg(files: TarFiles) -> None:
    replace_sdist_file(
        files,
        "/setup.cfg",
        b"[metadata]\nname = attacker-controlled\n"
        b"[options.entry_points]\nconsole_scripts =\n    kaji = os:system\n",
    )


def mutate_sdist_metadata(files: TarFiles) -> None:
    root_pkg = next(
        payload
        for member, payload in files
        if member.name.endswith("/PKG-INFO") and member.name.count("/") == 1
    )
    if root_pkg is None:
        fail("sdist PKG-INFO cannot be read")
    headers, body = root_pkg.split(b"\n\n", 1)
    replace_sdist_file(
        files,
        "/PKG-INFO",
        headers + b"\nRequires-Dist: attacker-package\n\n" + body,
    )


def mutate_sdist_project_url_mismatch(files: TarFiles) -> None:
    root_pkg = next(
        payload
        for member, payload in files
        if member.name.endswith("/PKG-INFO") and member.name.count("/") == 1
    )
    if root_pkg is None:
        fail("sdist PKG-INFO cannot be read")
    original = b"Project-URL: Repository, https://github.com/enkyuan/alloy"
    replacement = b"Project-URL: Repository, https://attacker.invalid/kaji"
    if original not in root_pkg:
        fail("sdist PKG-INFO canonical Project-URL is missing")
    replace_sdist_file(files, "/PKG-INFO", root_pkg.replace(original, replacement))


def mutate_sdist_package_test(files: TarFiles) -> None:
    source = next(
        member
        for member, _payload in files
        if member.name.endswith("/tests/test_github.py")
    )
    root = source.name.split("/", 1)[0]
    member = copy.copy(source)
    member.name = f"{root}/src/kaji/integrations/registry/github/tests/test_extra.py"
    payload = b"def test_unexpected_package_payload():\n    pass\n"
    member.size = len(payload)
    files.append((member, payload))


def run_case(
    *,
    name: str,
    expected_error: str,
    verifier: Path,
    wheel: Path,
    sdist: Path,
    root: Path,
    wheel_mutation: Callable[[WheelFiles], None] | None = None,
    sdist_mutation: Callable[[TarFiles], None] | None = None,
) -> None:
    case_dir = root / name
    case_dir.mkdir()
    case_wheel = case_dir / wheel.name
    case_sdist = case_dir / sdist.name
    if wheel_mutation is None:
        shutil.copy2(wheel, case_wheel)
    else:
        wheel_files = read_wheel(wheel)
        wheel_mutation(wheel_files)
        write_wheel(case_wheel, wheel_files)
    if sdist_mutation is None:
        shutil.copy2(sdist, case_sdist)
    else:
        sdist_files = read_sdist(sdist)
        sdist_mutation(sdist_files)
        write_sdist(case_sdist, sdist_files)

    completed = run_checked(
        [sys.executable, str(verifier), str(case_dir)],
        cwd=Path.cwd(),
        budget=PACKAGE_COMMAND_BUDGET,
        capture=True,
        check=False,
    )
    output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    if completed.returncode == 0:
        fail(f"archive verifier accepted adversarial {name} case")
    if expected_error not in output:
        fail(f"{name} failed for the wrong reason: {output.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args()
    sdk_root = Path(__file__).resolve().parents[1]
    dist_dir = (
        args.dist_dir if args.dist_dir.is_absolute() else sdk_root / args.dist_dir
    )
    wheel = find_one(dist_dir, "*.whl")
    sdist = find_one(dist_dir, "*.tar.gz")
    verifier = sdk_root / "scripts/verify_archives.py"

    with tempfile.TemporaryDirectory(prefix="kaji-archive-verifier-") as temporary:
        root = Path(temporary)
        cases = [
            (
                "wheel-metadata",
                "Requires-Dist differs from pyproject",
                mutate_metadata,
                None,
            ),
            (
                "wheel-entry-point",
                "console scripts differ from pyproject",
                mutate_entry_point,
                None,
            ),
            (
                "wheel-project-url-extra",
                "Project-URL differs from pyproject",
                mutate_wheel_project_url_extra,
                None,
            ),
            ("wheel-record", "RECORD hash mismatch", mutate_recorded_payload, None),
            (
                "wheel-oversized-metadata",
                "generated metadata exceeds size limit",
                mutate_oversized_metadata,
                None,
            ),
            (
                "wheel-package-test",
                "forbidden artifacts in wheel",
                mutate_wheel_package_test,
                None,
            ),
            ("sdist-setup", "setup.cfg is not the canonical", None, mutate_setup_cfg),
            (
                "sdist-metadata",
                "Requires-Dist differs from pyproject",
                None,
                mutate_sdist_metadata,
            ),
            (
                "sdist-project-url-mismatch",
                "Project-URL differs from pyproject",
                None,
                mutate_sdist_project_url_mismatch,
            ),
            (
                "sdist-package-test",
                "forbidden artifacts in sdist",
                None,
                mutate_sdist_package_test,
            ),
        ]
        for name, expected, wheel_mutation, sdist_mutation in cases:
            run_case(
                name=name,
                expected_error=expected,
                verifier=verifier,
                wheel=wheel,
                sdist=sdist,
                root=root,
                wheel_mutation=wheel_mutation,
                sdist_mutation=sdist_mutation,
            )

    print("PASS: archive verifier rejected all adversarial metadata cases")


if __name__ == "__main__":
    main()
