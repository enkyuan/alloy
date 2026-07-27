"""Closed-schema contract tests for the TypeScript consumer handoff."""

from __future__ import annotations

from copy import deepcopy
from email.message import Message
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import runpy
import sys
from typing import Any
from urllib.error import HTTPError

import pytest
from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_RELATIVE = "release/kaji-ts-consumer-handoff-v1.schema.json"
CANONICAL_SCHEMA = REPO_ROOT / "kaji" / "contracts" / SCHEMA_RELATIVE
SCHEMA_MIRRORS = (
    REPO_ROOT / "kaji" / "src" / "kaji" / "contracts" / SCHEMA_RELATIVE,
    REPO_ROOT / "kaji" / "ts" / "contracts" / SCHEMA_RELATIVE,
)
CONTRACT_CHECK = REPO_ROOT / "kaji" / "scripts" / "check_beta_contract.py"
ORCHESTRATOR = REPO_ROOT / "kaji" / "scripts" / "ts_handoff.py"

HEAD = "1" * 40
TREE = "2" * 40
MERGE_BASE = "3" * 40
VERIFIER = "4" * 40
ARTIFACT_SHA256 = "a" * 64
DIGEST = "b" * 64
LICENSE_SHA256 = "c" * 64
SIGNER_EMAIL = "release.signer@example.com"
TOOLS_15 = [
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
READS_13 = TOOLS_15[2:]
SHARED_TOOLS_6 = TOOLS_15[:6]
SHARED_READS_4 = SHARED_TOOLS_6[2:]
PUBLIC_SYMBOLS = [
    "CreateGitHubIntegrationOptions",
    "GitHubIntegration",
    "createGithubIntegration",
    "inspectIntegration",
]
ARTIFACT_SUBCHECKS = [
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


def _schema() -> dict[str, Any]:
    value = json.loads(CANONICAL_SCHEMA.read_text())
    assert isinstance(value, dict)
    return value


def _fragment_validator(schema: dict[str, Any], definition: str) -> Validator:
    return Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            "$ref": f"#/$defs/{definition}",
        }
    )


def _passed(ids: list[str]) -> list[dict[str, str]]:
    return [{"id": value, "result": "passed"} for value in ids]


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


def _receipt(receipt_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": receipt_id,
        "result": "passed",
        "sourceCommit": HEAD,
        "artifactSha256": ARTIFACT_SHA256,
        "evidence": evidence,
    }


