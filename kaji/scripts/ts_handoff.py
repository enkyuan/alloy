#!/usr/bin/env python3
"""Stage one immutable TypeScript package and finalize its consumer handoff."""

from __future__ import annotations

import argparse
import base64
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import sys
import tarfile
import tempfile
import time
from typing import Any, NoReturn
from urllib import request

from jsonschema import Draft202012Validator

from process_runner import (
    CommandError,
    CompletedCommand,
    METADATA_BUDGET,
    PACKAGE_ORCHESTRATOR_BUDGET,
    run_checked,
)


PACKAGE_NAME = "@kaji/sdk"
REPOSITORY_URL = "https://github.com/enkyuan/alloy.git"
BASE_REF = "refs/remotes/origin/main"
SCHEMA_NAME = "kaji-ts-consumer-handoff-v1.schema.json"
MANIFEST_NAME = "kaji-sdk.manifest.json"
STAGE_INDEX_NAME = "stage.json"
RAW_SOURCE_NAME = "source-equivalence.raw.json"
RAW_SIGNATURE_NAME = "signature-verification.raw.json"
SOURCE_RECEIPT_NAME = "source-equivalence.json"
SIGNATURE_RECEIPT_NAME = "signature-verification.json"
PACK_RECEIPT_NAME = "pack-once.json"
RECEIPT_SET_NAMES = (
    SOURCE_RECEIPT_NAME,
    SIGNATURE_RECEIPT_NAME,
    PACK_RECEIPT_NAME,
    "artifact-contract.json",
    "node-22.json",
    "node-24.json",
)
RECEIPT_IDS = (
    "source-equivalence",
    "signature-verification",
    "pack-once",
    "artifact-contract",
    "node-22",
    "node-24",
)
RECEIPT_DEFINITIONS = (
    "sourceReceipt",
    "signatureReceipt",
    "packReceipt",
    "artifactContractReceipt",
    "node22Receipt",
    "node24Receipt",
)
RECEIPT_DIGEST_KEYS = (
    "sourceEquivalence",
    "signatureVerification",
    "packOnce",
    "artifactContract",
    "node22",
    "node24",
)

REGISTRY_URL = "https://registry.npmjs.org/@kaji%2Fsdk"
REGISTRY_ORIGIN = "https://registry.npmjs.org"
REGISTRY_PATH = "/@kaji%2Fsdk"
REGISTRY_MAX_BYTES = 5 * 1024 * 1024
REGISTRY_DEADLINE_SECONDS = 30.0

SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
POSITIVE_DECIMAL = re.compile(r"[1-9][0-9]*")

CLEAN_COMMAND = ("bun", "run", "clean")
BUILD_COMMAND = ("bun", "run", "build")
AUDIT_COMMANDS = (
    ("bun", "run", "check:integrations"),
    ("bun", "run", "typecheck:registry"),
    ("bun", "run", "test", "tests/public-declarations.test.ts"),
)
PACK_COMMAND_NORMALIZED = (
    "npm",
    "pack",
    "--ignore-scripts",
    "--json",
    "--pack-destination",
    "$PACK_TEMP",
)

RELEASE_CHECKS = (
    "source-policy",
    "toolchain-policy",
    "registry-policy",
    "runtime-evidence-split",
    "artifact-policy",
    "license-policy",
)
INTERNAL_CHECKS = (
    "source-policy",
    "toolchain-policy",
    "runtime-evidence-split",
    "artifact-policy",
    "license-policy",
)

RegistryGet = Callable[[str, str], tuple[int, str, bytes]]
CommandRunner = Callable[[Sequence[str], Path, Mapping[str, str]], CompletedCommand]


class HandoffError(RuntimeError):
    """A closed, redaction-safe handoff failure."""

    def __init__(
        self,
        code: str,
        *,
        source_commit: str | None = None,
        artifact_sha256: str | None = None,
    ) -> None:
        self.code = code
        self.source_commit = source_commit
        self.artifact_sha256 = artifact_sha256
        super().__init__(code)


class HandoffInterrupted(BaseException):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(signum)


class RegistryDeadlineExceeded(TimeoutError):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise HandoffError("INVALID_ARGUMENT")


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _reject(
    code: str,
    *,
    source_commit: str | None = None,
    artifact_sha256: str | None = None,
) -> NoReturn:
    raise HandoffError(
        code,
        source_commit=source_commit,
        artifact_sha256=artifact_sha256,
    )


def _trusted_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _schema_path() -> Path:
    return _trusted_root() / "kaji" / "contracts" / "release" / SCHEMA_NAME


def _schema() -> dict[str, Any]:
    try:
        encoded = _schema_path().read_bytes()
        document = json.loads(encoded.decode("utf-8"))
        if not isinstance(document, dict):
            raise ValueError
        Draft202012Validator.check_schema(document)
        return document
    except Exception:
        _reject("SCHEMA_INVALID")


def _fragment_validator(
    schema: dict[str, Any], definition: str
) -> Draft202012Validator:
    return Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            "$ref": f"#/$defs/{definition}",
        }
    )


def _valid_semver(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.isascii()
        and SEMVER.fullmatch(value) is not None
    )


def _valid_hex40(value: object) -> bool:
    return isinstance(value, str) and HEX40.fullmatch(value) is not None


def _valid_hex64(value: object) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _positive_integer(value: str | None) -> int:
    if value is None or POSITIVE_DECIMAL.fullmatch(value) is None:
        _reject("INVALID_ARGUMENT")
    parsed = int(value)
    if parsed > 9_007_199_254_740_991:
        _reject("INVALID_ARGUMENT")
    return parsed


def npm_pack_basename_v1(name: str, version: str) -> str:
    if name != PACKAGE_NAME or not _valid_semver(version):
        _reject("INVALID_ARGUMENT")
    return f"{name.removeprefix('@').replace('/', '-')}-{version}.tgz"


