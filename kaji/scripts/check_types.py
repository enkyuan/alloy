"""Run ty against the SDK's conventional ``src`` package layout."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile

from process_runner import LOCAL_COMMAND_BUDGET, CommandExitError, run_checked


def main() -> int:
    sdk_root = Path(__file__).resolve().parents[1] / "packages" / "py"
    ty_binary = sdk_root / ".venv" / "bin" / "ty"
    command = [str(ty_binary)] if ty_binary.exists() else ["ty"]

    try:
        with tempfile.TemporaryDirectory(prefix="kaji-ty-") as typecheck_root:
            alias = Path(typecheck_root) / "kaji"
            try:
                alias.symlink_to(sdk_root / "src", target_is_directory=True)
            except OSError:
                shutil.copytree(sdk_root / "src", alias)
            run_checked(
                [
                    *command,
                    "check",
                    "--extra-search-path",
                    typecheck_root,
                    "src",
                    "tests",
                    *sys.argv[1:],
                ],
                cwd=sdk_root,
                budget=LOCAL_COMMAND_BUDGET,
            )
    except CommandExitError as error:
        return error.returncode if error.returncode >= 0 else 128 - error.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
