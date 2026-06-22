from __future__ import annotations

import json
from pathlib import Path


SPEC = {
    "info": {"title": "Pet API"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/pets/{id}": {"get": {"operationId": "getPet", "summary": "fetch a pet"}},
        "/pets": {"post": {"operationId": "createPet", "summary": "create pet"}},
    },
}


def test_gen_python_writes_tools_module(tmp_path: Path) -> None:
    import ast
    from agentkit.cli import main

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(SPEC))
    rc = main(
        ["gen", "--spec", str(spec_path), "--out", str(tmp_path), "--lang", "python"]
    )
    assert rc == 0
    body = (tmp_path / "tools.py").read_text()
    assert "TOOLS" in body
    assert "async def get_pet" in body
    ast.parse(body)


def test_gen_ts_writes_index_ts(tmp_path: Path) -> None:
    from agentkit.cli import main

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(SPEC))
    rc = main(["gen", "--spec", str(spec_path), "--out", str(tmp_path), "--lang", "ts"])
    assert rc == 0
    body = (tmp_path / "index.ts").read_text()
    assert "export const tools" in body
    assert "get_pet" in body
