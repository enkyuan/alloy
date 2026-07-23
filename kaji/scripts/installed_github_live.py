#!/usr/bin/env python3
"""Execute one narrow GitHub read/comment cell from an installed Python wheel."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, cast

from github_proof_control import (
    read_private_json,
    validate_private_fixture,
    validate_proof_token,
)


EXPECTED_TOOLS = frozenset(
    {
        "github_add_comment",
        "github_create_issue",
        "github_get_file",
        "github_get_issue",
        "github_list_issues",
        "github_search_code",
    }
)


def _contained(path: Path, root: Path, code: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        boundary = root.resolve(strict=True)
        resolved.relative_to(boundary)
    except (OSError, ValueError):
        raise RuntimeError(code) from None
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
    if (
        Path(client.__file__ or "").resolve() != (bundle / "client.py").resolve()
        or Path(integration.__file__ or "").resolve()
        != (bundle / "github.py").resolve()
    ):
        raise RuntimeError("bundle_identity_invalid")
    return client, integration


def _input(path: Path, runtime: str) -> dict[str, Any]:
    document = read_private_json(path)
    if type(document) is not dict or set(document) != {
        "runtime",
        "owner",
        "repository",
        "issueNumber",
        "marker",
    }:
        raise RuntimeError("input_invalid")
    fixture = validate_private_fixture(
        {
            "owner": document.get("owner"),
            "repository": document.get("repository"),
            "issueNumber": document.get("issueNumber"),
        }
    )
    marker = document.get("marker")
    if (
        document.get("runtime") != runtime
        or not isinstance(marker, str)
        or not 1 <= len(marker) <= 256
        or "\r" in marker
        or "\n" in marker
    ):
        raise RuntimeError("input_invalid")
    return {**fixture, "marker": marker}


async def _execute(
    integration_module: ModuleType,
    *,
    repository: str,
    issue_number: int,
    marker: str,
    token: str,
) -> dict[str, object]:
    from kaji.infra.events.journal import InMemoryEventJournal
    from kaji.infra.events.store import InMemoryEventStore
    from kaji.runtime.agents.approval import ApprovalDecision, ApprovalRequestContext
    from kaji.runtime.agents.cancellation import CancellationToken
    from kaji.runtime.agents.context import TurnContext
    from kaji.runtime.agents.planner import JournalEventEmitter, ToolPlanner
    from kaji.runtime.context import ToolInvocation
    from kaji.runtime.tools.policies import ToolPolicy
    from kaji.runtime.tools.registry import ToolRegistry

    async def token_for(_context: object) -> str:
        return token

    integration = integration_module.create_github_integration(
        token_for=token_for,
        repositories={repository},
    )
    registry = ToolRegistry()
    integration.register(registry)
    specs = {spec.name: spec for spec in registry.list_specs()}
    if set(specs) != EXPECTED_TOOLS:
        raise RuntimeError("tool_catalog_invalid")
    store = InMemoryEventStore()
    journal = InMemoryEventJournal(store)
    emitter = JournalEventEmitter(journal)
    approvals = 0
    expected_arguments = {
        "repository": repository,
        "issue_number": issue_number,
        "body": marker,
    }

    class ExactApproval:
        async def request(
            self,
            call: ToolInvocation,
            context: ApprovalRequestContext,
        ) -> ApprovalDecision:
            del context
            nonlocal approvals
            approvals += 1
            if (
                call.name != "github_add_comment"
                or dict(call.arguments) != expected_arguments
                or approvals != 1
            ):
                raise RuntimeError("approval_scope_invalid")
            return ApprovalDecision(True, "approved")

    async def execute(invocation: ToolInvocation) -> dict[str, object]:
        return await registry.execute(invocation)

    planner = ToolPlanner(
        execute,
        policy=ToolPolicy(require_approval_for={"external_effect"}),
        approval_handler=ExactApproval(),
        specs=specs,
    )
    try:
        read = await planner.execute_batch(
            "github-proof-read",
            [
                {
                    "id": "read",
                    "name": "github_get_issue",
                    "arguments": {
                        "repository": repository,
                        "issue_number": issue_number,
                    },
                }
            ],
            emitter,
            turn_id="github-proof-read",
            turn_context=TurnContext(principal_id="github-proof"),
            cancellation_token=CancellationToken(),
            approval_journal=journal,
        )
        read_result = read[0].get("result")
        if type(read_result) is not dict or read_result.get("number") != issue_number:
            raise RuntimeError("read_invalid")
        mutation = await planner.execute_batch(
            "github-proof-comment",
            [
                {
                    "id": "comment",
                    "name": "github_add_comment",
                    "arguments": expected_arguments,
                }
            ],
            emitter,
            turn_id="github-proof-comment",
            turn_context=TurnContext(principal_id="github-proof"),
            cancellation_token=CancellationToken(),
            approval_journal=journal,
        )
        comment = mutation[0].get("result")
        comment_id = comment.get("id") if type(comment) is dict else None
        if type(comment_id) is not int or comment_id < 1 or approvals != 1:
            raise RuntimeError("comment_invalid")
        return {
            "runtime": "python",
            "readPassed": True,
            "approvedCommentPassed": True,
            "commentId": comment_id,
        }
    finally:
        await integration.aclose()


async def _run(
    args: argparse.Namespace, environment: dict[str, str]
) -> dict[str, object]:
    if not sys.flags.isolated:
        raise RuntimeError("isolation_required")
    if any(
        name in environment
        for name in ("GITHUB_TOKEN", "GH_TOKEN", "PYTHONHOME", "PYTHONPATH")
    ):
        raise RuntimeError("environment_invalid")
    token = environment.get("KAJI_GITHUB_PROOF_TOKEN", "")
    if not token:
        raise RuntimeError("token_missing")
    token = validate_proof_token(token)
    sandbox = args.sandbox_root.resolve(strict=True)
    package_root = _contained(args.package_root, sandbox, "package_identity_invalid")
    bundle = _contained(args.bundle_root, sandbox, "bundle_identity_invalid")
    _contained(Path(__file__), sandbox, "runner_identity_invalid")
    import kaji

    if Path(kaji.__file__ or "").resolve().parent != package_root:
        raise RuntimeError("package_identity_invalid")
    values = _input(args.input, "python")
    _client, integration = _load_copied_modules(bundle)
    repository = f"{values['owner']}/{values['repository']}"
    return await _execute(
        integration,
        repository=repository,
        issue_number=cast(int, values["issueNumber"]),
        marker=cast(str, values["marker"]),
        token=token,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox-root", required=True, type=Path)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = asyncio.run(_run(args, dict(os.environ)))
    except Exception:
        print("installed GitHub proof failed", file=sys.stderr)
        return 1
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
