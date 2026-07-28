from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
from io import BytesIO
import inspect
import json
import os
from pathlib import Path
import stat
import struct
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
import zipfile

import pytest
from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "kaji" / "scripts"
VALIDATOR = SCRIPTS / "validate_typescript_onboarding_evidence.py"
SCHEMA = (
    REPO_ROOT
    / "kaji"
    / "contracts"
    / "release"
    / "typescript-onboarding-evidence-v1.schema.json"
)
COMMIT = "a" * 40
WORKFLOW_RUN = "https://github.com/enkyuan/alloy/actions/runs/123"
WORKFLOW_REF = "enkyuan/alloy/.github/workflows/kaji.rehearsal.yml@refs/heads/main"
TARBALL = "kaji-sdk-0.2.0-beta.9.tgz"


def _load(path: Path, name: str) -> ModuleType:
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _module() -> ModuleType:
    return _load(VALIDATOR, "test_validate_typescript_onboarding_evidence")


def _support() -> ModuleType:
    return _load(
        Path(__file__).with_name("test_compatibility_receipts.py"),
        "typescript_onboarding_compatibility_support",
    )


def _sha_bytes(encoded: bytes) -> str:
    return hashlib.sha256(encoded).hexdigest()


def _zip_bytes(
    members: dict[str, bytes],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    extras: dict[str, bytes] | None = None,
    modes: dict[str, int] | None = None,
    comment: bytes = b"",
) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=compression,
        allowZip64=False,
    ) as archive:
        for name, encoded in members.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = compression
            if extras and name in extras:
                info.extra = extras[name]
            if modes and name in modes:
                info.create_system = 3
                info.external_attr = modes[name] << 16
            archive.writestr(info, encoded)
        archive.comment = comment
    return output.getvalue()


