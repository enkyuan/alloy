from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest


def test_main_callable_from_top_level() -> None:
    mod = importlib.import_module("agentkit.cli")
    assert callable(mod.main)


def test_init_subcommand_writes_files(tmp_path: Path) -> None:
    from agentkit.cli import main
    rc = main(["init", str(tmp_path), "--provider", "openai", "--yes"])
    assert rc == 0
    assert (tmp_path / "agent.py").exists()
    assert (tmp_path / ".env.example").exists()


def test_unknown_command_returns_2(tmp_path: Path) -> None:
    from agentkit.cli import main
    with pytest.raises(SystemExit) as e:
        main(["nope"])
    assert e.value.code == 2
