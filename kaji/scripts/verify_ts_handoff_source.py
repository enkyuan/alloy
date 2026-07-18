#!/usr/bin/env python3
"""Verify an isolated Kaji source checkout with GitHub's signed-object API."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
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
import sys
import tempfile
import time
from typing import Any, NoReturn
from urllib import request

from process_runner import CommandError, METADATA_BUDGET, run_checked


REPOSITORY = "enkyuan/alloy"
REPOSITORY_URL = "https://github.com/enkyuan/alloy.git"
BASE_REF = "refs/remotes/origin/main"
API_ROOT = "https://api.github.com"
API_VERSION = "2026-03-10"
SOURCE_RESULT = "source-equivalence.raw.json"
SIGNATURE_RESULT = "signature-verification.raw.json"
MAX_REST_BYTES = 1_048_576
REST_DEADLINE_SECONDS = 30.0
REST_SOCKET_TIMEOUT_SECONDS = 30.0

HEX40 = re.compile(r"[0-9a-f]{40}")
EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
)
TAG_NAME = re.compile(
    r"kaji-[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?)*"
)
COMMITTER = re.compile(r"committer .+ <([^<>\n]+)> -?[0-9]+ [+-][0-9]{4}")

RestGet = Callable[[str, str], Mapping[str, Any]]


class VerificationError(RuntimeError):
    """A closed, redaction-safe handoff verification failure."""

    def __init__(self, code: str, *, source_commit: str | None = None) -> None:
        self.code = code
        self.source_commit = source_commit
        super().__init__(code)


class VerifierInterrupted(BaseException):
    """Signal converted to an exception so owned temporary output can be removed."""

    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(signum)


class RestDeadlineExceeded(TimeoutError):
    """The complete GitHub REST open/read operation exceeded its budget."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise VerificationError("INVALID_ARGUMENT")


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *_arguments: object, **_options: object) -> None:
        return None


def _reject(code: str, *, source_commit: str | None = None) -> NoReturn:
    raise VerificationError(code, source_commit=source_commit)


def _valid_hex40(value: object) -> bool:
    return isinstance(value, str) and HEX40.fullmatch(value) is not None


def _valid_email(value: object) -> bool:
    return (
        isinstance(value, str)
        and 3 <= len(value) <= 254
        and EMAIL.fullmatch(value) is not None
        and value.isascii()
    )


def _valid_tag(value: object) -> bool:
    return (
        isinstance(value, str)
        and 6 <= len(value) <= 128
        and TAG_NAME.fullmatch(value) is not None
        and not value.endswith(".lock")
        and value.isascii()
    )


def _trusted_root() -> Path:
    return Path(__file__).resolve().parents[2]


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


def _git(
    root: Path,
    *arguments: str,
    check: bool = True,
    failure_code: str = "SOURCE_COMMIT_MISMATCH",
) -> bytes:
    try:
        completed = run_checked(
            ("git", *arguments),
            cwd=root,
            budget=METADATA_BUDGET,
            capture=True,
            env=_git_environment(),
            check=check,
        )
    except CommandError:
        _reject(failure_code)
    if check or completed.returncode == 0:
        return completed.stdout
    return b""


def _git_text(
    root: Path,
    *arguments: str,
    failure_code: str = "SOURCE_COMMIT_MISMATCH",
) -> str:
    try:
        return _git(root, *arguments, failure_code=failure_code).decode("ascii").strip()
    except UnicodeError:
        _reject(failure_code)


def _checkout_root(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        _reject("SOURCE_NOT_ISOLATED")
    if not resolved.is_dir():
        _reject("SOURCE_NOT_ISOLATED")
    top = _git_text(
        resolved,
        "rev-parse",
        "--show-toplevel",
        failure_code="SOURCE_NOT_ISOLATED",
    )
    try:
        actual = Path(top).resolve(strict=True)
    except OSError:
        _reject("SOURCE_NOT_ISOLATED")
    if actual != resolved:
        _reject("SOURCE_NOT_ISOLATED")
    shallow = _git_text(
        resolved,
        "rev-parse",
        "--is-shallow-repository",
        failure_code="SOURCE_NOT_ISOLATED",
    )
    if shallow != "false":
        _reject("SOURCE_NOT_ISOLATED")
    return resolved


def _require_clean(root: Path) -> None:
    status = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        failure_code="SOURCE_DIRTY",
    )
    if status:
        _reject("SOURCE_DIRTY")


