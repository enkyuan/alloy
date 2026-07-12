"""Run ty against the SDK's current editable package layout.

The Python SDK intentionally maps ``src/`` to the installed ``kaji`` package
root via setuptools/editables. Runtime imports work through the generated PEP
660 finder, but ty does not resolve that finder as a package root. This wrapper
creates a temporary static-analysis-only shim:

    <tmp>/kaji -> <repo>/src

Then it runs ty with that shim as an extra search path. The shim is not written
to the repo and does not change runtime packaging.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from _repo_process import LOCAL_COMMAND_BUDGET, CommandExitError, run_checked


def main() -> int:
    sdk_root = Path(__file__).resolve().parents[1]
    source_root = sdk_root / "src"
    ty_binary = sdk_root / ".venv" / "bin" / "ty"
    command = [str(ty_binary)] if ty_binary.exists() else ["ty"]

    with TemporaryDirectory(prefix="kaji-ty-") as tmp:
        shim_root = Path(tmp)
        os.symlink(source_root, shim_root / "kaji", target_is_directory=True)
        try:
            run_checked(
                [
                    *command,
                    "check",
                    "--extra-search-path",
                    str(shim_root),
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