def _canonical_json(document: Any) -> bytes:
    return (
        json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")


def _raw_canonical_json(document: Any) -> bytes:
    return (
        json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")


def _sha256_bytes(encoded: bytes) -> str:
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        _reject("ARTIFACT_CHANGED")
    return digest.hexdigest()


def _npm_integrity(path: Path) -> str:
    digest = hashlib.sha512()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        _reject("ARTIFACT_CHANGED")
    return "sha512-" + base64.b64encode(digest.digest()).decode("ascii")


def _artifact_measurements(path: Path) -> tuple[int, str, str]:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise OSError(errno.EINVAL, "artifact is not a non-empty regular file")
        sha256 = hashlib.sha256()
        sha512 = hashlib.sha512()
        size = 0
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                sha256.update(chunk)
                sha512.update(chunk)
            after = os.fstat(stream.fileno())
        stable_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if not stable_identity or size != before.st_size:
            raise OSError(errno.EIO, "artifact changed while hashing")
        integrity = "sha512-" + base64.b64encode(sha512.digest()).decode("ascii")
        return size, sha256.hexdigest(), integrity
    except OSError:
        _reject("ARTIFACT_CHANGED")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError(errno.EINVAL, "path is not a regular file")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_noreplace(source: Path, destination: Path) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin":
        result = library.renamex_np(source_bytes, destination_bytes, 0x00000004)
    elif sys.platform.startswith("linux"):
        result = library.renameat2(-100, source_bytes, -100, destination_bytes, 1)
    else:
        raise OSError(errno.ENOTSUP, "exclusive rename is unsupported")
    if result != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def _safe_absent_destination(path: Path) -> Path:
    if path.name in {"", ".", ".."} or os.path.lexists(path):
        _reject("OUTPUT_EXISTS" if os.path.lexists(path) else "UNSAFE_PATH")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError:
        _reject("UNSAFE_PATH")
    if not parent.is_dir() or parent.is_symlink():
        _reject("UNSAFE_PATH")
    destination = parent / path.name
    if os.path.lexists(destination):
        _reject("OUTPUT_EXISTS")
    return destination


def _write_file(path: Path, encoded: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_file(path: Path, encoded: bytes) -> None:
    destination = _safe_absent_destination(path)
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{destination.name}.tmp-", dir=destination.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        _rename_noreplace(temporary, destination)
        temporary = None
        _fsync_directory(destination.parent)
    except FileExistsError:
        _reject("OUTPUT_EXISTS")
    except HandoffError:
        raise
    except OSError:
        _reject("INTERNAL_ERROR")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _owned_directory(destination: Path):
    output = _safe_absent_destination(destination)
    temporary: Path | None = None
    previous: dict[signal.Signals, Any] = {}

    def interrupted(signum: int, _frame: object) -> NoReturn:
        raise HandoffInterrupted(signum)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, interrupted)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent)
        )
        yield temporary
        _fsync_directory(temporary)
        _rename_noreplace(temporary, output)
        temporary = None
        _fsync_directory(output.parent)
    except FileExistsError:
        _reject("OUTPUT_EXISTS")
    except HandoffInterrupted:
        raise
    except HandoffError:
        raise
    except OSError:
        _reject("INTERNAL_ERROR")
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)


def _load_json(
    path: Path, *, code: str, canonical: str | None = None
) -> tuple[dict[str, Any], bytes]:
    try:
        if not path.is_file() or path.is_symlink():
            raise ValueError
        encoded = path.read_bytes()
        document = json.loads(encoded.decode("utf-8"))
        if not isinstance(document, dict):
            raise ValueError
        if canonical == "stable" and encoded != _canonical_json(document):
            raise ValueError
        if canonical == "raw" and encoded != _raw_canonical_json(document):
            raise ValueError
        return document, encoded
    except Exception:
        _reject(code)


def _exact_keys(document: Mapping[str, Any], keys: set[str], code: str) -> None:
    if set(document) != keys:
        _reject(code)


def _command_environment(command_home: Path) -> dict[str, str]:
    command_home = command_home.resolve(strict=True)
    owned_paths = {
        "HOME": command_home,
        "XDG_CONFIG_HOME": command_home / ".config",
        "XDG_CACHE_HOME": command_home / ".cache",
        "NPM_CONFIG_CACHE": command_home / ".npm-cache",
        "BUN_INSTALL_CACHE_DIR": command_home / ".bun-cache",
    }
    for path in owned_paths.values():
        path.mkdir(mode=0o700, exist_ok=True)
        path.chmod(0o700)
    environment = {
        key: value
        for key in (
            "PATH",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TMPDIR",
            "TEMP",
            "TMP",
            "SYSTEMROOT",
        )
        if (value := os.environ.get(key)) is not None
    }
    environment.update(
        {
            **{key: str(path) for key, path in owned_paths.items()},
            "GIT_TERMINAL_PROMPT": "0",
            "NPM_CONFIG_PROVENANCE": "false",
            "NPM_CONFIG_USERCONFIG": os.devnull,
            "NPM_CONFIG_GLOBALCONFIG": os.devnull,
            "NPM_CONFIG_AUDIT": "false",
            "NPM_CONFIG_FUND": "false",
            "NPM_CONFIG_UPDATE_NOTIFIER": "false",
        }
    )
    return environment


def _git_environment() -> dict[str, str]:
    environment = {
        key: value
        for key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
        if (value := os.environ.get(key)) is not None
    }
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _run_process(
    command: Sequence[str], cwd: Path, environment: Mapping[str, str]
) -> CompletedCommand:
    return run_checked(
        command,
        cwd=cwd,
        budget=PACKAGE_ORCHESTRATOR_BUDGET,
        capture=True,
        env=environment,
    )


def _metadata(
    command: Sequence[str], cwd: Path, environment: Mapping[str, str]
) -> bytes:
    try:
        return run_checked(
            command,
            cwd=cwd,
            budget=METADATA_BUDGET,
            capture=True,
            env=environment,
        ).stdout
    except CommandError:
        _reject("SOURCE_COMMIT_MISMATCH")


def _git_text(root: Path, *arguments: str) -> str:
    try:
        return (
            _metadata(("git", *arguments), root, _git_environment())
            .decode("ascii")
            .strip()
        )
    except UnicodeError:
        _reject("SOURCE_COMMIT_MISMATCH")


