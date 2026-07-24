#!/usr/bin/env python3
"""Run one bounded command with credentials removed and offline guards enabled."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile

from process_runner import (
    CommandError,
    LOCAL_ORCHESTRATOR_BUDGET,
    run_checked,
)


USAGE = "usage: offline_gate.py -- <command> [argument ...]"
TOOLCHAIN_COMMANDS = ("bun", "node", "npm", "npx", "uv")


def _selected_toolchain_directories(path: str) -> tuple[str, ...]:
    selected = {
        os.path.normpath(str(Path(executable).absolute().parent))
        for command in TOOLCHAIN_COMMANDS
        if (executable := shutil.which(command, path=path)) is not None
    }
    ordered: list[str] = []
    for value in path.split(os.pathsep):
        directory = Path(value)
        if not value or not directory.is_absolute():
            continue
        normalized = os.path.normpath(str(directory))
        if normalized in selected and normalized not in ordered:
            ordered.append(normalized)
    return tuple(ordered)


def offline_environment(
    *,
    home: Path,
    temporary: Path,
    toolchain_directories: tuple[str, ...] = (),
) -> dict[str, str]:
    """Build a closed child environment without inheriting host configuration."""
    path = os.pathsep.join(
        dict.fromkeys(
            [
                *toolchain_directories,
                str(Path(sys.executable).parent),
                "/usr/local/bin",
                "/opt/homebrew/bin",
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            ]
        )
    )
    return {
        "BUN_INSTALL_CACHE_DIR": str(temporary / "bun-cache"),
        "HOME": str(home),
        "KAJI_OFFLINE_GATE": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": path,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "TEMP": str(temporary),
        "TMP": str(temporary),
        "TMPDIR": str(temporary),
        "TZ": "UTC",
        "UV_CACHE_DIR": str(temporary / "uv-cache"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }


def _forward_status(returncode: int) -> int:
    if returncode >= 0:
        return returncode
    signum = -returncode
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
    return 128 + signum


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if (
        not arguments
        or arguments[0] != "--"
        or len(arguments) == 1
        or any(not argument for argument in arguments[1:])
    ):
        print(USAGE, file=sys.stderr)
        return 2
    command = arguments[1:]
    executable = shutil.which(command[0])
    if executable is None:
        print("offline gate command could not be started", file=sys.stderr)
        return 1
    command[0] = str(Path(executable).absolute())
    toolchain_directories = _selected_toolchain_directories(os.environ.get("PATH", ""))
    with tempfile.TemporaryDirectory(prefix="kaji-offline-") as root_text:
        root = Path(root_text)
        home = root / "home"
        temporary = root / "tmp"
        home.mkdir()
        temporary.mkdir()
        environment = offline_environment(
            home=home,
            temporary=temporary,
            toolchain_directories=toolchain_directories,
        )
        try:
            result = run_checked(
                command,
                cwd=Path.cwd(),
                env=environment,
                budget=LOCAL_ORCHESTRATOR_BUDGET,
                check=False,
            )
        except CommandError as error:
            print(f"offline gate failed: {error}", file=sys.stderr)
            return 1
    return _forward_status(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