def _manifest(mode: str) -> dict[str, Any]:
    release = mode == "release"
    exports = _exports()
    source_evidence = {
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
    signature_evidence = {
        "identityField": "gitCommit.committer.email",
        "approvedSignerEmail": SIGNER_EMAIL,
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
                "signerEmail": SIGNER_EMAIL,
                "payloadSha256": DIGEST,
            }
        ],
        "rawResultSha256": DIGEST,
        "mechanism": "github-rest-commit-verification",
    }
    construction = {"cleanCheckoutBuild": "passed", "packInvocationCount": 1}
    reproducibility = {"comparison": "not-run"}
    pack_evidence = {
        "mode": mode,
        "package": {"name": "kaji-sdk", "version": "0.2.0"},
        "artifact": {
            "filename": "kaji-sdk-0.2.0.tgz",
            "size": 1024,
            "npmIntegrity": "sha512-QUFBQQ==",
        },
        "toolchain": {
            "node": "24.11.0",
            "npm": "11.6.1",
            "bun": "1.3.11" if release else "1.3.14",
            "uv": "0.11.25",
        },
        "construction": construction,
        "reproducibility": reproducibility,
        "registry": {"status": "version-unused" if release else "not-claimed"},
        "sourceTreeRecheck": "passed",
    }
    policy = {
        "testFile": "kaji/ts/tests/github-registry.test.ts",
        "testName": "rejects approval for github_create_issue before token or HTTP",
        "tokenLookups": 0,
        "requestAttempts": 0,
    }
    artifact_contract_evidence = {
        "subchecks": _passed(ARTIFACT_SUBCHECKS),
        "packlist": {"memberCount": 125, "membersSha256": DIGEST},
        "package": {"exports": exports, "publicSymbols": PUBLIC_SYMBOLS},
        "typescript": {"minimumVersion": "5.7.3", "currentVersion": "6.0.3"},
        "installs": {
            "npm": {"artifactSha256": ARTIFACT_SHA256, "realCopy": True},
            "bun": {"artifactSha256": ARTIFACT_SHA256, "realCopy": True},
        },
        "catalogs": {
            "typescript": {
                "schemaVersion": "1.0.0",
                "catalogVersion": "0.2.0",
                "totalCount": 15,
                "readCount": 13,
                "tools": TOOLS_15,
                "readTools": READS_13,
            },
            "shared": {
                "manifestVersion": "0.1.0",
                "totalCount": 6,
                "readCount": 4,
                "tools": SHARED_TOOLS_6,
                "readTools": SHARED_READS_4,
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
        "license": {
            "id": "FSL-1.1-ALv2",
            "sha256": LICENSE_SHA256,
        },
    }
    node22 = {
        "nodeMajor": 22,
        "nodeVersion": "22.22.0",
        "npmVersion": "10.9.4",
        "installedArtifactSha256": ARTIFACT_SHA256,
        "realCopy": True,
        "checks": _passed(NODE_CHECKS),
    }
    node24 = {
        "nodeMajor": 24,
        "nodeVersion": "24.11.0",
        "npmVersion": "11.6.1",
        "installedArtifactSha256": ARTIFACT_SHA256,
        "realCopy": True,
        "checks": _passed(NODE_CHECKS),
    }
    receipt_digests = {
        "sourceEquivalence": "1" * 64,
        "signatureVerification": "2" * 64,
        "packOnce": "3" * 64,
        "artifactContract": "4" * 64,
        "node22": "5" * 64,
        "node24": "6" * 64,
    }
    gate = {
        "mode": mode,
        "registry": "version-unused" if release else "not-claimed",
        "signerWorkflow": {
            "repository": "enkyuan/alloy",
            "filePath": ".github/workflows/kaji.handoff.trusted.yml",
            "digest": VERIFIER,
            "ref": (
                f"enkyuan/alloy/.github/workflows/kaji.handoff.trusted.yml@{VERIFIER}"
            ),
        },
        "toolchain": {
            "node": "24.11.0",
            "npm": "11.6.1",
            "bun": "1.3.11" if release else "1.3.14",
            "uv": "0.11.25",
        },
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
    final_id = "release-gate" if release else "internal-evaluation-gate"
    receipts = [
        _receipt("source-equivalence", source_evidence),
        _receipt("signature-verification", signature_evidence),
        _receipt("pack-once", pack_evidence),
        _receipt("artifact-contract", artifact_contract_evidence),
        _receipt("node-22", node22),
        _receipt("node-24", node24),
        _receipt(final_id, gate),
    ]
    return {
        "schemaVersion": 1,
        "artifact": {
            "filename": "kaji-sdk-0.2.0.tgz",
            "size": 1024,
            "sha256": ARTIFACT_SHA256,
            "npmIntegrity": "sha512-QUFBQQ==",
            "construction": construction,
            "reproducibility": reproducibility,
        },
        "package": {
            "name": "kaji-sdk",
            "version": "0.2.0",
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
                "mechanism": "github-rest-commit-verification",
            },
        },
        "github": {
            "abi": {"schemaVersion": "1.0.0", "catalogVersion": "0.2.0"},
            "userAgentVersion": "0.2.0",
            "sharedManifestVersion": "0.1.0",
            "totalCount": 15,
            "readCount": 13,
            "tools": TOOLS_15,
            "readTools": READS_13,
            "shared": {
                "totalCount": 6,
                "readCount": 4,
                "tools": SHARED_TOOLS_6,
                "readTools": SHARED_READS_4,
            },
        },
        "upstreamVerification": receipts,
        "securityEvidence": {"policyBeforeRequest": {**policy, "result": "passed"}},
        "license": {
            "id": "FSL-1.1-ALv2",
            "file": "LICENSE",
            "sha256": LICENSE_SHA256,
            "competingUseApproved": False,
            "futureLicense": "Apache-2.0",
            "futureLicenseAfter": "second-anniversary",
        },
    }


def _independent_alias_valid(
    schema: dict[str, Any], definition: str, value: Any
) -> bool:
    rule = schema["$defs"][definition]
    if definition == "positiveInt":
        return type(value) is int and rule["minimum"] <= value <= rule["maximum"]
    if not isinstance(value, str):
        return False
    if len(value) < rule.get("minLength", 0):
        return False
    if "maxLength" in rule and len(value) > rule["maxLength"]:
        return False
    if "pattern" in rule and re.fullmatch(rule["pattern"], value) is None:
        return False
    negative_rules = [rule["not"]] if "not" in rule else []
    negative_rules.extend(
        nested["not"] for nested in rule.get("allOf", []) if "not" in nested
    )
    return not any(re.search(negative["pattern"], value) for negative in negative_rules)


def _npm_pack_basename_v1(schema: dict[str, Any], name: str, version: str) -> str:
    if name != "kaji-sdk":
        raise ValueError("unexpected package name")
    if not _independent_alias_valid(schema, "semver", version):
        raise ValueError("invalid package version")
    return f"{name}-{version}.tgz"


def _walk_schema(value: Any) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    if isinstance(value, dict):
        objects.append(value)
        for nested in value.values():
            objects.extend(_walk_schema(nested))
    elif isinstance(value, list):
        for nested in value:
            objects.extend(_walk_schema(nested))
    return objects


def test_handoff_schema_is_required_valid_and_byte_mirrored() -> None:
    checker = runpy.run_path(str(CONTRACT_CHECK), run_name="ts_handoff_schema_test")
    assert SCHEMA_RELATIVE in checker["REQUIRED_JSON"]

    canonical = CANONICAL_SCHEMA.read_bytes()
    schema = json.loads(canonical)
    Draft202012Validator.check_schema(schema)
    for mirror in SCHEMA_MIRRORS:
        assert mirror.read_bytes() == canonical


def test_handoff_schema_accepts_both_closed_seven_receipt_modes() -> None:
    schema = _schema()
    validator = Draft202012Validator(schema)

    for mode in ("release", "internal-evaluation"):
        manifest = _manifest(mode)
        validator.validate(manifest)
        assert len(manifest["upstreamVerification"]) == 7

    signed_tag = _manifest("release")
    signature = signed_tag["upstreamVerification"][1]["evidence"]
    signature["mechanism"] = "github-rest-commit-and-annotated-tag-verification"
    signature["tag"] = {
        "name": "kaji-release_1.alpha",
        "objectSha": "5" * 40,
        "targetCommit": HEAD,
        "taggerEmail": SIGNER_EMAIL,
        "verified": True,
        "reason": "valid",
    }
    signed_tag["source"]["signature"]["mechanism"] = signature["mechanism"]
    validator.validate(signed_tag)


def test_handoff_schema_accepts_first_publication_registry_evidence() -> None:
    manifest = _manifest("release")
    manifest["upstreamVerification"][2]["evidence"]["registry"] = {
        "status": "package-absent"
    }
    manifest["upstreamVerification"][6]["evidence"]["registry"] = "package-absent"

    Draft202012Validator(_schema()).validate(manifest)


def test_handoff_schema_accepts_exact_root_policy_projection() -> None:
    manifest = _manifest("release")
    assert manifest["securityEvidence"]["policyBeforeRequest"] == {
        "testFile": "kaji/ts/tests/github-registry.test.ts",
        "testName": "rejects approval for github_create_issue before token or HTTP",
        "result": "passed",
        "tokenLookups": 0,
        "requestAttempts": 0,
    }

    Draft202012Validator(_schema()).validate(manifest)


def test_handoff_schema_closes_every_object_and_receipt_variant() -> None:
    schema = _schema()
    for node in _walk_schema(schema):
        if "properties" in node:
            assert node.get("type") == "object", node
            assert node.get("additionalProperties") is False, node

    receipts = schema["$defs"]["sevenReceipts"]
    assert receipts["minItems"] == receipts["maxItems"] == 7
    assert receipts["items"] is False
    assert [
        item["$ref"].removeprefix("#/$defs/") for item in receipts["prefixItems"][:6]
    ] == [
        "sourceReceipt",
        "signatureReceipt",
        "packReceipt",
        "artifactContractReceipt",
        "node22Receipt",
        "node24Receipt",
    ]
    assert [
        item["$ref"].removeprefix("#/$defs/")
        for item in receipts["prefixItems"][6]["oneOf"]
    ] == ["releaseGateReceipt", "internalGateReceipt"]


def test_handoff_schema_rejects_open_or_reordered_evidence() -> None:
    validator = Draft202012Validator(_schema())
    mutations: list[dict[str, Any]] = []

    root_extra = _manifest("release")
    root_extra["unexpected"] = True
    mutations.append(root_extra)

    receipt_extra = _manifest("release")
    receipt_extra["upstreamVerification"][0]["unexpected"] = True
    mutations.append(receipt_extra)

    evidence_extra = _manifest("release")
    evidence_extra["upstreamVerification"][2]["evidence"]["unexpected"] = True
    mutations.append(evidence_extra)

    export_extra = _manifest("release")
    export_extra["package"]["exports"]["./unexpected"] = {
        "import": {"types": "./x.d.ts", "default": "./x.js"},
        "require": {"types": "./x.d.cts", "default": "./x.cjs"},
    }
    mutations.append(export_extra)

    reordered = _manifest("release")
    reordered["upstreamVerification"][0:2] = reversed(
        reordered["upstreamVerification"][0:2]
    )
    mutations.append(reordered)

    wrong_gate = _manifest("release")
    wrong_gate["upstreamVerification"][-1]["id"] = "internal-evaluation-gate"
    mutations.append(wrong_gate)

    github_completion = _manifest("release")
    github_completion["upstreamVerification"][3]["evidence"]["lifecycle"][
        "githubFailure"
    ]["stages"][-1] = "completed"
    mutations.append(github_completion)

    reproducibility_claim = _manifest("release")
    reproducibility_claim["artifact"]["reproducibility"]["comparison"] = "passed"
    mutations.append(reproducibility_claim)

    for mutation in mutations:
        assert not validator.is_valid(mutation)


def test_handoff_semver_basename_and_alias_tables_are_shared_and_closed() -> None:
    schema = _schema()
    conformance = schema["x-kajiConformance"]
    semver = _fragment_validator(schema, "semver")
    basename = _fragment_validator(schema, "basename")

    for case in conformance["semverBasename"]:
        assert semver.is_valid(case["value"]) is case["valid"]
        if case["valid"]:
            assert _independent_alias_valid(schema, "semver", case["value"])
            derived = _npm_pack_basename_v1(schema, "kaji-sdk", case["value"])
            assert derived == case["basename"]
            assert basename.is_valid(derived)
        else:
            assert "basename" not in case
            assert not _independent_alias_valid(schema, "semver", case["value"])
            with pytest.raises(ValueError, match="invalid package version"):
                _npm_pack_basename_v1(schema, "kaji-sdk", case["value"])

    for definition, cases in conformance["aliases"].items():
        validator = _fragment_validator(schema, definition)
        for case in cases:
            assert validator.is_valid(case["value"]) is case["valid"], (
                definition,
                case,
            )
            assert (
                _independent_alias_valid(schema, definition, case["value"])
                is case["valid"]
            ), (definition, case)

    tag_name = _fragment_validator(schema, "tagName")
    for case in conformance["tagSourceRefs"]:
        assert tag_name.is_valid(case["tag"]) is case["valid"]
        if case["valid"]:
            assert f"refs/tags/{case['tag']}" == case["ref"]

    workflow_identity = _fragment_validator(schema, "signerWorkflowIdentity")
    for case in conformance["signerWorkflowIdentities"]:
        value = case["value"]
        assert workflow_identity.is_valid(value) is case["schemaValid"]
        canonical_ref = f"{value['repository']}/{value['filePath']}@{value['digest']}"
        relation_valid = case["schemaValid"] and value["ref"] == canonical_ref
        assert relation_valid is case["relationValid"]


def test_handoff_failure_envelope_is_closed() -> None:
    schema = _schema()
    validator = _fragment_validator(schema, "failure")
    failure = {
        "schemaVersion": 1,
        "command": "stage",
        "result": "failed",
        "failureCode": "PACK_FAILED",
        "sourceCommit": HEAD,
        "artifactSha256": None,
    }
    validator.validate(failure)

    open_failure = deepcopy(failure)
    open_failure["details"] = "must not be retained"
    assert not validator.is_valid(open_failure)


def test_handoff_orchestrator_entrypoint_exists() -> None:
    assert ORCHESTRATOR.is_file()


def _handoff_module() -> Any:
    scripts = str(ORCHESTRATOR.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("kaji_ts_handoff_test", ORCHESTRATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_source_signature() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _manifest("internal-evaluation")
    source = deepcopy(manifest["upstreamVerification"][0]["evidence"])
    signature = deepcopy(manifest["upstreamVerification"][1]["evidence"])
    source.pop("rawResultSha256")
    signature.pop("rawResultSha256")
    return source, signature


def _workflow() -> dict[str, Any]:
    return {
        "repository": "enkyuan/alloy",
        "filePath": ".github/workflows/kaji.handoff.trusted.yml",
        "digest": VERIFIER,
        "ref": f"enkyuan/alloy/.github/workflows/kaji.handoff.trusted.yml@{VERIFIER}",
        "runId": 91,
        "attempt": 2,
    }


def _preflight_fixture(
    handoff: Any,
    root: Path,
    *,
    mode: str = "internal-evaluation",
    registry_result: str = "version-unused",
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], bytes, bytes]:
    inputs = root / "inputs"
    source_dir = inputs / "source"
    source_dir.mkdir(parents=True)
    source, signature = _raw_source_signature()
    source_bytes = handoff._raw_canonical_json(source)
    signature_bytes = handoff._raw_canonical_json(signature)
    (source_dir / handoff.RAW_SOURCE_NAME).write_bytes(source_bytes)
    (source_dir / handoff.RAW_SIGNATURE_NAME).write_bytes(signature_bytes)
    toolchain = {
        "node": "24.11.0",
        "npm": "11.6.1",
        "bun": "1.3.11" if mode == "release" else "1.3.14",
        "uv": "0.11.25",
    }
    workflow = _workflow()
    registry: dict[str, Any]
    if mode == "release":
        registry = {
            "schemaVersion": 1,
            "producer": "ts-handoff-preflight",
            "origin": handoff.REGISTRY_ORIGIN,
            "requestPath": handoff.REGISTRY_PATH,
            "package": "kaji-sdk",
            "version": "0.2.0-beta.7",
            "httpStatus": 404 if registry_result == "package-absent" else 200,
            "result": registry_result,
            "responseSha256": DIGEST,
            "sourceCommit": HEAD,
            "workflow": workflow,
        }
    else:
        registry = {"status": "not-claimed"}
    document = {
        "schemaVersion": 1,
        "command": "preflight",
        "result": "passed",
        "mode": mode,
        "sourceCommit": HEAD,
        "treeSha": TREE,
        "trustedVerifierCommit": VERIFIER,
        "package": {"name": "kaji-sdk", "version": "0.2.0-beta.7"},
        "rawInputs": {
            "source": {
                "filename": handoff.RAW_SOURCE_NAME,
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
            },
            "signature": {
                "filename": handoff.RAW_SIGNATURE_NAME,
                "sha256": hashlib.sha256(signature_bytes).hexdigest(),
            },
        },
        "toolchain": toolchain,
        "workflow": workflow,
        "registry": registry,
    }
    preflight_path = inputs / "preflight.json"
    preflight_path.write_bytes(handoff._canonical_json(document))
    return preflight_path, document, source, signature, source_bytes, signature_bytes


def _patch_source_boundary(
    monkeypatch: pytest.MonkeyPatch,
    handoff: Any,
    candidate: Path,
    source: dict[str, Any],
    signature: dict[str, Any],
    source_bytes: bytes,
    signature_bytes: bytes,
    toolchain: dict[str, str],
) -> None:
    monkeypatch.setattr(
        handoff,
        "_raw_inputs",
        lambda _path: (source, source_bytes, signature, signature_bytes),
    )
    monkeypatch.setattr(handoff, "_recheck_source", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(handoff, "_toolchain", lambda _root: toolchain)
    monkeypatch.setattr(
        handoff,
        "_package_metadata",
        lambda _root: {
            "name": "kaji-sdk",
            "version": "0.2.0-beta.7",
            "scripts": {"prebuild": "bun run validate:registry"},
        },
    )
    monkeypatch.setattr(handoff, "_trusted_run_identity", _workflow)


def test_handoff_cli_is_exactly_three_commands() -> None:
    handoff = _handoff_module()
    parser = handoff._parser()
    command_action = next(
        action for action in parser._actions if action.dest == "command"
    )
    assert set(command_action.choices) == {"preflight", "stage", "finalize"}
    with pytest.raises(handoff.HandoffError, match="INVALID_ARGUMENT"):
        parser.parse_args(["copy"])


def test_internal_preflight_never_calls_registry_and_records_no_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff_module()
    output = tmp_path / "inputs" / "preflight.json"
    source_dir = tmp_path / "inputs" / "source"
    source_dir.mkdir(parents=True)
    source, signature = _raw_source_signature()
    source_bytes = handoff._raw_canonical_json(source)
    signature_bytes = handoff._raw_canonical_json(signature)
    (source_dir / handoff.RAW_SOURCE_NAME).write_bytes(source_bytes)
    (source_dir / handoff.RAW_SIGNATURE_NAME).write_bytes(signature_bytes)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    monkeypatch.setattr(
        handoff,
        "_raw_inputs",
        lambda _path: (source, source_bytes, signature, signature_bytes),
    )
    monkeypatch.setattr(handoff, "_recheck_source", lambda *_args: candidate)
    monkeypatch.setattr(
        handoff,
        "_package_metadata",
        lambda _root: {"name": "kaji-sdk", "version": "0.2.0-beta.7"},
    )
    monkeypatch.setattr(
        handoff,
        "_toolchain",
        lambda _root: {
            "node": "24.11.0",
            "npm": "11.6.1",
            "bun": "1.3.14",
            "uv": "0.11.25",
        },
    )
    monkeypatch.setattr(handoff, "_trusted_run_identity", _workflow)

    def forbidden_registry(_url: str, _token: str) -> tuple[int, str, bytes]:
        raise AssertionError("internal preflight must not call the registry")

    handoff.preflight(
        mode="internal-evaluation",
        candidate_root=candidate,
        source_input_dir=source_dir,
        output=output,
        registry_get=forbidden_registry,
    )
    document = json.loads(output.read_text())
    assert document["registry"] == {"status": "not-claimed"}
    assert document["workflow"] == _workflow()
    assert output.read_bytes() == handoff._canonical_json(document)
    assert "NODE_AUTH_TOKEN" not in output.read_text()


@pytest.mark.parametrize(
    ("status", "url", "body", "expected_result"),
    [
        (
            200,
            "https://registry.npmjs.org/kaji-sdk",
            {"name": "kaji-sdk", "versions": {}},
            "version-unused",
        ),
        (
            404,
            "https://registry.npmjs.org/kaji-sdk",
            {"error": "Not found"},
            "package-absent",
        ),
        (404, "https://registry.npmjs.org/kaji-sdk", {}, None),
        (404, "https://example.com/redirect", {"error": "Not found"}, None),
        (302, "https://example.com/redirect", {}, None),
        (401, "https://registry.npmjs.org/kaji-sdk", {}, None),
        (403, "https://registry.npmjs.org/kaji-sdk", {}, None),
        (429, "https://registry.npmjs.org/kaji-sdk", {}, None),
        (500, "https://registry.npmjs.org/kaji-sdk", {}, None),
        (
            200,
            "https://registry.npmjs.org/kaji-sdk",
            {"name": "wrong", "versions": {}},
            None,
        ),
        (
            200,
            "https://registry.npmjs.org/kaji-sdk",
            {"name": "kaji-sdk", "versions": []},
            None,
        ),
        (
            200,
            "https://registry.npmjs.org/kaji-sdk",
            {"name": "kaji-sdk", "versions": {"0.2.0-beta.7": {}}},
            None,
        ),
    ],
)
def test_release_registry_proof_is_one_bounded_closed_lookup(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    url: str,
    body: dict[str, Any],
    expected_result: str | None,
) -> None:
    handoff = _handoff_module()
    monkeypatch.setenv("NODE_AUTH_TOKEN", "registry-secret")
    calls: list[tuple[str, str]] = []

    def registry_get(request_url: str, token: str) -> tuple[int, str, bytes]:
        calls.append((request_url, token))
        return status, url, json.dumps(body).encode()

    if expected_result is not None:
        proof = handoff._registry_proof("0.2.0-beta.7", HEAD, _workflow(), registry_get)
        assert proof["httpStatus"] == status
        assert proof["result"] == expected_result
        assert (
            proof["responseSha256"]
            == hashlib.sha256(json.dumps(body).encode()).hexdigest()
        )
        assert proof["workflow"] == _workflow()
        assert "registry-secret" not in json.dumps(proof)
    else:
        with pytest.raises(handoff.HandoffError, match="REGISTRY_UNAVAILABLE"):
            handoff._registry_proof("0.2.0-beta.7", HEAD, _workflow(), registry_get)
    assert calls == [(handoff.REGISTRY_URL, "registry-secret")]


def test_registry_get_preserves_one_bounded_canonical_not_found_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = _handoff_module()
    body = b'{"error":"Not found"}'

    class Opener:
        def open(self, request: Any, timeout: float) -> Any:
            assert request.full_url == handoff.REGISTRY_URL
            assert timeout > 0
            raise HTTPError(
                handoff.REGISTRY_URL,
                404,
                "Not Found",
                Message(),
                io.BytesIO(body),
            )

    monkeypatch.setattr(handoff.request, "build_opener", lambda *_handlers: Opener())

    assert handoff._registry_get(handoff.REGISTRY_URL, "registry-secret") == (
        404,
        handoff.REGISTRY_URL,
        body,
    )


def test_release_registry_rejects_missing_token_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = _handoff_module()
    monkeypatch.delenv("NODE_AUTH_TOKEN", raising=False)
    called = False

    def registry_get(_url: str, _token: str) -> tuple[int, str, bytes]:
        nonlocal called
        called = True
        raise AssertionError

    with pytest.raises(handoff.HandoffError, match="REGISTRY_UNAVAILABLE"):
        handoff._registry_proof("0.2.0-beta.7", HEAD, _workflow(), registry_get)
    assert called is False


@pytest.mark.parametrize(
    "result",
    [
        (200, "https://registry.npmjs.org/kaji-sdk", b"{"),
        (
            200,
            "https://registry.npmjs.org/kaji-sdk",
            b"x" * (5 * 1024 * 1024 + 1),
        ),
        TimeoutError("registry timeout"),
    ],
)
def test_release_registry_rejects_malformed_oversized_and_timeout_results(
    monkeypatch: pytest.MonkeyPatch, result: Any
) -> None:
    handoff = _handoff_module()
    monkeypatch.setenv("NODE_AUTH_TOKEN", "registry-secret")

    def registry_get(_url: str, _token: str) -> tuple[int, str, bytes]:
        if isinstance(result, BaseException):
            raise result
        return result

    with pytest.raises(handoff.HandoffError, match="REGISTRY_UNAVAILABLE"):
        handoff._registry_proof("0.2.0-beta.7", HEAD, _workflow(), registry_get)


def test_command_environment_allows_only_local_nonsecret_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = _handoff_module()
    parent_home = tmp_path / "parent-home"
    parent_home.mkdir()
    safe_environment = {
        "PATH": "safe-PATH",
        "LANG": "safe-LANG",
        "LC_ALL": "safe-LC_ALL",
        "LC_CTYPE": "safe-LC_CTYPE",
        "TMPDIR": "safe-TMPDIR",
        "TEMP": "safe-TEMP",
        "TMP": "safe-TMP",
        "SYSTEMROOT": "safe-SYSTEMROOT",
    }
    rejected_environment = {
        "GH_TOKEN": "secret-gh",
        "NODE_AUTH_TOKEN": "secret-node",
        "GITHUB_TOKEN": "secret-github",
        "NPM_TOKEN": "secret-npm",
        "HTTP_AUTHORIZATION": "secret-authorization",
        "UNRELATED_CREDENTIAL": "secret-unrelated",
        "HOME": str(parent_home),
        "XDG_CACHE_HOME": "/sensitive-xdg-cache",
        "NPM_CONFIG_CACHE": "/sensitive-npm-cache",
        "HTTPS_PROXY": "https://proxy.invalid",
        "NPM_CONFIG_REGISTRY": "https://registry.invalid",
        "NODE_OPTIONS": "--require=/sensitive/hook.cjs",
    }
    monkeypatch.setattr(
        handoff.os,
        "environ",
        {**safe_environment, **rejected_environment},
    )
    command_homes: list[Path] = []

    def assert_child_environment(environment: dict[str, str]) -> None:
        command_home = Path(environment["HOME"])
        owned_paths = {
            "XDG_CONFIG_HOME": command_home / ".config",
            "XDG_CACHE_HOME": command_home / ".cache",
            "NPM_CONFIG_CACHE": command_home / ".npm-cache",
            "BUN_INSTALL_CACHE_DIR": command_home / ".bun-cache",
        }
        assert command_home != parent_home
        assert command_home.is_dir()
        assert command_home.stat().st_mode & 0o777 == 0o700
        assert all(path.is_dir() for path in owned_paths.values())
        assert all(
            path.stat().st_mode & 0o777 == 0o700 for path in owned_paths.values()
        )
        assert environment == {
            **safe_environment,
            "HOME": str(command_home),
            **{key: str(path) for key, path in owned_paths.items()},
            "GIT_TERMINAL_PROMPT": "0",
            "NPM_CONFIG_PROVENANCE": "false",
            "NPM_CONFIG_USERCONFIG": handoff.os.devnull,
            "NPM_CONFIG_GLOBALCONFIG": handoff.os.devnull,
            "NPM_CONFIG_AUDIT": "false",
            "NPM_CONFIG_FUND": "false",
            "NPM_CONFIG_UPDATE_NOTIFIER": "false",
        }
        command_homes.append(command_home)

    def fake_run_checked(*_args: Any, **kwargs: Any) -> Any:
        assert_child_environment(dict(kwargs["env"]))
        return handoff.CompletedCommand(returncode=0, stdout=b"1.2.3\n")

    monkeypatch.setattr(handoff, "run_checked", fake_run_checked)
    assert handoff._tool_version(("bun", "--version"), tmp_path) == "1.2.3"

    def runner(_command: Any, _cwd: Path, environment: Any) -> Any:
        assert_child_environment(dict(environment))
        return handoff.CompletedCommand(returncode=0)

    handoff._run_stage_command(
        runner, ("bun", "run", "build"), tmp_path, "BUILD_FAILED"
    )
    assert len(set(command_homes)) == 2
    assert all(not path.exists() for path in command_homes)


def _stage_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    handoff: Any,
    *,
    mode: str = "internal-evaluation",
    registry_result: str = "version-unused",
) -> tuple[Path, Path, dict[str, Any], list[tuple[str, ...]], str]:
    preflight_path, preflight, source, signature, source_bytes, signature_bytes = (
        _preflight_fixture(
            handoff, tmp_path, mode=mode, registry_result=registry_result
        )
    )
    candidate = tmp_path / "candidate"
    (candidate / "kaji" / "ts").mkdir(parents=True)
    _patch_source_boundary(
        monkeypatch,
        handoff,
        candidate,
        source,
        signature,
        source_bytes,
        signature_bytes,
        preflight["toolchain"],
    )
    commands: list[tuple[str, ...]] = []
    tarball_payload = b"one immutable package"
    integrity = (
        "sha512-" + base64.b64encode(hashlib.sha512(tarball_payload).digest()).decode()
    )

    def runner(command: Any, _cwd: Path, environment: Any) -> Any:
        command_tuple = tuple(command)
        commands.append(command_tuple)
        assert "GH_TOKEN" not in environment
        assert "NODE_AUTH_TOKEN" not in environment
        if command_tuple[:2] == ("npm", "pack"):
            pack_root = Path(command_tuple[-1])
            filename = "kaji-sdk-0.2.0-beta.7.tgz"
            (pack_root / filename).write_bytes(tarball_payload)
            output = json.dumps(
                [
                    {
                        "filename": filename,
                        "size": len(tarball_payload),
                        "integrity": integrity,
                    }
                ]
            ).encode()
            return handoff.CompletedCommand(returncode=0, stdout=output)
        return handoff.CompletedCommand(returncode=0)

    stage_dir = tmp_path / "stage"
    handoff.stage(
        mode=mode,
        candidate_root=candidate,
        preflight_path=preflight_path,
        output_dir=stage_dir,
        command_runner=runner,
    )
    return preflight_path, stage_dir, preflight, commands, integrity


def test_stage_preserves_first_publication_registry_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff_module()
    _preflight, stage_dir, _document, _commands, _integrity = _stage_fixture(
        tmp_path,
        monkeypatch,
        handoff,
        mode="release",
        registry_result="package-absent",
    )

    pack = json.loads((stage_dir / handoff.PACK_RECEIPT_NAME).read_text())
    assert pack["evidence"]["registry"] == {"status": "package-absent"}


def test_stage_runs_frozen_commands_builds_once_and_packs_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff_module()
    _preflight, stage_dir, _document, commands, integrity = _stage_fixture(
        tmp_path, monkeypatch, handoff
    )
    assert commands[:5] == [
        handoff.CLEAN_COMMAND,
        handoff.BUILD_COMMAND,
        *handoff.AUDIT_COMMANDS,
    ]
    assert len([command for command in commands if command[:2] == ("npm", "pack")]) == 1
    assert (
        len([command for command in commands if command == handoff.BUILD_COMMAND]) == 1
    )
    assert all(
        "package:smoke" not in command and "attw" not in command for command in commands
    )
    index = json.loads((stage_dir / "stage.json").read_text())
    assert index["commands"]["pack"][-1] == "$PACK_TEMP"
    assert index["commands"]["packInvocationCount"] == 1
    assert index["artifact"]["npmIntegrity"] == integrity
    assert set(path.name for path in stage_dir.iterdir()) == {
        "stage.json",
        "source-equivalence.json",
        "signature-verification.json",
        "pack-once.json",
        "kaji-sdk-0.2.0-beta.7.tgz",
    }


def test_stage_fsyncs_tarball_before_receipts_and_atomic_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff_module()
    original_fsync_file = handoff._fsync_file
    original_write_file = handoff._write_file
    original_fsync_directory = handoff._fsync_directory
    original_rename = handoff._rename_noreplace
    events: list[tuple[str, Path, Path | None]] = []

    def fsync_file(path: Path) -> None:
        events.append(("file-fsync", path, None))
        assert path.name == "kaji-sdk-0.2.0-beta.7.tgz"
        assert path.parent.name.startswith(".stage.tmp-")
        assert not (path.parent / ".pack" / path.name).exists()
        original_fsync_file(path)

    def write_file(path: Path, encoded: bytes) -> None:
        events.append(("write", path, None))
        original_write_file(path, encoded)

    def fsync_directory(path: Path) -> None:
        events.append(("directory-fsync", path, None))
        original_fsync_directory(path)

    def rename(source: Path, destination: Path) -> None:
        events.append(("rename", source, destination))
        original_rename(source, destination)

    monkeypatch.setattr(handoff, "_fsync_file", fsync_file)
    monkeypatch.setattr(handoff, "_write_file", write_file)
    monkeypatch.setattr(handoff, "_fsync_directory", fsync_directory)
    monkeypatch.setattr(handoff, "_rename_noreplace", rename)
    _preflight, stage_dir, _document, _commands, _integrity = _stage_fixture(
        tmp_path, monkeypatch, handoff
    )

    tarball_fsync = next(
        index for index, event in enumerate(events) if event[0] == "file-fsync"
    )
    first_receipt_write = next(
        index for index, event in enumerate(events) if event[0] == "write"
    )
    temporary_directory_fsync = next(
        index
        for index, event in enumerate(events)
        if event[0] == "directory-fsync" and event[1].name.startswith(".stage.tmp-")
    )
    publication = next(
        index
        for index, event in enumerate(events)
        if event[0] == "rename" and event[2] == stage_dir
    )
    assert tarball_fsync < first_receipt_write < temporary_directory_fsync < publication


def test_stage_tarball_fsync_failure_cleans_only_owned_temporary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff_module()
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("preserve me")

    def fail_fsync(_path: Path) -> None:
        raise OSError("injected tarball fsync failure")

    monkeypatch.setattr(handoff, "_fsync_file", fail_fsync)
    with pytest.raises(handoff.HandoffError, match="INTERNAL_ERROR"):
        _stage_fixture(tmp_path, monkeypatch, handoff)
    assert unrelated.read_text() == "preserve me"
    assert not (tmp_path / "stage").exists()
    assert not list(tmp_path.glob(".stage.tmp-*"))


def test_stage_rejects_pack_metadata_disagreement_and_cleans_owned_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff_module()
    preflight_path, preflight, source, signature, source_bytes, signature_bytes = (
        _preflight_fixture(handoff, tmp_path)
    )
    candidate = tmp_path / "candidate"
    (candidate / "kaji" / "ts").mkdir(parents=True)
    _patch_source_boundary(
        monkeypatch,
        handoff,
        candidate,
        source,
        signature,
        source_bytes,
        signature_bytes,
        preflight["toolchain"],
    )

    def runner(command: Any, _cwd: Path, _environment: Any) -> Any:
        if tuple(command)[:2] == ("npm", "pack"):
            path = Path(command[-1]) / "kaji-sdk-0.2.0-beta.7.tgz"
            path.write_bytes(b"artifact")
            return handoff.CompletedCommand(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "filename": path.name,
                            "size": 999,
                            "integrity": "sha512-QUFBQQ==",
                        }
                    ]
                ).encode(),
            )
        return handoff.CompletedCommand(returncode=0)

    output = tmp_path / "stage"
    with pytest.raises(handoff.HandoffError, match="PACK_FAILED"):
        handoff.stage(
            mode="internal-evaluation",
            candidate_root=candidate,
            preflight_path=preflight_path,
            output_dir=output,
            command_runner=runner,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".stage.tmp-*"))


