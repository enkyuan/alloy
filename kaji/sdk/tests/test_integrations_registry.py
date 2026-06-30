"""Integration registry: manifest loading, listing, and install copies."""

from __future__ import annotations

from pathlib import Path

import pytest

from kaji.integrations import (
    IntegrationNotFound,
    Manifest,
    ManifestError,
    install_integration,
    list_integrations,
    load_manifest,
)


def test_list_integrations_includes_known_names() -> None:
    names = list_integrations()
    assert "echo" in names
    assert {"github", "gmail", "gcal"}.isdisjoint(names)


def test_load_manifest_returns_parsed_manifest() -> None:
    m = load_manifest("echo")
    assert isinstance(m, Manifest)
    assert m.name == "echo"
    assert m.namespace == "echo"
    assert m.auth.kind == "none"
    assert {"echo.py", "echo.ts"} <= set(m.files)
    tool_names = {t.name for t in m.tools}
    assert tool_names == {"say", "shout"}


def test_load_manifest_unknown_raises_integration_not_found() -> None:
    with pytest.raises(IntegrationNotFound):
        load_manifest("does-not-exist")


def test_install_integration_copies_files(tmp_path: Path) -> None:
    written = install_integration("echo", tmp_path)
    assert {p.name for p in written} == {"echo.py", "echo.ts"}
    target = tmp_path / "echo.py"
    assert target.exists()
    # Sanity: the copied file is non-trivial and importable Python.
    source = target.read_text()
    assert "async def say" in source
    assert "kaji.function_tool" in source


def test_install_integration_refuses_overwrite_without_force(tmp_path: Path) -> None:
    install_integration("echo", tmp_path)
    with pytest.raises(FileExistsError):
        install_integration("echo", tmp_path)


def test_install_integration_overwrites_with_force(tmp_path: Path) -> None:
    install_integration("echo", tmp_path)
    target = tmp_path / "echo.py"
    target.write_text("# modified by user\n")
    install_integration("echo", tmp_path, force=True)
    # Force re-copy restored the SDK content.
    assert "async def say" in target.read_text()


def test_manifest_validation_catches_missing_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Build a fake registry on disk with a bad manifest, point the loader
    at it, and assert ManifestError is raised."""
    import kaji.integrations as ai

    bad_root = tmp_path / "registry"
    bad_root.mkdir()
    (bad_root / "index.json").write_text(
        '{"version": "0.1.0", "integrations": {"broken": "broken/manifest.json"}}'
    )
    (bad_root / "broken").mkdir()
    # Manifest missing `tools` entirely.
    (bad_root / "broken" / "manifest.json").write_text(
        '{"name": "broken", "version": "0.1.0", "namespace": "broken", '
        '"description": "x", "auth": {"kind": "none"}, "files": ["x.py"]}'
    )

    monkeypatch.setattr(ai, "_registry_root", lambda: bad_root)
    with pytest.raises(ManifestError, match="missing keys"):
        load_manifest("broken")


def test_install_integration_rejects_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest with '..' in files[] must not write outside dest."""
    import kaji.integrations as ai

    bad_root = tmp_path / "registry"
    bad_root.mkdir()
    (bad_root / "index.json").write_text(
        '{"version": "0.1.0", "integrations": {"evil": "evil/manifest.json"}}'
    )
    (bad_root / "evil").mkdir()
    (bad_root / "evil" / "manifest.json").write_text(
        '{"name": "evil", "version": "0.1.0", "namespace": "evil", '
        '"description": "x", "auth": {"kind": "none"}, '
        '"files": ["../../etc/foo.py"], '
        '"tools": [{"name": "x", "description": "x"}]}'
    )
    monkeypatch.setattr(ai, "_registry_root", lambda: bad_root)
    dest = tmp_path / "out"
    with pytest.raises(ManifestError, match="unsafe file path"):
        install_integration("evil", dest)


def test_install_integration_rejects_absolute_path_in_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest with an absolute path in files[] must be rejected."""
    import kaji.integrations as ai

    bad_root = tmp_path / "registry"
    bad_root.mkdir()
    (bad_root / "index.json").write_text(
        '{"version": "0.1.0", "integrations": {"evil-abs": "evil-abs/manifest.json"}}'
    )
    (bad_root / "evil-abs").mkdir()
    (bad_root / "evil-abs" / "manifest.json").write_text(
        '{"name": "evil-abs", "version": "0.1.0", "namespace": "evil-abs", '
        '"description": "x", "auth": {"kind": "none"}, '
        '"files": ["/etc/foo.py"], '
        '"tools": [{"name": "x", "description": "x"}]}'
    )
    monkeypatch.setattr(ai, "_registry_root", lambda: bad_root)
    dest = tmp_path / "out"
    with pytest.raises(ManifestError, match="unsafe file path"):
        install_integration("evil-abs", dest)
