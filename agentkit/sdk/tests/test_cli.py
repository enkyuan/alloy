"""Tests for `agentkit init` CLI scaffold."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agentkit.cli import ENV_TEMPLATE, AGENT_TEMPLATE, init_project, main


# ---------------------------------------------------------------------------
# init_project
# ---------------------------------------------------------------------------


def test_init_project_creates_files(tmp_path: Path) -> None:
    written = init_project(tmp_path)
    names = {p.name for p in written}
    assert names == {"agent.py", ".env.example"}


def test_init_project_creates_target_directory(tmp_path: Path) -> None:
    target = tmp_path / "new-agent"
    assert not target.exists()
    init_project(target)
    assert target.is_dir()


def test_init_project_skips_existing_files(tmp_path: Path) -> None:
    init_project(tmp_path)

    # Write different content and call init_project without force
    (tmp_path / "agent.py").write_text("# custom")
    init_project(tmp_path)

    # Should not have overwritten
    assert (tmp_path / "agent.py").read_text() == "# custom"


def test_init_project_force_overwrites(tmp_path: Path) -> None:
    init_project(tmp_path)
    (tmp_path / "agent.py").write_text("# custom")
    init_project(tmp_path, force=True)
    assert (tmp_path / "agent.py").read_text() == AGENT_TEMPLATE


# ---------------------------------------------------------------------------
# main() CLI entry point
# ---------------------------------------------------------------------------


def test_main_init_writes_files(tmp_path: Path) -> None:
    rc = main(["init", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "agent.py").exists()
    assert (tmp_path / ".env.example").exists()


def test_main_init_prints_paths(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    main(["init", str(tmp_path)])
    out = capsys.readouterr().out
    assert "agent.py" in out
    assert ".env.example" in out


# ---------------------------------------------------------------------------
# Template correctness: canonical path uses AgentBuilder, not mock
# ---------------------------------------------------------------------------


def test_agent_template_is_valid_python() -> None:
    ast.parse(AGENT_TEMPLATE)


def test_agent_template_uses_agent_builder() -> None:
    assert "AgentBuilder" in AGENT_TEMPLATE


def test_agent_template_does_not_hardcode_mock() -> None:
    # Template must NOT use GetProvider("mock") as the default; it must be
    # env-driven so the developer is directed to configure a real provider.
    assert 'GetProvider("mock")' not in AGENT_TEMPLATE
    assert "MockProvider" not in AGENT_TEMPLATE


def test_agent_template_uses_env_driven_provider() -> None:
    # Provider must come from an environment variable, not a hardcoded name.
    assert "AGENTKIT_MODEL_PROVIDER" in AGENT_TEMPLATE
    assert "GetProvider(provider_name)" in AGENT_TEMPLATE


def test_agent_template_uses_agent_builder_not_manual_planner() -> None:
    # The scaffold should NOT hand-wire ToolPlanner + ExecuteTool; AgentBuilder
    # handles that internally. Raw ToolPlanner construction is the old pattern.
    assert "ToolPlanner(" not in AGENT_TEMPLATE
    assert "execute_tool" not in AGENT_TEMPLATE
    assert "ExecuteTool" not in AGENT_TEMPLATE


def test_env_template_mentions_api_keys() -> None:
    assert "OPENAI_API_KEY" in ENV_TEMPLATE
    assert "ANTHROPIC_API_KEY" in ENV_TEMPLATE


def test_env_template_mentions_provider_var() -> None:
    assert "AGENTKIT_MODEL_PROVIDER" in ENV_TEMPLATE