def _checkout_root(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        _reject("SOURCE_NOT_ISOLATED")
    if not resolved.is_dir() or _git_text(
        resolved, "rev-parse", "--show-toplevel"
    ) != str(resolved):
        _reject("SOURCE_NOT_ISOLATED")
    if _git_text(resolved, "rev-parse", "--is-shallow-repository") != "false":
        _reject("SOURCE_NOT_ISOLATED")
    return resolved


def _require_clean(root: Path) -> None:
    if _metadata(
        ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"),
        root,
        _git_environment(),
    ):
        _reject("SOURCE_DIRTY")


def _recheck_source(
    candidate_root: Path, source: Mapping[str, Any], signature: Mapping[str, Any]
) -> Path:
    candidate = _checkout_root(candidate_root)
    trusted = _checkout_root(_trusted_root())
    if (
        trusted == candidate
        or trusted.is_relative_to(candidate)
        or candidate.is_relative_to(trusted)
    ):
        _reject("SOURCE_NOT_ISOLATED")
    _require_clean(candidate)
    _require_clean(trusted)
    head = _git_text(candidate, "rev-parse", "--verify", "HEAD^{commit}")
    tree = _git_text(candidate, "rev-parse", "--verify", "HEAD^{tree}")
    merge_base = _git_text(candidate, "merge-base", BASE_REF, "HEAD")
    range_bytes = _metadata(
        ("git", "rev-list", "--reverse", "--topo-order", f"{merge_base}..{head}"),
        candidate,
        _git_environment(),
    )
    try:
        revision_range = range_bytes.decode("ascii").splitlines()
    except UnicodeError:
        _reject("SOURCE_COMMIT_MISMATCH")
    trusted_commit = _git_text(trusted, "rev-parse", "--verify", "HEAD^{commit}")
    try:
        verifier_sha = hashlib.sha256(
            (trusted / "kaji" / "scripts" / "verify_ts_handoff_source.py").read_bytes()
        ).hexdigest()
    except OSError:
        _reject("SOURCE_COMMIT_MISMATCH")
    if (
        head != source.get("headCommit")
        or tree != source.get("treeSha")
        or merge_base != source.get("mergeBase")
        or revision_range != source.get("range")
        or trusted_commit != source.get("trustedVerifierCommit")
        or signature.get("headCommit") != head
        or signature.get("treeSha") != tree
        or signature.get("mergeBase") != merge_base
        or signature.get("range") != revision_range
        or signature.get("verifierCommit") != trusted_commit
        or signature.get("verifierScriptSha256") != verifier_sha
    ):
        _reject(
            "SOURCE_COMMIT_MISMATCH", source_commit=head if _valid_hex40(head) else None
        )
    return candidate


def _raw_inputs(
    source_dir: Path,
) -> tuple[dict[str, Any], bytes, dict[str, Any], bytes]:
    source_path = source_dir / RAW_SOURCE_NAME
    signature_path = source_dir / RAW_SIGNATURE_NAME
    try:
        children = list(source_dir.iterdir())
    except OSError:
        _reject("RECEIPT_INVALID")
    if {item.name for item in children} != {RAW_SOURCE_NAME, RAW_SIGNATURE_NAME} or any(
        not item.is_file() or item.is_symlink() for item in children
    ):
        _reject("RECEIPT_INVALID")
    source, source_bytes = _load_json(
        source_path, code="RECEIPT_INVALID", canonical="raw"
    )
    signature, signature_bytes = _load_json(
        signature_path, code="RECEIPT_INVALID", canonical="raw"
    )
    schema = _schema()
    source_bound = {**source, "rawResultSha256": _sha256_bytes(source_bytes)}
    signature_bound = {**signature, "rawResultSha256": _sha256_bytes(signature_bytes)}
    if not _fragment_validator(schema, "sourceEvidence").is_valid(
        source_bound
    ) or not _fragment_validator(schema, "signatureEvidence").is_valid(signature_bound):
        _reject("RECEIPT_INVALID")
    _validate_source_signature_relations(source_bound, signature_bound)
    return source, source_bytes, signature, signature_bytes


def _validate_source_signature_relations(
    source: Mapping[str, Any], signature: Mapping[str, Any]
) -> None:
    head = source.get("headCommit")
    revision_range = source.get("range")
    commits = signature.get("commits")
    expected_commits = revision_range if revision_range else [head]
    if (
        signature.get("headCommit") != head
        or signature.get("treeSha") != source.get("treeSha")
        or signature.get("mergeBase") != source.get("mergeBase")
        or signature.get("verifierCommit") != source.get("trustedVerifierCommit")
        or signature.get("range") != revision_range
        or source.get("revisionCommand", [None] * 5)[4]
        != f"{source.get('mergeBase')}..{head}"
        or not isinstance(commits, list)
        or [item.get("sha") if isinstance(item, dict) else None for item in commits]
        != expected_commits
    ):
        _reject("RECEIPT_INVALID")
    signer = signature.get("approvedSignerEmail")
    if any(
        not isinstance(item, dict) or item.get("signerEmail") != signer
        for item in commits
    ):
        _reject("RECEIPT_INVALID")
    mechanism = signature.get("mechanism")
    if mechanism == "github-rest-commit-verification":
        if "tag" in signature:
            _reject("RECEIPT_INVALID")
    elif mechanism == "github-rest-commit-and-annotated-tag-verification":
        tag = signature.get("tag")
        if (
            not isinstance(tag, dict)
            or tag.get("taggerEmail") != signer
            or tag.get("targetCommit") != head
        ):
            _reject("RECEIPT_INVALID")
    else:
        _reject("RECEIPT_INVALID")


def _tool_version(command: Sequence[str], cwd: Path) -> str:
    try:
        with tempfile.TemporaryDirectory(prefix="kaji-command-home-") as temporary_home:
            completed = run_checked(
                command,
                cwd=cwd,
                budget=METADATA_BUDGET,
                capture=True,
                env=_command_environment(Path(temporary_home)),
            )
        output = (completed.stdout or completed.stderr).decode("ascii").strip()
    except (CommandError, OSError, UnicodeError):
        _reject("TOOLCHAIN_MISMATCH")
    match = re.search(
        r"(?<![0-9A-Za-z])v?([0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)",
        output,
    )
    if match is None or not _valid_semver(match.group(1)):
        _reject("TOOLCHAIN_MISMATCH")
    return match.group(1)


def _toolchain(root: Path) -> dict[str, str]:
    return {
        "node": _tool_version(("node", "--version"), root),
        "npm": _tool_version(("npm", "--version"), root),
        "bun": _tool_version(("bun", "--version"), root),
        "uv": _tool_version(("uv", "--version"), root),
    }


def _trusted_run_identity() -> dict[str, Any]:
    repository = os.environ.get("KAJI_HANDOFF_WORKFLOW_REPOSITORY")
    file_path = os.environ.get("KAJI_HANDOFF_WORKFLOW_FILE_PATH")
    digest = os.environ.get("KAJI_HANDOFF_WORKFLOW_SHA")
    reference = os.environ.get("KAJI_HANDOFF_WORKFLOW_REF")
    if (
        repository != "enkyuan/alloy"
        or file_path != ".github/workflows/kaji.handoff.trusted.yml"
        or not _valid_hex40(digest)
        or reference
        != f"enkyuan/alloy/.github/workflows/kaji.handoff.trusted.yml@{digest}"
    ):
        _reject("INVALID_ARGUMENT")
    return {
        "repository": repository,
        "filePath": file_path,
        "digest": digest,
        "ref": reference,
        "runId": _positive_integer(os.environ.get("GITHUB_RUN_ID")),
        "attempt": _positive_integer(os.environ.get("GITHUB_RUN_ATTEMPT")),
    }


@contextmanager
def _registry_deadline(seconds: float):
    deadline = time.monotonic() + seconds
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def expired(_signum: int, _frame: object) -> NoReturn:
        raise RegistryDeadlineExceeded

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield deadline
        if time.monotonic() > deadline:
            raise RegistryDeadlineExceeded
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def _registry_get(url: str, token: str) -> tuple[int, str, bytes]:
    registry_request = request.Request(
        url,
        headers={
            "Accept": "application/vnd.npm.install-v1+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "kaji-ts-handoff-preflight/1",
        },
        method="GET",
    )
    with _registry_deadline(REGISTRY_DEADLINE_SECONDS) as deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RegistryDeadlineExceeded
        with request.build_opener(_NoRedirect()).open(
            registry_request, timeout=remaining
        ) as response:
            body = response.read(REGISTRY_MAX_BYTES + 1)
            if time.monotonic() > deadline:
                raise RegistryDeadlineExceeded
            return response.status, response.geturl(), body


def _registry_proof(
    version: str,
    source_commit: str,
    workflow: Mapping[str, Any],
    registry_get: RegistryGet,
) -> dict[str, Any]:
    token = os.environ.get("NODE_AUTH_TOKEN")
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 1024
        or not token.isascii()
        or any(not 33 <= ord(character) <= 126 for character in token)
    ):
        _reject("REGISTRY_UNAVAILABLE", source_commit=source_commit)
    try:
        status, final_url, encoded = registry_get(REGISTRY_URL, token)
        if (
            status != 200
            or final_url != REGISTRY_URL
            or len(encoded) > REGISTRY_MAX_BYTES
        ):
            raise ValueError
        document = json.loads(encoded.decode("utf-8"))
        versions = document.get("versions") if isinstance(document, dict) else None
        if (
            document.get("name") != PACKAGE_NAME
            or not isinstance(versions, dict)
            or version in versions
        ):
            raise ValueError
    except Exception:
        _reject("REGISTRY_UNAVAILABLE", source_commit=source_commit)
    return {
        "schemaVersion": 1,
        "producer": "ts-handoff-preflight",
        "origin": REGISTRY_ORIGIN,
        "requestPath": REGISTRY_PATH,
        "package": PACKAGE_NAME,
        "version": version,
        "httpStatus": 200,
        "result": "version-unused",
        "packumentSha256": _sha256_bytes(encoded),
        "sourceCommit": source_commit,
        "workflow": dict(workflow),
    }


