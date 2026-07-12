"""Tests for `kaji add` and `kaji list-integrations`."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from kaji.cli import main
from kaji.integrations import ManifestError


def test_add_echo_copies_files(tmp_path: Path) -> None:
    rc = main(["add", "echo", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "echo.py").exists()
    assert (tmp_path / "echo.ts").exists()


def test_add_unknown_integration_returns_nonzero(tmp_path: Path) -> None:
    out = StringIO()
    with patch("sys.stdout", out):
        rc = main(["add", "does-not-exist", "--out", str(tmp_path)])
    assert rc == 1
    assert "Unknown integration" in out.getvalue()


def test_add_refuses_overwrite_without_force(tmp_path: Path) -> None:
    rc1 = main(["add", "echo", "--out", str(tmp_path)])
    assert rc1 == 0
    out = StringIO()
    with patch("sys.stdout", out):
        rc2 = main(["add", "echo", "--out", str(tmp_path)])
    assert rc2 == 0
    assert "current: echo" in out.getvalue()


def test_add_force_never_overwrites_local_modifications(tmp_path: Path) -> None:
    main(["add", "echo", "--out", str(tmp_path)])
    target = tmp_path / "echo.py"
    target.write_text("# modified\n")
    rc = main(["add", "echo", "--out", str(tmp_path), "--force"])
    assert rc == 5
    assert target.read_text() == "# modified\n"


def test_list_integrations_prints_echo() -> None:
    out = StringIO()
    with patch("sys.stdout", out):
        rc = main(["list-integrations"])
    assert rc == 0
    assert "echo" in out.getvalue()
    assert "github" in out.getvalue()
    assert "experimental" in out.getvalue()


def test_list_integrations_json_emits_valid_object() -> None:
    out = StringIO()
    with patch("sys.stdout", out):
        rc = main(["list-integrations", "--json"])
    assert rc == 0
    parsed = json.loads(out.getvalue())
    names = {entry["name"] for entry in parsed}
    assert "echo" in names
    assert "github" in names
    assert {"gmail", "gcal"}.isdisjoint(names)
    echo = next(entry for entry in parsed if entry["name"] == "echo")
    assert echo["auth_kind"] == "none"
    assert "say" in echo["tools"]
    assert echo["stability"] == "beta"
    assert echo["runtimes"] == ["python", "typescript"]


def test_list_integrations_returns_nonzero_for_corrupt_registry() -> None:
    out = StringIO()
    with (
        patch(
            "kaji.cli.list_integrations._list",
            side_effect=ManifestError("invalid registry"),
        ),
        patch("sys.stdout", out),
    ):
        rc = main(["list-integrations"])

    assert rc == 1
    assert "Registry error" in out.getvalue()


def test_default_destination_is_provider_scoped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["add", "echo"]) == 0
    assert (tmp_path / "integrations/echo/echo.py").is_file()
    assert not (tmp_path / "integrations/echo.py").exists()


def test_github_requires_opt_in_then_copies_the_complete_owner_bundle(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "github"
    denied = StringIO()
    with patch("sys.stdout", denied):
        assert main(["add", "github", "--out", str(destination)]) == 1
    assert not destination.exists()
    assert "--allow-experimental" in denied.getvalue()

    output = StringIO()
    with patch("sys.stdout", output):
        assert (
            main(
                [
                    "add",
                    "github",
                    "--allow-experimental",
                    "--out",
                    str(destination),
                ]
            )
            == 0
        )
    assert {path.name for path in destination.iterdir()} == {
        "github.py",
        "client.py",
        "github.ts",
        "client.ts",
        "github_pytest.py",
        "github_vitest.ts",
        "owner-fixtures.json",
        "LICENSE",
        ".kaji-integration-provenance.json",
    }
    provenance = json.loads(
        (destination / ".kaji-integration-provenance.json").read_text()
    )
    assert provenance["integration"] == "github"
    assert provenance["runtime"] == "python"
    assert provenance["stability"] == "experimental"
    assert len(provenance["abiSha256"]) == 64
    assert "fine-grained token" in output.getvalue()


def test_check_json_has_the_closed_shape_and_all_copy_states(tmp_path: Path) -> None:
    destination = tmp_path / "echo"

    absent = StringIO()
    with patch("sys.stdout", absent):
        assert (
            main(["add", "echo", "--check", "--json", "--out", str(destination)]) == 3
        )
    absent_row = json.loads(absent.getvalue())
    assert list(absent_row) == [
        "state",
        "integration",
        "runtime",
        "destination",
        "reason_code",
        "next_command",
    ]
    assert absent_row["state"] == "absent"

    assert main(["add", "echo", "--out", str(destination)]) == 0
    current = StringIO()
    with patch("sys.stdout", current):
        assert (
            main(["add", "echo", "--check", "--json", "--out", str(destination)]) == 0
        )
    assert json.loads(current.getvalue())["reason_code"] == "up_to_date"

    (destination / "echo.py").write_text("# owner edit\n")
    modified = StringIO()
    with patch("sys.stdout", modified):
        assert (
            main(["add", "echo", "--force", "--json", "--out", str(destination)]) == 5
        )
    assert json.loads(modified.getvalue())["reason_code"] == "local_changes"
    assert (destination / "echo.py").read_text() == "# owner edit\n"


def test_check_classifies_outdated_runtime_and_cross_provider(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    assert main(["add", "echo", "--out", str(destination)]) == 0
    sidecar = destination / ".kaji-integration-provenance.json"
    provenance = json.loads(sidecar.read_text())
    provenance["sdkVersion"] = "0.0.0-old"
    sidecar.write_text(json.dumps(provenance))

    outdated = StringIO()
    with patch("sys.stdout", outdated):
        assert (
            main(["add", "echo", "--check", "--json", "--out", str(destination)]) == 4
        )
    assert json.loads(outdated.getvalue())["reason_code"] == "upstream_changed"
    assert main(["add", "echo", "--force", "--out", str(destination)]) == 0

    provenance = json.loads(sidecar.read_text())
    provenance["runtime"] = "typescript"
    sidecar.write_text(json.dumps(provenance))
    runtime = StringIO()
    with patch("sys.stdout", runtime):
        assert (
            main(["add", "echo", "--check", "--json", "--out", str(destination)]) == 5
        )
    assert json.loads(runtime.getvalue())["reason_code"] == "runtime_mismatch"

    other = tmp_path / "other"
    assert main(["add", "echo", "--out", str(other)]) == 0
    cross = StringIO()
    with patch("sys.stdout", cross):
        assert (
            main(
                [
                    "add",
                    "github",
                    "--check",
                    "--json",
                    "--out",
                    str(other),
                ]
            )
            == 5
        )
    assert json.loads(cross.getvalue())["reason_code"] == "cross_provider"


def test_outdated_swap_rolls_back_when_second_rename_fails(
    tmp_path: Path, monkeypatch
) -> None:
    from kaji.integrations import load_manifest
    from kaji.integrations.copy import install_integration_bundle

    destination = tmp_path / "echo"
    assert main(["add", "echo", "--out", str(destination)]) == 0
    sidecar = destination / ".kaji-integration-provenance.json"
    provenance = json.loads(sidecar.read_text())
    provenance["sdkVersion"] = "0.0.0-old"
    sidecar.write_text(json.dumps(provenance))
    before = {path.name: path.read_bytes() for path in destination.iterdir()}

    original = Path.rename

    def fail_stage(self: Path, target: Path) -> Path:
        if self.name.startswith(".echo.kaji-stage-"):
            raise OSError("publish failed")
        return original(self, target)

    monkeypatch.setattr(Path, "rename", fail_stage)
    with pytest.raises(OSError, match="publish failed"):
        install_integration_bundle(
            load_manifest("echo"), destination, runtime="python", force=True
        )

    assert {path.name: path.read_bytes() for path in destination.iterdir()} == before
    assert not list(tmp_path.glob(".echo.kaji-*"))


def test_staging_copy_failure_leaves_the_old_bundle_byte_identical(
    tmp_path: Path, monkeypatch
) -> None:
    from kaji.integrations import load_manifest
    from kaji.integrations.copy import install_integration_bundle
    import kaji.integrations.copy as copy_module

    destination = tmp_path / "echo"
    assert main(["add", "echo", "--out", str(destination)]) == 0
    sidecar = destination / ".kaji-integration-provenance.json"
    provenance = json.loads(sidecar.read_text())
    provenance["sdkVersion"] = "0.0.0-old"
    sidecar.write_text(json.dumps(provenance))
    before = {path.name: path.read_bytes() for path in destination.iterdir()}

    def fail_copy(*_args, **_kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(copy_module.shutil, "copy2", fail_copy)
    with pytest.raises(OSError, match="copy failed"):
        install_integration_bundle(
            load_manifest("echo"), destination, runtime="python", force=True
        )
    assert {path.name: path.read_bytes() for path in destination.iterdir()} == before
    assert not list(tmp_path.glob(".echo.kaji-*"))


def test_check_force_is_rejected_without_creating_destination(tmp_path: Path) -> None:
    destination = tmp_path / "echo"
    assert (
        main(
            [
                "add",
                "echo",
                "--check",
                "--force",
                "--out",
                str(destination),
            ]
        )
        == 2
    )
    assert not destination.exists()
