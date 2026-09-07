#!/usr/bin/env python3
"""Private fixed-route GitHub proof control and owner-only JSON IO."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Iterator, NoReturn

import httpx


API_ORIGIN = "https://api.github.com"
API_VERSION = "2026-03-10"
USER_AGENT = "kaji-github-proof/1.0"
MAX_PRIVATE_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_RESPONSE_HEADER_FIELDS = 64
MAX_RESPONSE_HEADER_BYTES = 64 * 1024
MAX_TOKEN_CHARACTERS = 4_096
REQUEST_TIMEOUT_SECONDS = 10.0
COMPONENT = re.compile(r"[A-Za-z0-9_.-]{1,100}")
MAX_SAFE_INTEGER = 9_007_199_254_740_991
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
MARKER_PATTERN = re.compile(r"kaji-proof/[0-9a-f]{40}/(python|typescript)/[0-9a-f]{32}")
RUNTIMES = ("python", "typescript")
CELL_PHASES = {
    "planned",
    "dispatched",
    "identified",
    "cleanup_required",
    "cleaned",
    "failed",
}
FAILURE_ORIGINS = {
    "prerequisite",
    "preflight",
    "child",
    "receipt",
    "control",
    "cleanup",
    "interrupted",
}
STATE_KEYS = {
    "schemaVersion",
    "commit",
    "releaseManifestSha256",
    "owner",
    "repository",
    "issueNumber",
    "cells",
}
CELL_KEYS = {
    "runtime",
    "marker",
    "phase",
    "dispatchAttempted",
    "reconciliationRequired",
    "commentId",
    "failureOrigin",
    "readPassed",
    "approvedCommentPassed",
    "controlReadbackPassed",
    "absenceObserved",
}


class GitHubProofError(RuntimeError):
    """A static, redaction-safe proof failure."""


def _fail(code: str) -> NoReturn:
    raise GitHubProofError(code)


def validate_proof_token(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_TOKEN_CHARACTERS
        or "\r" in value
        or "\n" in value
        or "\0" in value
    ):
        _fail("control_token_invalid")
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        _fail("control_token_invalid")
    return value


class _DuplicateKeyError(ValueError):
    pass


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> NoReturn:
    raise ValueError


def decode_json_object(encoded: bytes, *, code: str) -> dict[str, Any]:
    try:
        document = json.loads(
            encoded,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        _fail(code)
    if type(document) is not dict:
        _fail(code)
    return document


def _private_boundary_index(path: Path) -> int:
    parts = path.parts
    candidates = [
        index
        for index, part in enumerate(parts[:-1])
        if part == ".artifacts"
        and index + 1 < len(parts)
        and parts[index + 1] == "private"
    ]
    if not candidates:
        _fail("private_input_invalid")
    return candidates[-1] + 1


def normalize_private_path(path: Path) -> Path:
    try:
        normalized = Path(os.path.abspath(os.path.normpath(os.fspath(path))))
    except (OSError, TypeError, ValueError):
        _fail("private_input_invalid")
    boundary_index = _private_boundary_index(normalized)
    if boundary_index >= len(normalized.parts) - 1:
        _fail("private_input_invalid")
    boundary = Path(*normalized.parts[: boundary_index + 1])
    if not normalized.is_relative_to(boundary):
        _fail("private_input_invalid")
    return normalized


def _validate_private_directory(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        _fail("private_input_invalid")


def _validate_private_file(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_size > MAX_PRIVATE_BYTES
    ):
        _fail("private_input_invalid")


def _directory_flags() -> int:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        _fail("private_input_invalid")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@contextmanager
def _private_parent(path: Path) -> Iterator[tuple[Path, int]]:
    normalized = normalize_private_path(path)
    boundary_index = _private_boundary_index(normalized)
    descriptor: int | None = None
    try:
        descriptor = os.open(normalized.anchor, _directory_flags())
        for index, component in enumerate(normalized.parts[1:-1], start=1):
            child = os.open(
                component,
                _directory_flags(),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
            if index >= boundary_index:
                _validate_private_directory(os.fstat(descriptor))
        yield normalized, descriptor
    except GitHubProofError:
        raise
    except OSError:
        _fail("private_input_invalid")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _file_snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_private_bytes(path: Path) -> bytes:
    with _private_parent(path) as (normalized, parent):
        descriptor: int | None = None
        try:
            descriptor = os.open(
                normalized.name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=parent,
            )
            before = os.fstat(descriptor)
            _validate_private_file(before)
            chunks = bytearray()
            while len(chunks) <= MAX_PRIVATE_BYTES:
                chunk = os.read(
                    descriptor,
                    min(8_192, MAX_PRIVATE_BYTES + 1 - len(chunks)),
                )
                if not chunk:
                    break
                chunks.extend(chunk)
            after = os.fstat(descriptor)
            if (
                len(chunks) > MAX_PRIVATE_BYTES
                or _file_snapshot(before) != _file_snapshot(after)
                or len(chunks) != after.st_size
            ):
                _fail("private_input_invalid")
            return bytes(chunks)
        except GitHubProofError:
            raise
        except OSError:
            _fail("private_input_invalid")
        finally:
            if descriptor is not None:
                os.close(descriptor)


def read_private_json(path: Path) -> dict[str, Any]:
    return decode_json_object(
        _read_private_bytes(path),
        code="private_input_invalid",
    )


def _encoded_json(document: Mapping[str, Any], *, code: str) -> bytes:
    try:
        encoded = (
            json.dumps(
                document,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode()
    except (TypeError, ValueError, UnicodeError):
        _fail(code)
    if len(encoded) > MAX_PRIVATE_BYTES:
        _fail(code)
    return encoded


def write_private_json(path: Path, document: Mapping[str, Any]) -> None:
    encoded = _encoded_json(document, code="private_output_invalid")
    with _private_parent(path) as (normalized, parent):
        temporary = f".{normalized.name}.{secrets.token_hex(12)}.tmp"
        descriptor: int | None = None
        created = False
        try:
            try:
                existing = os.stat(
                    normalized.name,
                    dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                existing = None
            if existing is not None:
                _validate_private_file(existing)
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            created = True
            os.fchmod(descriptor, 0o600)
            offset = 0
            while offset < len(encoded):
                offset += os.write(descriptor, encoded[offset:])
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            _validate_private_file(metadata)
            if metadata.st_size != len(encoded):
                _fail("private_output_invalid")
            os.close(descriptor)
            descriptor = None
            os.replace(
                temporary,
                normalized.name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
            )
            created = False
            os.fsync(parent)
        except GitHubProofError:
            raise
        except OSError:
            _fail("private_output_invalid")
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if created:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
                except OSError:
                    _fail("private_output_invalid")


def remove_private_file(path: Path) -> None:
    with _private_parent(path) as (normalized, parent):
        descriptor: int | None = None
        try:
            descriptor = os.open(
                normalized.name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=parent,
            )
            _validate_private_file(os.fstat(descriptor))
            os.close(descriptor)
            descriptor = None
            os.unlink(normalized.name, dir_fd=parent)
            os.fsync(parent)
        except GitHubProofError:
            raise
        except OSError:
            _fail("private_output_invalid")
        finally:
            if descriptor is not None:
                os.close(descriptor)


def state_lock_path(state_path: Path) -> Path:
    normalized = normalize_private_path(state_path)
    return normalized.with_name(f".{normalized.name}.lock")


@contextmanager
def private_state_lock(state_path: Path) -> Iterator[None]:
    lock_path = state_lock_path(state_path)
    with _private_parent(lock_path) as (normalized, parent):
        descriptor: int | None = None
        locked = False
        try:
            descriptor = os.open(
                normalized.name,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            os.fchmod(descriptor, 0o600)
            _validate_private_file(os.fstat(descriptor))
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                _fail("state_lock_busy")
            locked = True
            yield
        except GitHubProofError:
            raise
        except OSError:
            _fail("state_lock_invalid")
        finally:
            if descriptor is not None:
                if locked:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    except OSError:
                        pass
                os.close(descriptor)


def _repository_fixture(
    owner: Any, repository: Any, issue_number: Any
) -> tuple[str, str, int]:
    checked_owner = _component(owner)
    checked_repository = _component(repository)
    checked_issue = _identifier(issue_number)
    return checked_owner, checked_repository, checked_issue


def validate_private_fixture(document: Mapping[str, Any]) -> dict[str, Any]:
    if type(document) is not dict or set(document) != {
        "owner",
        "repository",
        "issueNumber",
    }:
        _fail("fixture_invalid")
    owner, repository, issue_number = _repository_fixture(
        document.get("owner"),
        document.get("repository"),
        document.get("issueNumber"),
    )
    return {
        "owner": owner,
        "repository": repository,
        "issueNumber": issue_number,
    }


def _empty_cell(runtime: str, marker: str) -> dict[str, Any]:
    return {
        "runtime": runtime,
        "marker": marker,
        "phase": "planned",
        "dispatchAttempted": False,
        "reconciliationRequired": False,
        "commentId": None,
        "failureOrigin": None,
        "readPassed": False,
        "approvedCommentPassed": False,
        "controlReadbackPassed": False,
        "absenceObserved": False,
    }


def new_proof_state(
    *,
    commit: str,
    release_manifest_sha256: str,
    owner: str,
    repository: str,
    issue_number: int,
    markers: Mapping[str, str],
) -> dict[str, Any]:
    if (
        not isinstance(commit, str)
        or COMMIT_PATTERN.fullmatch(commit) is None
        or not isinstance(release_manifest_sha256, str)
        or SHA256_PATTERN.fullmatch(release_manifest_sha256) is None
        or set(markers) != set(RUNTIMES)
    ):
        _fail("state_binding_invalid")
    checked_owner, checked_repository, checked_issue = _repository_fixture(
        owner, repository, issue_number
    )
    cells: list[dict[str, Any]] = []
    for runtime in RUNTIMES:
        marker = markers[runtime]
        if (
            not isinstance(marker, str)
            or MARKER_PATTERN.fullmatch(marker) is None
            or f"/{runtime}/" not in marker
            or not marker.startswith(f"kaji-proof/{commit}/")
        ):
            _fail("state_invalid")
        cells.append(_empty_cell(runtime, marker))
    if cells[0]["marker"] == cells[1]["marker"]:
        _fail("state_invalid")
    return {
        "schemaVersion": "1.0.0",
        "commit": commit,
        "releaseManifestSha256": release_manifest_sha256,
        "owner": checked_owner,
        "repository": checked_repository,
        "issueNumber": checked_issue,
        "cells": cells,
    }


def _validate_cell(value: Any, runtime: str, commit: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != CELL_KEYS:
        _fail("state_invalid")
    if value.get("runtime") != runtime:
        _fail("state_invalid")
    marker = value.get("marker")
    phase = value.get("phase")
    dispatch = value.get("dispatchAttempted")
    reconciliation = value.get("reconciliationRequired")
    comment_id = value.get("commentId")
    failure_origin = value.get("failureOrigin")
    absence_observed = value.get("absenceObserved")
    booleans = (
        value.get("readPassed"),
        value.get("approvedCommentPassed"),
        value.get("controlReadbackPassed"),
    )
    if (
        not isinstance(marker, str)
        or MARKER_PATTERN.fullmatch(marker) is None
        or not marker.startswith(f"kaji-proof/{commit}/{runtime}/")
        or phase not in CELL_PHASES
        or type(dispatch) is not bool
        or type(reconciliation) is not bool
        or type(absence_observed) is not bool
        or any(type(item) is not bool for item in booleans)
        or (
            comment_id is not None
            and (type(comment_id) is not int or not 1 <= comment_id <= MAX_SAFE_INTEGER)
        )
        or (failure_origin is not None and failure_origin not in FAILURE_ORIGINS)
    ):
        _fail("state_invalid")
    if not dispatch and (reconciliation or comment_id is not None or absence_observed):
        _fail("state_invalid")
    if comment_id is not None and not dispatch:
        _fail("state_invalid")
    if phase == "planned" and (
        dispatch
        or reconciliation
        or comment_id is not None
        or failure_origin is not None
        or absence_observed
    ):
        _fail("state_invalid")
    if phase == "dispatched" and (
        not dispatch
        or not reconciliation
        or comment_id is not None
        or failure_origin is not None
        or absence_observed
    ):
        _fail("state_invalid")
    if phase in {"identified", "cleanup_required"} and (
        not dispatch
        or not reconciliation
        or comment_id is None
        or failure_origin is not None
        or absence_observed
    ):
        _fail("state_invalid")
    if phase == "cleaned" and (
        not dispatch
        or reconciliation
        or comment_id is None
        or failure_origin is not None
        or booleans != (True, True, True)
        or absence_observed
    ):
        _fail("state_invalid")
    if phase == "failed" and (
        failure_origin is None or (absence_observed and not dispatch)
    ):
        _fail("state_invalid")
    return dict(value)


def validate_proof_state(
    document: Mapping[str, Any],
    *,
    expected_commit: str,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    if (
        type(document) is not dict
        or set(document) != STATE_KEYS
        or document.get("schemaVersion") != "1.0.0"
        or COMMIT_PATTERN.fullmatch(expected_commit) is None
        or document.get("commit") != expected_commit
        or not isinstance(document.get("releaseManifestSha256"), str)
        or SHA256_PATTERN.fullmatch(document["releaseManifestSha256"]) is None
        or (
            expected_manifest_sha256 is not None
            and document["releaseManifestSha256"] != expected_manifest_sha256
        )
    ):
        _fail("state_binding_invalid")
    owner, repository, issue_number = _repository_fixture(
        document.get("owner"),
        document.get("repository"),
        document.get("issueNumber"),
    )
    cells = document.get("cells")
    if type(cells) is not list or len(cells) != 2:
        _fail("state_invalid")
    checked_cells = [
        _validate_cell(cell, runtime, expected_commit)
        for cell, runtime in zip(cells, RUNTIMES, strict=True)
    ]
    if checked_cells[0]["marker"] == checked_cells[1]["marker"]:
        _fail("state_invalid")
    return {
        "schemaVersion": "1.0.0",
        "commit": expected_commit,
        "releaseManifestSha256": document["releaseManifestSha256"],
        "owner": owner,
        "repository": repository,
        "issueNumber": issue_number,
        "cells": checked_cells,
    }


def update_proof_cell(
    state: dict[str, Any], runtime: str, **changes: Any
) -> dict[str, Any]:
    if runtime not in RUNTIMES or not set(changes).issubset(CELL_KEYS - {"runtime"}):
        _fail("state_invalid")
    cells = state.get("cells")
    if type(cells) is not list:
        _fail("state_invalid")
    for cell in cells:
        if type(cell) is dict and cell.get("runtime") == runtime:
            cell.update(changes)
            return cell
    _fail("state_invalid")


def _component(value: str) -> str:
    if (
        not isinstance(value, str)
        or COMPONENT.fullmatch(value) is None
        or value in {".", ".."}
    ):
        _fail("control_route_invalid")
    return value


def _identifier(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        _fail("control_route_invalid")
    return value


def canonical_issue_url(owner: str, repository: str, issue_number: int) -> str:
    return (
        f"{API_ORIGIN}/repos/{_component(owner)}/{_component(repository)}"
        f"/issues/{_identifier(issue_number)}"
    )


class GitHubProofControl:
    """The three fixed GitHub routes needed to reconcile proof comments."""

    def __init__(
        self,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        checked_token = validate_proof_token(token)
        self._headers = {
            "accept": "application/vnd.github+json",
            "authorization": f"Bearer {checked_token}",
            "user-agent": USER_AGENT,
            "x-github-api-version": API_VERSION,
        }
        self._client = httpx.AsyncClient(
            base_url=API_ORIGIN,
            transport=transport,
            follow_redirects=False,
            timeout=None,
            trust_env=False,
        )

    async def __aenter__(self) -> GitHubProofControl:
        return self

    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: object,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _comment_path(owner: str, repository: str, comment_id: int) -> str:
        return (
            f"/repos/{_component(owner)}/{_component(repository)}"
            f"/issues/comments/{_identifier(comment_id)}"
        )

    @staticmethod
    def _comments_path(owner: str, repository: str, issue_number: int) -> str:
        return (
            f"/repos/{_component(owner)}/{_component(repository)}"
            f"/issues/{_identifier(issue_number)}/comments?per_page=100&page=1"
        )

    @staticmethod
    def _bounded_headers(headers: httpx.Headers) -> None:
        fields = headers.multi_items()
        if len(fields) > MAX_RESPONSE_HEADER_FIELDS:
            _fail("control_response_limit")
        try:
            size = sum(
                len(name.encode("utf-8")) + len(value.encode("utf-8"))
                for name, value in fields
            )
        except UnicodeError:
            _fail("control_response_limit")
        if size > MAX_RESPONSE_HEADER_BYTES:
            _fail("control_response_limit")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        allow_missing: bool,
    ) -> tuple[int, Mapping[str, str], bytes]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._client.stream(
                    method, path, headers=self._headers
                ) as response:
                    self._bounded_headers(response.headers)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            _fail("control_response_limit")
                    status = response.status_code
                    if allow_missing and status == 404:
                        return status, response.headers, bytes(body)
                    if 300 <= status < 400:
                        _fail("control_redirect")
                    if status == 403:
                        _fail("control_forbidden")
                    if status == 429:
                        _fail("control_rate_limited")
                    expected = 200 if method == "GET" else 204
                    if status != expected:
                        _fail("control_rejected")
                    return status, response.headers, bytes(body)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            _fail("control_timeout")
        except GitHubProofError:
            raise
        except (httpx.HTTPError, OSError):
            _fail("control_unavailable")

    @staticmethod
    def _comment(document: Any) -> dict[str, Any]:
        if type(document) is not dict:
            _fail("control_response_invalid")
        comment_id = document.get("id")
        body = document.get("body")
        issue_url = document.get("issue_url")
        if (
            type(comment_id) is not int
            or not 1 <= comment_id <= MAX_SAFE_INTEGER
            or not isinstance(body, str)
            or not isinstance(issue_url, str)
            or re.fullmatch(
                (
                    rf"{re.escape(API_ORIGIN)}/repos/"
                    r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}"
                    r"/issues/[1-9][0-9]*"
                ),
                issue_url,
            )
            is None
        ):
            _fail("control_response_invalid")
        try:
            body.encode("utf-8")
        except UnicodeError:
            _fail("control_response_invalid")
        return {"id": comment_id, "body": body, "issueUrl": issue_url}

    @staticmethod
    def _json(encoded: bytes) -> Any:
        try:
            return json.loads(
                encoded,
                object_pairs_hook=_object_without_duplicates,
                parse_constant=_reject_nonfinite,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError):
            _fail("control_response_invalid")

    async def get_comment(
        self, owner: str, repository: str, comment_id: int
    ) -> dict[str, Any] | None:
        status, _headers, body = await self._request(
            "GET",
            self._comment_path(owner, repository, comment_id),
            allow_missing=True,
        )
        return None if status == 404 else self._comment(self._json(body))

    async def list_issue_comments(
        self, owner: str, repository: str, issue_number: int
    ) -> list[dict[str, Any]]:
        _status, headers, body = await self._request(
            "GET",
            self._comments_path(owner, repository, issue_number),
            allow_missing=False,
        )
        link = headers.get("link", "")
        document = self._json(body)
        if 'rel="next"' in link or type(document) is not list or len(document) >= 100:
            _fail("control_list_ambiguous")
        return [self._comment(item) for item in document]

    async def delete_comment(
        self, owner: str, repository: str, comment_id: int
    ) -> None:
        await self._request(
            "DELETE",
            self._comment_path(owner, repository, comment_id),
            allow_missing=False,
        )