def _package_metadata(candidate: Path) -> dict[str, Any]:
    document, _encoded = _load_json(
        candidate / "kaji" / "ts" / "package.json", code="SOURCE_COMMIT_MISMATCH"
    )
    if document.get("name") != PACKAGE_NAME or not _valid_semver(
        document.get("version")
    ):
        _reject("SOURCE_COMMIT_MISMATCH")
    return document


def _preflight_document(
    *,
    mode: str,
    candidate_root: Path,
    source_input_dir: Path,
    output: Path,
    registry_get: RegistryGet,
) -> dict[str, Any]:
    output_parent = output.parent.resolve(strict=True)
    expected_source = output_parent / "source"
    try:
        actual_source = source_input_dir.resolve(strict=True)
    except OSError:
        _reject("RECEIPT_INVALID")
    if actual_source != expected_source:
        _reject("UNSAFE_PATH")
    source, source_bytes, signature, signature_bytes = _raw_inputs(actual_source)
    candidate = _recheck_source(candidate_root, source, signature)
    package = _package_metadata(candidate)
    workflow = _trusted_run_identity()
    if source.get("trustedVerifierCommit") != workflow["digest"]:
        _reject("SOURCE_COMMIT_MISMATCH", source_commit=source.get("headCommit"))
    toolchain = _toolchain(candidate)
    if mode == "release" and (
        toolchain["bun"] != "1.3.11" or toolchain["uv"] != "0.11.25"
    ):
        _reject("TOOLCHAIN_MISMATCH", source_commit=source.get("headCommit"))
    registry: dict[str, Any]
    if mode == "release":
        registry = _registry_proof(
            package["version"], source["headCommit"], workflow, registry_get
        )
    else:
        registry = {"status": "not-claimed"}
    return {
        "schemaVersion": 1,
        "command": "preflight",
        "result": "passed",
        "mode": mode,
        "sourceCommit": source["headCommit"],
        "treeSha": source["treeSha"],
        "trustedVerifierCommit": source["trustedVerifierCommit"],
        "package": {"name": PACKAGE_NAME, "version": package["version"]},
        "rawInputs": {
            "source": {
                "filename": RAW_SOURCE_NAME,
                "sha256": _sha256_bytes(source_bytes),
            },
            "signature": {
                "filename": RAW_SIGNATURE_NAME,
                "sha256": _sha256_bytes(signature_bytes),
            },
        },
        "toolchain": toolchain,
        "workflow": workflow,
        "registry": registry,
    }


def _validate_preflight(document: Mapping[str, Any], mode: str) -> None:
    _exact_keys(
        document,
        {
            "schemaVersion",
            "command",
            "result",
            "mode",
            "sourceCommit",
            "treeSha",
            "trustedVerifierCommit",
            "package",
            "rawInputs",
            "toolchain",
            "workflow",
            "registry",
        },
        "RECEIPT_INVALID",
    )
    if (
        document.get("schemaVersion") != 1
        or document.get("command") != "preflight"
        or document.get("result") != "passed"
        or document.get("mode") != mode
        or not _valid_hex40(document.get("sourceCommit"))
        or not _valid_hex40(document.get("treeSha"))
        or not _valid_hex40(document.get("trustedVerifierCommit"))
    ):
        _reject("RECEIPT_INVALID")
    package = document.get("package")
    raw_inputs = document.get("rawInputs")
    toolchain = document.get("toolchain")
    workflow = document.get("workflow")
    registry = document.get("registry")
    if not all(
        isinstance(item, dict)
        for item in (package, raw_inputs, toolchain, workflow, registry)
    ):
        _reject("RECEIPT_INVALID")
    _exact_keys(package, {"name", "version"}, "RECEIPT_INVALID")
    if package.get("name") != PACKAGE_NAME or not _valid_semver(package.get("version")):
        _reject("RECEIPT_INVALID")
    _exact_keys(raw_inputs, {"source", "signature"}, "RECEIPT_INVALID")
    for key, filename in (
        ("source", RAW_SOURCE_NAME),
        ("signature", RAW_SIGNATURE_NAME),
    ):
        item = raw_inputs.get(key)
        if not isinstance(item, dict):
            _reject("RECEIPT_INVALID")
        _exact_keys(item, {"filename", "sha256"}, "RECEIPT_INVALID")
        if item.get("filename") != filename or not _valid_hex64(item.get("sha256")):
            _reject("RECEIPT_INVALID")
    _exact_keys(toolchain, {"node", "npm", "bun", "uv"}, "RECEIPT_INVALID")
    if any(not _valid_semver(toolchain.get(key)) for key in toolchain):
        _reject("RECEIPT_INVALID")
    _exact_keys(
        workflow,
        {"repository", "filePath", "digest", "ref", "runId", "attempt"},
        "RECEIPT_INVALID",
    )
    if (
        workflow.get("repository") != "enkyuan/alloy"
        or workflow.get("filePath") != ".github/workflows/kaji.handoff.trusted.yml"
        or not _valid_hex40(workflow.get("digest"))
        or workflow.get("ref")
        != f"enkyuan/alloy/.github/workflows/kaji.handoff.trusted.yml@{workflow.get('digest')}"
        or type(workflow.get("runId")) is not int
        or type(workflow.get("attempt")) is not int
        or not 1 <= workflow["runId"] <= 9_007_199_254_740_991
        or not 1 <= workflow["attempt"] <= 9_007_199_254_740_991
    ):
        _reject("RECEIPT_INVALID")
    if document.get("trustedVerifierCommit") != workflow.get("digest"):
        _reject("RECEIPT_INVALID")
    if mode == "internal-evaluation":
        if registry != {"status": "not-claimed"}:
            _reject("RECEIPT_INVALID")
    else:
        _exact_keys(
            registry,
            {
                "schemaVersion",
                "producer",
                "origin",
                "requestPath",
                "package",
                "version",
                "httpStatus",
                "result",
                "packumentSha256",
                "sourceCommit",
                "workflow",
            },
            "RECEIPT_INVALID",
        )
        if (
            registry.get("schemaVersion") != 1
            or registry.get("producer") != "ts-handoff-preflight"
            or registry.get("origin") != REGISTRY_ORIGIN
            or registry.get("requestPath") != REGISTRY_PATH
            or registry.get("package") != PACKAGE_NAME
            or registry.get("version") != package.get("version")
            or registry.get("httpStatus") != 200
            or registry.get("result") != "version-unused"
            or not _valid_hex64(registry.get("packumentSha256"))
            or registry.get("sourceCommit") != document.get("sourceCommit")
            or registry.get("workflow") != workflow
        ):
            _reject("RECEIPT_INVALID")


