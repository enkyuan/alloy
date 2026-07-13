"""Bounded, repository-scoped GitHub REST client."""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
import json
import math
import re
import time
from typing import Any, Literal, Protocol, cast
from urllib.parse import quote, unquote

from kaji.infra.events.errors import DurableJsonLimitError, InvalidDurableValueError
from kaji.infra.events.json import canonical_json, durable_json_snapshot
from kaji.infra.events.schemas import MAX_DURABLE_TOOL_RESULT_BYTES
from kaji.integrations.errors import (
    IntegrationAuthRequiredError,
    IntegrationExecutionError,
    IntegrationPolicyError,
    IntegrationRateLimitedError,
    IntegrationTransientReadError,
)
from kaji.integrations.fixed_origin import IntegrationResponse
from kaji.runtime.agents.cancellation import CancelledError
from kaji.runtime.context import ToolExecutionContext
from kaji.runtime.tools.execution import ToolExecutionError


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_SCOPE_QUALIFIER = re.compile(r"(?:repo|org|user):", re.IGNORECASE)
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_SEARCH_RESULT_BYTES = 32 * 1024
_MAX_FILE_BYTES = 48 * 1024
_MAX_TOKEN_CHARACTERS = 4_096
_MAX_URL_CHARACTERS = 2_048
_GENERAL_ACCEPT = "application/vnd.github+json"
_SEARCH_ACCEPT = "application/vnd.github.text-match+json"

_Sleep = Callable[[float], Awaitable[None]]
_Monotonic = Callable[[], float]
_Route = Literal[
    "search_code",
    "get_file",
    "list_issues",
    "get_issue",
    "create_issue",
    "add_comment",
]


class _GitHubHttp(Protocol):
    async def request(
        self,
        path_and_query: str,
        *,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        context: ToolExecutionContext,
    ) -> IntegrationResponse: ...


class _ProviderShapeError(ValueError):
    pass


class _UnknownMutationError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("GitHub mutation outcome is unknown")


def _policy_error() -> IntegrationPolicyError:
    return IntegrationPolicyError()


def _auth_error() -> IntegrationAuthRequiredError:
    return IntegrationAuthRequiredError("github_token_missing")


def _api_error() -> IntegrationExecutionError:
    return IntegrationExecutionError("api_rejected")


def _transient_error() -> IntegrationTransientReadError:
    return IntegrationTransientReadError()


def _rate_error() -> IntegrationRateLimitedError:
    return IntegrationRateLimitedError()


def _require_repository(value: object, allowed: frozenset[str]) -> str:
    if (
        not isinstance(value, str)
        or not _REPOSITORY.fullmatch(value)
        or value not in allowed
    ):
        raise _policy_error()
    return value