def _revision(root: Path, expression: str) -> str:
    value = _git_text(root, "rev-parse", "--verify", expression)
    if not _valid_hex40(value):
        _reject("SOURCE_COMMIT_MISMATCH")
    return value


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    try:
        completed = run_checked(
            ("git", "merge-base", "--is-ancestor", ancestor, descendant),
            cwd=root,
            budget=METADATA_BUDGET,
            capture=True,
            env=_git_environment(),
            check=False,
        )
    except CommandError:
        _reject("SOURCE_COMMIT_MISMATCH")
    if completed.stdout or completed.stderr:
        _reject("SOURCE_COMMIT_MISMATCH")
    if completed.returncode not in {0, 1}:
        _reject("SOURCE_COMMIT_MISMATCH")
    return completed.returncode == 0


def _canonical_range(root: Path, base: str, head: str) -> list[str]:
    encoded = _git(
        root,
        "rev-list",
        "--reverse",
        "--topo-order",
        f"{base}..{head}",
    )
    try:
        lines = encoded.decode("ascii").splitlines()
    except UnicodeError:
        _reject("SOURCE_COMMIT_MISMATCH")
    if any(not _valid_hex40(item) for item in lines) or len(lines) != len(set(lines)):
        _reject("SOURCE_COMMIT_MISMATCH")
    if lines and (lines[-1] != head or lines.count(head) != 1):
        _reject("SOURCE_COMMIT_MISMATCH")
    return lines


def _script_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()
    except OSError:
        _reject("SOURCE_COMMIT_MISMATCH")


def _open_github(github_request: request.Request, *, timeout: float) -> Any:
    return request.build_opener(_NoRedirect()).open(github_request, timeout=timeout)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RestDeadlineExceeded
    return remaining


@contextmanager
def _absolute_rest_deadline(seconds: float) -> Iterator[float]:
    started = time.monotonic()
    deadline = started + seconds
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_delay, previous_interval = signal.getitimer(signal.ITIMER_REAL)
    installed = False

    def expired(_signum: int, _frame: object) -> NoReturn:
        raise RestDeadlineExceeded

    try:
        signal.signal(signal.SIGALRM, expired)
        installed = True
        signal.setitimer(signal.ITIMER_REAL, _remaining(deadline))
        yield deadline
    finally:
        if installed:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            elapsed = time.monotonic() - started
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_delay > 0:
                signal.setitimer(
                    signal.ITIMER_REAL,
                    max(previous_delay - elapsed, 1e-6),
                    previous_interval,
                )


def _set_response_timeout(response: Any, timeout: float) -> None:
    stream = getattr(response, "fp", None)
    raw = getattr(stream, "raw", None)
    socket = getattr(raw, "_sock", None)
    setter = getattr(socket, "settimeout", None)
    if callable(setter):
        setter(timeout)


