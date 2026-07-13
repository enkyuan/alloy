from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_main_callable_from_top_level() -> None:
    mod = importlib.import_module("kaji.cli")
    assert callable(mod.main)


def test_init_subcommand_writes_files(tmp_path: Path) -> None:
    from kaji.cli import main

    rc = main(["init", str(tmp_path), "--provider", "mock", "--yes"])
    assert rc == 0
    assert (tmp_path / "agent.py").exists()
    assert (tmp_path / ".env.example").exists()


def test_unknown_command_returns_2(tmp_path: Path) -> None:
    from kaji.cli import main

    with pytest.raises(SystemExit) as e:
        main(["nope"])
    assert e.value.code == 2


def test_init_defaults_are_noninteractive_and_mock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kaji.cli import main
    from kaji.cli import _prompts

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        _prompts,
        "select",
        lambda *_args, **_kwargs: pytest.fail("init unexpectedly prompted"),
    )

    assert main(["init", "--yes"]) == 0
    assert 'kaji.get_provider("mock")' in (tmp_path / "agent.py").read_text()


def test_init_preflights_every_destination_before_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from kaji.cli import main

    existing = tmp_path / ".env.example"
    existing.write_text("keep-me")

    assert main(["init", str(tmp_path), "--yes"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refusing to overwrite without --force" in captured.err
    assert existing.read_text() == "keep-me"
    assert not (tmp_path / "agent.py").exists()


def test_global_flags_precede_init_and_help_is_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from kaji.cli import main

    assert main(["--no-color", "--verbose", "init", str(tmp_path), "--yes"]) == 0
    assert "\x1b[" not in capsys.readouterr().out
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    assert "kaji (Python package kaji) 0.2.0b1" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["init", "--provider", "unknown"],
        ["init", "--provider"],
        ["init", "--unknown"],
    ],
)
def test_malformed_init_usage_exits_2(argv: list[str]) -> None:
    from kaji.cli import main

    with pytest.raises(SystemExit) as caught:
        main(argv)
    assert caught.value.code == 2