def test_stage_detects_source_mutation_before_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff_module()
    preflight_path, preflight, source, signature, source_bytes, signature_bytes = (
        _preflight_fixture(handoff, tmp_path)
    )
    candidate = tmp_path / "candidate"
    (candidate / "kaji" / "ts").mkdir(parents=True)
    _patch_source_boundary(
        monkeypatch,
        handoff,
        candidate,
        source,
        signature,
        source_bytes,
        signature_bytes,
        preflight["toolchain"],
    )
    rechecks = 0

    def recheck(*_args: Any, **_kwargs: Any) -> Path:
        nonlocal rechecks
        rechecks += 1
        if rechecks == 3:
            raise handoff.HandoffError("SOURCE_COMMIT_MISMATCH", source_commit=HEAD)
        return candidate

    monkeypatch.setattr(handoff, "_recheck_source", recheck)
    commands: list[tuple[str, ...]] = []

    def runner(command: Any, _cwd: Path, _environment: Any) -> Any:
        commands.append(tuple(command))
        return handoff.CompletedCommand(returncode=0)

    output = tmp_path / "stage"
    with pytest.raises(handoff.HandoffError, match="SOURCE_COMMIT_MISMATCH"):
        handoff.stage(
            mode="internal-evaluation",
            candidate_root=candidate,
            preflight_path=preflight_path,
            output_dir=output,
            command_runner=runner,
        )
    assert rechecks == 3
    assert not any(command[:2] == ("npm", "pack") for command in commands)
    assert not output.exists()


