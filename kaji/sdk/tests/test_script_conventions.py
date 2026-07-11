from __future__ import annotations

import ast
import re
from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[1]
SCRIPT_DIRS = (REPO_ROOT / "kaji" / "scripts", SDK_ROOT / "scripts")
SNAKE_CASE_PYTHON = re.compile(r"[a-z][a-z0-9_]*\.py")


def test_kaji_scripts_are_snake_case_python() -> None:
    for directory in SCRIPT_DIRS:
        scripts = sorted(path for path in directory.iterdir() if path.is_file())
        assert scripts, f"no scripts found under {directory}"

        for script in scripts:
            assert SNAKE_CASE_PYTHON.fullmatch(script.name), script
            tree = ast.parse(script.read_text(), filename=str(script))
            shell_keywords = [
                keyword
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                for keyword in node.keywords
                if keyword.arg == "shell"
            ]
            assert not shell_keywords, f"shell subprocess in {script}"
