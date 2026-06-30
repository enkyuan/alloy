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


def test_echo_py_template_sets_echo_namespace():
    """Both Python tools must declare namespace='echo' so they don't fall
    through to function_tool's default 'fn' namespace. That default would
    break the cross-language contract: the TS template registers under
    echo.say / echo.shout; the Python template must match."""
    from kaji.integrations.registry.echo import echo as echo_mod

    assert echo_mod.say.namespace == "echo"
    assert echo_mod.shout.namespace == "echo"
    assert echo_mod.say.spec.name == "say"
    assert echo_mod.shout.spec.name == "shout"


def test_echo_py_tools_register_without_collision(tmp_path: Path):
    """The two bound tools must both register cleanly into a fresh registry."""
    from kaji.integrations.registry.echo import echo as echo_mod
    from kaji.runtime.tools.registry import ToolRegistry

    registry = ToolRegistry()
    echo_mod.say.register(registry)
    echo_mod.shout.register(registry)
    specs = {s.name for s in registry.list_specs()}
    assert {"echo_say", "echo_shout"} <= specs or {"say", "shout"} <= specs


def test_every_registry_manifest_file_exists_on_disk():
    """Catch packaging drift: every file declared by a manifest must actually
    ship with the wheel. A manifest that lists a file outside the package-data
    globs would silently break install_integration on installed wheels.
    """
    from kaji.integrations import list_integrations, load_manifest

    for name in list_integrations():
        m = load_manifest(name)
        for rel in m.files:
            assert (m.root / rel).exists(), f"{name}: missing {rel}"