def _github_rest_get(path: str, token: str) -> Mapping[str, Any]:
    url = f"{API_ROOT}{path}"
    github_request = request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "kaji-ts-handoff-source-verifier/1",
            "X-GitHub-Api-Version": API_VERSION,
        },
        method="GET",
    )
    with _absolute_rest_deadline(REST_DEADLINE_SECONDS) as deadline:
        open_timeout = min(REST_SOCKET_TIMEOUT_SECONDS, _remaining(deadline))
        with _open_github(github_request, timeout=open_timeout) as response:
            if response.status != 200 or response.geturl() != url:
                raise RuntimeError("unexpected GitHub response")
            _set_response_timeout(
                response,
                min(REST_SOCKET_TIMEOUT_SECONDS, _remaining(deadline)),
            )
            encoded = response.read(MAX_REST_BYTES + 1)
            _remaining(deadline)
    if len(encoded) > MAX_REST_BYTES:
        raise RuntimeError("GitHub response too large")
    document = json.loads(encoded.decode("utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("GitHub response must be an object")
    return document


def _rest(rest_get: RestGet, path: str, token: str, code: str) -> Mapping[str, Any]:
    try:
        document = rest_get(path, token)
    except Exception:
        raise VerificationError(code) from None
    if not isinstance(document, Mapping):
        _reject(code)
    return document


def _payload_committer(payload: object) -> tuple[str, bytes]:
    if not isinstance(payload, str):
        _reject("SIGNATURE_INVALID")
    try:
        encoded = payload.encode("utf-8")
    except UnicodeError:
        _reject("SIGNATURE_INVALID")
    if len(encoded) > MAX_REST_BYTES:
        _reject("SIGNATURE_INVALID")
    header, separator, _message = payload.partition("\n\n")
    if separator != "\n\n" or "\r" in header or "\0" in header:
        _reject("SIGNATURE_INVALID")
    committers = [line for line in header.splitlines() if line.startswith("committer ")]
    if len(committers) != 1:
        _reject("SIGNATURE_INVALID")
    matched = COMMITTER.fullmatch(committers[0])
    if matched is None or not _valid_email(matched.group(1)):
        _reject("SIGNATURE_INVALID")
    return matched.group(1), encoded


def _verify_commit(
    sha: str,
    *,
    signer: str,
    token: str,
    rest_get: RestGet,
) -> dict[str, Any]:
    document = _rest(
        rest_get,
        f"/repos/{REPOSITORY}/git/commits/{sha}",
        token,
        "SIGNATURE_INVALID",
    )
    verification = document.get("verification")
    committer = document.get("committer")
    if (
        document.get("sha") != sha
        or not isinstance(verification, Mapping)
        or verification.get("verified") is not True
        or verification.get("reason") != "valid"
        or not isinstance(committer, Mapping)
    ):
        _reject("SIGNATURE_INVALID")
    response_email = committer.get("email")
    if response_email != signer:
        _reject("SIGNER_NOT_APPROVED")
    payload = verification.get("payload")
    payload_email, encoded_payload = _payload_committer(payload)
    if payload_email != response_email:
        _reject("SIGNATURE_INVALID")
    return {
        "sha": sha,
        "verified": True,
        "reason": "valid",
        "signerEmail": signer,
        "payloadSha256": hashlib.sha256(encoded_payload).hexdigest(),
    }


def _verify_tag(
    name: str,
    *,
    head: str,
    signer: str,
    token: str,
    rest_get: RestGet,
) -> dict[str, Any]:
    ref = _rest(
        rest_get,
        f"/repos/{REPOSITORY}/git/ref/tags/{name}",
        token,
        "TAG_INVALID",
    )
    ref_object = ref.get("object")
    if (
        ref.get("ref") != f"refs/tags/{name}"
        or not isinstance(ref_object, Mapping)
        or ref_object.get("type") != "tag"
        or not _valid_hex40(ref_object.get("sha"))
    ):
        _reject("TAG_INVALID")
    object_sha = ref_object["sha"]
    assert isinstance(object_sha, str)
    tag = _rest(
        rest_get,
        f"/repos/{REPOSITORY}/git/tags/{object_sha}",
        token,
        "TAG_INVALID",
    )
    verification = tag.get("verification")
    tagger = tag.get("tagger")
    target = tag.get("object")
    if (
        tag.get("sha") != object_sha
        or tag.get("tag") != name
        or not isinstance(verification, Mapping)
        or verification.get("verified") is not True
        or verification.get("reason") != "valid"
        or not isinstance(tagger, Mapping)
        or not isinstance(target, Mapping)
        or target.get("type") != "commit"
        or target.get("sha") != head
    ):
        _reject("TAG_INVALID")
    if tagger.get("email") != signer:
        _reject("SIGNER_NOT_APPROVED")
    return {
        "name": name,
        "objectSha": object_sha,
        "targetCommit": head,
        "taggerEmail": signer,
        "verified": True,
        "reason": "valid",
    }


def _canonical_json(document: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    with path.open("xb") as stream:
        stream.write(_canonical_json(document))
        stream.flush()
        os.fsync(stream.fileno())


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
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _output_path(path: Path) -> Path:
    if os.path.lexists(path):
        _reject("OUTPUT_EXISTS")
    if path.name in {"", ".", ".."}:
        _reject("UNSAFE_PATH")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError:
        _reject("UNSAFE_PATH")
    if not parent.is_dir():
        _reject("UNSAFE_PATH")
    destination = parent / path.name
    if os.path.lexists(destination):
        _reject("OUTPUT_EXISTS")
    return destination


def _write_outputs(
    output: Path,
    source_document: Mapping[str, Any],
    signature_document: Mapping[str, Any],
) -> None:
    watched = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous: dict[signal.Signals, Any] = {}
    temporary: Path | None = None

    def interrupted(signum: int, _frame: object) -> NoReturn:
        raise VerifierInterrupted(signum)

    try:
        for signum in watched:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, interrupted)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent)
        )
        _write_json(temporary / SOURCE_RESULT, source_document)
        _write_json(temporary / SIGNATURE_RESULT, signature_document)
        _fsync_directory(temporary)
        try:
            _rename_noreplace(temporary, output)
        except FileExistsError:
            _reject("OUTPUT_EXISTS")
        except OSError:
            _reject("INTERNAL_ERROR")
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)


