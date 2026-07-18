"""Closed-schema contract tests for the TypeScript consumer handoff."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import runpy
from typing import Any

import pytest
from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_RELATIVE = "release/kaji-ts-consumer-handoff-v1.schema.json"
CANONICAL_SCHEMA = REPO_ROOT / "kaji" / "contracts" / SCHEMA_RELATIVE
SCHEMA_MIRRORS = (
    REPO_ROOT / "kaji" / "src" / "kaji" / "contracts" / SCHEMA_RELATIVE,
    REPO_ROOT / "kaji" / "ts" / "contracts" / SCHEMA_RELATIVE,
)
CONTRACT_CHECK = REPO_ROOT / "kaji" / "scripts" / "check_beta_contract.py"

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


def _fragment_validator(
    schema: dict[str, Any], definition: str
) -> Draft202012Validator:
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
        "package": {"name": "@kaji/sdk", "version": "0.2.0"},
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
        "testFile": "kaji/ts/tests/github-client.test.ts",
        "testName": "rejects-before-token-lookup",
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
            "id": "PolyForm-Noncommercial-1.0.0",
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
        "commercialUseClaim": "not-approved",
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
            "name": "@kaji/sdk",
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
            "id": "PolyForm-Noncommercial-1.0.0",
            "file": "LICENSE",
            "sha256": LICENSE_SHA256,
            "commercialUseApproved": False,
            "intendedUse": "internal-evaluation-only",
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
    if name != "@kaji/sdk":
        raise ValueError("unexpected package name")
    if not _independent_alias_valid(schema, "semver", version):
        raise ValueError("invalid package version")
    return f"{name.removeprefix('@').replace('/', '-')}-{version}.tgz"


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
            derived = _npm_pack_basename_v1(schema, "@kaji/sdk", case["value"])
            assert derived == case["basename"]
            assert basename.is_valid(derived)
        else:
            assert "basename" not in case
            assert not _independent_alias_valid(schema, "semver", case["value"])
            with pytest.raises(ValueError, match="invalid package version"):
                _npm_pack_basename_v1(schema, "@kaji/sdk", case["value"])

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