def _release_members(module: ModuleType) -> dict[str, bytes]:
    payloads = {
        "kaji_sdk-0.2.0b1-py3-none-any.whl": b"retained-wheel",
        "kaji_sdk-0.2.0b1.tar.gz": b"retained-sdist",
        TARBALL: b"retained-typescript-tarball",
    }
    entries = []
    for name, encoded in payloads.items():
        package, version = module.release_verification.EXPECTED_ARTIFACTS[name]
        entries.append(
            {
                "commit": COMMIT,
                "contractVersion": "1.0.0",
                "file": name,
                "package": package,
                "sha256": _sha_bytes(encoded),
                "size": len(encoded),
                "version": version,
            }
        )
    audit = REPO_ROOT / "kaji" / "build-requirements.txt"
    manifest = {
        "schemaVersion": 1,
        "commit": COMMIT,
        "packages": dict(module.release_verification.EXPECTED_PACKAGES),
        "buildTools": {
            "bun": "1.3.11",
            "editables": "0.6",
            "node": "24.7.0",
            "npm": "11.5.1",
            "setuptools": "83.0.0",
            "uv": "0.11.25",
        },
        "buildAudit": {
            "file": "kaji/build-requirements.txt",
            "sha256": hashlib.sha256(audit.read_bytes()).hexdigest(),
        },
        "artifacts": entries,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    checksums = "\n".join(
        f"{_sha_bytes(payloads[name])}  {name}" for name in payloads
    ).encode()
    return {
        **payloads,
        "manifest.json": manifest_bytes,
        "SHA256SUMS": checksums,
    }


def _archive(
    module: ModuleType,
    *,
    name: str,
    artifact_id: int,
    archive_bytes: bytes,
) -> Any:
    return module.AuthenticatedArtifactArchive(
        name=name,
        artifact_id=artifact_id,
        digest="sha256:" + _sha_bytes(archive_bytes),
        run_id=123,
        run_attempt=1,
        head_sha=COMMIT,
        expired=False,
        archive_bytes=archive_bytes,
    )


def _fixture(tmp_path: Path) -> tuple[ModuleType, dict[str, Any], dict[str, Any]]:
    module = _module()
    support = _support()
    producer_members = _release_members(module)
    producer_bytes = _zip_bytes(producer_members)
    producer = _archive(
        module,
        name="kaji-beta-artifacts",
        artifact_id=456,
        archive_bytes=producer_bytes,
    )
    manifest_sha256 = _sha_bytes(producer_members["manifest.json"])
    tarball = producer_members[TARBALL]
    common = {
        "commit": COMMIT,
        "manifest_sha256": manifest_sha256,
        "tarball_sha256": _sha_bytes(tarball),
        "tarball_size": len(tarball),
        "workflow_run": WORKFLOW_RUN,
        "workflow_run_attempt": 1,
        "producer_artifact_id": 456,
        "producer_artifact_digest": producer.digest,
    }
    receipts = {
        22: support.node_v2_receipt(22, **common),
        24: support.node_v2_receipt(24, **common),
    }
    node_archives = {}
    archive_paths = {}
    producer_path = tmp_path / "producer.zip"
    producer_path.write_bytes(producer_bytes)
    archive_paths["producer"] = producer_path
    for major, artifact_id in ((22, 2201), (24, 2401)):
        receipt_bytes = json.dumps(receipts[major], sort_keys=True).encode()
        encoded = _zip_bytes({"compatibility-receipt.json": receipt_bytes})
        node_archives[major] = _archive(
            module,
            name=f"kaji-node-compat-{major}",
            artifact_id=artifact_id,
            archive_bytes=encoded,
        )
        path = tmp_path / f"node-{major}.zip"
        path.write_bytes(encoded)
        archive_paths[major] = path
    kwargs = {
        "producer_archive": producer,
        "node22_archive": node_archives[22],
        "node24_archive": node_archives[24],
        "expected_workflow_run": WORKFLOW_RUN,
        "expected_workflow_ref": WORKFLOW_REF,
        "expected_workflow_sha": COMMIT,
    }
    context = {
        "producer_members": producer_members,
        "receipts": receipts,
        "archive_paths": archive_paths,
        "support": support,
    }
    return module, kwargs, context


def _replace_node_receipt(
    module: ModuleType,
    archive: Any,
    receipt: dict[str, Any],
    *,
    formatting: str = "compact",
    extras: dict[str, bytes] | None = None,
) -> Any:
    if formatting == "pretty":
        encoded = json.dumps(receipt, indent=2).encode()
    else:
        encoded = json.dumps(receipt, sort_keys=True).encode()
    archive_bytes = _zip_bytes(
        {"compatibility-receipt.json": encoded},
        extras=extras,
    )
    return replace(
        archive,
        archive_bytes=archive_bytes,
        digest="sha256:" + _sha_bytes(archive_bytes),
    )


def _replace_path(
    document: dict[str, Any], path: tuple[Any, ...], value: Any
) -> dict[str, Any]:
    changed = deepcopy(document)
    cursor: Any = changed
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value
    return changed


def _object_paths(value: Any, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    paths: list[tuple[Any, ...]] = []
    if isinstance(value, dict):
        paths.append(path)
        for key, child in value.items():
            paths.extend(_object_paths(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_object_paths(child, (*path, index)))
    return paths


def _leaf_paths(value: Any, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    paths: list[tuple[Any, ...]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            paths.extend(_leaf_paths(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_leaf_paths(child, (*path, index)))
    else:
        paths.append(path)
    return paths


def _at(value: Any, path: tuple[Any, ...]) -> Any:
    cursor = value
    for part in path:
        cursor = cursor[part]
    return cursor


def _residuals(directory: Path, output: Path) -> list[Path]:
    return list(directory.glob(f".{output.name}.*"))


def test_composition_is_exact_deterministic_and_schema_valid(tmp_path: Path) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    first = module.compose_document(**kwargs)
    second = module.compose_document(**kwargs)

    assert first == second
    assert [cell["runtime"]["version"].split(".", 1)[0] for cell in first["cells"]] == [
        "v22",
        "v24",
    ]
    assert [cell["sourceArtifact"]["name"] for cell in first["cells"]] == [
        "kaji-node-compat-22",
        "kaji-node-compat-24",
    ]
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text()))
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(first)
    module.validate_document(first)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schemaVersion",), "2.0.0"),
        (("commit",), "b" * 40),
        (("packageArtifact", "size"), True),
        (("producerArtifact", "id"), 0),
        (("producerArtifact", "runAttempt"), 2),
        (("cells", 0, "sourceArtifact", "id"), 9_007_199_254_740_992),
        (("cells", 0, "runtime", "version"), "v24.14.0"),
        (("cells", 0, "runner", "configuredLabel"), "ubuntu-latest"),
        (("cells", 0, "runner", "platformArch"), "arm64"),
        (("cells", 0, "invocation", "workflowRun"), WORKFLOW_RUN + "0"),
        (("cells", 0, "invocation", "workflowRef"), "foreign/ref"),
        (("cells", 0, "toolchain", "node"), "v22.13.0"),
        (("cells", 0, "timings", "npm", "warmRunMs"), True),
        (("cells", 0, "onboardingProofs", "npm", "manager"), "bun"),
        (
            ("cells", 0, "onboardingProofs", "npm", "assertions", "echoLifecycle"),
            ["started", "requested", "completed"],
        ),
        (
            (
                "cells",
                0,
                "onboardingProofs",
                "npm",
                "assertions",
                "echoLifecycleCounts",
                "completed",
            ),
            2,
        ),
        (
            ("cells", 0, "onboardingProofs", "npm", "assertions", "echoResult"),
            {"message": "changed"},
        ),
        (("cells", 0, "conclusion"), "failed"),
    ],
)
def test_validate_document_rejects_retained_field_mutations(
    tmp_path: Path, path: tuple[Any, ...], value: Any
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    with pytest.raises(module.EvidenceError):
        module.validate_document(_replace_path(document, path, value))


@pytest.mark.parametrize(
    "path",
    [
        ("packageArtifact",),
        ("packageArtifact", "sha256"),
        ("producerArtifact", "digest"),
        ("cells", 0, "sourceArtifact", "receiptSha256"),
        ("cells", 0, "runner", "imageVersion"),
        ("cells", 0, "invocation", "job"),
        ("cells", 0, "runtime", "version"),
        ("cells", 0, "onboardingProofs", "npm", "phases", "echoRun"),
        (
            "cells",
            0,
            "onboardingProofs",
            "npm",
            "assertions",
            "echoToolCallIdNonempty",
        ),
        ("cells", 0, "timings", "bun", "coldSetupToOutputMs"),
        ("cells", 0, "toolchain", "typescript"),
    ],
)
def test_schema_is_recursively_closed_and_requires_nested_fields(
    tmp_path: Path, path: tuple[Any, ...]
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    missing = deepcopy(document)
    cursor: Any = missing
    for part in path[:-1]:
        cursor = cursor[part]
    cursor.pop(path[-1])
    with pytest.raises(module.EvidenceError):
        module.validate_document(missing)

    extra = deepcopy(document)
    cursor = extra
    for part in path[:-1]:
        cursor = cursor[part]
    if not isinstance(cursor, dict):
        cursor = extra
    cursor["unexpected"] = True
    with pytest.raises(module.EvidenceError):
        module.validate_document(extra)


def test_every_object_boundary_is_closed_and_required(tmp_path: Path) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    for path in _object_paths(document):
        target = _at(document, path)
        assert isinstance(target, dict) and target
        missing = deepcopy(document)
        _at(missing, path).pop(next(iter(target)))
        with pytest.raises(module.EvidenceError):
            module.validate_document(missing)
        extra = deepcopy(document)
        _at(extra, path)["unexpected"] = True
        with pytest.raises(module.EvidenceError):
            module.validate_document(extra)


def test_wrong_swapped_missing_or_third_cell_is_rejected(tmp_path: Path) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    variants = [
        {**deepcopy(document), "cells": list(reversed(document["cells"]))},
        {**deepcopy(document), "cells": document["cells"][:1]},
        {**deepcopy(document), "cells": document["cells"] + [document["cells"][1]]},
    ]
    for invalid in variants:
        with pytest.raises(module.EvidenceError):
            module.validate_document(invalid)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("producer_archive", "artifact_id", 457),
        ("producer_archive", "digest", "sha256:" + "e" * 64),
        ("producer_archive", "run_id", 124),
        ("producer_archive", "run_attempt", 2),
        ("producer_archive", "head_sha", "b" * 40),
        ("producer_archive", "expired", True),
        ("node22_archive", "name", "kaji-node-compat-24"),
        ("node22_archive", "artifact_id", 2401),
        ("node22_archive", "run_id", 124),
        ("node22_archive", "run_attempt", 2),
        ("node22_archive", "head_sha", "b" * 40),
        ("node22_archive", "expired", True),
    ],
)
def test_trusted_artifact_substitution_fails_closed(
    tmp_path: Path, target: str, field: str, value: Any
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    kwargs[target] = replace(kwargs[target], **{field: value})
    with pytest.raises(module.EvidenceError):
        module.compose_document(**kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_workflow_run", "https://github.com/enkyuan/alloy/actions/runs/124"),
        (
            "expected_workflow_ref",
            "enkyuan/alloy/.github/workflows/kaji.publish.yml@refs/tags/kaji-v0.2.0-beta.9",
        ),
        ("expected_workflow_sha", "b" * 40),
    ],
)
def test_trusted_workflow_substitution_fails_closed(
    tmp_path: Path, field: str, value: str
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    kwargs[field] = value
    with pytest.raises(module.EvidenceError):
        module.compose_document(**kwargs)


def test_archive_digest_and_member_substitution_fail_closed(tmp_path: Path) -> None:
    module, kwargs, context = _fixture(tmp_path)
    original = kwargs["node22_archive"]
    changed_bytes = original.archive_bytes + b"trailing"
    with pytest.raises(module.EvidenceError, match="digest"):
        module.compose_document(
            **{
                **kwargs,
                "node22_archive": replace(original, archive_bytes=changed_bytes),
            }
        )
    changed_digest = "sha256:" + _sha_bytes(changed_bytes)
    with pytest.raises(module.EvidenceError, match="ZIP"):
        module.compose_document(
            **{
                **kwargs,
                "node22_archive": replace(
                    original,
                    archive_bytes=changed_bytes,
                    digest=changed_digest,
                ),
            }
        )

    producer_members = dict(context["producer_members"])
    producer_members[TARBALL] = b"substituted"
    producer_bytes = _zip_bytes(producer_members)
    with pytest.raises(module.EvidenceError, match="release artifact set"):
        module.compose_document(
            **{
                **kwargs,
                "producer_archive": replace(
                    kwargs["producer_archive"],
                    archive_bytes=producer_bytes,
                    digest="sha256:" + _sha_bytes(producer_bytes),
                ),
            }
        )

    malformed_members = dict(context["producer_members"])
    malformed_manifest = json.loads(malformed_members["manifest.json"])
    malformed_manifest["artifacts"][0]["file"] = []
    malformed_members["manifest.json"] = json.dumps(
        malformed_manifest, sort_keys=True
    ).encode()
    malformed_bytes = _zip_bytes(malformed_members)
    with pytest.raises(module.EvidenceError, match="release artifact set"):
        module.compose_document(
            **{
                **kwargs,
                "producer_archive": replace(
                    kwargs["producer_archive"],
                    archive_bytes=malformed_bytes,
                    digest="sha256:" + _sha_bytes(malformed_bytes),
                ),
            }
        )


def test_raw_receipt_hash_binds_exact_authenticated_member_bytes(
    tmp_path: Path,
) -> None:
    module, kwargs, context = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    kwargs["node22_archive"] = _replace_node_receipt(
        module,
        kwargs["node22_archive"],
        context["receipts"][22],
        formatting="pretty",
    )
    recomputed = module.recompute_document(**kwargs)
    assert (
        recomputed["cells"][0]["sourceArtifact"]["receiptSha256"]
        != document["cells"][0]["sourceArtifact"]["receiptSha256"]
    )
    with pytest.raises(module.EvidenceError, match="recomputation differs"):
        module.recompute_and_compare(document, **kwargs)


def test_nonpassed_local_and_legacy_receipts_are_rejected(tmp_path: Path) -> None:
    module, kwargs, context = _fixture(tmp_path)
    valid = context["receipts"][22]
    not_run = {
        "schemaVersion": 2,
        "executionMode": "protected",
        "commit": None,
        "releaseManifestSha256": None,
        "artifactSha256": {},
        "runtime": {"version": None},
        "artifacts": {},
        "githubPackageProofs": {},
        "onboardingProofs": {},
        "conclusion": "not_run",
        "failureCode": "compatibility_not_completed",
        "failedPhase": None,
        "failureKind": "unknown",
    }
    substitutions = [
        {**valid, "executionMode": "local"},
        {
            **not_run,
            "conclusion": "failed",
            "failedPhase": "npm:package-install",
            "failureKind": "timeout",
        },
        not_run,
        context["support"].python_v1_receipt(),
    ]
    for receipt in substitutions:
        changed = _replace_node_receipt(module, kwargs["node22_archive"], receipt)
        with pytest.raises(module.EvidenceError):
            module.compose_document(**{**kwargs, "node22_archive": changed})


def test_raw_receipt_proofs_lifecycle_and_static_runner_are_revalidated(
    tmp_path: Path,
) -> None:
    module, kwargs, context = _fixture(tmp_path)
    valid = context["receipts"][22]
    mutations = []
    for mutate in (
        lambda value: value["githubPackageProofs"]["npm"].__setitem__(
            "unexpected", True
        ),
        lambda value: value["githubPackageProofs"].pop("bun"),
        lambda value: value["githubPackageProofs"]["bun"].__setitem__(
            "aliasCollisionRejected", False
        ),
        lambda value: value["onboardingProofs"]["npm"]["phases"].__setitem__(
            "echoRun", False
        ),
        lambda value: value["onboardingProofs"]["npm"]["assertions"].__setitem__(
            "echoLifecycle", ["started", "requested", "completed"]
        ),
        lambda value: value["runner"].__setitem__("configuredLabel", "ubuntu-latest"),
    ):
        changed = deepcopy(valid)
        mutate(changed)
        mutations.append(changed)
    for receipt in mutations:
        changed_archive = _replace_node_receipt(
            module, kwargs["node22_archive"], receipt
        )
        with pytest.raises(module.EvidenceError):
            module.compose_document(**{**kwargs, "node22_archive": changed_archive})


def test_image_version_is_observed_not_caller_trusted(tmp_path: Path) -> None:
    module, kwargs, context = _fixture(tmp_path)
    receipt = deepcopy(context["receipts"][22])
    receipt["runner"]["imageVersion"] = "observed.1"
    kwargs["node22_archive"] = _replace_node_receipt(
        module, kwargs["node22_archive"], receipt
    )
    document = module.compose_document(**kwargs)
    assert document["cells"][0]["runner"]["imageVersion"] == "observed.1"
    assert "TrustedRunner" not in vars(module)
    assert "node22_runner" not in inspect.signature(module.compose_document).parameters
    assert "--node22-image-version" not in VALIDATOR.read_text()


def test_recompute_compare_is_strict_for_every_retained_leaf(tmp_path: Path) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    for path in _leaf_paths(document):
        value = _at(document, path)
        if isinstance(value, bool):
            replacement = not value
        elif isinstance(value, int):
            replacement = value + 1
        elif isinstance(value, str):
            replacement = value + "x"
        elif value is None:
            replacement = "unexpected"
        else:
            raise AssertionError(f"unhandled aggregate leaf at {path}")
        with pytest.raises(module.EvidenceError):
            module.recompute_and_compare(
                _replace_path(document, path, replacement),
                **kwargs,
            )
    module.recompute_and_compare(document, **kwargs)


def test_stable_archive_loader_rejects_symlink_and_drift(tmp_path: Path) -> None:
    module, kwargs, context = _fixture(tmp_path)
    source = context["archive_paths"][22]
    symlink = tmp_path / "node-link.zip"
    symlink.symlink_to(source)
    with pytest.raises(module.EvidenceError):
        module.load_authenticated_archive(
            symlink,
            name="kaji-node-compat-22",
            artifact_id=2201,
            digest=kwargs["node22_archive"].digest,
            run_id=123,
            run_attempt=1,
            head_sha=COMMIT,
            expired=False,
        )
    source.write_bytes(source.read_bytes() + b"drift")
    with pytest.raises(module.EvidenceError):
        module.load_authenticated_archive(
            source,
            name="kaji-node-compat-22",
            artifact_id=2201,
            digest=kwargs["node22_archive"].digest,
            run_id=123,
            run_attempt=1,
            head_sha=COMMIT,
            expired=False,
        )


@pytest.mark.parametrize(
    "variant",
    [
        "duplicate",
        "unexpected",
        "traversal",
        "directory",
        "symlink",
        "encrypted",
        "unsupported",
        "comment",
        "prefix",
        "trailing",
        "zip64",
        "ratio",
        "nul_suffix",
        "local_method",
        "local_encrypted",
        "unreferenced_gap",
        "deflate_trailing",
    ],
)
def test_zip_abuse_is_rejected(tmp_path: Path, variant: str) -> None:
    module, kwargs, context = _fixture(tmp_path)
    receipt_bytes = json.dumps(context["receipts"][22], sort_keys=True).encode()
    if variant == "duplicate":
        output = BytesIO()
        with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
            archive.writestr("compatibility-receipt.json", receipt_bytes)
            with pytest.warns(UserWarning):
                archive.writestr("compatibility-receipt.json", receipt_bytes)
        encoded = output.getvalue()
    elif variant == "unexpected":
        encoded = _zip_bytes(
            {
                "compatibility-receipt.json": receipt_bytes,
                "unexpected": b"x",
            }
        )
    elif variant == "traversal":
        encoded = _zip_bytes({"../compatibility-receipt.json": receipt_bytes})
    elif variant == "directory":
        encoded = _zip_bytes(
            {"compatibility-receipt.json": receipt_bytes},
            modes={"compatibility-receipt.json": stat.S_IFDIR | 0o700},
        )
    elif variant == "symlink":
        encoded = _zip_bytes(
            {"compatibility-receipt.json": b"target"},
            modes={"compatibility-receipt.json": stat.S_IFLNK | 0o777},
        )
    elif variant == "unsupported":
        encoded = _zip_bytes(
            {"compatibility-receipt.json": receipt_bytes},
            compression=zipfile.ZIP_BZIP2,
        )
    elif variant == "comment":
        encoded = _zip_bytes(
            {"compatibility-receipt.json": receipt_bytes},
            comment=b"ambiguous",
        )
    elif variant in {"prefix", "trailing"}:
        base = _zip_bytes({"compatibility-receipt.json": receipt_bytes})
        encoded = (b"prefix" + base) if variant == "prefix" else (base + b"tail")
    elif variant == "zip64":
        changed = bytearray(_zip_bytes({"compatibility-receipt.json": receipt_bytes}))
        struct.pack_into("<H", changed, len(changed) - 12, 0xFFFF)
        struct.pack_into("<H", changed, len(changed) - 10, 0xFFFF)
        encoded = bytes(changed)
    elif variant == "ratio":
        encoded = _zip_bytes({"compatibility-receipt.json": b"0" * (1024 * 1024)})
    elif variant == "nul_suffix":
        changed = bytearray(
            _zip_bytes(
                {"compatibility-receipt.json": receipt_bytes},
                compression=zipfile.ZIP_STORED,
            )
        )
        local_name_length = struct.unpack_from("<H", changed, 26)[0]
        local_name_end = 30 + local_name_length
        changed[local_name_end:local_name_end] = b"\x00X"
        struct.pack_into("<H", changed, 26, local_name_length + 2)
        central = changed.index(b"PK\x01\x02")
        central_name_length = struct.unpack_from("<H", changed, central + 28)[0]
        central_name_end = central + 46 + central_name_length
        changed[central_name_end:central_name_end] = b"\x00X"
        struct.pack_into("<H", changed, central + 28, central_name_length + 2)
        eocd = changed.index(b"PK\x05\x06")
        central_size = struct.unpack_from("<L", changed, eocd + 12)[0]
        central_offset = struct.unpack_from("<L", changed, eocd + 16)[0]
        struct.pack_into("<L", changed, eocd + 12, central_size + 2)
        struct.pack_into("<L", changed, eocd + 16, central_offset + 2)
        encoded = bytes(changed)
    elif variant in {"local_method", "local_encrypted"}:
        changed = bytearray(_zip_bytes({"compatibility-receipt.json": receipt_bytes}))
        if variant == "local_method":
            struct.pack_into("<H", changed, 8, 99)
        else:
            local_flags = struct.unpack_from("<H", changed, 6)[0]
            struct.pack_into("<H", changed, 6, local_flags | 1)
        encoded = bytes(changed)
    elif variant == "unreferenced_gap":
        changed = bytearray(_zip_bytes({"compatibility-receipt.json": receipt_bytes}))
        central = changed.index(b"PK\x01\x02")
        gap = b"HIDDEN-UNREFERENCED-BYTES"
        changed[central:central] = gap
        eocd = changed.index(b"PK\x05\x06")
        central_offset = struct.unpack_from("<L", changed, eocd + 16)[0]
        struct.pack_into("<L", changed, eocd + 16, central_offset + len(gap))
        encoded = bytes(changed)
    elif variant == "deflate_trailing":
        changed = bytearray(_zip_bytes({"compatibility-receipt.json": receipt_bytes}))
        local_name_length, local_extra_length = struct.unpack_from("<HH", changed, 26)
        data_start = 30 + local_name_length + local_extra_length
        compressed_size = struct.unpack_from("<L", changed, 18)[0]
        hidden = b"HIDDEN-DEFLATE-TAIL"
        changed[data_start + compressed_size : data_start + compressed_size] = hidden
        struct.pack_into("<L", changed, 18, compressed_size + len(hidden))
        central = changed.index(b"PK\x01\x02")
        struct.pack_into("<L", changed, central + 20, compressed_size + len(hidden))
        eocd = changed.index(b"PK\x05\x06")
        central_offset = struct.unpack_from("<L", changed, eocd + 16)[0]
        struct.pack_into("<L", changed, eocd + 16, central_offset + len(hidden))
        encoded = bytes(changed)
    else:
        changed = bytearray(
            _zip_bytes(
                {"compatibility-receipt.json": receipt_bytes},
                compression=zipfile.ZIP_STORED,
            )
        )
        struct.pack_into("<H", changed, 6, struct.unpack_from("<H", changed, 6)[0] | 1)
        central = changed.index(b"PK\x01\x02")
        struct.pack_into(
            "<H",
            changed,
            central + 8,
            struct.unpack_from("<H", changed, central + 8)[0] | 1,
        )
        encoded = bytes(changed)
    changed_archive = replace(
        kwargs["node22_archive"],
        archive_bytes=encoded,
        digest="sha256:" + _sha_bytes(encoded),
    )
    with pytest.raises(module.EvidenceError):
        module.compose_document(**{**kwargs, "node22_archive": changed_archive})


def test_ordinary_zip_extra_field_is_accepted(tmp_path: Path) -> None:
    module, kwargs, context = _fixture(tmp_path)
    kwargs["node22_archive"] = _replace_node_receipt(
        module,
        kwargs["node22_archive"],
        context["receipts"][22],
        extras={"compatibility-receipt.json": b"\xfe\xca\x02\x00ok"},
    )
    module.compose_document(**kwargs)


def test_no_mutable_document_hash_pair_input_exists(tmp_path: Path) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    assert "LoadedNodeReceipt" not in vars(module)
    assert "load_node_receipt" not in vars(module)
    assert type(kwargs["node22_archive"].archive_bytes) is bytes
    forged = replace(
        kwargs["node22_archive"],
        digest="sha256:" + "f" * 64,
    )
    with pytest.raises(module.EvidenceError):
        module.compose_document(**{**kwargs, "node22_archive": forged})


def test_atomic_writer_is_owner_only_exact_and_preserves_pre_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    digest = module.write_json_atomic(output, document)
    encoded = json.dumps(document, indent=2, sort_keys=True).encode()
    assert output.read_bytes() == encoded
    assert not output.read_bytes().endswith(b"\n")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert digest == _sha_bytes(encoded)
    assert _residuals(tmp_path, output) == []

    previous = output.read_bytes()
    monkeypatch.setattr(
        module.os,
        "rename",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(module.EvidenceError):
        module.write_json_atomic(output, document)
    assert output.read_bytes() == previous
    assert _residuals(tmp_path, output) == []


def test_temp_initialization_cleanup_failure_is_terminally_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    real_unlink = module.os.unlink

    def fail_fchmod(_descriptor: int, _mode: int) -> None:
        raise OSError

    def fail_temp_unlink(name: str, *, dir_fd: int | None = None) -> None:
        if name.endswith(".tmp"):
            raise OSError
        real_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "fchmod", fail_fchmod)
    monkeypatch.setattr(module.os, "unlink", fail_temp_unlink)
    with pytest.raises(module.EvidenceCleanupAmbiguous):
        module.write_json_atomic(output, document)
    temporaries = list(tmp_path.glob(f".{output.name}.*.tmp"))
    assert not output.exists()
    assert len(temporaries) == 1
    assert stat.S_IMODE(temporaries[0].stat().st_mode) == 0o600


def test_recovery_initialization_cleanup_failure_is_terminally_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    output.write_bytes(b"old")
    real_unlink = module.os.unlink

    def fail_fchmod(_descriptor: int, _mode: int) -> None:
        raise OSError

    def fail_recovery_unlink(name: str, *, dir_fd: int | None = None) -> None:
        if name.endswith(".recovery"):
            raise OSError
        real_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "fchmod", fail_fchmod)
    monkeypatch.setattr(module.os, "unlink", fail_recovery_unlink)
    with pytest.raises(module.EvidenceCleanupAmbiguous):
        module.write_json_atomic(output, document)
    recoveries = list(tmp_path.glob(f".{output.name}.*.recovery"))
    assert output.read_bytes() == b"old"
    assert len(recoveries) == 1
    assert stat.S_IMODE(recoveries[0].stat().st_mode) == 0o600


def test_rollback_initialization_cleanup_failure_is_terminally_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    output.write_bytes(b"old")
    real_fchmod = module.os.fchmod
    real_fsync = module.os.fsync
    real_unlink = module.os.unlink
    directory_calls = 0
    fchmod_calls = 0

    def fail_post_replace_fsync(descriptor: int) -> None:
        nonlocal directory_calls
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_calls += 1
            if directory_calls == 2:
                raise OSError
        real_fsync(descriptor)

    def fail_rollback_fchmod(descriptor: int, mode: int) -> None:
        nonlocal fchmod_calls
        fchmod_calls += 1
        if fchmod_calls == 3:
            raise OSError
        real_fchmod(descriptor, mode)

    def fail_rollback_unlink(name: str, *, dir_fd: int | None = None) -> None:
        if name.endswith(".rollback"):
            raise OSError
        real_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "fchmod", fail_rollback_fchmod)
    monkeypatch.setattr(module.os, "fsync", fail_post_replace_fsync)
    monkeypatch.setattr(module.os, "unlink", fail_rollback_unlink)
    with pytest.raises(module.EvidenceCleanupAmbiguous) as raised:
        module.write_json_atomic(output, document)
    recoveries = list(tmp_path.glob(f".{output.name}.*.recovery"))
    rollbacks = list(tmp_path.glob(f".{output.name}.*.rollback"))
    assert raised.value.recovery_name is not None
    assert len(recoveries) == 1
    assert recoveries[0].name == raised.value.recovery_name
    assert recoveries[0].read_bytes() == b"old"
    assert stat.S_IMODE(recoveries[0].stat().st_mode) == 0o600
    assert len(rollbacks) == 1
    assert stat.S_IMODE(rollbacks[0].stat().st_mode) == 0o600


def test_atomic_writer_rolls_back_directory_fsync_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    output.write_bytes(b"previous-durable-evidence")
    real_fsync = module.os.fsync
    directory_calls = 0

    def fail_first_directory_fsync(descriptor: int) -> None:
        nonlocal directory_calls
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_calls += 1
            if directory_calls == 2:
                raise OSError
        real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_first_directory_fsync)
    with pytest.raises(module.EvidenceError) as raised:
        module.write_json_atomic(output, document)
    assert not isinstance(raised.value, module.EvidenceWriteAmbiguous)
    assert directory_calls >= 2
    assert output.read_bytes() == b"previous-durable-evidence"
    assert _residuals(tmp_path, output) == []