def preflight(
    *,
    mode: str,
    candidate_root: Path,
    source_input_dir: Path,
    output: Path,
    registry_get: RegistryGet = _registry_get,
) -> None:
    document = _preflight_document(
        mode=mode,
        candidate_root=candidate_root,
        source_input_dir=source_input_dir,
        output=output,
        registry_get=registry_get,
    )
    _validate_preflight(document, mode)
    _atomic_file(output, _canonical_json(document))


def _stage_receipt(
    receipt_id: str, source_commit: str, artifact_sha: str, evidence: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "id": receipt_id,
        "result": "passed",
        "sourceCommit": source_commit,
        "artifactSha256": artifact_sha,
        "evidence": dict(evidence),
    }


def _run_stage_command(
    runner: CommandRunner,
    command: Sequence[str],
    root: Path,
    code: str,
) -> CompletedCommand:
    try:
        with tempfile.TemporaryDirectory(prefix="kaji-command-home-") as temporary_home:
            return runner(
                command,
                root,
                _command_environment(Path(temporary_home)),
            )
    except Exception:
        _reject(code)


def stage(
    *,
    mode: str,
    candidate_root: Path,
    preflight_path: Path,
    output_dir: Path,
    command_runner: CommandRunner = _run_process,
) -> None:
    preflight_document, preflight_bytes = _load_json(
        preflight_path, code="RECEIPT_INVALID", canonical="stable"
    )
    _validate_preflight(preflight_document, mode)
    source_dir = preflight_path.parent.resolve(strict=True) / "source"
    source, source_bytes, signature, signature_bytes = _raw_inputs(source_dir)
    raw_inputs = preflight_document["rawInputs"]
    if raw_inputs["source"]["sha256"] != _sha256_bytes(source_bytes) or raw_inputs[
        "signature"
    ]["sha256"] != _sha256_bytes(signature_bytes):
        _reject("RECEIPT_INVALID")
    candidate = _recheck_source(candidate_root, source, signature)
    if _toolchain(candidate) != preflight_document["toolchain"]:
        _reject("TOOLCHAIN_MISMATCH", source_commit=source["headCommit"])
    package = _package_metadata(candidate)
    if {"name": package["name"], "version": package["version"]} != preflight_document[
        "package"
    ] or (package.get("scripts") or {}).get("prebuild") != "bun run validate:registry":
        _reject("SOURCE_COMMIT_MISMATCH", source_commit=source["headCommit"])
    ts_root = candidate / "kaji" / "ts"

    with _owned_directory(output_dir) as temporary:
        _run_stage_command(command_runner, CLEAN_COMMAND, ts_root, "BUILD_FAILED")
        _recheck_source(candidate, source, signature)
        _run_stage_command(command_runner, BUILD_COMMAND, ts_root, "BUILD_FAILED")
        for command in AUDIT_COMMANDS:
            _run_stage_command(command_runner, command, ts_root, "BUILD_FAILED")
        _recheck_source(candidate, source, signature)

        pack_temp = temporary / ".pack"
        pack_temp.mkdir()
        actual_pack = (*PACK_COMMAND_NORMALIZED[:-1], str(pack_temp))
        completed = _run_stage_command(
            command_runner, actual_pack, ts_root, "PACK_FAILED"
        )
        try:
            pack_results = json.loads(completed.stdout.decode("utf-8"))
        except Exception:
            _reject("PACK_FAILED", source_commit=source["headCommit"])
        if (
            not isinstance(pack_results, list)
            or len(pack_results) != 1
            or not isinstance(pack_results[0], dict)
        ):
            _reject("PACK_COUNT_INVALID", source_commit=source["headCommit"])
        result = pack_results[0]
        files = list(pack_temp.iterdir())
        if len(files) != 1 or not files[0].is_file() or files[0].is_symlink():
            _reject("PACK_COUNT_INVALID", source_commit=source["headCommit"])
        tarball = files[0]
        expected_name = npm_pack_basename_v1(PACKAGE_NAME, package["version"])
        if tarball.name != expected_name or result.get("filename") != expected_name:
            _reject("PACK_FAILED", source_commit=source["headCommit"])
        size = tarball.stat().st_size
        if size <= 0:
            _reject("PACK_FAILED", source_commit=source["headCommit"])
        artifact_sha = _sha256_file(tarball)
        integrity = _npm_integrity(tarball)
        if result.get("size") != size or result.get("integrity") != integrity:
            _reject("PACK_FAILED", source_commit=source["headCommit"])
        destination_tarball = temporary / expected_name
        os.replace(tarball, destination_tarball)
        _fsync_file(destination_tarball)
        pack_temp.rmdir()
        _recheck_source(candidate, source, signature)

        source_evidence = {**source, "rawResultSha256": _sha256_bytes(source_bytes)}
        signature_evidence = {
            **signature,
            "rawResultSha256": _sha256_bytes(signature_bytes),
        }
        registry_status = "version-unused" if mode == "release" else "not-claimed"
        pack_evidence = {
            "mode": mode,
            "package": {"name": PACKAGE_NAME, "version": package["version"]},
            "artifact": {
                "filename": expected_name,
                "size": size,
                "npmIntegrity": integrity,
            },
            "toolchain": preflight_document["toolchain"],
            "construction": {
                "cleanCheckoutBuild": "passed",
                "packInvocationCount": 1,
            },
            "reproducibility": {"comparison": "not-run"},
            "registry": {"status": registry_status},
            "sourceTreeRecheck": "passed",
        }
        receipts = (
            _stage_receipt(
                "source-equivalence",
                source["headCommit"],
                artifact_sha,
                source_evidence,
            ),
            _stage_receipt(
                "signature-verification",
                source["headCommit"],
                artifact_sha,
                signature_evidence,
            ),
            _stage_receipt(
                "pack-once", source["headCommit"], artifact_sha, pack_evidence
            ),
        )
        schema = _schema()
        for receipt, definition in zip(receipts, RECEIPT_DEFINITIONS[:3], strict=True):
            if not _fragment_validator(schema, definition).is_valid(receipt):
                _reject(
                    "RECEIPT_INVALID",
                    source_commit=source["headCommit"],
                    artifact_sha256=artifact_sha,
                )
        receipt_entries: list[dict[str, str]] = []
        for receipt, filename in zip(
            receipts,
            (SOURCE_RECEIPT_NAME, SIGNATURE_RECEIPT_NAME, PACK_RECEIPT_NAME),
            strict=True,
        ):
            encoded = _canonical_json(receipt)
            _write_file(temporary / filename, encoded)
            receipt_entries.append(
                {
                    "id": receipt["id"],
                    "filename": filename,
                    "sha256": _sha256_bytes(encoded),
                }
            )
        index = {
            "schemaVersion": 1,
            "command": "stage",
            "result": "passed",
            "mode": mode,
            "sourceCommit": source["headCommit"],
            "treeSha": source["treeSha"],
            "trustedVerifierCommit": source["trustedVerifierCommit"],
            "preflightSha256": _sha256_bytes(preflight_bytes),
            "artifact": {
                "filename": expected_name,
                "size": size,
                "sha256": artifact_sha,
                "npmIntegrity": integrity,
            },
            "receipts": receipt_entries,
            "commands": {
                "clean": list(CLEAN_COMMAND),
                "build": list(BUILD_COMMAND),
                "audits": [list(command) for command in AUDIT_COMMANDS],
                "pack": list(PACK_COMMAND_NORMALIZED),
                "packInvocationCount": 1,
            },
        }
        _validate_stage_index(index, mode)
        _write_file(temporary / STAGE_INDEX_NAME, _canonical_json(index))


