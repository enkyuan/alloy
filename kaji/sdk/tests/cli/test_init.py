from __future__ import annotations

from pathlib import Path


from kaji.cli.init import init_project
from kaji.cli.templates import agent_template, env_template


def test_init_project_creates_files(tmp_path: Path) -> None:
    written = init_project(tmp_path, provider="openai")
    assert {p.name for p in written} == {"agent.py", ".env.example"}


def test_init_project_skips_existing(tmp_path: Path) -> None:
    init_project(tmp_path, provider="openai")
    (tmp_path / "agent.py").write_text("# custom")
    init_project(tmp_path, provider="openai")
    assert (tmp_path / "agent.py").read_text() == "# custom"


def test_init_project_force_overwrites(tmp_path: Path) -> None:
    init_project(tmp_path, provider="openai")
    (tmp_path / "agent.py").write_text("# custom")
    init_project(tmp_path, provider="openai", force=True)
    assert (tmp_path / "agent.py").read_text() == agent_template("openai")


def test_agent_template_is_valid_python() -> None:
    import ast

    ast.parse(agent_template("openai"))


def test_env_template_mentions_provider() -> None:
    env = env_template("anthropic")
    assert "KAJI_MODEL_PROVIDER=anthropic" in env
    assert "ANTHROPIC_API_KEY" in env
