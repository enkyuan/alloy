from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[1]
SCRIPT_DIRS = (REPO_ROOT / "kaji" / "scripts", SDK_ROOT / "scripts")
TYPESCRIPT_SCRIPTS = REPO_ROOT / "kaji" / "ts" / "scripts"
SNAKE_CASE_PYTHON = re.compile(r"[a-z][a-z0-9_]*\.py")
SDK_PRIVATE_ADAPTERS = {"_repo_process.py"}


def test_kaji_scripts_are_snake_case_python() -> None:
    for directory in SCRIPT_DIRS:
        scripts = sorted(path for path in directory.iterdir() if path.is_file())
        assert scripts, f"no scripts found under {directory}"

        for script in scripts:
            assert SNAKE_CASE_PYTHON.fullmatch(script.name) or (
                directory == SDK_ROOT / "scripts"
                and script.name in SDK_PRIVATE_ADAPTERS
            ), script
            tree = ast.parse(script.read_text(), filename=str(script))
            shell_keywords = [
                keyword
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                for keyword in node.keywords
                if keyword.arg == "shell"
            ]
            assert not shell_keywords, f"shell subprocess in {script}"


def test_release_process_ownership_is_centralized() -> None:
    root_owner = REPO_ROOT / "kaji" / "scripts" / "process_runner.py"
    sdk_adapter = SDK_ROOT / "scripts" / "_repo_process.py"
    for directory in SCRIPT_DIRS:
        for script in sorted(directory.glob("*.py")):
            if script == root_owner:
                continue
            tree = ast.parse(script.read_text(), filename=str(script))
            imports_subprocess = any(
                isinstance(node, (ast.Import, ast.ImportFrom))
                and (
                    (
                        isinstance(node, ast.Import)
                        and any(alias.name == "subprocess" for alias in node.names)
                    )
                    or (
                        isinstance(node, ast.ImportFrom) and node.module == "subprocess"
                    )
                )
                for node in ast.walk(tree)
            )
            assert not imports_subprocess, (
                f"direct process owner outside {root_owner}: {script}"
            )

    adapter = sdk_adapter.read_text()
    assert "process_runner" in adapter
    assert "subprocess" not in adapter

    spec = importlib.util.spec_from_file_location(
        "test_repo_process_adapter", sdk_adapter
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.run_checked.__module__ == "process_runner"
    assert module.CommandBudget.__module__ == "process_runner"

    typescript_owner = TYPESCRIPT_SCRIPTS / "command.ts"
    for script in sorted(TYPESCRIPT_SCRIPTS.iterdir()):
        if script == typescript_owner or script.suffix not in {".ts", ".mts"}:
            continue
        source = script.read_text()
        assert "node:child_process" not in source, script
        assert "execFileSync" not in source, script