def _external_receipts(
    stage_dir: Path,
    handoff: Any,
    license_bytes: bytes,
    *,
    mode: str = "internal-evaluation",
) -> tuple[Path, Path, Path, str]:
    index = json.loads((stage_dir / "stage.json").read_text())
    artifact_sha = index["artifact"]["sha256"]
    manifest = _manifest(mode)
    artifact_contract = deepcopy(manifest["upstreamVerification"][3])
    node22 = deepcopy(manifest["upstreamVerification"][4])
    node24 = deepcopy(manifest["upstreamVerification"][5])
    for receipt in (artifact_contract, node22, node24):
        receipt["artifactSha256"] = artifact_sha
        receipt["sourceCommit"] = HEAD
    artifact_contract["evidence"]["installs"]["npm"]["artifactSha256"] = artifact_sha
    artifact_contract["evidence"]["installs"]["bun"]["artifactSha256"] = artifact_sha
    artifact_contract["evidence"]["license"]["sha256"] = hashlib.sha256(
        license_bytes
    ).hexdigest()
    node22["evidence"]["installedArtifactSha256"] = artifact_sha
    node24["evidence"]["installedArtifactSha256"] = artifact_sha
    paths = (
        stage_dir.parent / "artifact-contract.json",
        stage_dir.parent / "node-22.json",
        stage_dir.parent / "node-24.json",
    )
    for path, receipt in zip(paths, (artifact_contract, node22, node24), strict=True):
        path.write_bytes(handoff._canonical_json(receipt))
    return *paths, artifact_sha