def _validate_stage_index(document: Mapping[str, Any], mode: str) -> None:
    _exact_keys(
        document,
        {
            "schemaVersion",
            "command",
            "result",
            "mode",
            "sourceCommit",
            "treeSha",
            "trustedVerifierCommit",
            "preflightSha256",
            "artifact",
            "receipts",
            "commands",
        },
        "RECEIPT_INVALID",
    )
    if (
        document.get("schemaVersion") != 1
        or document.get("command") != "stage"
        or document.get("result") != "passed"
        or document.get("mode") != mode
        or not all(
            _valid_hex40(document.get(key))
            for key in ("sourceCommit", "treeSha", "trustedVerifierCommit")
        )
        or not _valid_hex64(document.get("preflightSha256"))
    ):
        _reject("RECEIPT_INVALID")
    artifact = document.get("artifact")
    receipts = document.get("receipts")
    commands = document.get("commands")
    if (
        not isinstance(artifact, dict)
        or not isinstance(receipts, list)
        or not isinstance(commands, dict)
    ):
        _reject("RECEIPT_INVALID")
    _exact_keys(
        artifact, {"filename", "size", "sha256", "npmIntegrity"}, "RECEIPT_INVALID"
    )
    if (
        not isinstance(artifact.get("filename"), str)
        or Path(artifact["filename"]).name != artifact["filename"]
        or type(artifact.get("size")) is not int
        or artifact["size"] <= 0
        or not _valid_hex64(artifact.get("sha256"))
        or not isinstance(artifact.get("npmIntegrity"), str)
    ):
        _reject("RECEIPT_INVALID")
    if len(receipts) != 3:
        _reject("RECEIPT_INVALID")
    for item, receipt_id, filename in zip(
        receipts,
        RECEIPT_IDS[:3],
        (SOURCE_RECEIPT_NAME, SIGNATURE_RECEIPT_NAME, PACK_RECEIPT_NAME),
        strict=True,
    ):
        if not isinstance(item, dict):
            _reject("RECEIPT_INVALID")
        _exact_keys(item, {"id", "filename", "sha256"}, "RECEIPT_INVALID")
        if (
            item.get("id") != receipt_id
            or item.get("filename") != filename
            or not _valid_hex64(item.get("sha256"))
        ):
            _reject("RECEIPT_INVALID")
    _exact_keys(
        commands,
        {"clean", "build", "audits", "pack", "packInvocationCount"},
        "RECEIPT_INVALID",
    )
    if commands != {
        "clean": list(CLEAN_COMMAND),
        "build": list(BUILD_COMMAND),
        "audits": [list(command) for command in AUDIT_COMMANDS],
        "pack": list(PACK_COMMAND_NORMALIZED),
        "packInvocationCount": 1,
    }:
        _reject("RECEIPT_INVALID")


def _directory_files(root: Path) -> dict[str, Path]:
    try:
        children = list(root.iterdir())
    except OSError:
        _reject("RECEIPT_INVALID")
    if any(not item.is_file() or item.is_symlink() for item in children):
        _reject("RECEIPT_INVALID")
    return {item.name: item for item in children}


def _load_receipt(
    path: Path, definition: str, schema: dict[str, Any]
) -> tuple[dict[str, Any], bytes]:
    document, encoded = _load_json(path, code="RECEIPT_INVALID", canonical="stable")
    if not _fragment_validator(schema, definition).is_valid(document):
        _reject("RECEIPT_INVALID")
    return document, encoded


def _verify_archive_identity(tarball: Path) -> tuple[dict[str, Any], bytes]:
    try:
        with tarfile.open(tarball, "r:gz") as archive:
            package_member = archive.getmember("package/package.json")
            license_member = archive.getmember("package/LICENSE")
            if (
                not package_member.isfile()
                or package_member.issym()
                or package_member.islnk()
                or not license_member.isfile()
                or license_member.issym()
                or license_member.islnk()
            ):
                raise ValueError
            package_stream = archive.extractfile(package_member)
            license_stream = archive.extractfile(license_member)
            if package_stream is None or license_stream is None:
                raise ValueError
            package = json.loads(package_stream.read().decode("utf-8"))
            license_bytes = license_stream.read()
            if not isinstance(package, dict):
                raise ValueError
            return package, license_bytes
    except Exception:
        _reject("VALIDATION_FAILED")


def _validate_receipt_relations(
    receipts: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    preflight: Mapping[str, Any],
    stage_index: Mapping[str, Any],
    artifact_size: int,
    artifact_sha: str,
    artifact_integrity: str,
    candidate_toolchain: Mapping[str, str],
) -> None:
    if len(receipts) != 6:
        _reject("RECEIPT_INVALID")
    if [receipt.get("id") for receipt in receipts] != list(RECEIPT_IDS):
        _reject("RECEIPT_INVALID")
    if any(
        receipt.get("sourceCommit") != stage_index["sourceCommit"]
        or receipt.get("artifactSha256") != artifact_sha
        for receipt in receipts
    ):
        _reject("RECEIPT_INVALID")
    source = receipts[0]["evidence"]
    signature = receipts[1]["evidence"]
    _validate_source_signature_relations(source, signature)
    if (
        source.get("headCommit") != stage_index["sourceCommit"]
        or source.get("treeSha") != stage_index["treeSha"]
        or source.get("trustedVerifierCommit") != stage_index["trustedVerifierCommit"]
        or source.get("headCommit") != preflight["sourceCommit"]
        or source.get("treeSha") != preflight["treeSha"]
        or source.get("trustedVerifierCommit") != preflight["trustedVerifierCommit"]
        or source.get("rawResultSha256") != preflight["rawInputs"]["source"]["sha256"]
        or signature.get("rawResultSha256")
        != preflight["rawInputs"]["signature"]["sha256"]
    ):
        _reject("RECEIPT_INVALID")
    pack = receipts[2]["evidence"]
    expected_registry = (
        {"status": preflight["registry"]["result"]}
        if mode == "release"
        else preflight["registry"]
    )
    expected_pack_artifact = {
        "filename": stage_index["artifact"]["filename"],
        "size": artifact_size,
        "npmIntegrity": artifact_integrity,
    }
    if (
        pack.get("mode") != mode
        or pack.get("registry") != expected_registry
        or pack.get("package") != preflight["package"]
        or pack.get("artifact") != expected_pack_artifact
        or pack.get("toolchain") != preflight["toolchain"]
        or pack.get("toolchain") != candidate_toolchain
        or pack.get("construction", {}).get("packInvocationCount")
        != stage_index["commands"]["packInvocationCount"]
        or stage_index["artifact"]["sha256"] != artifact_sha
        or stage_index["artifact"]["size"] != artifact_size
        or stage_index["artifact"]["npmIntegrity"] != artifact_integrity
    ):
        _reject("RECEIPT_INVALID")
    artifact_contract = receipts[3]["evidence"]
    if (
        artifact_contract["installs"]["npm"]["artifactSha256"] != artifact_sha
        or artifact_contract["installs"]["bun"]["artifactSha256"] != artifact_sha
        or receipts[4]["evidence"]["installedArtifactSha256"] != artifact_sha
        or receipts[5]["evidence"]["installedArtifactSha256"] != artifact_sha
    ):
        _reject("RECEIPT_INVALID")