def test_atomic_writer_retains_one_owner_only_recovery_on_double_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    previous = b"previous-durable-evidence"
    output.write_bytes(previous)
    real_fsync = module.os.fsync
    real_rename = module.os.rename
    directory_calls = 0
    rename_calls = 0

    def fail_first_directory_fsync(descriptor: int) -> None:
        nonlocal directory_calls
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_calls += 1
            if directory_calls == 2:
                raise OSError
        real_fsync(descriptor)

    def fail_rollback_rename(*args: Any, **kwargs: Any) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError
        real_rename(*args, **kwargs)

    monkeypatch.setattr(module.os, "fsync", fail_first_directory_fsync)
    monkeypatch.setattr(module.os, "rename", fail_rollback_rename)
    with pytest.raises(module.EvidenceWriteAmbiguous) as raised:
        module.write_json_atomic(output, document)
    recoveries = list(tmp_path.glob(f".{output.name}.*.recovery"))
    assert len(recoveries) == 1
    assert recoveries[0].name == raised.value.recovery_name
    assert recoveries[0].read_bytes() == previous
    assert stat.S_IMODE(recoveries[0].stat().st_mode) == 0o600
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []
    assert list(tmp_path.glob(f".{output.name}.*.rollback")) == []


def test_atomic_writer_recreates_recovery_if_rollback_cleanup_is_not_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    previous = b"previous-durable-evidence"
    output.write_bytes(previous)
    real_fsync = module.os.fsync
    directory_calls = 0

    def fail_primary_and_rollback_cleanup(descriptor: int) -> None:
        nonlocal directory_calls
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_calls += 1
            if directory_calls in {2, 4}:
                raise OSError
        real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_primary_and_rollback_cleanup)
    with pytest.raises(module.EvidenceWriteAmbiguous) as raised:
        module.write_json_atomic(output, document)
    recoveries = list(tmp_path.glob(f".{output.name}.*.recovery"))
    assert output.read_bytes() == previous
    assert len(recoveries) == 1
    assert recoveries[0].name == raised.value.recovery_name
    assert recoveries[0].read_bytes() == previous
    assert stat.S_IMODE(recoveries[0].stat().st_mode) == 0o600
    assert list(tmp_path.glob(f".{output.name}.*.rollback")) == []


