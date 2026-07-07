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
import subprocess
import sys
from tempfile import TemporaryDirectory


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    src = project / "src"
    ty = project / ".venv" / "bin" / "ty"
    ty_cmd = [str(ty)] if ty.exists() else ["ty"]

    with TemporaryDirectory(prefix="kaji-ty-") as tmp:
        shim_root = Path(tmp)
        os.symlink(src, shim_root / "kaji", target_is_directory=True)
        return subprocess.call(
            [
                *ty_cmd,
                "check",
                "--extra-search-path",
                str(shim_root),
                "src",
                "tests",
                *sys.argv[1:],
            ],
            cwd=project,
        )


if __name__ == "__main__":
    raise SystemExit(main())
