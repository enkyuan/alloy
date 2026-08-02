"""Tests for `kaji add` and `kaji list-integrations`."""

from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest

from kaji.cli import main
from kaji.integrations import Manifest, ManifestAuth, ManifestError
from kaji.integrations.copy import BundleStatus


def test_add_echo_copies_files(tmp_path: Path) -> None:
    rc = main(["add", "echo", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "echo.py").exists()


def test_add_unknown_integration_returns_nonzero(tmp_path: Path) -> None:
    out = StringIO()
    err = StringIO()
    with patch("sys.stdout", out), patch("sys.stderr", err):
        rc = main(["add", "does-not-exist", "--out", str(tmp_path)])
    assert rc == 1
    assert out.getvalue() == ""
    assert "Unknown integration" in err.getvalue()
    assert "usage:" not in err.getvalue()


@pytest.mark.parametrize(
    "arguments",
    (["add"], ["add", "echo", "--out"], ["add", "echo", "--unknown"]),
)
def test_add_malformed_usage_exits_two_on_stderr_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    out = StringIO()
    err = StringIO()
    with (
        patch("sys.stdout", out),
        patch("sys.stderr", err),
        pytest.raises(SystemExit) as raised,
    ):
        main(arguments)
    assert raised.value.code == 2
    assert out.getvalue() == ""
    assert "usage:" in err.getvalue()
    assert not (tmp_path / "integrations").exists()


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
    assert "beta" in out.getvalue()


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
    assert list(echo) == [
        "name",
        "version",
        "stability",
        "runtimes",
        "auth",
        "experimental_opt_in_required",
        "next_commands",
    ]
    assert echo == {
        "name": "echo",
        "version": "0.1.0",
        "stability": "beta",
        "runtimes": ["python", "typescript"],
        "auth": {"kind": "none", "provider": None},
        "experimental_opt_in_required": False,
        "next_commands": {
            "python": "python -m kaji.cli add echo",
            "typescript": "bun --no-install -e 'import(\"kaji-sdk/cli\")' -- add echo",
        },
    }


def test_list_integrations_human_uses_the_closed_cross_runtime_projection() -> None:
    out = StringIO()
    with patch("sys.stdout", out):
        assert main(["list-integrations"]) == 0
    lines = out.getvalue().splitlines()
    assert lines[0] == "echo  [beta]  v0.1.0  auth=none  runtimes=python,typescript"
    assert lines[1] == "  python: python -m kaji.cli add echo"
    assert (
        lines[2]
        == "  typescript: bun --no-install -e 'import(\"kaji-sdk/cli\")' -- add echo"
    )


def test_list_integrations_sorts_rows_by_code_point_like_typescript(
    tmp_path: Path,
) -> None:
    def manifest(name: str) -> Manifest:
        return Manifest(
            name=name,
            version="0.1.0",
            namespace=name.replace("-", "_"),
            description=f"{name} fixture.",
            auth=ManifestAuth(kind="none"),
            files=("fixture.py",),
            tools=(),
            extras=(),
            peer_deps=MappingProxyType({}),
            stability="beta",
            runtimes=("python",),
            path=tmp_path / name / "manifest.json",
        )

    output = StringIO()
    with (
        patch(
            "kaji.cli.list_integrations._list",
            return_value=["aa", "a_", "a0", "a-b"],
        ),
        patch(
            "kaji.cli.list_integrations.load_manifest",
            side_effect=lambda name: manifest(name),
        ),
        patch("sys.stdout", output),
    ):
        assert main(["list-integrations", "--json"]) == 0

    assert [row["name"] for row in json.loads(output.getvalue())] == [
        "a-b",
        "a0",
        "a_",
        "aa",
    ]


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


def test_github_copies_the_python_owner_bundle(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "github"
    output = StringIO()
    with patch("sys.stdout", output):
        assert (
            main(
                [
                    "add",
                    "github",
                    "--out",
                    str(destination),
                ]
            )
            == 0
        )
    assert {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    } == {
        "github.py",
        "client.py",
        "tests/test_github.py",
        "owner-fixtures.json",
        "LICENSE",
        ".kaji-integration-provenance.json",
    }
    provenance = json.loads(
        (destination / ".kaji-integration-provenance.json").read_text()
    )
    assert provenance["integration"] == "github"
    assert provenance["runtime"] == "python"
    assert provenance["stability"] == "beta"
    assert len(provenance["abiSha256"]) == 64
    assert "fine-grained token" in output.getvalue()


def test_oauth_guidance_is_exact_and_only_after_successful_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kaji.cli import add

    manifest = Manifest(
        name="gmail",
        version="0.1.0",
        namespace="gmail",
        description="Gmail fixture.",
        auth=ManifestAuth(
            kind="oauth",
            provider="google",
            client_id_env="GOOGLE_CLIENT_ID",
            client_secret_env="GOOGLE_CLIENT_SECRET",
            scopes=("scope.a", "scope.b"),
            docs="https://example.test/oauth",
        ),
        files=("gmail.py",),
        tools=(),
        extras=("oauth-keyring",),
        peer_deps=MappingProxyType({}),
        stability="experimental",
        runtimes=("python", "typescript"),
        path=tmp_path / "manifest.json",
    )
    monkeypatch.setattr(add, "load_manifest", lambda _name: manifest)
    written = BundleStatus(
        "current", "installed", tmp_path, (tmp_path / "gmail.py",), "observed"
    )
    monkeypatch.setattr(
        add, "install_integration_bundle", lambda *_args, **_kwargs: written
    )
    args = argparse.Namespace(
        name="gmail",
        out=str(tmp_path),
        check=False,
        force=False,
        allow_experimental=True,
        json=False,
    )
    output = StringIO()
    with patch("sys.stdout", output):
        assert add.run(args) == 0
    rendered = output.getvalue()
    for expected in (
        "client ID env: GOOGLE_CLIENT_ID",
        "client secret env: GOOGLE_CLIENT_SECRET",
        "scopes: scope.a, scope.b",
        "docs: https://example.test/oauth",
        "python -m kaji.cli connect gmail --principal <stable-host-principal-id>",
        "bun --no-install -e 'import(\"kaji-sdk/cli\")' -- connect gmail --principal <stable-host-principal-id>",
    ):
        assert expected in rendered
    assert "oauth-keyring" not in rendered

    monkeypatch.setattr(
        add,
        "install_integration_bundle",
        lambda *_args, **_kwargs: BundleStatus(
            "current", "up_to_date", tmp_path, (), "observed"
        ),
    )
    output = StringIO()
    with patch("sys.stdout", output):
        assert add.run(args) == 0
    assert "connect gmail" not in output.getvalue()


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


def test_install_rejects_final_destination_symlink_without_victim_writes(
    tmp_path: Path,
) -> None:
    from kaji.integrations import load_manifest
    from kaji.integrations.copy import install_integration_bundle

    victim = tmp_path / "victim"
    victim.mkdir()
    destination = tmp_path / "echo"
    destination.symlink_to(victim, target_is_directory=True)

    with pytest.raises(FileExistsError, match="unsafe_destination"):
        install_integration_bundle(load_manifest("echo"), destination, runtime="python")

    assert list(victim.iterdir()) == []
    assert destination.is_symlink()


def test_install_rejects_nested_ancestor_symlink_without_victim_writes(
    tmp_path: Path,
) -> None:
    from kaji.integrations import load_manifest
    from kaji.integrations.copy import install_integration_bundle

    victim = tmp_path / "victim"
    victim.mkdir()
    ancestor = tmp_path / "linked-parent"
    ancestor.symlink_to(victim, target_is_directory=True)
    destination = ancestor / "nested" / "echo"

    with pytest.raises(FileExistsError, match="unsafe_destination"):
        install_integration_bundle(load_manifest("echo"), destination, runtime="python")

    assert list(victim.iterdir()) == []
    assert ancestor.is_symlink()


def test_outdated_swap_restores_edit_made_between_recheck_and_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kaji.integrations import load_manifest
    from kaji.integrations.copy import install_integration_bundle

    destination = tmp_path / "echo"
    assert main(["add", "echo", "--out", str(destination)]) == 0
    sidecar = destination / ".kaji-integration-provenance.json"
    provenance = json.loads(sidecar.read_text())
    provenance["sdkVersion"] = "0.0.0-old"
    sidecar.write_text(json.dumps(provenance))
    concurrent = b"# concurrent owner edit\n"
    original = Path.rename

    def edit_then_rename(self: Path, target: Path) -> Path:
        if self == destination:
            (destination / "echo.py").write_bytes(concurrent)
        return original(self, target)

    monkeypatch.setattr(Path, "rename", edit_then_rename)
    with pytest.raises(ManifestError, match="Destination changed"):
        install_integration_bundle(
            load_manifest("echo"), destination, runtime="python", force=True
        )

    assert (destination / "echo.py").read_bytes() == concurrent
    assert not list(tmp_path.glob(".echo.kaji-*"))


def test_absent_publish_never_deletes_new_destination(
    tmp_path: Path,
) -> None:
    from kaji.integrations import load_manifest
    from kaji.integrations.copy import install_integration_bundle

    destination = tmp_path / "echo"
    concurrent = b"concurrent owner bytes\n"

    def replace_after_check(path: Path) -> None:
        path.rmdir()
        path.mkdir()
        (path / "owner.txt").write_bytes(concurrent)

    with pytest.raises(ManifestError, match="Destination changed"):
        install_integration_bundle(
            load_manifest("echo"),
            destination,
            runtime="python",
            _after_reservation_check=replace_after_check,
        )

    assert (destination / "owner.txt").read_bytes() == concurrent


@pytest.mark.parametrize("nonempty", [False, True])
def test_absent_reservation_rejects_concurrent_destination_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nonempty: bool
) -> None:
    from kaji.integrations import load_manifest
    from kaji.integrations.copy import install_integration_bundle

    destination = tmp_path / "echo"
    concurrent = b"concurrent owner bytes\n"
    original = Path.mkdir
    injected = False

    def create_before_reservation(self: Path, *args, **kwargs) -> None:
        nonlocal injected
        if self == destination and not injected:
            injected = True
            original(self)
            if nonempty:
                (self / "owner.txt").write_bytes(concurrent)
        original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", create_before_reservation)
    with pytest.raises(ManifestError, match="Destination changed"):
        install_integration_bundle(load_manifest("echo"), destination, runtime="python")

    assert destination.is_dir()
    if nonempty:
        assert (destination / "owner.txt").read_bytes() == concurrent
    else:
        assert list(destination.iterdir()) == []


@pytest.mark.parametrize("mode", ["mutate", "replace"])
def test_absent_reservation_preserves_mutation_or_replacement_before_publish(
    tmp_path: Path, mode: str
) -> None:
    from kaji.integrations import load_manifest
    from kaji.integrations.copy import install_integration_bundle

    destination = tmp_path / "echo"
    concurrent = b"concurrent owner bytes\n"
    replacement_identity: list[tuple[int, int]] = []

    def race(path: Path) -> None:
        if mode == "mutate":
            (path / "owner.txt").write_bytes(concurrent)
        else:
            path.rmdir()
            path.mkdir()
            metadata = path.lstat()
            replacement_identity.append((metadata.st_dev, metadata.st_ino))

    with pytest.raises(ManifestError, match="Destination changed"):
        install_integration_bundle(
            load_manifest("echo"),
            destination,
            runtime="python",
            _before_reservation_publish=race,
        )

    assert destination.is_dir()
    if mode == "mutate":
        assert (destination / "owner.txt").read_bytes() == concurrent
    else:
        metadata = destination.lstat()
        assert (metadata.st_dev, metadata.st_ino) == replacement_identity[0]
        assert list(destination.iterdir()) == []


def test_absent_postcheck_empty_replacement_receives_no_publication_writes(
    tmp_path: Path,
) -> None:
    from kaji.integrations import load_manifest
    from kaji.integrations.copy import install_integration_bundle

    destination = tmp_path / "echo"
    replacement_identity: list[tuple[int, int]] = []

    def replace_after_check(path: Path) -> None:
        path.rmdir()
        path.mkdir()
        metadata = path.lstat()
        replacement_identity.append((metadata.st_dev, metadata.st_ino))

    with pytest.raises(ManifestError, match="Destination changed"):
        install_integration_bundle(
            load_manifest("echo"),
            destination,
            runtime="python",
            _after_reservation_check=replace_after_check,
        )

    metadata = destination.lstat()
    assert (metadata.st_dev, metadata.st_ino) == replacement_identity[0]
    assert list(destination.iterdir()) == []


def test_absent_cleanup_never_removes_postcheck_empty_replacement(
    tmp_path: Path,
) -> None:
    from kaji.integrations import load_manifest
    from kaji.integrations.copy import install_integration_bundle

    destination = tmp_path / "echo"
    replacement_identity: list[tuple[int, int]] = []

    def stop_after_check(_path: Path) -> None:
        raise RuntimeError("stop before publication")

    def replace_before_cleanup(path: Path) -> None:
        path.rmdir()
        path.mkdir()
        metadata = path.lstat()
        replacement_identity.append((metadata.st_dev, metadata.st_ino))

    with pytest.raises(RuntimeError, match="stop before publication"):
        install_integration_bundle(
            load_manifest("echo"),
            destination,
            runtime="python",
            _after_reservation_check=stop_after_check,
            _before_reservation_cleanup=replace_before_cleanup,
        )

    metadata = destination.lstat()
    assert (metadata.st_dev, metadata.st_ino) == replacement_identity[0]
    assert list(destination.iterdir()) == []


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
    out = StringIO()
    err = StringIO()
    with patch("sys.stdout", out), patch("sys.stderr", err):
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
    assert out.getvalue() == ""
    assert "--check cannot be combined with --force" in err.getvalue()
    assert "usage:" in err.getvalue()
    assert not destination.exists()
