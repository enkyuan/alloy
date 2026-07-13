"""GitHub tools backed by the provider-fixed bounded REST client."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Mapping
from typing import Any, Protocol, cast

from kaji.integrations.fixed_origin import FixedOriginClient
from kaji.integrations.registry.github.client import GitHubClient
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    NOOP_TRACE,
    TraceSink,
)
from kaji.runtime.context import ToolExecutionContext
from kaji.runtime.integrations.base import Integration
from kaji.runtime.tools.registry import ToolHandler, ToolSpec


class _GitHubClientLike(Protocol):
    async def add_comment(
        self, context: ToolExecutionContext, **values: Any
    ) -> Mapping[str, object]: ...
    async def create_issue(
        self, context: ToolExecutionContext, **values: Any
    ) -> Mapping[str, object]: ...
    async def get_file(
        self, context: ToolExecutionContext, **values: Any
    ) -> Mapping[str, object]: ...
    async def get_issue(
        self, context: ToolExecutionContext, **values: Any
    ) -> Mapping[str, object]: ...
    async def list_issues(
        self, context: ToolExecutionContext, **values: Any
    ) -> Mapping[str, object]: ...
    async def search_code(
        self, context: ToolExecutionContext, **values: Any
    ) -> Mapping[str, object]: ...


_REPOSITORY = {
    "type": "string",
    "pattern": "^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$",
}
_ISSUE_NUMBER = {"type": "integer", "minimum": 1, "maximum": 9_007_199_254_740_991}


def _parameters(
    properties: dict[str, object], required: list[str]
) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _specs() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(
            name="add_comment",
            description="Add a comment to a GitHub issue.",
            parameters=_parameters(
                {
                    "repository": _REPOSITORY,
                    "issue_number": _ISSUE_NUMBER,
                    "body": {"type": "string", "minLength": 1, "maxLength": 16_384},
                },
                ["repository", "issue_number", "body"],
            ),
            risk="external_effect",
            parallel_safe=False,
            timeout_ms=15_000,
        ),
        ToolSpec(
            name="create_issue",
            description="Create a GitHub issue.",
            parameters=_parameters(
                {
                    "repository": _REPOSITORY,
                    "title": {"type": "string", "minLength": 1, "maxLength": 256},
                    "body": {"type": "string", "minLength": 0, "maxLength": 16_384},
                },
                ["repository", "title", "body"],
            ),
            risk="external_effect",
            parallel_safe=False,
            timeout_ms=15_000,
        ),
        ToolSpec(
            name="get_file",
            description="Get a file from a GitHub repository.",
            parameters=_parameters(
                {
                    "repository": _REPOSITORY,
                    "path": {"type": "string", "minLength": 1, "maxLength": 512},
                    "ref": {"type": "string", "minLength": 1, "maxLength": 100},
                },
                ["repository", "path"],
            ),
            risk="read",
            parallel_safe=True,
            timeout_ms=10_000,
        ),
        ToolSpec(
            name="get_issue",
            description="Get a GitHub issue.",
            parameters=_parameters(
                {"repository": _REPOSITORY, "issue_number": _ISSUE_NUMBER},
                ["repository", "issue_number"],
            ),
            risk="read",
            parallel_safe=True,
            timeout_ms=10_000,
        ),
        ToolSpec(
            name="list_issues",
            description="List GitHub issues.",
            parameters=_parameters(
                {
                    "repository": _REPOSITORY,
                    "state": {
                        "type": "string",
                        "enum": ["open", "closed", "all"],
                        "default": "open",
                    },
                    "page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1_000,
                        "default": 1,
                    },
                    "per_page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 10,
                    },
                },
                ["repository"],
            ),
            risk="read",
            parallel_safe=True,
            timeout_ms=10_000,
        ),
        ToolSpec(
            name="search_code",
            description="Search code in a GitHub repository.",
            parameters=_parameters(
                {
                    "repository": _REPOSITORY,
                    "query": {"type": "string", "minLength": 1, "maxLength": 256},
                    "page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 1,
                    },
                    "per_page": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 10,
                    },
                },
                ["repository", "query"],
            ),
            risk="read",
            parallel_safe=True,
            timeout_ms=10_000,
        ),
    )


class GitHubIntegration(Integration):
    def __init__(self, client: _GitHubClientLike) -> None:
        self._client = client

    @property
    def namespace(self) -> str:
        return "github"

    def tools(self) -> list[tuple[ToolSpec, ToolHandler]]:
        pairs: list[tuple[ToolSpec, ToolHandler]] = []
        for spec in _specs():
            method = cast(
                Callable[..., Awaitable[Mapping[str, object]]],
                getattr(self._client, spec.name),
            )

            async def handler(
                context: ToolExecutionContext,
                arguments: dict[str, Any],
                *,
                _method: Callable[..., Awaitable[Mapping[str, object]]] = method,
            ) -> dict[str, object]:
                return dict(await _method(context, **arguments))

            pairs.append((spec, handler))
        return pairs


def create_github_integration(
    *,
    token_for: Callable[[ToolExecutionContext], Awaitable[str]],
    repositories: Collection[str],
    metrics_sink: MetricsSink = NOOP_METRICS,
    trace_sink: TraceSink = NOOP_TRACE,
) -> GitHubIntegration:
    return _create_github_integration_for_test(
        token_for=token_for,
        repositories=repositories,
        http=FixedOriginClient.for_github(
            metrics_sink=metrics_sink,
            trace_sink=trace_sink,
        ),
    )


def _create_github_integration_for_test(
    *,
    token_for: Callable[[ToolExecutionContext], Awaitable[str]],
    repositories: Collection[str],
    http: FixedOriginClient,
) -> GitHubIntegration:
    return GitHubIntegration(
        GitHubClient(token_for=token_for, repositories=repositories, http=http)
    )


class _InspectionClient:
    def __getattr__(self, _name: str) -> Callable[..., Awaitable[Mapping[str, object]]]:
        async def reject(*_args: object, **_kwargs: object) -> Mapping[str, object]:
            raise RuntimeError("inspection dependencies must not execute")

        return reject


def inspect_integration() -> GitHubIntegration:
    return GitHubIntegration(cast(_GitHubClientLike, _InspectionClient()))
