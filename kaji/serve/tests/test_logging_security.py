"""Production logging must not disclose exception or transcript contents."""

from __future__ import annotations

import ast
from pathlib import Path


def _production_sources() -> list[Path]:
    source_root = Path(__file__).resolve().parents[1] / "src" / "kaji_serve"
    return sorted(source_root.rglob("*.py"))


def _logger_calls(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "logger"
        ):
            calls.append(node)
    return calls


def test_production_logging_has_no_raw_exceptions_or_tracebacks() -> None:
    for path in _production_sources():
        source = path.read_text()
        tree = ast.parse(source)
        exception_names = {
            handler.name
            for handler in ast.walk(tree)
            if isinstance(handler, ast.ExceptHandler) and handler.name is not None
        }

        assert "logger.exception" not in source, path
        assert "exc_info=True" not in source, path

        for call in _logger_calls(tree):
            for argument in call.args[1:]:
                assert not (
                    isinstance(argument, ast.Name) and argument.id in exception_names
                ), (path, ast.unparse(call))


def test_stt_logging_has_no_transcript_or_user_identifiers() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "kaji_serve"
    paths = (
        source_root / "modalities" / "voice" / "stt" / "handler.py",
        source_root / "modalities" / "voice" / "stt" / "soniox_gateway.py",
    )
    sensitive_names = {"complete_text", "final_text", "full_text", "user_id"}

    for path in paths:
        tree = ast.parse(path.read_text())
        for call in _logger_calls(tree):
            logged_names = {
                node.id for node in ast.walk(call) if isinstance(node, ast.Name)
            }
            assert sensitive_names.isdisjoint(logged_names), (path, ast.unparse(call))
