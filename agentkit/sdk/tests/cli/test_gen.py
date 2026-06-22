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


# A spec with typed query parameters and a body. The generator must:
#  - reflect the typed query param in the JSON Schema (integer, not string)
#  - emit url.searchParams.set in TS / params=… in Python for the query
#  - exclude path+query keys from the body in both outputs
TYPED_SPEC = {
    "info": {"title": "Pet API"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/pets/{id}": {
            "get": {
                "operationId": "getPet",
                "summary": "fetch a pet",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "description": "max related items",
                        "schema": {"type": "integer"},
                    },
                ],
            }
        }
    },
}


def test_gen_python_emits_typed_query_params(tmp_path: Path) -> None:
    import ast
    from agentkit.cli import main

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(TYPED_SPEC))
    rc = main(
        ["gen", "--spec", str(spec_path), "--out", str(tmp_path), "--lang", "python"]
    )
    assert rc == 0
    body = (tmp_path / "tools.py").read_text()
    ast.parse(body)
    # Query param surfaced as integer in the JSON schema.
    assert '"limit": {"type": "integer"' in body
    # Required list only has the path param.
    assert '"required": ["id"]' in body
    # The HTTP call wires the query into params=… not the body.
    assert "params={k: args[k] for k in" in body


def test_gen_ts_emits_searchparams_and_excludes_body_for_get(tmp_path: Path) -> None:
    from agentkit.cli import main

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(TYPED_SPEC))
    rc = main(["gen", "--spec", str(spec_path), "--out", str(tmp_path), "--lang", "ts"])
    assert rc == 0
    body = (tmp_path / "index.ts").read_text()
    assert 'limit: { type: "integer"' in body
    assert 'url.searchParams.set("limit"' in body or "url.searchParams.set(q" in body
    # GET has no body, so no JSON.stringify call should be emitted.
    assert "JSON.stringify" not in body
