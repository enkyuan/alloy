from pathlib import Path

from agentkit.cli import init_project, main


def test_init_project_writes_minimal_scaffold(tmp_path: Path):
    written = init_project(tmp_path)

    assert tmp_path / "agent.py" in written
    assert tmp_path / ".env.example" in written
    assert "AgentRuntime" in (tmp_path / "agent.py").read_text()
    assert "OPENAI_API_KEY" in (tmp_path / ".env.example").read_text()


def test_init_project_does_not_overwrite_without_force(tmp_path: Path):
    agent_file = tmp_path / "agent.py"
    agent_file.write_text("custom")

    written = init_project(tmp_path)

    assert agent_file not in written
    assert agent_file.read_text() == "custom"


def test_cli_init(tmp_path: Path, capsys):
    assert main(["init", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "agent.py" in output
    assert (tmp_path / "agent.py").exists()