def test_atomic_writer_recreates_deleted_recovery_before_ambiguous_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    previous = b"previous-durable-evidence"
    output.write_bytes(previous)
    real_fsync = module.os.fsync
    real_rename = module.os.rename
    directory_calls = 0
    rename_calls = 0

    def fail_post_replace_fsync(descriptor: int) -> None:
        nonlocal directory_calls
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_calls += 1
            if directory_calls == 2:
                raise OSError
        real_fsync(descriptor)

    def delete_recovery_then_fail_rollback(*args: Any, **kwargs: Any) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 1:
            directory_fd = kwargs["src_dir_fd"]
            recovery = next(
                name for name in os.listdir(directory_fd) if name.endswith(".recovery")
            )
            os.unlink(recovery, dir_fd=directory_fd)
            real_rename(*args, **kwargs)
            return
        raise OSError

    monkeypatch.setattr(module.os, "fsync", fail_post_replace_fsync)
    monkeypatch.setattr(module.os, "rename", delete_recovery_then_fail_rollback)
    with pytest.raises(module.EvidenceWriteAmbiguous) as raised:
        module.write_json_atomic(output, document)
    recoveries = list(tmp_path.glob(f".{output.name}.*.recovery"))
    assert len(recoveries) == 1
    assert recoveries[0].name == raised.value.recovery_name
    assert recoveries[0].read_bytes() == previous
    assert stat.S_IMODE(recoveries[0].stat().st_mode) == 0o600


