"""`kaji init` -- scaffold a new project."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import _prompts
from ._style import color
from .templates import agent_template, env_template

PROVIDERS = ["openai", "anthropic", "kimi", "gemini"]


def _write(path: Path, body: str, *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.write_text(body)
    return True


def init_project(
    target: Path, *, provider: str = "openai", force: bool = False
) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, body in (
        ("agent.py", agent_template(provider)),
        (".env.example", env_template(provider)),
    ):
        path = target / name
        if _write(path, body, force=force):
            written.append(path)
    return written


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("init", help="scaffold a new kaji project")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--provider", choices=PROVIDERS, default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--yes", action="store_true", help="non-interactive")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    target = Path(args.path)
    provider = args.provider
    if provider is None and not args.yes:
        provider = _prompts.select(
            "Default LLM provider",
            [
                ("openai", "OpenAI"),
                ("anthropic", "Anthropic"),
                ("kimi", "Kimi"),
                ("gemini", "Gemini"),
            ],
        )
    provider = provider or "openai"
    written = init_project(target, provider=provider, force=args.force)
    if not written:
        print(color("Nothing written -- pass --force to overwrite.", "yellow"))
        return 0
    for p in written:
        print(p)
    return 0
