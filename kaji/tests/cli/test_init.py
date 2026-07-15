from __future__ import annotations

import json
import os
from pathlib import Path
from typing import NotRequired, TypedDict, cast

import pytest

from kaji.cli.init import (
    ScaffoldRollbackError,
    _directory_identity,
    _open_directory,
    _publish_force,
    init_project,
)
from kaji.cli.templates import agent_template, env_template


REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_CASES = REPO_ROOT / "kaji" / "contracts" / "cli" / "init-cases-v1.json"
CLI_CORPUS = json.loads(CLI_CASES.read_text())


class CliCase(TypedDict):
    name: str
    args: list[str]
    exitCode: int
    setup: NotRequired[str]
    typescriptOnly: NotRequired[bool]


PYTHON_CLI_CASES = [
    case
    for case in cast(list[CliCase], CLI_CORPUS["cases"])
    if not case.get("typescriptOnly", False)
]


def test_init_project_creates_files(tmp_path: Path) -> None:
    written = init_project(tmp_path, provider="openai")
    assert {p.name for p in written} == {"agent.py", ".env.example"}
    assert "OPENAI_API_KEY=\n" in (tmp_path / ".env.example").read_text()


def test_init_project_skips_existing(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text("# custom")
    written = init_project(tmp_path, provider="openai")
    assert written == []
    assert (tmp_path / "agent.py").read_text() == "# custom"
    assert not (tmp_path / ".env.example").exists()


def test_init_project_force_overwrites(tmp_path: Path) -> None:
    init_project(tmp_path, provider="openai")
    (tmp_path / "agent.py").write_text("# custom")
    init_project(tmp_path, provider="openai", force=True)
    assert (tmp_path / "agent.py").read_text() == agent_template("openai")
    assert not [path for path in tmp_path.iterdir() if ".kaji-" in path.name]


def test_init_project_force_rolls_back_partial_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = b"\x00original-agent\xff"
    (tmp_path / "agent.py").write_bytes(original)
    rename = os.rename
    failed = False

    def fail_second_publication(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal failed
        if (
            not failed
            and destination == ".env.example"
            and ".kaji-" in source
            and "kaji-backup" not in source
        ):
            failed = True
            raise OSError("injected publication failure")
        rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "rename", fail_second_publication)

    with pytest.raises(OSError, match="injected publication failure"):
        init_project(tmp_path, provider="mock", force=True)

    assert failed
    assert (tmp_path / "agent.py").read_bytes() == original
    assert not (tmp_path / ".env.example").exists()
    assert not [path for path in tmp_path.iterdir() if ".kaji-" in path.name]


def test_force_transaction_restores_removes_and_cleans_three_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = b"\x00original-existing\xff"
    destinations = [
        tmp_path / "existing.py",
        tmp_path / "new.py",
        tmp_path / "failure.py",
    ]
    destinations[0].write_bytes(original)
    sources = [tmp_path / f".source-{index}.kaji-test.tmp" for index in range(3)]
    for index, source in enumerate(sources):
        source.write_bytes(f"replacement-{index}".encode())

    rename = os.rename
    directory_fd = _open_directory(tmp_path)
    target_identity = _directory_identity(directory_fd)

    def fail_third_publication(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if source == sources[2].name and destination == destinations[2].name:
            raise OSError("injected third publication failure")
        rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "rename", fail_third_publication)

    try:
        with pytest.raises(OSError, match="injected third publication failure"):
            _publish_force(
                directory_fd,
                [source.name for source in sources],
                [destination.name for destination in destinations],
                target=tmp_path,
                target_identity=target_identity,
            )
    finally:
        os.close(directory_fd)

    assert destinations[0].read_bytes() == original
    assert not destinations[1].exists()
    assert not destinations[2].exists()
    assert not [path for path in tmp_path.iterdir() if ".kaji-" in path.name]


def test_force_transaction_preserves_backup_instead_of_clobbering_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = b"original-existing"
    destinations = [
        tmp_path / "existing.py",
        tmp_path / "new.py",
        tmp_path / "failure.py",
    ]
    destinations[0].write_bytes(original)
    sources = [tmp_path / f".race-source-{index}.kaji-test.tmp" for index in range(3)]
    for index, source in enumerate(sources):
        source.write_bytes(f"replacement-{index}".encode())
    raced = tmp_path / ".raced-in.kaji-test.tmp"
    raced.write_bytes(b"raced-in-replacement")
    rename = os.rename
    directory_fd = _open_directory(tmp_path)
    target_identity = _directory_identity(directory_fd)

    def race_before_third_failure(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        if source == sources[2].name and destination == destinations[2].name:
            rename(
                raced.name,
                destinations[0].name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            raise OSError("injected third publication failure")
        rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "rename", race_before_third_failure)

    try:
        with pytest.raises(ScaffoldRollbackError) as caught:
            _publish_force(
                directory_fd,
                [source.name for source in sources],
                [destination.name for destination in destinations],
                target=tmp_path,
                target_identity=target_identity,
            )
    finally:
        os.close(directory_fd)

    assert destinations[0].read_bytes() == b"raced-in-replacement"
    assert not destinations[1].exists()
    backups = list(tmp_path.glob(".existing.py.kaji-backup-*.tmp"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert caught.value.backup_names == (backups[0].name,)


def test_cli_reports_only_generated_backup_basename_after_rollback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import importlib

    from kaji.cli import main

    init_module = importlib.import_module("kaji.cli.init")
    backup_name = ".agent.py.kaji-backup-0123456789abcdef0123456789abcdef.tmp"
    secret = "/private/operator/customer-secret/original.py"

    def fail_init(*_args: object, **_kwargs: object) -> list[Path]:
        error = ScaffoldRollbackError({backup_name, secret})
        error.__cause__ = OSError(secret)
        raise error

    monkeypatch.setattr(init_module, "init_project", fail_init)

    assert main(["init", str(tmp_path / "sensitive-target"), "--force"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "kaji init failed while writing the scaffold; "
        f"original preserved in target directory as {backup_name}\n"
    )
    assert secret not in captured.err


@pytest.mark.parametrize("force", [False, True], ids=["nonforce", "force"])
def test_init_rejects_target_swapped_to_symlink_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    force: bool,
) -> None:
    target = tmp_path / "target"
    detached = tmp_path / "detached"
    victim = tmp_path / "victim"
    target.mkdir()
    victim.mkdir()
    if force:
        (target / "agent.py").write_text("original-agent")
    (victim / "agent.py").write_text("victim-agent")
    (victim / ".env.example").write_text("victim-env")
    open_directory = os.open
    swapped = False

    def swap_before_open(
        path: str | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and dir_fd is None and Path(path) == target:
            target.rename(detached)
            target.symlink_to(victim, target_is_directory=True)
            swapped = True
        return open_directory(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_before_open)

    with pytest.raises(OSError):
        init_project(target, force=force)

    assert swapped
    assert (victim / "agent.py").read_text() == "victim-agent"
    assert (victim / ".env.example").read_text() == "victim-env"
    assert not [path for path in detached.iterdir() if ".kaji-" in path.name]
    assert not (detached / ".env.example").exists()
    if force:
        assert (detached / "agent.py").read_text() == "original-agent"
    else:
        assert not list(detached.iterdir())


@pytest.mark.parametrize("force", [False, True], ids=["nonforce", "force"])
def test_init_rolls_back_target_swapped_to_symlink_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    force: bool,
) -> None:
    target = tmp_path / "target"
    detached = tmp_path / "detached"
    victim = tmp_path / "victim"
    target.mkdir()
    victim.mkdir()
    if force:
        (target / "agent.py").write_text("original-agent")
    (victim / "agent.py").write_text("victim-agent")
    (victim / ".env.example").write_text("victim-env")
    open_directory = os.open
    target_opens = 0

    def swap_before_revalidation(
        path: str | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal target_opens
        if dir_fd is None and Path(path) == target:
            target_opens += 1
            if target_opens == 2:
                target.rename(detached)
                target.symlink_to(victim, target_is_directory=True)
        return open_directory(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_before_revalidation)

    with pytest.raises(ValueError, match="target directory changed during write"):
        init_project(target, force=force)

    assert target_opens == 2
    assert target.is_symlink()
    assert (victim / "agent.py").read_text() == "victim-agent"
    assert (victim / ".env.example").read_text() == "victim-env"
    assert not [path for path in detached.iterdir() if ".kaji-" in path.name]
    assert not (detached / ".env.example").exists()
    if force:
        assert (detached / "agent.py").read_text() == "original-agent"
    else:
        assert not (detached / "agent.py").exists()


@pytest.mark.parametrize(
    "missing_capability",
    ["O_DIRECTORY", "O_NOFOLLOW", "dir_fd"],
)
def test_init_fails_closed_when_safe_directory_apis_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing_capability: str,
) -> None:
    from kaji.cli import main

    if missing_capability == "dir_fd":
        monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd - {os.open})
    else:
        monkeypatch.delattr(os, missing_capability)

    target = tmp_path / "unsupported"
    assert main(["init", str(target), "--yes"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "kaji init failed while writing the scaffold\n"
    assert target.is_dir()
    assert not list(target.iterdir())


def test_agent_template_is_valid_python() -> None:
    import ast

    ast.parse(agent_template("openai"))


def test_agent_template_uses_high_level_turn_api() -> None:
    source = agent_template("mock")
    assert "runtime.turn(" in source
    assert "runtime.run_turn(" not in source
    assert "store.append(" not in source
    assert 'kaji.get_provider("mock")' in source
    assert "result.turn_id" in source
    assert "event.sequence" in source


def test_env_template_mentions_provider() -> None:
    env = env_template("anthropic")
    assert "KAJI_MODEL_PROVIDER=anthropic" in env
    assert "ANTHROPIC_API_KEY" in env


def test_shared_cli_argument_corpus_is_canonical() -> None:
    corpus = CLI_CORPUS

    assert corpus["schemaVersion"] == 1
    assert corpus["grammar"] == (
        "kaji [--no-color] [--verbose] init [path] "
        "--provider mock|openai|anthropic --yes --force"
    )
    assert {case["name"] for case in corpus["cases"]} >= {
        "defaults",
        "explicit-path",
        "mock-provider",
        "openai-provider",
        "anthropic-provider",
        "yes",
        "force",
        "unknown-provider",
        "missing-provider-value",
        "existing-file-refusal",
    }


@pytest.mark.parametrize(
    "case",
    PYTHON_CLI_CASES,
    ids=[case["name"] for case in PYTHON_CLI_CASES],
)
def test_shared_cli_argument_corpus_executes_python(
    case: CliCase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from kaji.cli import main

    monkeypatch.chdir(tmp_path)
    if case.get("setup") == "existing-file":
        (tmp_path / "agent.py").write_text("keep-me")

    argv = ["init", *(str(argument) for argument in case["args"])]
    try:
        exit_code = main(argv)
    except SystemExit as error:
        assert isinstance(error.code, int)
        exit_code = error.code

    assert exit_code == case["exitCode"]
    captured = capsys.readouterr()
    target = tmp_path / "project" if case["name"] == "explicit-path" else tmp_path
    if exit_code == 0:
        provider = "mock"
        args = [str(argument) for argument in case["args"]]
        if "--provider" in args:
            provider = args[args.index("--provider") + 1]
        assert f'kaji.get_provider("{provider}")' in (target / "agent.py").read_text()
        if case["name"] == "force":
            assert (target / "agent.py").read_text() != "keep-me"
        summary = (
            Path("project", "agent.py")
            if case["name"] == "explicit-path"
            else Path("agent.py")
        )
        assert str(summary) in captured.out
        assert captured.err == ""
    else:
        assert captured.out == ""
        assert captured.err
        if case["name"] == "existing-file-refusal":
            assert (tmp_path / "agent.py").read_text() == "keep-me"
            assert not (tmp_path / ".env.example").exists()


@pytest.mark.parametrize("provider", ["mock", "openai", "anthropic"])
def test_init_project_supports_only_stable_provider_modes(
    tmp_path: Path, provider: str
) -> None:
    written = init_project(tmp_path / provider, provider=provider)
    assert {path.name for path in written} == {"agent.py", ".env.example"}


def test_init_project_defaults_to_no_key_mock(tmp_path: Path) -> None:
    written = init_project(tmp_path)
    assert {path.name for path in written} == {"agent.py", ".env.example"}
    assert 'kaji.get_provider("mock")' in (tmp_path / "agent.py").read_text()


def test_force_never_follows_a_generated_destination_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("keep-me")
    (tmp_path / "agent.py").symlink_to(outside)

    with pytest.raises(ValueError, match="unsafe scaffold destination"):
        init_project(tmp_path, force=True)

    assert outside.read_text() == "keep-me"
    assert not (tmp_path / ".env.example").exists()


def test_broken_symlink_counts_as_a_collision(tmp_path: Path) -> None:
    (tmp_path / "agent.py").symlink_to(tmp_path / "missing-target.py")

    with pytest.raises(ValueError, match="unsafe scaffold destination"):
        init_project(tmp_path)
    assert not (tmp_path / ".env.example").exists()