def test_atomic_writer_rejects_checked_temp_name_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    previous = b"previous"
    output.write_bytes(previous)
    attacker = tmp_path / "attacker"
    attacker.write_bytes(b"attacker")
    real_rename = module.os.rename
    first = True

    def swap_then_rename(
        source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        nonlocal first
        if first:
            first = False
            os.unlink(source, dir_fd=src_dir_fd)
            os.symlink("attacker", source, dir_fd=src_dir_fd)
        real_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(module.os, "rename", swap_then_rename)
    with pytest.raises(module.EvidenceError):
        module.write_json_atomic(output, document)
    assert output.read_bytes() == previous
    assert not output.is_symlink()
    assert _residuals(tmp_path, output) == []


def test_atomic_writer_rejects_parent_directory_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    parent = tmp_path / "output"
    parent.mkdir()
    original = tmp_path / "original-output"
    replacement = tmp_path / "replacement-output"
    replacement.mkdir()
    output = parent / "evidence.json"
    output.write_bytes(b"previous")
    real_create = module._create_exclusive_at
    first = True

    def swap_parent(*args: Any, **kwargs: Any) -> tuple[int, str]:
        nonlocal first
        if first:
            first = False
            parent.rename(original)
            parent.symlink_to(replacement, target_is_directory=True)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(module, "_create_exclusive_at", swap_parent)
    with pytest.raises(module.EvidenceError):
        module.write_json_atomic(output, document)
    assert (original / "evidence.json").read_bytes() == b"previous"
    assert not (replacement / "evidence.json").exists()
    assert _residuals(original, original / "evidence.json") == []


def test_atomic_writer_refuses_symlink_missing_parent_and_unsafe_name(
    tmp_path: Path,
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    target = tmp_path / "target.json"
    target.write_text("preserve")
    output = tmp_path / "output.json"
    output.symlink_to(target)
    with pytest.raises(module.EvidenceError) as raised:
        module.write_json_atomic(output, document)
    assert target.read_text() == "preserve"
    assert str(tmp_path) not in str(raised.value)
    with pytest.raises(module.EvidenceError):
        module.write_json_atomic(tmp_path / "missing" / "output.json", document)
    with pytest.raises(module.EvidenceError):
        module.write_json_atomic(tmp_path / "unsafe\\name.json", document)


def test_atomic_writer_rejects_unsafe_directory_and_missing_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o700)
    unsafe.chmod(0o777)
    output = unsafe / "evidence.json"
    try:
        with pytest.raises(module.EvidenceError):
            module.write_json_atomic(output, document)
        assert not output.exists()
    finally:
        unsafe.chmod(0o700)

    safe_output = tmp_path / "safe.json"
    safe_output.write_bytes(b"preserve")
    monkeypatch.setattr(module.os, "supports_dir_fd", frozenset())
    with pytest.raises(module.EvidenceError):
        module.write_json_atomic(safe_output, document)
    assert safe_output.read_bytes() == b"preserve"
    assert _residuals(tmp_path, safe_output) == []


def test_pre_replace_cleanup_fsync_failure_is_terminally_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    output.write_bytes(b"old")
    real_fsync = module.os.fsync
    directory_calls = 0

    def fail_cleanup_fsync(descriptor: int) -> None:
        nonlocal directory_calls
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_calls += 1
            if directory_calls == 2:
                raise OSError
        real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_cleanup_fsync)
    monkeypatch.setattr(
        module.os,
        "rename",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(module.EvidenceCleanupAmbiguous):
        module.write_json_atomic(output, document)
    assert directory_calls == 2
    assert output.read_bytes() == b"old"
    assert _residuals(tmp_path, output) == []


def test_failed_primary_rename_destination_drift_retains_old_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    output.write_bytes(b"old")

    def drift_then_fail(
        _source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        assert src_dir_fd == dst_dir_fd
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_TRUNC,
            dir_fd=dst_dir_fd,
        )
        try:
            os.write(descriptor, b"tampered")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        raise OSError

    monkeypatch.setattr(module.os, "rename", drift_then_fail)
    with pytest.raises(module.EvidenceWriteAmbiguous) as raised:
        module.write_json_atomic(output, document)
    recoveries = list(tmp_path.glob(f".{output.name}.*.recovery"))
    assert output.read_bytes() == b"tampered"
    assert len(recoveries) == 1
    assert recoveries[0].name == raised.value.recovery_name
    assert recoveries[0].read_bytes() == b"old"
    assert stat.S_IMODE(recoveries[0].stat().st_mode) == 0o600


def test_failed_primary_rename_destination_drift_with_residual_cleanup_is_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    output.write_bytes(b"old")
    real_unlink = module.os.unlink

    def drift_then_fail(
        _source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        assert src_dir_fd == dst_dir_fd
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_TRUNC,
            dir_fd=dst_dir_fd,
        )
        try:
            os.write(descriptor, b"tampered")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        raise OSError

    def fail_temp_unlink(name: str, *, dir_fd: int | None = None) -> None:
        if name.endswith(".tmp"):
            raise OSError
        real_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "rename", drift_then_fail)
    monkeypatch.setattr(module.os, "unlink", fail_temp_unlink)
    with pytest.raises(module.EvidenceCleanupAmbiguous) as raised:
        module.write_json_atomic(output, document)
    recoveries = list(tmp_path.glob(f".{output.name}.*.recovery"))
    temporaries = list(tmp_path.glob(f".{output.name}.*.tmp"))
    assert raised.value.recovery_name is not None
    assert output.read_bytes() == b"tampered"
    assert len(recoveries) == 1
    assert recoveries[0].name == raised.value.recovery_name
    assert recoveries[0].read_bytes() == b"old"
    assert stat.S_IMODE(recoveries[0].stat().st_mode) == 0o600
    assert len(temporaries) == 1
    assert stat.S_IMODE(temporaries[0].stat().st_mode) == 0o600


