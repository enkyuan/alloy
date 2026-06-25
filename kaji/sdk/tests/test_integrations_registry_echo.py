"""Tests for the echo integration's registry entry.

Echo is the cross-language proof: a trivial integration registered in the
shared on-disk registry with both a .py and a .ts source. These tests verify
the Python loader handles the manifest and installs both files.
"""

from __future__ import annotations

from pathlib import Path

from kaji.integrations import install_integration, load_manifest


def test_echo_manifest_loads():
    m = load_manifest("echo")
    assert m.name == "echo"
    assert m.namespace == "echo"
    assert m.auth.kind == "none"
    assert {"echo.py", "echo.ts"} <= set(m.files)
    assert {t.name for t in m.tools} == {"say", "shout"}


def test_echo_install_copies_both_files(tmp_path: Path):
    written = install_integration("echo", tmp_path)
    names = {p.name for p in written}
    assert {"echo.py", "echo.ts"} <= names
    assert (tmp_path / "echo.py").read_text().startswith('"""Echo integration')