def _require_unchanged(
    *,
    candidate: Path,
    trusted: Path,
    head: str,
    tree: str,
    merge_base: str,
    revision_range: Sequence[str],
    trusted_commit: str,
    verifier_sha256: str,
) -> None:
    _require_clean(candidate)
    _require_clean(trusted)
    if (
        _revision(candidate, "HEAD^{commit}") != head
        or _revision(candidate, "HEAD^{tree}") != tree
        or _git_text(candidate, "merge-base", BASE_REF, "HEAD") != merge_base
        or _canonical_range(candidate, merge_base, head) != list(revision_range)
        or _revision(trusted, "HEAD^{commit}") != trusted_commit
        or _script_sha256() != verifier_sha256
    ):
        _reject("SOURCE_COMMIT_MISMATCH")
    _revision(trusted, f"{BASE_REF}^{{commit}}")
    if not _is_ancestor(trusted, trusted_commit, BASE_REF):
        _reject("TRUSTED_VERIFIER_NOT_ON_DEFAULT")


def verify_source(
    *,
    candidate_root: Path,
    base_ref: str,
    mode: str,
    tag_name: str | None,
    output_dir: Path,
    rest_get: RestGet = _github_rest_get,
) -> None:
    """Verify source/signatures and atomically write the two closed raw results."""

    output = _output_path(output_dir)
    if base_ref != BASE_REF or mode not in {"commit", "signed-tag"}:
        _reject("INVALID_ARGUMENT")
    if (mode == "commit" and tag_name is not None) or (
        mode == "signed-tag" and not _valid_tag(tag_name)
    ):
        _reject("INVALID_ARGUMENT")

    signer = os.environ.get("KAJI_RELEASE_SIGNER_EMAIL")
    if not _valid_email(signer):
        _reject("SIGNER_NOT_APPROVED")
    token = os.environ.get("GH_TOKEN")
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 1024
        or not token.isascii()
        or any(not 33 <= ord(char) <= 126 for char in token)
    ):
        _reject("SIGNATURE_INVALID")

    trusted = _checkout_root(_trusted_root())
    candidate = _checkout_root(candidate_root)
    if (
        trusted == candidate
        or trusted.is_relative_to(candidate)
        or candidate.is_relative_to(trusted)
    ):
        _reject("SOURCE_NOT_ISOLATED")
    _require_clean(trusted)
    _require_clean(candidate)

    trusted_commit = _revision(trusted, "HEAD^{commit}")
    _revision(trusted, f"{BASE_REF}^{{commit}}")
    if not _is_ancestor(trusted, trusted_commit, BASE_REF):
        _reject("TRUSTED_VERIFIER_NOT_ON_DEFAULT")
    verifier_sha256 = _script_sha256()
    head = _revision(candidate, "HEAD^{commit}")
    tree = _revision(candidate, "HEAD^{tree}")
    merge_base = _git_text(candidate, "merge-base", BASE_REF, "HEAD")
    if not _valid_hex40(merge_base):
        _reject("SOURCE_COMMIT_MISMATCH", source_commit=head)
    revision_range = _canonical_range(candidate, merge_base, head)
    if not revision_range and (
        head != merge_base or not _is_ancestor(candidate, head, BASE_REF)
    ):
        _reject("SIGNATURE_RANGE_EMPTY", source_commit=head)
    commits_to_verify = revision_range or [head]

    try:
        commit_results = [
            _verify_commit(sha, signer=signer, token=token, rest_get=rest_get)
            for sha in commits_to_verify
        ]
        tag_result = (
            _verify_tag(
                tag_name,
                head=head,
                signer=signer,
                token=token,
                rest_get=rest_get,
            )
            if mode == "signed-tag" and isinstance(tag_name, str)
            else None
        )
        _require_unchanged(
            candidate=candidate,
            trusted=trusted,
            head=head,
            tree=tree,
            merge_base=merge_base,
            revision_range=revision_range,
            trusted_commit=trusted_commit,
            verifier_sha256=verifier_sha256,
        )
    except VerificationError as error:
        if error.source_commit is None:
            error.source_commit = head
        raise

    source_document = {
        "repository": REPOSITORY_URL,
        "headCommit": head,
        "treeSha": tree,
        "mergeBase": merge_base,
        "revisionCommand": [
            "git",
            "rev-list",
            "--reverse",
            "--topo-order",
            f"{merge_base}..{head}",
        ],
        "range": revision_range,
        "checkout": "separate-fetch-depth-0",
        "clean": True,
        "trustedVerifierCommit": trusted_commit,
    }
    signature_document: dict[str, Any] = {
        "identityField": "gitCommit.committer.email",
        "approvedSignerEmail": signer,
        "verifierSource": "trusted-default-branch",
        "headCommit": head,
        "treeSha": tree,
        "verifierCommit": trusted_commit,
        "verifierScriptSha256": verifier_sha256,
        "mergeBase": merge_base,
        "range": revision_range,
        "commits": commit_results,
        "mechanism": "github-rest-commit-verification",
    }
    if tag_result is not None:
        signature_document["mechanism"] = (
            "github-rest-commit-and-annotated-tag-verification"
        )
        signature_document["tag"] = tag_result
    _write_outputs(output, source_document, signature_document)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--base-ref", required=True, choices=(BASE_REF,))
    parser.add_argument("--mode", required=True, choices=("commit", "signed-tag"))
    parser.add_argument("--tag-name")
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    arguments = _parser().parse_args(argv)
    if (arguments.mode == "commit" and arguments.tag_name is not None) or (
        arguments.mode == "signed-tag" and not _valid_tag(arguments.tag_name)
    ):
        _reject("INVALID_ARGUMENT")
    return arguments


def _failure_document(error: VerificationError) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "command": "source-verify",
        "result": "failed",
        "failureCode": error.code,
        "sourceCommit": error.source_commit,
        "artifactSha256": None,
    }


def _run(argv: Sequence[str], *, rest_get: RestGet = _github_rest_get) -> int:
    try:
        arguments = _arguments(argv)
        verify_source(
            candidate_root=arguments.candidate_root,
            base_ref=arguments.base_ref,
            mode=arguments.mode,
            tag_name=arguments.tag_name,
            output_dir=arguments.output_dir,
            rest_get=rest_get,
        )
    except VerificationError as error:
        sys.stderr.buffer.write(_canonical_json(_failure_document(error)))
        return 2 if error.code == "INVALID_ARGUMENT" else 1
    except VerifierInterrupted as interrupted:
        error = VerificationError("INTERNAL_ERROR")
        sys.stderr.buffer.write(_canonical_json(_failure_document(error)))
        return 128 + interrupted.signum
    except Exception:
        error = VerificationError("INTERNAL_ERROR")
        sys.stderr.buffer.write(_canonical_json(_failure_document(error)))
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return _run(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
