"""AgentKit command line helpers."""

from __future__ import annotations

import argparse
from pathlib import Path


AGENT_TEMPLATE = '''"""Minimal AgentKit runtime scaffold."""

from __future__ import annotations

import agentkit


store = agentkit.InMemoryEventStore()
bus = agentkit.InMemoryEventBus()


planner = agentkit.ToolPlanner(
    executor=lambda name, args: agentkit.execute_tool("local-user", name, args)
)


runtime = agentkit.AgentRuntime(
    bus=bus,
    store=store,
    provider=agentkit.get_provider("mock"),
    planner=planner,
    tools=agentkit.list_tool_specs(),
)


async def send(session_id: str, content: str):
    await runtime.send(session_id, content)
    return await store.get_events(session_id)
'''


ENV_TEMPLATE = """# Swap the mock provider in agent.py for a real provider when ready.
# AGENTKIT_MODEL_PROVIDER=kimi
# OPENROUTER_API_KEY=
# OPENAI_API_KEY=
# ANTHROPIC_API_KEY=
# GEMINI_API_KEY=
"""


def _write(path: Path, content: str, *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.write_text(content)
    return True


def init_project(target: Path, *, force: bool = False) -> list[Path]:
    """Create a minimal local AgentKit scaffold."""
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, content in {
        "agent.py": AGENT_TEMPLATE,
        ".env.example": ENV_TEMPLATE,
    }.items():
        path = target / filename
        if _write(path, content, force=force):
            written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentkit")
    subcommands = parser.add_subparsers(dest="command", required=True)

    init_parser = subcommands.add_parser("init", help="Create a minimal scaffold")
    init_parser.add_argument("path", nargs="?", default=".")
    init_parser.add_argument("--force", action="store_true", help="Overwrite files")

    args = parser.parse_args(argv)
    if args.command == "init":
        written = init_project(Path(args.path), force=args.force)
        for path in written:
            print(path)
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
