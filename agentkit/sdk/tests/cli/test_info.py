import json

from agentkit.cli import main
from agentkit.cli.info import collect


def test_collect_returns_known_sections() -> None:
    out = collect()
    assert "python" in out
    assert "platform" in out
    assert "agentkit" in out
    assert "providers" in out


def test_info_json(capsys) -> None:
    rc = main(["info", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "python" in data