def test_finalize_aggregates_six_receipts_and_writes_exact_three_file_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff_module()
    preflight_path, stage_dir, preflight, _commands, _integrity = _stage_fixture(
        tmp_path, monkeypatch, handoff
    )
    license_bytes = b"FSL fixture"
    artifact_contract, node22, node24, artifact_sha = _external_receipts(
        stage_dir, handoff, license_bytes
    )
    candidate = tmp_path / "candidate"
    verified_archive_paths: list[Path] = []

    def verify_copied_archive(path: Path) -> tuple[dict[str, Any], bytes]:
        verified_archive_paths.append(path)
        assert path.parent.name.startswith(".bundle.tmp-")
        assert path.parent != stage_dir
        return (
            {
                "name": "kaji-sdk",
                "version": "0.2.0-beta.7",
                "exports": _exports(),
            },
            license_bytes,
        )

    monkeypatch.setattr(handoff, "_verify_archive_identity", verify_copied_archive)
    monkeypatch.setattr(handoff, "_trusted_run_identity", _workflow)
    monkeypatch.setattr(handoff, "_toolchain", lambda _root: preflight["toolchain"])
    monkeypatch.setattr(handoff, "_recheck_source", lambda *_args, **_kwargs: candidate)
    output = tmp_path / "bundle"
    handoff.finalize(
        mode="internal-evaluation",
        candidate_root=candidate,
        preflight_path=preflight_path,
        stage_dir=stage_dir,
        artifact_contract_path=artifact_contract,
        node22_path=node22,
        node24_path=node24,
        output_dir=output,
    )
    assert set(path.name for path in output.iterdir()) == {
        "kaji-sdk-0.2.0-beta.7.tgz",
        "kaji-sdk.manifest.json",
        "kaji-ts-consumer-handoff-v1.schema.json",
    }
    manifest = json.loads((output / "kaji-sdk.manifest.json").read_text())
    assert manifest["artifact"]["sha256"] == artifact_sha
    assert [receipt["id"] for receipt in manifest["upstreamVerification"]] == [
        *handoff.RECEIPT_IDS,
        "internal-evaluation-gate",
    ]
    assert manifest["license"]["competingUseApproved"] is False
    assert manifest["license"]["futureLicense"] == "Apache-2.0"
    assert len(verified_archive_paths) == 1
    receipt_set = preflight_path.parent / "receipt-set"
    assert [path.name for path in sorted(receipt_set.iterdir())] == sorted(
        handoff.RECEIPT_SET_NAMES
    )