def test_post_replace_residual_cleanup_failure_is_not_standard_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, kwargs, _ = _fixture(tmp_path)
    document = module.compose_document(**kwargs)
    output = tmp_path / "evidence.json"
    output.write_bytes(b"old")
    real_fsync = module.os.fsync
    real_rename = module.os.rename
    real_unlink = module.os.unlink
    directory_calls = 0
    rename_calls = 0

    def fail_post_replace_fsync(descriptor: int) -> None:
        nonlocal directory_calls
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_calls += 1
            if directory_calls == 2:
                raise OSError
        real_fsync(descriptor)

    def fail_rollback_rename(*args: Any, **kwargs: Any) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError
        real_rename(*args, **kwargs)

    def fail_rollback_unlink(name: str, *, dir_fd: int | None = None) -> None:
        if name.endswith(".rollback"):
            raise OSError
        real_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "fsync", fail_post_replace_fsync)
    monkeypatch.setattr(module.os, "rename", fail_rollback_rename)
    monkeypatch.setattr(module.os, "unlink", fail_rollback_unlink)
    with pytest.raises(module.EvidenceCleanupAmbiguous) as raised:
        module.write_json_atomic(output, document)
    assert raised.value.recovery_name is not None
    recoveries = list(tmp_path.glob(f".{output.name}.*.recovery"))
    rollbacks = list(tmp_path.glob(f".{output.name}.*.rollback"))
    assert len(recoveries) == 1
    assert recoveries[0].read_bytes() == b"old"
    assert len(rollbacks) == 1


