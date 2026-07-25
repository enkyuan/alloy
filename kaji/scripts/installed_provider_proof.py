#!/usr/bin/env python3
"""Run one redacted provider tool-loop proof from an installed Kaji wheel."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

import kaji
from kaji.infra.events.types import EventType
from kaji.runtime.agents.context import TurnContext
from kaji.runtime.providers.openai import OpenAIProvider


MARKER = "kaji-installed-provider-proof-marker"
EXPECTED_ECHO = {"marker": MARKER, "source": "kaji-installed-provider-proof"}
PROVIDER_KEYS = {"openai": "OPENAI_API_KEY"}
FORBIDDEN_TERMINALS = {
    EventType.AGENT_TURN_EXHAUSTED,
    EventType.AGENT_TURN_FAILED,
    EventType.TOOL_CALL_FAILED,
    EventType.CANCELLATION_REQUESTED,
    EventType.CANCELLATION_COMPLETED,
}


class EchoProofIntegration(kaji.Integration):
    namespace = "proof"

    @kaji.tool(
        description="Echo the supplied marker back to the caller.",
        parameters={
            "type": "object",
            "properties": {"marker": {"type": "string"}},
            "required": ["marker"],
            "additionalProperties": False,
        },
        risk="read",
    )
    async def echo(
        self, _ctx: kaji.ToolExecutionContext, args: dict[str, Any]
    ) -> dict[str, Any]:
        return {"marker": args["marker"], "source": "kaji-installed-provider-proof"}


def _base_receipt(provider: str, model: str) -> dict[str, Any]:
    package_file = getattr(kaji, "__file__", None)
    resolved = str(Path(package_file).resolve()) if package_file else "unresolved"
    return {
        "sdk": "python",
        "provider": provider,
        "proof": "real_normalized_tool_loop",
        "status": "failed",
        "model": model,
        "resolvedPackage": resolved,
        "requestedToolCalls": 0,
        "completedToolCalls": 0,
        "requestedToolCallIds": [],
        "completedToolCallIds": [],
        "echoResultMatched": False,
        "finalTextPresent": False,
        "forbiddenTerminalEvents": [],
    }


async def _run(provider_name: str, model: str, api_key: str) -> dict[str, Any]:
    provider = OpenAIProvider(api_key=api_key, model=model)
    runtime = (
        kaji.AgentBuilder()
        .provider(provider)
        .integration(EchoProofIntegration())
        .default_context(TurnContext(principal_id=f"{provider_name}-installed-proof"))
        .system_prompt(
            "You are validating installed SDK tool execution. Call the `proof_echo` "
            "tool exactly once with the marker from the user message, then give a "
            "short final answer."
        )
        .build(store=kaji.InMemoryEventStore())
    )
    result = await runtime.turn(
        f"Call `proof_echo` exactly once with marker `{MARKER}`, then finish.",
        session_id=f"{provider_name}-installed-provider-proof",
    )
    requested = [
        event for event in result.events if event.type == EventType.TOOL_CALL_REQUESTED
    ]
    completed = [
        event for event in result.events if event.type == EventType.TOOL_CALL_COMPLETED
    ]
    event_types = [event.type for event in result.events]
    forbidden = sorted(
        event_type.value
        for event_type in set(event_types)
        if event_type in FORBIDDEN_TERMINALS
    )
    receipt = _base_receipt(provider_name, model)
    receipt.update(
        requestedToolCalls=len(requested),
        completedToolCalls=len(completed),
        requestedToolCallIds=[event.tool_call_id for event in requested],
        completedToolCallIds=[event.tool_call_id for event in completed],
        echoResultMatched=(
            len(completed) == 1 and completed[0].result == EXPECTED_ECHO
        ),
        finalTextPresent=bool(result.text.strip()),
        forbiddenTerminalEvents=forbidden,
    )
    receipt["status"] = (
        "passed"
        if receipt["requestedToolCalls"] == 1
        and receipt["completedToolCalls"] == 1
        and receipt["requestedToolCallIds"] == receipt["completedToolCallIds"]
        and receipt["echoResultMatched"] is True
        and receipt["finalTextPresent"] is True
        and not forbidden
        else "failed"
    )
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=tuple(PROVIDER_KEYS))
    parser.add_argument("--model", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    model = args.model.strip()
    api_key = os.environ.get(PROVIDER_KEYS[args.provider], "").strip()
    if not model or not api_key:
        print(json.dumps(_base_receipt(args.provider, model), sort_keys=True))
        print("provider proof configuration is incomplete", file=sys.stderr)
        return 2
    try:
        receipt = asyncio.run(_run(args.provider, model, api_key))
    except Exception:
        print(json.dumps(_base_receipt(args.provider, model), sort_keys=True))
        print("provider proof execution failed", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
