#!/usr/bin/env python3
"""Exercise a CLI-copied GitHub bundle against one installed Kaji artifact."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
import importlib
import json
import os
from pathlib import Path
import socket
import sys
from types import ModuleType
from typing import Any, cast


EXPECTED_TOOLS = frozenset(
    {
        "add_comment",
        "create_issue",
        "get_file",
        "get_issue",
        "list_issues",
        "search_code",
    }
)


def _contained(path: Path, root: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        boundary = root.resolve(strict=True)
        resolved.relative_to(boundary)
    except (OSError, ValueError) as error:
        raise RuntimeError(f"{label} is outside the installed smoke sandbox") from error
    return resolved


def _load_copied_modules(bundle: Path) -> tuple[ModuleType, ModuleType]:
    owner = ModuleType("owner_integrations")
    owner.__path__ = [str(bundle.parent)]  # type: ignore[attr-defined]
    package = ModuleType("owner_integrations.github")
    package.__path__ = [str(bundle)]  # type: ignore[attr-defined]
    sys.modules[owner.__name__] = owner
    sys.modules[package.__name__] = package
    client = importlib.import_module("owner_integrations.github.client")
    integration = importlib.import_module("owner_integrations.github.github")
    if Path(client.__file__ or "").resolve() != (bundle / "client.py").resolve():
        raise RuntimeError("copied GitHub client did not resolve from its owner bundle")
    if Path(integration.__file__ or "").resolve() != (bundle / "github.py").resolve():
        raise RuntimeError(
            "copied GitHub integration did not resolve from its owner bundle"
        )
    return client, integration


def _context() -> object:
    from kaji.runtime.agents.cancellation import CancellationToken
    from kaji.runtime.context import ToolExecutionContext

    return ToolExecutionContext(
        principal_id="installed-proof",
        session_id="session",
        turn_id="turn",
        request_id="request",
        trace_id="trace",
        tool_call_id="call",
        idempotency_key="session:call",
        cancellation_token=CancellationToken(),
        deadline_monotonic=None,
        db=None,
        metadata={},
    )


class _ScriptedHttp:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.contexts: list[object] = []

    async def request(
        self,
        path_and_query: str,
        *,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        context: object,
    ) -> object:
        from kaji.integrations.errors import IntegrationTransportError
        from kaji.integrations.fixed_origin import IntegrationResponse
        from kaji.runtime.agents.cancellation import CancelledError

        self.requests.append(
            {
                "method": method,
                "path_and_query": path_and_query,
                "headers": dict(headers),
                "body": None if body is None else body.decode("utf-8"),
            }
        )
        self.contexts.append(context)
        if not self.responses:
            raise RuntimeError("scripted GitHub response queue was exhausted")
        response = self.responses.pop(0)
        transport_error = response.get("transport_error")
        if transport_error == "response_limit":
            raise IntegrationTransportError(
                "INTEGRATION_RESPONSE_LIMIT", "response_limit_exceeded"
            )
        if transport_error == "cancelled":
            raise CancelledError("private cancellation detail")
        if transport_error == "connection":
            raise OSError("private connection detail")
        payload = (
            json.dumps(
                response["json"], ensure_ascii=False, separators=(",", ":")
            ).encode()
            if "json" in response
            else str(response.get("body", "")).encode()
        )
        return IntegrationResponse(
            status=response["status"],
            headers=response.get("headers", {}),
            body=payload,
        )


async def _run_cases(
    client_module: ModuleType,
    integration_module: ModuleType,
    fixture: dict[str, Any],
) -> tuple[set[str], bool, int]:
    from kaji.runtime.tools.execution import ToolExecutionError

    repository = fixture["repository"]
    token = fixture["token"]
    cases = cast(list[dict[str, Any]], fixture["cases"])
    executed_tools: set[str] = set()
    unknown_mutation_preserved = False
    mutation_retries = -1

    for case in cases:
        http = _ScriptedHttp(case["responses"])
        token_contexts: list[object] = []
        sleeps: list[float] = []

        async def token_for(execution_context: object) -> str:
            token_contexts.append(execution_context)
            return token

        async def sleep(delay: float) -> None:
            sleeps.append(delay)

        client = client_module.GitHubClient(
            token_for=token_for,
            repositories=[repository],
            http=http,
            _sleep=sleep,
            _monotonic=lambda: 0.0,
        )
        integration = integration_module.GitHubIntegration(client)
        handlers = {spec.name: handler for spec, handler in integration.tools()}
        operation = case["operation"]
        if set(handlers) != EXPECTED_TOOLS or operation not in handlers:
            raise RuntimeError(
                "copied GitHub integration exposed an unexpected tool set"
            )
        execution_context = _context()
        arguments = {"repository": repository, **case["input"]}
        try:
            result = await handlers[operation](execution_context, arguments)
            actual: dict[str, object] = {"result": result}
        except ToolExecutionError as error:
            actual = {
                "error": {
                    "code": error.error_code,
                    "outcome": error.outcome,
                    "retryable": error.retryable,
                }
            }
        except asyncio.CancelledError:
            actual = {"exception": "cancelled"}
        except Exception as error:
            if "private" in str(error).lower():
                raise RuntimeError("private transport detail escaped") from None
            actual = {"exception": "unknown"}

        if (
            actual != case["expected"]
            or http.requests != case["expected_requests"]
            or sleeps != case.get("expected_sleeps", [])
            or len(token_contexts) != case.get("expected_token_calls", 1)
            or any(seen is not execution_context for seen in token_contexts)
            or any(seen is not execution_context for seen in http.contexts)
            or http.responses
        ):
            raise RuntimeError("installed GitHub conformance case failed")
        executed_tools.add(operation)
        if case["name"] == "connection loss after write dispatch is unknown":
            unknown_mutation_preserved = actual == {"exception": "unknown"}
            mutation_retries = max(0, len(http.requests) - 1)

    return executed_tools, unknown_mutation_preserved, mutation_retries


async def _approval_precedes_credentials(
    client_module: ModuleType, integration_module: ModuleType, repository: str
) -> bool:
    from kaji.infra.events.journal import InMemoryEventJournal
    from kaji.infra.events.store import InMemoryEventStore
    from kaji.infra.events.types import EventType
    from kaji.runtime.agents.cancellation import CancellationToken
    from kaji.runtime.agents.context import TurnContext
    from kaji.runtime.agents.approval import (
        ApprovalDecision,
        ApprovalRequestContext,
    )
    from kaji.runtime.agents.planner import JournalEventEmitter, ToolPlanner
    from kaji.runtime.context import ToolInvocation
    from kaji.runtime.tools.policies import ToolPolicy
    from kaji.runtime.tools.registry import ToolRegistry

    credential_calls = 0
    request_calls = 0

    async def token_for(_context: object) -> str:
        nonlocal credential_calls
        credential_calls += 1
        raise RuntimeError("credential access must not run")

    class RejectingHttp:
        async def request(self, *_args: object, **_kwargs: object) -> object:
            nonlocal request_calls
            request_calls += 1
            raise RuntimeError("HTTP must not run")

    integration = integration_module.GitHubIntegration(
        client_module.GitHubClient(
            token_for=token_for,
            repositories=[repository],
            http=RejectingHttp(),
        )
    )
    registry = ToolRegistry()
    integration.register(registry)
    specs = {spec.name: spec for spec in registry.list_specs()}
    journal = InMemoryEventJournal(InMemoryEventStore())
    events: list[object] = []

    async def observe(event: object) -> None:
        events.append(event)

    async def execute(invocation: object) -> dict[str, object]:
        return await registry.execute(cast(Any, invocation))

    class RejectingApproval:
        async def request(
            self,
            _call: ToolInvocation,
            _context: ApprovalRequestContext,
        ) -> ApprovalDecision:
            return ApprovalDecision(
                granted=False,
                code="rejected",
                reason="Rejected by installed package proof",
            )

    planner = ToolPlanner(
        execute,
        policy=ToolPolicy(require_approval_for={"external_effect"}),
        approval_handler=RejectingApproval(),
        specs=specs,
    )
    arguments = {
        "github_create_issue": {
            "repository": repository,
            "title": "title",
            "body": "body",
        },
        "github_add_comment": {
            "repository": repository,
            "issue_number": 1,
            "body": "body",
        },
    }
    for index, (name, values) in enumerate(arguments.items()):
        result = await planner.execute_batch(
            "session",
            [{"id": f"call-{index}", "name": name, "arguments": values}],
            JournalEventEmitter(journal, before_commit=observe),
            turn_id=f"turn-{index}",
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=CancellationToken(),
            approval_journal=journal,
        )
        if result[0].get("error_code") != "APPROVAL_REJECTED":
            return False
    return (
        credential_calls == 0
        and request_calls == 0
        and EventType.TOOL_CALL_STARTED
        not in [getattr(event, "type", None) for event in events]
    )


def _deny_network() -> list[int]:
    attempts: list[int] = []

    def reject(*_args: object, **_kwargs: object) -> object:
        attempts.append(1)
        raise RuntimeError("external network is disabled in package proof")

    socket.socket.connect = reject  # type: ignore[method-assign]
    socket.socket.connect_ex = reject  # type: ignore[method-assign]
    socket.create_connection = reject  # type: ignore[assignment]
    socket.getaddrinfo = reject  # type: ignore[assignment]
    return attempts


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if not sys.flags.isolated:
        raise RuntimeError("installed Python proof must run in isolated mode")
    if any(name in os.environ for name in ("GITHUB_TOKEN", "PYTHONHOME", "PYTHONPATH")):
        raise RuntimeError("installed Python proof environment is not isolated")
    sandbox = args.sandbox_root.resolve(strict=True)
    bundle = _contained(args.bundle_root, sandbox, "GitHub bundle")
    package = _contained(args.package_root, sandbox, "Kaji package")
    _contained(Path(__file__), sandbox, "GitHub proof runner")

    network_attempts = _deny_network()
    import kaji

    if Path(kaji.__file__ or "").resolve().parent != package:
        raise RuntimeError("Kaji did not resolve from the installed artifact")
    fixture_path = _contained(
        package / "contracts/integrations/github-api-conformance-v1.json",
        package,
        "GitHub conformance contract",
    )
    fixture = cast(dict[str, Any], json.loads(fixture_path.read_text()))
    client_module, integration_module = _load_copied_modules(bundle)
    executed, unknown_preserved, retries = await _run_cases(
        client_module, integration_module, fixture
    )
    approval_first = await _approval_precedes_credentials(
        client_module, integration_module, fixture["repository"]
    )
    if (
        executed != EXPECTED_TOOLS
        or not unknown_preserved
        or retries != 0
        or not approval_first
        or network_attempts
    ):
        raise RuntimeError("installed GitHub proof assertions failed")
    return {
        "schemaVersion": 1,
        "evidenceClass": "offline_exact_artifact_smoke",
        "integration": "github",
        "runtime": "python",
        "network": "scripted",
        "liveProvider": False,
        "contractVersion": fixture["version"],
        "caseCount": len(fixture["cases"]),
        "toolCount": len(executed),
        "approvalDeniedBeforeCredentialAccess": True,
        "mutationRetries": retries,
        "unknownMutationPreserved": True,
        "sourceRuntimeDetected": False,
        "conclusion": "passed",
        "failureCode": None,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox-root", required=True, type=Path)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        receipt = asyncio.run(_run(parse_args(argv)))
    except Exception:
        print("installed GitHub package proof failed", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
