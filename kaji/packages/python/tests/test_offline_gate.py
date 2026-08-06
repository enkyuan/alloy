from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
from types import ModuleType
from types import SimpleNamespace
from typing import cast

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = REPO_ROOT / "kaji" / "scripts"
OFFLINE_GATE = SCRIPTS / "offline_gate.py"


def _load_offline_gate(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "test_offline_gate_module", OFFLINE_GATE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_environment_is_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "poison-openai")
    monkeypatch.setenv("GITHUB_TOKEN", "poison-github")
    monkeypatch.setenv("https_proxy", "http://poison.invalid")
    monkeypatch.setenv("NODE_OPTIONS", "--require=poison")
    module = _load_offline_gate(monkeypatch)

    environment = module.offline_environment(
        home=tmp_path / "home", temporary=tmp_path / "tmp"
    )

    assert environment == {
        "BUN_INSTALL_CACHE_DIR": str(tmp_path / "tmp" / "bun-cache"),
        "HOME": str(tmp_path / "home"),
        "KAJI_OFFLINE_GATE": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.pathsep.join(
            dict.fromkeys(
                [
                    str(Path(sys.executable).parent),
                    "/usr/local/bin",
                    "/opt/homebrew/bin",
                    "/usr/bin",
                    "/bin",
                    "/usr/sbin",
                    "/sbin",
                ]
            )
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "TEMP": str(tmp_path / "tmp"),
        "TMP": str(tmp_path / "tmp"),
        "TMPDIR": str(tmp_path / "tmp"),
        "TZ": "UTC",
        "UV_CACHE_DIR": str(tmp_path / "tmp" / "uv-cache"),
        "XDG_CACHE_HOME": str(tmp_path / "home" / ".cache"),
        "XDG_CONFIG_HOME": str(tmp_path / "home" / ".config"),
    }


@pytest.mark.parametrize("arguments", [[], ["pytest"], ["--"]])
def test_offline_gate_rejects_missing_delimiter_or_command(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    module = _load_offline_gate(monkeypatch)
    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("child process must not start")

    monkeypatch.setattr(module, "run_checked", fail_if_called)
    assert module.main(arguments) == 2
    assert called is False


def test_offline_gate_forwards_command_and_exit_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_offline_gate(monkeypatch)
    captured: dict[str, object] = {}

    def run_checked(command: list[str], **options: object) -> object:
        captured.update(command=command, **options)
        return SimpleNamespace(returncode=19)

    monkeypatch.setattr(module, "run_checked", run_checked)
    assert module.main(["--", sys.executable, "-m", "pytest"]) == 19
    executable = shutil.which(sys.executable)
    assert executable is not None
    assert captured["command"] == [str(Path(executable).absolute()), "-m", "pytest"]
    assert captured["cwd"] == Path.cwd()
    assert captured["check"] is False
    environment = cast(dict[str, str], captured["env"])
    assert environment["KAJI_OFFLINE_GATE"] == "1"


def test_offline_gate_rejects_an_unresolved_executable_before_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_offline_gate(monkeypatch)
    monkeypatch.setattr(module.shutil, "which", lambda _value: None)
    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("child process must not start")

    monkeypatch.setattr(module, "run_checked", fail_if_called)
    assert module.main(["--", "ci-installed-tool", "test"]) == 1
    assert called is False


def test_offline_gate_preserves_virtualenv_launcher_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_offline_gate(monkeypatch)
    launcher = "/tmp/kaji-venv/bin/python"
    captured: list[str] = []
    monkeypatch.setattr(module.shutil, "which", lambda _value, **_options: launcher)

    def run_checked(command: list[str], **_options: object) -> object:
        captured.extend(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module, "run_checked", run_checked)
    assert module.main(["--", "python", "-m", "pytest"]) == 0
    assert captured == [launcher, "-m", "pytest"]


def test_offline_gate_sanitizes_a_real_child_environment(tmp_path: Path) -> None:
    environment = dict(os.environ)
    environment.update(
        OPENAI_API_KEY="poison-openai",
        GITHUB_TOKEN="poison-github",
        HTTPS_PROXY="http://poison.invalid",
        NODE_OPTIONS="--require=poison",
    )
    probe = (
        "import os,sys;"
        "blocked=('OPENAI_API_KEY','GITHUB_TOKEN','HTTPS_PROXY','NODE_OPTIONS');"
        "sys.exit(0 if os.environ.get('KAJI_OFFLINE_GATE') == '1' "
        "and not any(name in os.environ for name in blocked) else 23)"
    )
    result = subprocess.run(
        [sys.executable, str(OFFLINE_GATE), "--", sys.executable, "-c", probe],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


def test_offline_gate_preserves_selected_nested_toolchain(tmp_path: Path) -> None:
    pinned_bin = tmp_path / "pinned-bin"
    pinned_bin.mkdir()
    pinned_bun = pinned_bin / "bun"
    pinned_bun.write_text("#!/bin/sh\nprintf '1.3.11\\n'\n")
    pinned_bun.chmod(0o755)
    environment = dict(os.environ)
    environment["PATH"] = os.pathsep.join(
        [str(pinned_bin), environment.get("PATH", "")]
    )
    environment.update(
        OPENAI_API_KEY="poison-openai",
        NPM_TOKEN="poison-npm",
        NODE_AUTH_TOKEN="poison-node",
        HTTP_PROXY="http://poison.invalid",
        HTTPS_PROXY="http://poison.invalid",
        ALL_PROXY="http://poison.invalid",
        http_proxy="http://poison.invalid",
        https_proxy="http://poison.invalid",
        all_proxy="http://poison.invalid",
    )
    probe = (
        "import os, subprocess, sys\n"
        "blocked = ('OPENAI_API_KEY', 'NPM_TOKEN', 'NODE_AUTH_TOKEN', "
        "'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', "
        "'https_proxy', 'all_proxy')\n"
        "if any(name in os.environ for name in blocked):\n"
        "    raise SystemExit(23)\n"
        "result = subprocess.run(['bun', '--version'], check=False, "
        "capture_output=True)\n"
        "sys.stdout.buffer.write(result.stdout)\n"
        "raise SystemExit(result.returncode)\n"
    )

    result = subprocess.run(
        [sys.executable, str(OFFLINE_GATE), "--", sys.executable, "-c", probe],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 0
    assert result.stdout == b"1.3.11\n"
    assert result.stderr == b""


@pytest.mark.skipif(os.name != "posix", reason="signal forwarding requires POSIX")
def test_offline_gate_forwards_child_signal(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(OFFLINE_GATE),
            "--",
            sys.executable,
            "-c",
            "import os,signal; os.kill(os.getpid(), signal.SIGTERM)",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == -signal.SIGTERM
    assert result.stdout == b""
    assert result.stderr == b""
