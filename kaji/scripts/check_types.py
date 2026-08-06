"""Run ty against the SDK's conventional ``src/kaji`` package layout."""

from __future__ import annotations

from pathlib import Path
import sys

from process_runner import LOCAL_COMMAND_BUDGET, CommandExitError, run_checked


def main() -> int:
    sdk_root = Path(__file__).resolve().parents[1] / "packages" / "python"
    ty_binary = sdk_root / ".venv" / "bin" / "ty"
    command = [str(ty_binary)] if ty_binary.exists() else ["ty"]

    try:
        run_checked(
            [*command, "check", "src", "tests", *sys.argv[1:]],
            cwd=sdk_root,
            budget=LOCAL_COMMAND_BUDGET,
        )
    except CommandExitError as error:
        return error.returncode if error.returncode >= 0 else 128 - error.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