@pytest.mark.parametrize("attack", ["mutate-source", "truncate", "same-size-corrupt"])
def test_finalize_rejects_adversarial_copy_bytes_before_receipt_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    handoff = _handoff_module()
    preflight_path, stage_dir, preflight, _commands, _integrity = _stage_fixture(
        tmp_path, monkeypatch, handoff
    )
    license_bytes = b"FSL fixture"
    artifact_contract, node22, node24, _artifact_sha = _external_receipts(
        stage_dir, handoff, license_bytes
    )
    candidate = tmp_path / "candidate"
    monkeypatch.setattr(handoff, "_trusted_run_identity", _workflow)
    monkeypatch.setattr(handoff, "_toolchain", lambda _root: preflight["toolchain"])
    monkeypatch.setattr(handoff, "_recheck_source", lambda *_args, **_kwargs: candidate)
    archive_checks: list[Path] = []
    monkeypatch.setattr(
        handoff,
        "_verify_archive_identity",
        lambda path: archive_checks.append(path),
    )
    original_copy = handoff.shutil.copyfile

    def adversarial_copy(source: Path, destination: Path) -> str:
        source_path = Path(source)
        destination_path = Path(destination)
        payload = source_path.read_bytes()
        if attack == "mutate-source":
            source_path.write_bytes(b"mutated while the final copy was in progress")
            return str(original_copy(source_path, destination_path))
        if attack == "truncate":
            destination_path.write_bytes(payload[:4])
        else:
            destination_path.write_bytes(b"x" * len(payload))
        return str(destination_path)

    monkeypatch.setattr(handoff.shutil, "copyfile", adversarial_copy)
    output = tmp_path / "bundle"
    with pytest.raises(handoff.HandoffError, match="ARTIFACT_CHANGED"):
        handoff.finalize(
            mode="internal-evaluation",
            candidate_root=candidate,
            preflight_path=preflight_path,
            stage_dir=stage_dir,
            artifact_contract_path=artifact_contract,
            node22_path=node22,
            node24_path=node24,
            output_dir=output,
        )
    assert archive_checks == []
    assert not output.exists()
    assert not (preflight_path.parent / "receipt-set").exists()
    assert not list(tmp_path.glob(".bundle.tmp-*"))
    assert not list(preflight_path.parent.glob(".receipt-set.tmp-*"))


