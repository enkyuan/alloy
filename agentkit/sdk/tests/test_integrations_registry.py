"""Integration registry: manifest loading, listing, and install copies."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.integrations import (
    IntegrationNotFound,
    Manifest,
    ManifestError,
    install_integration,
    list_integrations,
    load_manifest,
)


def test_list_integrations_includes_github() -> None:
    names = list_integrations()
    assert "github" in names


def test_load_manifest_returns_parsed_manifest() -> None:
    m = load_manifest("github")
    assert isinstance(m, Manifest)
    assert m.name == "github"
    assert m.namespace == "github"
    assert m.auth.kind == "env"
    assert m.auth.env == "GITHUB_TOKEN"
    assert "github.py" in m.files
    tool_names = {t.name for t in m.tools}
    assert {"get_repo", "list_issues", "get_pull_request", "search_repos"} <= tool_names


def test_load_manifest_unknown_raises_integration_not_found() -> None:
    with pytest.raises(IntegrationNotFound):
        load_manifest("does-not-exist")


def test_install_integration_copies_files(tmp_path: Path) -> None:
    written = install_integration("github", tmp_path)
    assert any(p.name == "github.py" for p in written)
    target = tmp_path / "github.py"
    assert target.exists()
    # Sanity: the copied file is non-trivial and importable Python.
    source = target.read_text()
    assert "class GitHub" in source
    assert "agentkit.Integration" in source


def test_install_integration_refuses_overwrite_without_force(tmp_path: Path) -> None:
    install_integration("github", tmp_path)
    with pytest.raises(FileExistsError):
        install_integration("github", tmp_path)


def test_install_integration_overwrites_with_force(tmp_path: Path) -> None:
    install_integration("github", tmp_path)
    target = tmp_path / "github.py"
    target.write_text("# modified by user\n")
    install_integration("github", tmp_path, force=True)
    # Force re-copy restored the SDK content.
    assert "class GitHub" in target.read_text()


def test_manifest_validation_catches_missing_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Build a fake registry on disk with a bad manifest, point the loader
    at it, and assert ManifestError is raised."""
    import agentkit.integrations as ai

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
