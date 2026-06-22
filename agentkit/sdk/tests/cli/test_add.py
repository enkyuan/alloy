"""Tests for `agentkit add` and `agentkit list-integrations`."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agentkit.cli import main


def test_add_github_copies_file(tmp_path: Path) -> None:
    rc = main(["add", "github", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "github.py").exists()


def test_add_unknown_integration_returns_nonzero(tmp_path: Path) -> None:
    out = StringIO()
    with patch("sys.stdout", out):
        rc = main(["add", "does-not-exist", "--out", str(tmp_path)])
    assert rc == 1
    assert "Unknown integration" in out.getvalue()


def test_add_refuses_overwrite_without_force(tmp_path: Path) -> None:
    rc1 = main(["add", "github", "--out", str(tmp_path)])
    assert rc1 == 0
    out = StringIO()
    with patch("sys.stdout", out):
        rc2 = main(["add", "github", "--out", str(tmp_path)])
    assert rc2 == 1
    assert "--force" in out.getvalue()


def test_add_force_overwrites(tmp_path: Path) -> None:
    main(["add", "github", "--out", str(tmp_path)])
    target = tmp_path / "github.py"
    target.write_text("# modified\n")
    rc = main(["add", "github", "--out", str(tmp_path), "--force"])
    assert rc == 0
    assert "class GitHub" in target.read_text()


def test_list_integrations_prints_github() -> None:
    out = StringIO()
    with patch("sys.stdout", out):
        rc = main(["list-integrations"])
    assert rc == 0
    assert "github" in out.getvalue()


def test_list_integrations_json_emits_valid_object() -> None:
    out = StringIO()
    with patch("sys.stdout", out):
        rc = main(["list-integrations", "--json"])
    assert rc == 0
    parsed = json.loads(out.getvalue())
    names = {entry["name"] for entry in parsed}
    assert "github" in names
    github = next(entry for entry in parsed if entry["name"] == "github")
    assert github["auth_kind"] == "env"
    assert "get_repo" in github["tools"]