@pytest.mark.parametrize("mismatch", ["package", "exports", "license"])
def test_finalize_rejects_copied_package_or_license_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    handoff = _handoff_module()
    preflight_path, stage_dir, preflight, _commands, _integrity = _stage_fixture(
        tmp_path, monkeypatch, handoff
    )
    license_bytes = b"FSL fixture"
    artifact_contract, node22, node24, _artifact_sha = _external_receipts(
        stage_dir, handoff, license_bytes
    )
    candidate = tmp_path / "candidate"
    monkeypatch.setattr(handoff, "_trusted_run_identity", _workflow)
    monkeypatch.setattr(handoff, "_toolchain", lambda _root: preflight["toolchain"])
    monkeypatch.setattr(handoff, "_recheck_source", lambda *_args, **_kwargs: candidate)

    def mismatched_identity(path: Path) -> tuple[dict[str, Any], bytes]:
        assert path.parent.name.startswith(".bundle.tmp-")
        package = {
            "name": "kaji-sdk",
            "version": "0.2.0-beta.7",
            "exports": _exports(),
        }
        selected_license = license_bytes
        if mismatch == "package":
            package["version"] = "0.2.0-beta.2"
        elif mismatch == "exports":
            package["exports"] = {".": _exports()["."]}
        else:
            selected_license = b"wrong license"
        return package, selected_license

    monkeypatch.setattr(handoff, "_verify_archive_identity", mismatched_identity)
    output = tmp_path / "bundle"
    with pytest.raises(handoff.HandoffError, match="VALIDATION_FAILED"):
        handoff.finalize(
            mode="internal-evaluation",
            candidate_root=candidate,
            preflight_path=preflight_path,
            stage_dir=stage_dir,
            artifact_contract_path=artifact_contract,
            node22_path=node22,
            node24_path=node24,
            output_dir=output,
        )
    assert not output.exists()
    assert not (preflight_path.parent / "receipt-set").exists()
    assert not list(tmp_path.glob(".bundle.tmp-*"))


def _rewrite_staged_receipt(
    stage_dir: Path, handoff: Any, filename: str, document: dict[str, Any]
) -> None:
    encoded = handoff._canonical_json(document)
    (stage_dir / filename).write_bytes(encoded)
    index_path = stage_dir / handoff.STAGE_INDEX_NAME
    index = json.loads(index_path.read_text())
    entry = next(item for item in index["receipts"] if item["filename"] == filename)
    entry["sha256"] = hashlib.sha256(encoded).hexdigest()
    index_path.write_bytes(handoff._canonical_json(index))


