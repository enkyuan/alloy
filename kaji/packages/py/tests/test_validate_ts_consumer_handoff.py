"""Adversarial black-box tests for the independent TypeScript handoff validator."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from typing import Any, Callable

import pytest


SCRIPT = Path(__file__).parents[3] / "scripts" / "validate_ts_consumer_handoff.py"
SCHEMA = (
    Path(__file__).parents[3]
    / "contracts/release/kaji-ts-consumer-handoff-v1.schema.json"
)
LICENSE = Path(__file__).parents[3] / "packages/ts/LICENSE"

HEAD = "1" * 40
TREE = "2" * 40
MERGE_BASE = "3" * 40
VERIFIER = "4" * 40
DIGEST = "a" * 64
EMAIL = "release.signer@example.com"
VERSION = "0.2.0"
ARTIFACT_NAME = f"irogane-kaji-{VERSION}.tgz"
SIGNER = {
    "repository": "enkyuan/alloy",
    "filePath": ".github/workflows/kaji.handoff.trusted.yml",
    "digest": VERIFIER,
    "ref": f"enkyuan/alloy/.github/workflows/kaji.handoff.trusted.yml@{VERIFIER}",
}
TOOLS = [
    "add_comment",
    "create_issue",
    "get_file",
    "get_issue",
    "list_issues",
    "search_code",
    "get_commit",
    "get_pull_request",
    "list_pull_request_files",
    "list_check_runs",
    "get_workflow_run",
    "list_workflow_jobs",
    "list_file_commits",
    "get_release",
    "list_deployments",
]
READS = TOOLS[2:]
SHARED_TOOLS = TOOLS[:6]
SHARED_READS = SHARED_TOOLS[2:]
PUBLIC_SYMBOLS = [
    "CreateGitHubIntegrationOptions",
    "GitHubIntegration",
    "createGithubIntegration",
    "inspectIntegration",
]
SUBCHECKS = [
    "safe-packlist",
    "source-byte-equality",
    "export-targets",
    "declarations",
    "typescript-5.7.3-mts",
    "typescript-5.7.3-cts",
    "typescript-current-mts",
    "typescript-current-cts",
    "npm-install",
    "bun-install",
    "public-github-surface",
    "typescript-catalog-15-13",
    "shared-python-catalog-6-4",
    "lifecycle-identity",
    "policy-before-token",
    "packaged-license",
]
NODE_CHECKS = ["npm-install", "esm-import", "commonjs-require", "catalog-15-13"]
RECEIPT_NAMES = (
    "source-equivalence.json",
    "signature-verification.json",
    "pack-once.json",
    "artifact-contract.json",
    "node-22.json",
    "node-24.json",
)
RECEIPT_KEYS = (
    "sourceEquivalence",
    "signatureVerification",
    "packOnce",
    "artifactContract",
    "node22",
    "node24",
)


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "validate_ts_consumer_handoff", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module()


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")


def _passed(values: list[str]) -> list[dict[str, str]]:
    return [{"id": value, "result": "passed"} for value in values]


def _exports() -> dict[str, Any]:
    def entry(stem: str) -> dict[str, Any]:
        return {
            "import": {
                "types": f"./dist/{stem}.d.ts",
                "default": f"./dist/{stem}.js",
            },
            "require": {
                "types": f"./dist/{stem}.d.cts",
                "default": f"./dist/{stem}.cjs",
            },
        }

    return {
        ".": entry("index"),
        "./testing": entry("testing"),
        "./openai": entry("openai"),
        "./anthropic": entry("anthropic"),
        "./integrations": entry("integrations"),
        "./integrations/github": entry("integrations/github"),
        "./auth": entry("auth"),
        "./cli": {
            "import": {
                "types": "./dist/cli/package-entry.d.ts",
                "default": "./dist/cli/package-entry.js",
            },
            "require": {
                "types": "./dist/cli/package-entry-cjs.d.cts",
                "default": "./dist/cli/package-entry-cjs.cjs",
            },
        },
    }


def _targets(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for child in value.values():
            result.extend(_targets(child))
        return result
    return []


def _tar_files(
    *,
    package_patch: dict[str, Any] | None = None,
    license_bytes: bytes | None = None,
    declarations: bytes | None = None,
) -> dict[str, bytes]:
    exports = _exports()
    package = {
        "name": "@irogane/kaji",
        "version": VERSION,
        "license": "FSL-1.1-ALv2",
        "exports": exports,
    }
    package.update(package_patch or {})
    symbols = (
        declarations
        or (
            "export type CreateGitHubIntegrationOptions = {};\n"
            "export declare class GitHubIntegration {}\n"
            "export declare function createGithubIntegration(): GitHubIntegration;\n"
            "export declare function inspectIntegration(): GitHubIntegration;\n"
        ).encode()
    )
    files = {
        "package/package.json": json.dumps(package, sort_keys=True).encode(),
        "package/LICENSE": LICENSE.read_bytes()
        if license_bytes is None
        else license_bytes,
    }
    for target in _targets(exports):
        name = f"package/{target.removeprefix('./')}"
        files[name] = (
            symbols
            if target.endswith(("github.d.ts", "github.d.cts"))
            else b"export {};\n"
        )
    return files


def _write_tarball(
    path: Path,
    files: dict[str, bytes],
    *,
    link: tuple[str, str] | None = None,
    duplicate: str | None = None,
) -> list[str]:
    names: list[str] = []
    with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for name, payload in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(payload))
            names.append(name)
        if duplicate is not None:
            payload = files[duplicate]
            info = tarfile.TarInfo(duplicate)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))
            names.append(duplicate)
        if link is not None:
            info = tarfile.TarInfo(link[0])
            info.type = tarfile.SYMTYPE
            info.linkname = link[1]
            archive.addfile(info)
            names.append(link[0])
    return sorted(names, key=lambda value: value.encode("ascii"))


def _measure(path: Path) -> tuple[int, str, str]:
    payload = path.read_bytes()
    return (
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        "sha512-" + base64.b64encode(hashlib.sha512(payload).digest()).decode(),
    )


def _receipt(
    receipt_id: str, artifact_sha: str, evidence: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": receipt_id,
        "result": "passed",
        "sourceCommit": HEAD,
        "artifactSha256": artifact_sha,
        "evidence": evidence,
    }


def _fixture(tmp_path: Path, mode: str = "release") -> dict[str, Any]:
    bundle = tmp_path / "bundle"
    receipts_dir = tmp_path / "receipts"
    bundle.mkdir()
    receipts_dir.mkdir()
    tarball = bundle / ARTIFACT_NAME
    members = _write_tarball(tarball, _tar_files())
    size, artifact_sha, integrity = _measure(tarball)
    release = mode == "release"
    exports = _exports()
    construction = {"cleanCheckoutBuild": "passed", "packInvocationCount": 1}
    reproducibility = {"comparison": "not-run"}
    toolchain = {
        "node": "24.11.0",
        "npm": "11.6.1",
        "bun": "1.3.11" if release else "1.3.14",
        "uv": "0.11.25",
    }
    policy = {
        "testFile": "kaji/packages/ts/tests/github-registry.test.ts",
        "testName": "rejects approval for github_create_issue before token or HTTP",
        "tokenLookups": 0,
        "requestAttempts": 0,
    }
    license_sha = hashlib.sha256(LICENSE.read_bytes()).hexdigest()
    source = {
        "repository": "https://github.com/enkyuan/alloy.git",
        "headCommit": HEAD,
        "treeSha": TREE,
        "mergeBase": MERGE_BASE,
        "revisionCommand": [
            "git",
            "rev-list",
            "--reverse",
            "--topo-order",
            f"{MERGE_BASE}..{HEAD}",
        ],
        "range": [HEAD],
        "checkout": "separate-fetch-depth-0",
        "clean": True,
        "trustedVerifierCommit": VERIFIER,
        "rawResultSha256": DIGEST,
    }
    signature = {
        "identityField": "gitCommit.committer.email",
        "approvedSignerEmail": EMAIL,
        "verifierSource": "trusted-default-branch",
        "headCommit": HEAD,
        "treeSha": TREE,
        "verifierCommit": VERIFIER,
        "verifierScriptSha256": DIGEST,
        "mergeBase": MERGE_BASE,
        "range": [HEAD],
        "commits": [
            {
                "sha": HEAD,
                "verified": True,
                "reason": "valid",
                "signerEmail": EMAIL,
                "payloadSha256": DIGEST,
            }
        ],
        "rawResultSha256": DIGEST,
        "mechanism": (
            "github-rest-commit-and-annotated-tag-verification"
            if release
            else "github-rest-commit-verification"
        ),
    }
    if release:
        signature["tag"] = {
            "name": "kaji-release_1.alpha",
            "objectSha": "5" * 40,
            "targetCommit": HEAD,
            "taggerEmail": EMAIL,
            "verified": True,
            "reason": "valid",
        }
    pack = {
        "mode": mode,
        "package": {"name": "@irogane/kaji", "version": VERSION},
        "artifact": {
            "filename": ARTIFACT_NAME,
            "size": size,
            "npmIntegrity": integrity,
        },
        "toolchain": toolchain,
        "construction": construction,
        "reproducibility": reproducibility,
        "registry": {"status": "version-unused" if release else "not-claimed"},
        "sourceTreeRecheck": "passed",
    }
    artifact_contract = {
        "subchecks": _passed(SUBCHECKS),
        "packlist": {
            "memberCount": len(members),
            "membersSha256": hashlib.sha256(
                b"".join(name.encode() + b"\n" for name in members)
            ).hexdigest(),
        },
        "package": {"exports": exports, "publicSymbols": PUBLIC_SYMBOLS},
        "typescript": {"minimumVersion": "5.7.3", "currentVersion": "6.0.3"},
        "installs": {
            "npm": {"artifactSha256": artifact_sha, "realCopy": True},
            "bun": {"artifactSha256": artifact_sha, "realCopy": True},
        },
        "catalogs": {
            "typescript": {
                "schemaVersion": "1.0.0",
                "catalogVersion": "0.2.0",
                "totalCount": 15,
                "readCount": 13,
                "tools": TOOLS,
                "readTools": READS,
            },
            "shared": {
                "manifestVersion": "0.1.0",
                "totalCount": 6,
                "readCount": 4,
                "tools": SHARED_TOOLS,
                "readTools": SHARED_READS,
            },
        },
        "lifecycle": {
            "githubFailure": {
                "stages": ["requested", "started", "failed"],
                "providerAlias": "github_get_file",
                "catalogName": "github.get_file",
                "sameIdentityAtEveryStage": True,
            },
            "syntheticCompletion": {
                "stages": ["requested", "started", "completed"],
                "providerAlias": "synthetic_complete",
                "catalogName": "synthetic.complete",
                "sameIdentityAtEveryStage": True,
            },
        },
        "policy": policy,
        "license": {"id": "FSL-1.1-ALv2", "sha256": license_sha},
    }
    node22 = {
        "nodeMajor": 22,
        "nodeVersion": "22.22.0",
        "npmVersion": "10.9.4",
        "installedArtifactSha256": artifact_sha,
        "realCopy": True,
        "checks": _passed(NODE_CHECKS),
    }
    node24 = {
        "nodeMajor": 24,
        "nodeVersion": "24.11.0",
        "npmVersion": "11.6.1",
        "installedArtifactSha256": artifact_sha,
        "realCopy": True,
        "checks": _passed(NODE_CHECKS),
    }
    first_six = [
        _receipt("source-equivalence", artifact_sha, source),
        _receipt("signature-verification", artifact_sha, signature),
        _receipt("pack-once", artifact_sha, pack),
        _receipt("artifact-contract", artifact_sha, artifact_contract),
        _receipt("node-22", artifact_sha, node22),
        _receipt("node-24", artifact_sha, node24),
    ]
    receipt_bytes = [_canonical(value) for value in first_six]
    receipt_digests = {
        key: hashlib.sha256(encoded).hexdigest()
        for key, encoded in zip(RECEIPT_KEYS, receipt_bytes, strict=True)
    }
    gate_evidence = {
        "mode": mode,
        "registry": "version-unused" if release else "not-claimed",
        "signerWorkflow": SIGNER,
        "toolchain": toolchain,
        "publicReleaseClaim": "eligible" if release else "not-claimed",
        "licenseUseClaim": "permitted-purpose-only",
        "receiptSha256": receipt_digests,
        "checks": _passed(
            [
                "source-policy",
                "toolchain-policy",
                *(["registry-policy"] if release else []),
                "runtime-evidence-split",
                "artifact-policy",
                "license-policy",
            ]
        ),
    }
    gate = _receipt(
        "release-gate" if release else "internal-evaluation-gate",
        artifact_sha,
        gate_evidence,
    )
    manifest = {
        "schemaVersion": 1,
        "artifact": {
            "filename": ARTIFACT_NAME,
            "size": size,
            "sha256": artifact_sha,
            "npmIntegrity": integrity,
            "construction": construction,
            "reproducibility": reproducibility,
        },
        "package": {
            "name": "@irogane/kaji",
            "version": VERSION,
            "exports": exports,
            "publicSymbols": {"github": PUBLIC_SYMBOLS},
        },
        "source": {
            "repository": "https://github.com/enkyuan/alloy.git",
            "commit": HEAD,
            "tree": TREE,
            "mergeBase": MERGE_BASE,
            "verifierCommit": VERIFIER,
            "signature": {
                "required": True,
                "result": "passed",
                "mechanism": signature["mechanism"],
            },
        },
        "github": {
            "abi": {"schemaVersion": "1.0.0", "catalogVersion": "0.2.0"},
            "userAgentVersion": "0.2.0",
            "sharedManifestVersion": "0.1.0",
            "totalCount": 15,
            "readCount": 13,
            "tools": TOOLS,
            "readTools": READS,
            "shared": {
                "totalCount": 6,
                "readCount": 4,
                "tools": SHARED_TOOLS,
                "readTools": SHARED_READS,
            },
        },
        "upstreamVerification": [*first_six, gate],
        "securityEvidence": {"policyBeforeRequest": {**policy, "result": "passed"}},
        "license": {
            "id": "FSL-1.1-ALv2",
            "file": "LICENSE",
            "sha256": license_sha,
            "competingUseApproved": False,
            "futureLicense": "Apache-2.0",
            "futureLicenseAfter": "second-anniversary",
        },
    }
    fx = {
        "bundle": bundle,
        "receipts": receipts_dir,
        "tarball": tarball,
        "manifest": manifest,
        "mode": mode,
    }
    _persist(fx)
    (bundle / "kaji-ts-consumer-handoff-v1.schema.json").write_bytes(
        SCHEMA.read_bytes()
    )
    return fx


def _persist(fx: dict[str, Any]) -> None:
    manifest = fx["manifest"]
    first_six = manifest["upstreamVerification"][:6]
    receipt_bytes = [_canonical(value) for value in first_six]
    gate = manifest["upstreamVerification"][6]
    gate["evidence"]["receiptSha256"] = {
        key: hashlib.sha256(encoded).hexdigest()
        for key, encoded in zip(RECEIPT_KEYS, receipt_bytes, strict=True)
    }
    (fx["bundle"] / "kaji.manifest.json").write_bytes(_canonical(manifest))
    for name, encoded in zip(RECEIPT_NAMES, receipt_bytes, strict=True):
        (fx["receipts"] / name).write_bytes(encoded)


def _validate(fx: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    arguments = {
        "bundle_dir": fx["bundle"],
        "receipts_dir": fx["receipts"],
        "expected_mode": fx["mode"],
        "expected_commit": HEAD,
        "expected_signer_repository": SIGNER["repository"],
        "expected_signer_file_path": SIGNER["filePath"],
        "expected_signer_digest": SIGNER["digest"],
        "expected_signer_ref": SIGNER["ref"],
    }
    arguments.update(overrides)
    return VALIDATOR.validate_bundle(**arguments)


def _assert_failure(fx: dict[str, Any], code: str, **overrides: Any) -> None:
    with pytest.raises(VALIDATOR.ValidationError) as raised:
        _validate(fx, **overrides)
    assert raised.value.code == code


@pytest.mark.parametrize("mode", ["release", "internal-evaluation"])
def test_validates_both_modes_and_emits_exact_closed_success(
    tmp_path: Path, mode: str
) -> None:
    fx = _fixture(tmp_path, mode)
    result = _validate(fx)
    assert list(result) == [
        "schemaVersion",
        "command",
        "result",
        "mode",
        "sourceCommit",
        "artifact",
        "manifestSha256",
        "schemaSha256",
        "receiptSha256",
        "signerWorkflow",
        "checks",
    ]
    assert result["result"] == "passed"
    assert result["mode"] == mode
    assert (
        result["artifact"]["sha256"]
        == hashlib.sha256(fx["tarball"].read_bytes()).hexdigest()
    )
    assert result["checks"] == list(VALIDATOR.CHECKS)


def test_validates_first_publication_registry_evidence(tmp_path: Path) -> None:
    fx = _fixture(tmp_path, "release")
    fx["manifest"]["upstreamVerification"][2]["evidence"]["registry"] = {
        "status": "package-absent"
    }
    fx["manifest"]["upstreamVerification"][6]["evidence"]["registry"] = "package-absent"
    _persist(fx)

    assert _validate(fx)["result"] == "passed"


def test_cli_writes_one_canonical_success_document_without_repacking(
    tmp_path: Path,
) -> None:
    fx = _fixture(tmp_path)
    output = tmp_path / "evidence" / "validation.json"
    output.parent.mkdir()
    arguments = [
        "--bundle-dir",
        str(fx["bundle"]),
        "--receipts-dir",
        str(fx["receipts"]),
        "--expected-mode",
        fx["mode"],
        "--expected-commit",
        HEAD,
        "--expected-signer-repository",
        SIGNER["repository"],
        "--expected-signer-file-path",
        SIGNER["filePath"],
        "--expected-signer-digest",
        SIGNER["digest"],
        "--expected-signer-ref",
        SIGNER["ref"],
        "--output",
        str(output),
    ]
    before = fx["tarball"].read_bytes()
    assert VALIDATOR._run(arguments) == 0
    document = json.loads(output.read_text())
    assert output.read_bytes() == _canonical(document)
    assert fx["tarball"].read_bytes() == before


def test_accepts_exact_empty_range_commit_relations(tmp_path: Path) -> None:
    fx = _fixture(tmp_path, "internal-evaluation")
    source = fx["manifest"]["upstreamVerification"][0]["evidence"]
    signature = fx["manifest"]["upstreamVerification"][1]["evidence"]
    source["range"] = []
    signature["range"] = []
    _persist(fx)
    assert _validate(fx)["result"] == "passed"


@pytest.mark.parametrize(
    ("mode", "mechanism"),
    [
        ("release", "github-rest-commit-verification"),
        (
            "internal-evaluation",
            "github-rest-commit-and-annotated-tag-verification",
        ),
    ],
)
def test_rejects_cross_mode_signature_mechanisms(
    tmp_path: Path, mode: str, mechanism: str
) -> None:
    fx = _fixture(tmp_path, mode)
    signature = fx["manifest"]["upstreamVerification"][1]["evidence"]
    signature["mechanism"] = mechanism
    fx["manifest"]["source"]["signature"]["mechanism"] = mechanism
    if mode == "release":
        signature.pop("tag")
    else:
        signature["tag"] = {
            "name": "kaji-release_1.alpha",
            "objectSha": "5" * 40,
            "targetCommit": HEAD,
            "taggerEmail": EMAIL,
            "verified": True,
            "reason": "valid",
        }
    _persist(fx)
    _assert_failure(fx, "RECEIPT_INVALID")


def test_rejects_root_and_external_signature_mechanism_disagreement(
    tmp_path: Path,
) -> None:
    fx = _fixture(tmp_path)
    fx["manifest"]["source"]["signature"]["mechanism"] = (
        "github-rest-commit-verification"
    )
    _persist(fx)
    _assert_failure(fx, "RECEIPT_INVALID")


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda fx: (fx["bundle"] / "extra").write_text("x"), "UNSAFE_PATH"),
        (
            lambda fx: (fx["receipts"] / "extra.json").write_text("{}"),
            "RECEIPT_INVALID",
        ),
        (
            lambda fx: (
                fx["bundle"] / "kaji-ts-consumer-handoff-v1.schema.json"
            ).write_text("{}\n"),
            "SCHEMA_INVALID",
        ),
        (
            lambda fx: (fx["bundle"] / "kaji.manifest.json").write_text(
                json.dumps(fx["manifest"])
            ),
            "SCHEMA_INVALID",
        ),
        (
            lambda fx: fx["tarball"].write_bytes(fx["tarball"].read_bytes() + b"x"),
            "ARTIFACT_CHANGED",
        ),
    ],
)
def test_rejects_bundle_schema_canonical_and_artifact_mutations(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], Any], code: str
) -> None:
    fx = _fixture(tmp_path)
    mutation(fx)
    _assert_failure(fx, code)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda m: m["source"].__setitem__("tree", "9" * 40), "RECEIPT_INVALID"),
        (
            lambda m: m["upstreamVerification"][0]["evidence"][
                "revisionCommand"
            ].__setitem__(4, f"{'9' * 40}..{HEAD}"),
            "RECEIPT_INVALID",
        ),
        (
            lambda m: m["upstreamVerification"][1]["evidence"]["commits"][
                0
            ].__setitem__("signerEmail", "attacker@example.com"),
            "SIGNER_NOT_APPROVED",
        ),
        (
            lambda m: m["upstreamVerification"][2]["evidence"]["artifact"].__setitem__(
                "size", m["artifact"]["size"] + 1
            ),
            "RECEIPT_INVALID",
        ),
        (
            lambda m: m["upstreamVerification"][3]["evidence"]["packlist"].__setitem__(
                "membersSha256", "9" * 64
            ),
            "RECEIPT_INVALID",
        ),
        (
            lambda m: m["upstreamVerification"][3]["evidence"]["catalogs"][
                "typescript"
            ].__setitem__("catalogVersion", "9.9.9"),
            "SCHEMA_INVALID",
        ),
        (
            lambda m: m["upstreamVerification"][4]["evidence"].__setitem__(
                "nodeVersion", "24.0.0"
            ),
            "RECEIPT_INVALID",
        ),
        (
            lambda m: m["upstreamVerification"][3]["evidence"]["installs"][
                "npm"
            ].__setitem__("artifactSha256", "9" * 64),
            "RECEIPT_INVALID",
        ),
        (
            lambda m: m["upstreamVerification"][3]["evidence"]["license"].__setitem__(
                "sha256", "9" * 64
            ),
            "VALIDATION_FAILED",
        ),
        (
            lambda m: m["upstreamVerification"][6]["evidence"].__setitem__(
                "signerWorkflow",
                {
                    **SIGNER,
                    "digest": "9" * 40,
                    "ref": f"enkyuan/alloy/.github/workflows/kaji.handoff.trusted.yml@{'9' * 40}",
                },
            ),
            "RECEIPT_INVALID",
        ),
    ],
)
def test_rejects_bounded_cross_receipt_mutation_families(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], code: str
) -> None:
    fx = _fixture(tmp_path)
    mutate(fx["manifest"])
    _persist(fx)
    _assert_failure(fx, code)


def test_rejects_receipt_byte_disagreement_and_reordering(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    left = fx["receipts"] / RECEIPT_NAMES[0]
    right = fx["receipts"] / RECEIPT_NAMES[1]
    left_bytes, right_bytes = left.read_bytes(), right.read_bytes()
    left.write_bytes(right_bytes)
    right.write_bytes(left_bytes)
    _assert_failure(fx, "RECEIPT_INVALID")


def test_rejects_noncanonical_receipt_bytes(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    path = fx["receipts"] / RECEIPT_NAMES[0]
    path.write_text(json.dumps(json.loads(path.read_text())))
    _assert_failure(fx, "RECEIPT_INVALID")


def test_rejects_wrong_expected_commit_mode_and_signer_identity(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    _assert_failure(fx, "SOURCE_COMMIT_MISMATCH", expected_commit="9" * 40)
    _assert_failure(fx, "RECEIPT_INVALID", expected_mode="internal-evaluation")
    _assert_failure(
        fx,
        "INVALID_ARGUMENT",
        expected_signer_repository="attacker/alloy",
    )
    _assert_failure(
        fx,
        "INVALID_ARGUMENT",
        expected_signer_ref=f"enkyuan/alloy/.github/workflows/kaji.handoff.trusted.yml@{'9' * 40}",
    )


@pytest.mark.parametrize(
    "archive_mutation",
    [
        "link",
        "duplicate",
        "unsafe-path",
        "bad-package",
        "bad-license",
        "bad-declarations",
    ],
)
def test_rejects_archive_links_duplicates_package_license_and_declarations(
    tmp_path: Path, archive_mutation: str
) -> None:
    fx = _fixture(tmp_path)
    files = _tar_files()
    link = None
    duplicate = None
    if archive_mutation == "link":
        link = ("package/dist/link.js", "../../outside")
    elif archive_mutation == "duplicate":
        duplicate = "package/package.json"
    elif archive_mutation == "unsafe-path":
        files["package/../escape"] = b"escape"
    elif archive_mutation == "bad-package":
        files = _tar_files(package_patch={"name": "@attacker/sdk"})
    elif archive_mutation == "bad-license":
        files = _tar_files(license_bytes=b"wrong license\n")
    else:
        files = _tar_files(declarations=b"export {};\n")
    _write_tarball(fx["tarball"], files, link=link, duplicate=duplicate)
    size, sha256, integrity = _measure(fx["tarball"])
    manifest = fx["manifest"]
    manifest["artifact"].update(
        {"size": size, "sha256": sha256, "npmIntegrity": integrity}
    )
    for receipt in manifest["upstreamVerification"]:
        receipt["artifactSha256"] = sha256
    pack = manifest["upstreamVerification"][2]["evidence"]
    pack["artifact"].update({"size": size, "npmIntegrity": integrity})
    contract = manifest["upstreamVerification"][3]["evidence"]
    contract["installs"]["npm"]["artifactSha256"] = sha256
    contract["installs"]["bun"]["artifactSha256"] = sha256
    manifest["upstreamVerification"][4]["evidence"]["installedArtifactSha256"] = sha256
    manifest["upstreamVerification"][5]["evidence"]["installedArtifactSha256"] = sha256
    _persist(fx)
    expected = (
        "UNSAFE_PATH"
        if archive_mutation in {"link", "duplicate", "unsafe-path"}
        else "VALIDATION_FAILED"
    )
    _assert_failure(fx, expected)


@pytest.mark.parametrize("cap", ["members", "member-bytes", "total-bytes"])
def test_enforces_archive_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap: str
) -> None:
    fx = _fixture(tmp_path)
    if cap == "members":
        monkeypatch.setattr(VALIDATOR, "MAX_ARCHIVE_MEMBERS", 1)
    elif cap == "member-bytes":
        monkeypatch.setattr(VALIDATOR, "MAX_ARCHIVE_MEMBER_BYTES", 1)
    else:
        monkeypatch.setattr(VALIDATOR, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 1)
    _assert_failure(fx, "UNSAFE_PATH")


def test_failure_is_closed_atomic_redacted_and_never_overwrites_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fx = _fixture(tmp_path)
    output = tmp_path / "validation.json"
    output.write_text("preserve")
    failures = tmp_path / "failures"
    failures.mkdir()
    arguments = [
        "--bundle-dir",
        str(fx["bundle"]),
        "--receipts-dir",
        str(fx["receipts"]),
        "--expected-mode",
        "release",
        "--expected-commit",
        HEAD,
        "--expected-signer-repository",
        SIGNER["repository"],
        "--expected-signer-file-path",
        SIGNER["filePath"],
        "--expected-signer-digest",
        SIGNER["digest"],
        "--expected-signer-ref",
        SIGNER["ref"],
        "--output",
        str(output),
        "--failure-dir",
        str(failures),
    ]
    assert VALIDATOR._run(arguments) == 1
    assert output.read_text() == "preserve"
    failure_path = failures / "validate.failure.json"
    failure = json.loads(failure_path.read_text())
    assert failure_path.read_bytes() == _canonical(failure)
    assert failure == {
        "schemaVersion": 1,
        "command": "validate",
        "result": "failed",
        "failureCode": "OUTPUT_EXISTS",
        "sourceCommit": None,
        "artifactSha256": None,
    }
    stderr = capsys.readouterr().err
    assert "Authorization" not in stderr and "token" not in stderr.lower()