def _policy_string(value: object, *, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise _policy_error()
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _policy_error() from None
    return value


def _policy_integer(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _policy_error()
    return value


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise _ProviderShapeError() from None


def _truncate_utf8(value: str, maximum: int) -> str:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise _ProviderShapeError() from None
    if len(encoded) <= maximum:
        return value
    return encoded[:maximum].decode("utf-8", errors="ignore")


def _object(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise _ProviderShapeError()
    return cast(dict[str, Any], value)


def _array(value: object) -> list[Any]:
    if type(value) is not list:
        raise _ProviderShapeError()
    return cast(list[Any], value)


def _provider_character_string(
    value: object,
    *,
    minimum: int = 0,
    maximum: int,
) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise _ProviderShapeError()
    _utf8_size(value)
    return value


def _provider_byte_string(
    value: object,
    *,
    minimum: int = 0,
    maximum: int,
) -> str:
    if not isinstance(value, str) or len(value) < minimum:
        raise _ProviderShapeError()
    if _utf8_size(value) > maximum:
        raise _ProviderShapeError()
    return value


def _provider_integer(
    value: object,
    *,
    minimum: int = 0,
    maximum: int = _MAX_SAFE_INTEGER,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _ProviderShapeError()
    return value


def _body(value: object, *, maximum: int) -> str:
    if value is None:
        return ""
    return _provider_byte_string(value, maximum=maximum)


def _state(value: object) -> str:
    if value not in {"open", "closed"}:
        raise _ProviderShapeError()
    return cast(str, value)


def _url(value: object) -> str:
    return _provider_character_string(value, minimum=1, maximum=_MAX_URL_CHARACTERS)


def _encode_component(value: str | int) -> str:
    try:
        return quote(str(value), safe="-._~", encoding="utf-8", errors="strict")
    except UnicodeError:
        raise _policy_error() from None


def _query_string(query: Mapping[str, str | int] | None) -> str:
    if query is None or not query:
        return ""
    if not isinstance(query, Mapping):
        raise _policy_error()
    pairs: list[str] = []
    for key in sorted(query):
        value = query[key]
        if not isinstance(key, str) or not key or type(value) not in {str, int}:
            raise _policy_error()
        pairs.append(f"{_encode_component(key)}={_encode_component(value)}")
    return "?" + "&".join(pairs)


def _encode_content_path(value: object) -> str:
    path = _policy_string(value, minimum=1, maximum=512)
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _policy_error()
    return "/".join(_encode_component(part) for part in parts)


def _validate_encoded_content_path(value: str) -> None:
    parts = value.split("/")
    decoded: list[str] = []
    try:
        for part in parts:
            plain = unquote(part, encoding="utf-8", errors="strict")
            if (
                not plain
                or plain in {".", ".."}
                or "/" in plain
                or "\\" in plain
                or _encode_component(plain) != part
            ):
                raise _policy_error()
            decoded.append(plain)
    except UnicodeError:
        raise _policy_error() from None
    _policy_string("/".join(decoded), minimum=1, maximum=512)


def _normalized_token(value: object) -> str:
    if not isinstance(value, str) or "\r" in value or "\n" in value:
        raise _auth_error()
    token = value.strip()
    if not token or len(token) > _MAX_TOKEN_CHARACTERS:
        raise _auth_error()
    try:
        token.encode("utf-8")
    except UnicodeEncodeError:
        raise _auth_error() from None
    return token


def _retry_after(headers: Mapping[str, str]) -> float | None:
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        delay = float(raw)
    except ValueError:
        return None
    if not math.isfinite(delay) or not 0 <= delay <= 2:
        return None
    return delay


def _is_rate_limited(response: IntegrationResponse) -> bool:
    return response.status == 429 or (
        response.status == 403
        and (
            _retry_after(response.headers) is not None
            or response.headers.get("x-ratelimit-remaining") == "0"
        )
    )


def _route_for(
    *,
    method: Literal["GET", "POST"],
    repository: str,
    path: str,
    query: Mapping[str, str | int] | None,
    body: Mapping[str, object] | None,
    mutation: bool,
) -> _Route:
    prefix = f"/repos/{repository}"
    query_keys = set(query or {})
    body_keys = set(body or {})
    if method == "GET" and not mutation and path == "/search/code":
        if query is None or query_keys != {"q", "page", "per_page"} or body is not None:
            raise _policy_error()
        q = query["q"]
        suffix = f" repo:{repository}"
        if not isinstance(q, str) or not q.endswith(suffix):
            raise _policy_error()
        user_query = q[: -len(suffix)]
        _validate_search_input(user_query, query["page"], query["per_page"])
        return "search_code"
    if method == "GET" and not mutation and path.startswith(prefix + "/contents/"):
        if body is not None or not query_keys <= {"ref"}:
            raise _policy_error()
        _validate_encoded_content_path(path.removeprefix(prefix + "/contents/"))
        if query and "ref" in query:
            _policy_string(query["ref"], minimum=1, maximum=100)
        return "get_file"
    if path == prefix + "/issues":
        if method == "GET" and not mutation:
            if (
                query is None
                or query_keys != {"state", "page", "per_page"}
                or body is not None
            ):
                raise _policy_error()
            _validate_list_input(query["state"], query["page"], query["per_page"])
            return "list_issues"
        if method == "POST" and mutation:
            if query is not None or body is None or body_keys != {"title", "body"}:
                raise _policy_error()
            _validate_create_input(body["title"], body["body"])
            return "create_issue"
    issue_path = re.fullmatch(re.escape(prefix) + r"/issues/([1-9][0-9]*)", path)
    if (
        issue_path
        and method == "GET"
        and not mutation
        and query is None
        and body is None
    ):
        _policy_integer(int(issue_path.group(1)), minimum=1, maximum=_MAX_SAFE_INTEGER)
        return "get_issue"
    comment_path = re.fullmatch(
        re.escape(prefix) + r"/issues/([1-9][0-9]*)/comments", path
    )
    if comment_path and method == "POST" and mutation and query is None:
        if body is None or body_keys != {"body"}:
            raise _policy_error()
        _policy_integer(
            int(comment_path.group(1)), minimum=1, maximum=_MAX_SAFE_INTEGER
        )
        _validate_comment_body(body["body"])
        return "add_comment"
    raise _policy_error()


def _validate_search_input(query: object, page: object, per_page: object) -> str:
    value = _policy_string(query, minimum=1, maximum=256)
    if _SCOPE_QUALIFIER.search(value):
        raise _policy_error()
    _policy_integer(page, minimum=1, maximum=50)
    _policy_integer(per_page, minimum=1, maximum=20)
    return value


def _validate_list_input(state: object, page: object, per_page: object) -> None:
    if state not in {"open", "closed", "all"}:
        raise _policy_error()
    _policy_integer(page, minimum=1, maximum=1_000)
    _policy_integer(per_page, minimum=1, maximum=20)


def _validate_create_input(title: object, body: object) -> None:
    _policy_string(title, minimum=1, maximum=256)
    value = _policy_string(body, minimum=0, maximum=16_384)
    if len(value.encode("utf-8")) > 16_384:
        raise _policy_error()


def _validate_comment_body(body: object) -> None:
    value = _policy_string(body, minimum=1, maximum=16_384)
    if len(value.encode("utf-8")) > 16_384:
        raise _policy_error()


class GitHubClient:
    def __init__(
        self,
        *,
        token_for: Callable[[ToolExecutionContext], Awaitable[str]],
        repositories: Collection[str],
        http: _GitHubHttp,
        _sleep: _Sleep = asyncio.sleep,
        _monotonic: _Monotonic = time.monotonic,
    ) -> None:
        if not callable(token_for) or not callable(_sleep) or not callable(_monotonic):
            raise _policy_error()
        try:
            snapshot = tuple(repositories)
        except TypeError:
            raise _policy_error() from None
        if any(
            not isinstance(item, str) or not _REPOSITORY.fullmatch(item)
            for item in snapshot
        ):
            raise _policy_error()
        self._repositories = frozenset(snapshot)
        self._token_for = token_for
        self._http = http
        self._sleep = _sleep
        self._monotonic = _monotonic

    async def search_code(
        self,
        context: ToolExecutionContext,
        *,
        repository: str,
        query: str,
        page: int = 1,
        per_page: int = 10,
    ) -> Mapping[str, object]:
        repository = _require_repository(repository, self._repositories)
        query = _validate_search_input(query, page, per_page)
        return cast(
            Mapping[str, object],
            await self.request_json(
                context,
                method="GET",
                repository=repository,
                path="/search/code",
                query={
                    "q": f"{query} repo:{repository}",
                    "page": page,
                    "per_page": per_page,
                },
            ),
        )

    async def get_file(
        self,
        context: ToolExecutionContext,
        *,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> Mapping[str, object]:
        repository = _require_repository(repository, self._repositories)
        encoded_path = _encode_content_path(path)
        query = (
            None
            if ref is None
            else {"ref": _policy_string(ref, minimum=1, maximum=100)}
        )
        return cast(
            Mapping[str, object],
            await self.request_json(
                context,
                method="GET",
                repository=repository,
                path=f"/repos/{repository}/contents/{encoded_path}",
                query=query,
            ),
        )

    async def list_issues(
        self,
        context: ToolExecutionContext,
        *,
        repository: str,
        state: str = "open",
        page: int = 1,
        per_page: int = 10,
    ) -> Mapping[str, object]:
        repository = _require_repository(repository, self._repositories)
        _validate_list_input(state, page, per_page)
        return cast(
            Mapping[str, object],
            await self.request_json(
                context,
                method="GET",
                repository=repository,
                path=f"/repos/{repository}/issues",
                query={"state": state, "page": page, "per_page": per_page},
            ),
        )

    async def get_issue(
        self,
        context: ToolExecutionContext,
        *,
        repository: str,
        issue_number: int,
    ) -> Mapping[str, object]:
        repository = _require_repository(repository, self._repositories)
        number = _policy_integer(issue_number, minimum=1, maximum=_MAX_SAFE_INTEGER)
        return cast(
            Mapping[str, object],
            await self.request_json(
                context,
                method="GET",
                repository=repository,
                path=f"/repos/{repository}/issues/{number}",
            ),
        )

    async def create_issue(
        self,
        context: ToolExecutionContext,
        *,
        repository: str,
        title: str,
        body: str,
    ) -> Mapping[str, object]:
        repository = _require_repository(repository, self._repositories)
        _validate_create_input(title, body)
        return cast(
            Mapping[str, object],
            await self.request_json(
                context,
                method="POST",
                repository=repository,
                path=f"/repos/{repository}/issues",
                body={"title": title, "body": body},
                mutation=True,
            ),
        )

    async def add_comment(
        self,
        context: ToolExecutionContext,
        *,
        repository: str,
        issue_number: int,
        body: str,
    ) -> Mapping[str, object]:
        repository = _require_repository(repository, self._repositories)
        number = _policy_integer(issue_number, minimum=1, maximum=_MAX_SAFE_INTEGER)
        _validate_comment_body(body)
        return cast(
            Mapping[str, object],
            await self.request_json(
                context,
                method="POST",
                repository=repository,
                path=f"/repos/{repository}/issues/{number}/comments",
                body={"body": body},
                mutation=True,
            ),
        )

    async def request_json(
        self,
        context: ToolExecutionContext,
        *,
        method: Literal["GET", "POST"],
        repository: str,
        path: str,
        query: Mapping[str, str | int] | None = None,
        body: Mapping[str, object] | None = None,
        mutation: bool = False,
    ) -> Mapping[str, object] | Sequence[object]:
        repository = _require_repository(repository, self._repositories)
        route = _route_for(
            method=method,
            repository=repository,
            path=path,
            query=query,
            body=body,
            mutation=mutation,
        )
        path_and_query = path + _query_string(query)
        request_body = (
            None
            if body is None
            else canonical_json(body, subject="integration request body").encode()
        )
        headers = {
            "accept": _SEARCH_ACCEPT if route == "search_code" else _GENERAL_ACCEPT,
        }

        context.cancellation_token.raise_if_cancelled()
        try:
            token = await self._token_for(context)
        except asyncio.CancelledError:
            raise
        except ToolExecutionError:
            raise
        except Exception:
            raise _auth_error() from None
        context.cancellation_token.raise_if_cancelled()
        headers["authorization"] = f"Bearer {_normalized_token(token)}"
        if request_body is not None:
            headers["content-type"] = "application/json"

        response: IntegrationResponse
        for attempt in range(2):
            try:
                response = await self._http.request(
                    path_and_query,
                    method=method,
                    headers=headers,
                    body=request_body,
                    context=context,
                )
            except (asyncio.CancelledError, TimeoutError):
                raise
            except ToolExecutionError:
                raise
            except Exception:
                if mutation:
                    raise _UnknownMutationError() from None
                raise _transient_error() from None

            if _is_rate_limited(response):
                delay = _retry_after(response.headers)
                if (
                    method == "GET"
                    and attempt == 0
                    and delay is not None
                    and self._deadline_allows(context, delay)
                ):
                    await self._sleep_before_retry(context, delay)
                    continue
                raise _rate_error()
            break
        else:  # pragma: no cover - bounded loop always breaks or raises
            raise _rate_error()

        if response.status == 401:
            raise _auth_error()
        if response.status == 403:
            raise _api_error()
        if not 200 <= response.status < 300:
            if mutation and response.status >= 500:
                raise _UnknownMutationError()
            if response.status in {404, 422} or 400 <= response.status < 500:
                raise _api_error()
            if mutation:
                raise _UnknownMutationError()
            raise _transient_error()

        try:
            decoded = response.body.decode("utf-8", errors="strict")
            document = json.loads(
                decoded,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
            normalized = self._normalize(route, repository, document)
            return cast(
                Mapping[str, object] | Sequence[object],
                durable_json_snapshot(
                    normalized,
                    subject="tool_result",
                    max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
                ),
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
            _ProviderShapeError,
            InvalidDurableValueError,
            DurableJsonLimitError,
        ):
            if mutation:
                raise _UnknownMutationError() from None
            raise _transient_error() from None

    def _deadline_allows(self, context: ToolExecutionContext, delay: float) -> bool:
        return (
            context.deadline_monotonic is None
            or context.deadline_monotonic - self._monotonic() > delay
        )

    async def _sleep_before_retry(
        self, context: ToolExecutionContext, delay: float
    ) -> None:
        context.cancellation_token.raise_if_cancelled()

        async def sleep() -> None:
            await self._sleep(delay)

        sleeping = asyncio.create_task(sleep())
        cancelled = asyncio.create_task(context.cancellation_token.wait())
        try:
            done, _ = await asyncio.wait(
                {sleeping, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancelled in done or context.cancellation_token.is_cancelled:
                sleeping.cancel()
                raise CancelledError("Integration request cancelled")
            await sleeping
        finally:
            for task in (sleeping, cancelled):
                if not task.done():
                    task.cancel()
            await asyncio.gather(sleeping, cancelled, return_exceptions=True)

    def _normalize(self, route: _Route, repository: str, document: object) -> object:
        if route == "search_code":
            return self._normalize_search(repository, document)
        if route == "get_file":
            return self._normalize_file(document)
        if route == "list_issues":
            return self._normalize_issue_list(document)
        if route in {"get_issue", "create_issue"}:
            return self._normalize_issue(document)
        return self._normalize_comment(document)

    def _normalize_search(self, repository: str, document: object) -> object:
        root = _object(document)
        total_count = _provider_integer(root.get("total_count"))
        items = _array(root.get("items"))
        for value in items:
            item = _object(value)
            found_repository = _object(item.get("repository"))
            if found_repository.get("full_name") != repository:
                raise _ProviderShapeError()
        normalized_items: list[dict[str, object]] = []
        for value in items[:20]:
            item = _object(value)
            matches = item.get("text_matches", [])
            fragment = ""
            if matches is not None:
                rows = _array(matches)
                if rows:
                    fragment = _provider_byte_string(
                        _object(rows[0]).get("fragment"), maximum=1_048_576
                    )
            normalized_items.append(
                {
                    "path": _provider_character_string(
                        item.get("path"), minimum=1, maximum=512
                    ),
                    "sha": _provider_character_string(
                        item.get("sha"), minimum=1, maximum=64
                    ),
                    "fragment": _truncate_utf8(fragment, 1_024),
                }
            )
        result = {"total_count": total_count, "items": normalized_items}
        try:
            return durable_json_snapshot(
                result, subject="tool_result", max_bytes=_MAX_SEARCH_RESULT_BYTES
            )
        except (InvalidDurableValueError, DurableJsonLimitError):
            raise _ProviderShapeError() from None

    def _normalize_file(self, document: object) -> object:
        root = _object(document)
        if root.get("type") != "file" or root.get("encoding") != "base64":
            raise _ProviderShapeError()
        path = _provider_character_string(root.get("path"), minimum=1, maximum=512)
        sha = _provider_character_string(root.get("sha"), minimum=1, maximum=64)
        size = _provider_integer(root.get("size"))
        content = _provider_character_string(root.get("content"), maximum=1_048_576)
        if size > _MAX_FILE_BYTES:
            return {
                "path": path,
                "sha": sha,
                "size": size,
                "content_omitted": True,
            }
        normalized = content.replace("\r", "").replace("\n", "")
        try:
            decoded = base64.b64decode(normalized, validate=True)
        except (binascii.Error, ValueError):
            raise _ProviderShapeError() from None
        if base64.b64encode(decoded).decode() != normalized or len(decoded) != size:
            raise _ProviderShapeError()
        if len(decoded) > _MAX_FILE_BYTES:
            return {
                "path": path,
                "sha": sha,
                "size": size,
                "content_omitted": True,
            }
        try:
            text = decoded.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise _ProviderShapeError() from None
        return {
            "path": path,
            "sha": sha,
            "size": size,
            "content": text,
            "content_omitted": False,
        }

    def _normalize_issue_list(self, document: object) -> object:
        items: list[dict[str, object]] = []
        for value in _array(document)[:20]:
            issue = _object(value)
            body = (
                ""
                if issue.get("body") is None
                else _provider_byte_string(issue.get("body"), maximum=1_048_576)
            )
            items.append(
                {
                    "number": _provider_integer(issue.get("number"), minimum=1),
                    "state": _state(issue.get("state")),
                    "title": _provider_character_string(
                        issue.get("title"), minimum=1, maximum=256
                    ),
                    "body_preview": _truncate_utf8(body, 1_024),
                }
            )
        return {"items": items}

    def _normalize_issue(self, document: object) -> object:
        issue = _object(document)
        return {
            "number": _provider_integer(issue.get("number"), minimum=1),
            "state": _state(issue.get("state")),
            "title": _provider_character_string(
                issue.get("title"), minimum=1, maximum=256
            ),
            "body": _body(issue.get("body"), maximum=16_384),
            "url": _url(issue.get("html_url")),
        }

    def _normalize_comment(self, document: object) -> object:
        comment = _object(document)
        return {
            "id": _provider_integer(comment.get("id"), minimum=1),
            "url": _url(comment.get("html_url")),
        }