@pytest.mark.parametrize(
    ("mode", "mutation"),
    [
        ("internal-evaluation", "release-pack"),
        ("release", "internal-pack"),
        ("release", "registry"),
        ("internal-evaluation", "package-version"),
        ("internal-evaluation", "artifact-filename"),
        ("internal-evaluation", "artifact-size"),
        ("internal-evaluation", "artifact-integrity"),
        ("internal-evaluation", "artifact-digest"),
        ("internal-evaluation", "toolchain"),
        ("internal-evaluation", "raw-source-digest"),
        ("internal-evaluation", "source-tree"),
        ("internal-evaluation", "trusted-verifier"),
    ],
)
def test_finalize_binds_pack_and_source_evidence_to_preflight_stage_and_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    mutation: str,
) -> None:
    handoff = _handoff_module()
    preflight_path, stage_dir, preflight, _commands, _integrity = _stage_fixture(
        tmp_path, monkeypatch, handoff, mode=mode
    )
    pack_path = stage_dir / handoff.PACK_RECEIPT_NAME
    pack = json.loads(pack_path.read_text())
    if mutation == "release-pack":
        pack["evidence"]["mode"] = "release"
        pack["evidence"]["registry"] = {"status": "version-unused"}
    elif mutation == "internal-pack":
        pack["evidence"]["mode"] = "internal-evaluation"
        pack["evidence"]["registry"] = {"status": "not-claimed"}
    elif mutation == "registry":
        pack["evidence"]["registry"] = {"status": "not-claimed"}
    elif mutation == "package-version":
        pack["evidence"]["package"]["version"] = "0.2.0-beta.2"
    elif mutation == "artifact-filename":
        pack["evidence"]["artifact"]["filename"] = "kaji-sdk-0.2.0-beta.2.tgz"
    elif mutation == "artifact-size":
        pack["evidence"]["artifact"]["size"] += 1
    elif mutation == "artifact-integrity":
        pack["evidence"]["artifact"]["npmIntegrity"] = (
            "sha512-"
            + base64.b64encode(hashlib.sha512(b"different artifact").digest()).decode()
        )
    elif mutation == "artifact-digest":
        pack["artifactSha256"] = "d" * 64
    elif mutation == "toolchain":
        pack["evidence"]["toolchain"]["node"] = "24.12.0"
    if mutation in {
        "release-pack",
        "internal-pack",
        "registry",
        "package-version",
        "artifact-filename",
        "artifact-size",
        "artifact-integrity",
        "artifact-digest",
        "toolchain",
    }:
        _rewrite_staged_receipt(stage_dir, handoff, handoff.PACK_RECEIPT_NAME, pack)
    else:
        source_path = stage_dir / handoff.SOURCE_RECEIPT_NAME
        signature_path = stage_dir / handoff.SIGNATURE_RECEIPT_NAME
        source = json.loads(source_path.read_text())
        signature = json.loads(signature_path.read_text())
        if mutation == "raw-source-digest":
            source["evidence"]["rawResultSha256"] = "f" * 64
            _rewrite_staged_receipt(
                stage_dir, handoff, handoff.SOURCE_RECEIPT_NAME, source
            )
        elif mutation == "source-tree":
            source["evidence"]["treeSha"] = "6" * 40
            signature["evidence"]["treeSha"] = "6" * 40
            _rewrite_staged_receipt(
                stage_dir, handoff, handoff.SOURCE_RECEIPT_NAME, source
            )
            _rewrite_staged_receipt(
                stage_dir, handoff, handoff.SIGNATURE_RECEIPT_NAME, signature
            )
        else:
            source["evidence"]["trustedVerifierCommit"] = "7" * 40
            signature["evidence"]["verifierCommit"] = "7" * 40
            _rewrite_staged_receipt(
                stage_dir, handoff, handoff.SOURCE_RECEIPT_NAME, source
            )
            _rewrite_staged_receipt(
                stage_dir, handoff, handoff.SIGNATURE_RECEIPT_NAME, signature
            )

    license_bytes = b"FSL fixture"
    artifact_contract, node22, node24, _artifact_sha = _external_receipts(
        stage_dir, handoff, license_bytes, mode=mode
    )
    candidate = tmp_path / "candidate"
    monkeypatch.setattr(handoff, "_trusted_run_identity", _workflow)
    monkeypatch.setattr(handoff, "_toolchain", lambda _root: preflight["toolchain"])
    monkeypatch.setattr(handoff, "_recheck_source", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        handoff,
        "_verify_archive_identity",
        lambda _path: (
            {
                "name": "kaji-sdk",
                "version": "0.2.0-beta.7",
                "exports": _exports(),
            },
            license_bytes,
        ),
    )
    output = tmp_path / "bundle"
    with pytest.raises(handoff.HandoffError, match="RECEIPT_INVALID"):
        handoff.finalize(
            mode=mode,
            candidate_root=candidate,
            preflight_path=preflight_path,
            stage_dir=stage_dir,
            artifact_contract_path=artifact_contract,
            node22_path=node22,
            node24_path=node24,
            output_dir=output,
        )
    assert not output.exists()
    assert not (preflight_path.parent / "receipt-set").exists()
    assert not list(tmp_path.glob(".bundle.tmp-*"))


def test_finalize_rejects_cross_receipt_digest_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff_module()
    preflight_path, stage_dir, preflight, _commands, _integrity = _stage_fixture(
        tmp_path, monkeypatch, handoff
    )
    license_bytes = b"FSL fixture"
    artifact_contract, node22, node24, _artifact_sha = _external_receipts(
        stage_dir, handoff, license_bytes
    )
    mutated = json.loads(node24.read_text())
    mutated["artifactSha256"] = "f" * 64
    node24.write_bytes(handoff._canonical_json(mutated))
    monkeypatch.setattr(handoff, "_trusted_run_identity", _workflow)
    monkeypatch.setattr(handoff, "_toolchain", lambda _root: preflight["toolchain"])
    monkeypatch.setattr(
        handoff, "_recheck_source", lambda *_args, **_kwargs: tmp_path / "candidate"
    )
    with pytest.raises(handoff.HandoffError, match="RECEIPT_INVALID"):
        handoff.finalize(
            mode="internal-evaluation",
            candidate_root=tmp_path / "candidate",
            preflight_path=preflight_path,
            stage_dir=stage_dir,
            artifact_contract_path=artifact_contract,
            node22_path=node22,
            node24_path=node24,
            output_dir=tmp_path / "bundle",
        )
    assert not (tmp_path / "bundle").exists()
    assert not (preflight_path.parent / "receipt-set").exists()


def test_atomic_paths_preserve_existing_output_and_clean_cross_device_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff_module()
    existing = tmp_path / "existing.json"
    existing.write_text("owned")
    with pytest.raises(handoff.HandoffError, match="OUTPUT_EXISTS"):
        handoff._atomic_file(existing, b"replacement")
    assert existing.read_text() == "owned"

    output = tmp_path / "new.json"

    def cross_device(_source: Path, _destination: Path) -> None:
        raise OSError(18, "cross-device")

    monkeypatch.setattr(handoff, "_rename_noreplace", cross_device)
    with pytest.raises(handoff.HandoffError, match="INTERNAL_ERROR"):
        handoff._atomic_file(output, b"payload")
    assert not output.exists()
    assert not list(tmp_path.glob(".new.json.tmp-*"))


def test_failure_documents_are_closed_and_token_free() -> None:
    handoff = _handoff_module()
    failure = handoff._failure_document(
        "stage",
        handoff.HandoffError(
            "PACK_FAILED", source_commit=HEAD, artifact_sha256=ARTIFACT_SHA256
        ),
    )
    _fragment_validator(_schema(), "failure").validate(failure)
    assert set(failure) == {
        "schemaVersion",
        "command",
        "result",
        "failureCode",
        "sourceCommit",
        "artifactSha256",
    }
    assert "token" not in json.dumps(failure).lower()