def _manifest_document(
    *,
    index: Mapping[str, Any],
    artifact_size: int,
    artifact_sha: str,
    artifact_integrity: str,
    receipts: Sequence[Mapping[str, Any]],
    gate: Mapping[str, Any],
    source: Mapping[str, Any],
    signature: Mapping[str, Any],
) -> dict[str, Any]:
    pack = receipts[2]["evidence"]
    artifact_contract = receipts[3]["evidence"]
    typescript_catalog = artifact_contract["catalogs"]["typescript"]
    shared_catalog = artifact_contract["catalogs"]["shared"]
    return {
        "schemaVersion": 1,
        "artifact": {
            "filename": index["artifact"]["filename"],
            "size": artifact_size,
            "sha256": artifact_sha,
            "npmIntegrity": artifact_integrity,
            "construction": pack["construction"],
            "reproducibility": pack["reproducibility"],
        },
        "package": {
            "name": PACKAGE_NAME,
            "version": pack["package"]["version"],
            "exports": artifact_contract["package"]["exports"],
            "publicSymbols": {"github": artifact_contract["package"]["publicSymbols"]},
        },
        "source": {
            "repository": REPOSITORY_URL,
            "commit": source["headCommit"],
            "tree": source["treeSha"],
            "mergeBase": source["mergeBase"],
            "verifierCommit": source["trustedVerifierCommit"],
            "signature": {
                "required": True,
                "result": "passed",
                "mechanism": signature["mechanism"],
            },
        },
        "github": {
            "abi": {
                "schemaVersion": typescript_catalog["schemaVersion"],
                "catalogVersion": typescript_catalog["catalogVersion"],
            },
            "userAgentVersion": "0.2.0",
            "sharedManifestVersion": shared_catalog["manifestVersion"],
            "totalCount": typescript_catalog["totalCount"],
            "readCount": typescript_catalog["readCount"],
            "tools": typescript_catalog["tools"],
            "readTools": typescript_catalog["readTools"],
            "shared": {
                "totalCount": shared_catalog["totalCount"],
                "readCount": shared_catalog["readCount"],
                "tools": shared_catalog["tools"],
                "readTools": shared_catalog["readTools"],
            },
        },
        "upstreamVerification": [*receipts, gate],
        "securityEvidence": {
            "policyBeforeRequest": {
                **artifact_contract["policy"],
                "result": "passed",
            }
        },
        "license": {
            "id": "FSL-1.1-ALv2",
            "file": "LICENSE",
            "sha256": artifact_contract["license"]["sha256"],
            "competingUseApproved": False,
            "futureLicense": "Apache-2.0",
            "futureLicenseAfter": "second-anniversary",
        },
    }


