import json
import re

from agentkit.cli import main


def test_secret_default(capsys) -> None:
    rc = main(["secret"])
    assert rc == 0
    out = capsys.readouterr().out
    assert re.search(r"AGENTKIT_SECRET=[0-9a-f]{64}", out)


def test_secret_json(capsys) -> None:
    rc = main(["secret", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "AGENTKIT_SECRET"
    assert re.fullmatch(r"[0-9a-f]{64}", data["value"])