def test_cli_composes_recomputes_and_redacts_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module, kwargs, context = _fixture(tmp_path)
    output = tmp_path / "cli-evidence.json"
    arguments = SimpleNamespace(
        producer_archive=context["archive_paths"]["producer"],
        node22_archive=context["archive_paths"][22],
        node24_archive=context["archive_paths"][24],
        producer_artifact_id=456,
        producer_artifact_digest=kwargs["producer_archive"].digest,
        node22_source_artifact_id=2201,
        node22_source_artifact_digest=kwargs["node22_archive"].digest,
        node24_source_artifact_id=2401,
        node24_source_artifact_digest=kwargs["node24_archive"].digest,
        expected_run_id=123,
        expected_workflow_run=WORKFLOW_RUN,
        expected_workflow_ref=WORKFLOW_REF,
        expected_workflow_sha=COMMIT,
        output=output,
    )
    monkeypatch.setattr(module, "parse_args", lambda: arguments)
    assert module.main() == 0
    assert capsys.readouterr().out.startswith(
        "PASS: TypeScript onboarding evidence written sha256="
    )
    module.validate_document(json.loads(output.read_text()))

    arguments.producer_artifact_digest = "secret-canary-at-" + str(tmp_path)
    assert module.main() == 1
    failure = capsys.readouterr().out
    assert failure.startswith("FAIL: /digest:")
    assert "secret-canary" not in failure
    assert str(tmp_path) not in failure