def finalize(
    *,
    mode: str,
    candidate_root: Path,
    preflight_path: Path,
    stage_dir: Path,
    artifact_contract_path: Path,
    node22_path: Path,
    node24_path: Path,
    output_dir: Path,
) -> None:
    _safe_absent_destination(output_dir)
    receipt_set = preflight_path.parent.resolve(strict=True) / "receipt-set"
    _safe_absent_destination(receipt_set)
    preflight_document, preflight_bytes = _load_json(
        preflight_path, code="RECEIPT_INVALID", canonical="stable"
    )
    _validate_preflight(preflight_document, mode)
    stage_files = _directory_files(stage_dir)
    index, _index_bytes = _load_json(
        stage_dir / STAGE_INDEX_NAME, code="RECEIPT_INVALID", canonical="stable"
    )
    _validate_stage_index(index, mode)
    expected_stage = {
        STAGE_INDEX_NAME,
        SOURCE_RECEIPT_NAME,
        SIGNATURE_RECEIPT_NAME,
        PACK_RECEIPT_NAME,
        index["artifact"]["filename"],
    }
    if set(stage_files) != expected_stage:
        _reject("RECEIPT_INVALID")
    if index["preflightSha256"] != _sha256_bytes(preflight_bytes):
        _reject("RECEIPT_INVALID")
    if (
        index["sourceCommit"] != preflight_document["sourceCommit"]
        or index["treeSha"] != preflight_document["treeSha"]
        or index["trustedVerifierCommit"] != preflight_document["trustedVerifierCommit"]
    ):
        _reject("RECEIPT_INVALID")
    tarball = stage_dir / index["artifact"]["filename"]
    artifact_size, artifact_sha, artifact_integrity = _artifact_measurements(tarball)
    if (
        artifact_sha != index["artifact"]["sha256"]
        or artifact_size != index["artifact"]["size"]
        or artifact_integrity != index["artifact"]["npmIntegrity"]
    ):
        _reject(
            "ARTIFACT_CHANGED",
            source_commit=index["sourceCommit"],
            artifact_sha256=artifact_sha,
        )
    schema = _schema()
    supplied_paths = (
        stage_dir / SOURCE_RECEIPT_NAME,
        stage_dir / SIGNATURE_RECEIPT_NAME,
        stage_dir / PACK_RECEIPT_NAME,
        artifact_contract_path,
        node22_path,
        node24_path,
    )
    loaded = [
        _load_receipt(path, definition, schema)
        for path, definition in zip(supplied_paths, RECEIPT_DEFINITIONS, strict=True)
    ]
    receipts = [item[0] for item in loaded]
    receipt_bytes = [item[1] for item in loaded]
    for entry, encoded in zip(index["receipts"], receipt_bytes[:3], strict=True):
        if entry["sha256"] != _sha256_bytes(encoded):
            _reject("RECEIPT_INVALID")
    source = receipts[0]["evidence"]
    signature = receipts[1]["evidence"]
    candidate = _recheck_source(candidate_root, source, signature)
    candidate_toolchain = _toolchain(candidate)
    if candidate_toolchain != preflight_document["toolchain"]:
        _reject(
            "TOOLCHAIN_MISMATCH",
            source_commit=index["sourceCommit"],
            artifact_sha256=artifact_sha,
        )
    workflow = _trusted_run_identity()
    if workflow != preflight_document["workflow"]:
        _reject("RECEIPT_INVALID")
    with _owned_directory(output_dir) as final_temporary:
        copied_tarball = final_temporary / index["artifact"]["filename"]
        shutil.copyfile(tarball, copied_tarball)
        _fsync_file(copied_tarball)
        copied_size, copied_sha, copied_integrity = _artifact_measurements(
            copied_tarball
        )
        if (
            copied_size != index["artifact"]["size"]
            or copied_sha != index["artifact"]["sha256"]
            or copied_integrity != index["artifact"]["npmIntegrity"]
            or (copied_size, copied_sha, copied_integrity)
            != (artifact_size, artifact_sha, artifact_integrity)
        ):
            _reject(
                "ARTIFACT_CHANGED",
                source_commit=index["sourceCommit"],
                artifact_sha256=copied_sha,
            )
        _validate_receipt_relations(
            receipts,
            mode=mode,
            preflight=preflight_document,
            stage_index=index,
            artifact_size=copied_size,
            artifact_sha=copied_sha,
            artifact_integrity=copied_integrity,
            candidate_toolchain=candidate_toolchain,
        )

        pack = receipts[2]["evidence"]
        artifact_contract = receipts[3]["evidence"]
        packed_package, license_bytes = _verify_archive_identity(copied_tarball)
        if (
            packed_package.get("name") != preflight_document["package"]["name"]
            or packed_package.get("version") != preflight_document["package"]["version"]
            or packed_package.get("version") != pack["package"]["version"]
            or packed_package.get("exports") != artifact_contract["package"]["exports"]
            or _sha256_bytes(license_bytes) != artifact_contract["license"]["sha256"]
        ):
            _reject("VALIDATION_FAILED")

        digest_values = {
            key: _sha256_bytes(encoded)
            for key, encoded in zip(RECEIPT_DIGEST_KEYS, receipt_bytes, strict=True)
        }
        signer = {
            key: workflow[key] for key in ("repository", "filePath", "digest", "ref")
        }
        if source["trustedVerifierCommit"] != signer["digest"]:
            _reject("RECEIPT_INVALID")
        release = mode == "release"
        if release and preflight_document["registry"].get("workflow") != workflow:
            _reject("RECEIPT_INVALID")
        gate_evidence = {
            "mode": mode,
            "registry": "version-unused" if release else "not-claimed",
            "signerWorkflow": signer,
            "toolchain": candidate_toolchain,
            "publicReleaseClaim": "eligible" if release else "not-claimed",
            "licenseUseClaim": "permitted-purpose-only",
            "receiptSha256": digest_values,
            "checks": [
                {"id": check, "result": "passed"}
                for check in (RELEASE_CHECKS if release else INTERNAL_CHECKS)
            ],
        }
        gate = _stage_receipt(
            "release-gate" if release else "internal-evaluation-gate",
            index["sourceCommit"],
            copied_sha,
            gate_evidence,
        )
        gate_definition = "releaseGateReceipt" if release else "internalGateReceipt"
        if not _fragment_validator(schema, gate_definition).is_valid(gate):
            _reject("RECEIPT_INVALID")
        manifest = _manifest_document(
            index=index,
            artifact_size=copied_size,
            artifact_sha=copied_sha,
            artifact_integrity=copied_integrity,
            receipts=receipts,
            gate=gate,
            source=source,
            signature=signature,
        )
        if not Draft202012Validator(schema).is_valid(manifest):
            _reject("SCHEMA_INVALID")
        _write_file(final_temporary / MANIFEST_NAME, _canonical_json(manifest))
        _write_file(final_temporary / SCHEMA_NAME, _schema_path().read_bytes())
        with _owned_directory(receipt_set) as receipt_temporary:
            for filename, encoded in zip(RECEIPT_SET_NAMES, receipt_bytes, strict=True):
                _write_file(receipt_temporary / filename, encoded)


def _failure_document(command: str, error: HandoffError) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "command": command,
        "result": "failed",
        "failureCode": error.code,
        "sourceCommit": error.source_commit,
        "artifactSha256": error.artifact_sha256,
    }


def _write_failure(
    failure_dir: Path | None, command: str, document: Mapping[str, Any]
) -> None:
    encoded = _canonical_json(document)
    if failure_dir is not None:
        try:
            root = failure_dir.resolve(strict=True)
            if not root.is_dir() or root.is_symlink():
                raise OSError
            destination = root / f"{command}.failure.json"
            if not os.path.lexists(destination):
                _atomic_file(destination, encoded)
        except Exception:
            pass
    sys.stderr.buffer.write(encoded)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=_ArgumentParser
    )
    for name in ("preflight", "stage", "finalize"):
        child = subparsers.add_parser(name)
        child.add_argument(
            "--mode", required=True, choices=("release", "internal-evaluation")
        )
        child.add_argument("--candidate-root", required=True, type=Path)
        child.add_argument("--failure-dir", type=Path)
    preflight_parser = subparsers.choices["preflight"]
    preflight_parser.add_argument("--source-input-dir", required=True, type=Path)
    preflight_parser.add_argument("--output", required=True, type=Path)
    stage_parser = subparsers.choices["stage"]
    stage_parser.add_argument("--preflight", required=True, type=Path)
    stage_parser.add_argument("--output-dir", required=True, type=Path)
    finalize_parser = subparsers.choices["finalize"]
    finalize_parser.add_argument("--preflight", required=True, type=Path)
    finalize_parser.add_argument("--stage-dir", required=True, type=Path)
    finalize_parser.add_argument("--artifact-contract", required=True, type=Path)
    finalize_parser.add_argument("--node-22", required=True, type=Path)
    finalize_parser.add_argument("--node-24", required=True, type=Path)
    finalize_parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def _run(
    argv: Sequence[str],
    *,
    registry_get: RegistryGet = _registry_get,
    command_runner: CommandRunner = _run_process,
) -> int:
    command = "preflight"
    failure_dir: Path | None = None
    try:
        arguments = _parser().parse_args(argv)
        command = arguments.command
        failure_dir = arguments.failure_dir
        if command == "preflight":
            preflight(
                mode=arguments.mode,
                candidate_root=arguments.candidate_root,
                source_input_dir=arguments.source_input_dir,
                output=arguments.output,
                registry_get=registry_get,
            )
        elif command == "stage":
            stage(
                mode=arguments.mode,
                candidate_root=arguments.candidate_root,
                preflight_path=arguments.preflight,
                output_dir=arguments.output_dir,
                command_runner=command_runner,
            )
        else:
            finalize(
                mode=arguments.mode,
                candidate_root=arguments.candidate_root,
                preflight_path=arguments.preflight,
                stage_dir=arguments.stage_dir,
                artifact_contract_path=arguments.artifact_contract,
                node22_path=arguments.node_22,
                node24_path=arguments.node_24,
                output_dir=arguments.output_dir,
            )
    except HandoffError as error:
        _write_failure(failure_dir, command, _failure_document(command, error))
        return 2 if error.code == "INVALID_ARGUMENT" else 1
    except HandoffInterrupted as interrupted:
        error = HandoffError("INTERNAL_ERROR")
        _write_failure(failure_dir, command, _failure_document(command, error))
        return 128 + interrupted.signum
    except Exception:
        error = HandoffError("INTERNAL_ERROR")
        _write_failure(failure_dir, command, _failure_document(command, error))
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return _run(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
