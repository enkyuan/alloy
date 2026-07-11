"""Tests for `kaji add` and `kaji list-integrations`."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from kaji.cli import main
from kaji.integrations import ManifestError


def test_add_echo_copies_files(tmp_path: Path) -> None:
    rc = main(["add", "echo", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "echo.py").exists()
    assert (tmp_path / "echo.ts").exists()


def test_add_unknown_integration_returns_nonzero(tmp_path: Path) -> None:
    out = StringIO()
    with patch("sys.stdout", out):
        rc = main(["add", "does-not-exist", "--out", str(tmp_path)])
    assert rc == 1
    assert "Unknown integration" in out.getvalue()


def test_add_refuses_overwrite_without_force(tmp_path: Path) -> None:
    rc1 = main(["add", "echo", "--out", str(tmp_path)])
    assert rc1 == 0
    out = StringIO()
    with patch("sys.stdout", out):
        rc2 = main(["add", "echo", "--out", str(tmp_path)])
    assert rc2 == 1
    assert "--force" in out.getvalue()


def test_add_force_overwrites(tmp_path: Path) -> None:
    main(["add", "echo", "--out", str(tmp_path)])
    target = tmp_path / "echo.py"
    target.write_text("# modified\n")
    rc = main(["add", "echo", "--out", str(tmp_path), "--force"])
    assert rc == 0
    assert "async def say" in target.read_text()


def test_list_integrations_prints_echo() -> None:
    out = StringIO()
    with patch("sys.stdout", out):
        rc = main(["list-integrations"])
    assert rc == 0
    assert "echo" in out.getvalue()
    assert "github" not in out.getvalue()


def test_list_integrations_json_emits_valid_object() -> None:
    out = StringIO()
    with patch("sys.stdout", out):
        rc = main(["list-integrations", "--json"])
    assert rc == 0
    parsed = json.loads(out.getvalue())
    names = {entry["name"] for entry in parsed}
    assert "echo" in names
    assert {"github", "gmail", "gcal"}.isdisjoint(names)
    echo = next(entry for entry in parsed if entry["name"] == "echo")
    assert echo["auth_kind"] == "none"
    assert "say" in echo["tools"]
    assert echo["stability"] == "beta"
    assert echo["runtimes"] == ["python", "typescript"]


def test_list_integrations_returns_nonzero_for_corrupt_registry() -> None:
    out = StringIO()
    with (
        patch(
            "kaji.cli.list_integrations._list",
            side_effect=ManifestError("invalid registry"),
        ),
        patch("sys.stdout", out),
    ):
        rc = main(["list-integrations"])

    assert rc == 1
    assert "Registry error" in out.getvalue()