def test_cli_never_retries_ambiguous_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module, kwargs, context = _fixture(tmp_path)
    output = tmp_path / "cli-evidence.json"
    arguments = SimpleNamespace(
        producer_archive=context["archive_paths"]["producer"],
        node22_archive=context["archive_paths"][22],
        node24_archive=context["archive_paths"][24],
        producer_artifact_id=456,
        producer_artifact_digest=kwargs["producer_archive"].digest,
        node22_source_artifact_id=2201,
        node22_source_artifact_digest=kwargs["node22_archive"].digest,
        node24_source_artifact_id=2401,
        node24_source_artifact_digest=kwargs["node24_archive"].digest,
        expected_run_id=123,
        expected_workflow_run=WORKFLOW_RUN,
        expected_workflow_ref=WORKFLOW_REF,
        expected_workflow_sha=COMMIT,
        output=output,
    )
    calls = 0

    def ambiguous(*_args: Any, **_kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        raise module.EvidenceWriteAmbiguous(".evidence.recovery")

    monkeypatch.setattr(module, "parse_args", lambda: arguments)
    monkeypatch.setattr(module, "write_json_atomic", ambiguous)
    assert module.main() == 2
    assert calls == 1
    assert capsys.readouterr().out.startswith("AMBIGUOUS:")
