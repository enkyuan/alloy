from __future__ import annotations

import re
import subprocess
import sys
import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text()


def _assert_external_actions_are_sha_pinned(workflow: str) -> None:
    references = re.findall(r"^\s*(?:-\s*)?uses: ([^\s#]+)", workflow, re.MULTILINE)
    external = [reference for reference in references if not reference.startswith("./")]
    assert external
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) for reference in external)
    assert not any(
        re.search(r"@(main|master|release/|v\d)", reference) for reference in external
    )


def test_ci_uses_real_package_smokes_and_supported_runtime_matrix() -> None:
    python = _read(".github/workflows/python.test.yml")
    ts = _read(".github/workflows/ts.test.yml")
    lint = _read(".github/workflows/ts.lint.yml")

    assert "scripts/verify_wheel.sh" in python
    assert "verify_wheel_contents.sh" not in python
    assert 'python-version: "3.11"' in python
    assert 'python-version: "3.14"' in python
    assert "scripts/smoke-installed.mts" in ts
    assert "smoke-install.mts" not in ts
    assert 'node-version: ["22", "24"]' in ts
    for command in (
        "bun run format:check",
        "bun run lint",
        "bun run typecheck:registry",
        "bun run validate:registry",
        "bun run check:integrations",
    ):
        assert command in lint


def test_release_gate_runs_package_metadata_and_supply_chain_checks() -> None:
    script = _read("kaji/scripts/beta-release-check.sh")

    for expected in (
        "--release",
        "uv run ruff format --check src tests",
        "uv run pip-audit",
        "--extra openai --extra anthropic",
        "--requirement build-requirements.txt",
        "bun audit --production",
        "bun x publint",
        "bun x attw --pack .",
        "verify-package-metadata.py",
        "verify_npm_package.py",
        'bun scripts/smoke-installed.mts "$TARBALL"',
        "Reverify final Python artifacts",
        "bun run package:smoke",
        "bun run typecheck:registry",
        "bun run validate:registry",
        "bun run check:integrations",
    ):
        assert expected in script

    metadata_verifier = _read("kaji/scripts/verify-package-metadata.py")
    assert '"buildAudit": {' in metadata_verifier
    assert '"file": "kaji/sdk/build-requirements.txt"' in metadata_verifier
    assert '"sha256": sha256(build_audit)' in metadata_verifier
    assert "verify_npm_tarball(npm_tarball, repo)" in metadata_verifier

    npm_verifier = _read("kaji/scripts/verify_npm_package.py")
    for expected in (
        "npm tarball member set differs from checkout",
        "npm tarball file differs from checkout",
        "npm packaged contracts differ from canonical shared contracts",
        "npm package target is missing or outside dist/",
        "npm registry manifest is missing",
    ):
        assert expected in npm_verifier

    installed_smoke = _read("kaji/ts/scripts/smoke-installed.mts")
    for expected in (
        '"openai@6.42.0"',
        '"@anthropic-ai/sdk@0.104.1"',
        '"audit", "--omit=dev", "--audit-level=high"',
    ):
        assert expected in installed_smoke


def test_protected_release_workflows_fail_closed_and_attach_provenance() -> None:
    rehearsal = _read(".github/workflows/kaji.beta.yml")
    publish = _read(".github/workflows/kaji.beta-publish.yml")

    assert "environment: kaji-beta" in rehearsal
    assert "OPENAI_API_KEY" in rehearsal
    assert "ANTHROPIC_API_KEY" in rehearsal
    assert "live-provider-proof.sh" in rehearsal
    assert "needs: [offline-release, python-compat, node-compat]" in rehearsal
    assert "needs.offline-release.result == 'success'" in rehearsal
    assert "needs.python-compat.result == 'success'" in rehearsal
    assert "needs.node-compat.result == 'success'" in rehearsal
    assert "group: kaji-beta-rehearsal-0.2.0-beta.1" in rehearsal
    assert "offline-gate-summary.json" in rehearsal
    assert "if: ${{ always() }}" in rehearsal
    _assert_external_actions_are_sha_pinned(rehearsal)
    for expected in (
        "verification.verified",
        "environment: kaji-beta",
        "environment: kaji-beta-publish",
        "pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b",
        "npm publish",
        "--provenance",
        "actions/attest-build-provenance@e8998f949152b193b063cb0ec769d69d929409be",
        "SHA256SUMS",
        "sbom",
        "run-beta-benchmarks.sh --full",
        "live-provider-proof.sh",
        "group: kaji-beta-publish-${{ github.ref_name }}",
        "KAJI_RELEASE_SIGNER_EMAIL",
        'verification.reason !== "valid"',
        "tag.data.tag !== tagName",
        "signed beta tagger is not repository-approved",
        'core.setOutput("tag-object", tagObject)',
        'core.setOutput("commit", tag.data.object.sha)',
        "Revalidate downloaded filenames, sizes, hashes, and commit",
        "offline-gate-summary.json",
        "offline-gates.log",
        "steps.provenance.outputs.bundle-path",
        "steps.provenance.outputs.attestation-id",
        "steps.provenance.outputs.attestation-url",
        "provenance.bundle.jsonl",
        "provenance.json",
        "partial_or_ambiguous",
        "github.run_attempt == 1",
        "publisher-preflight:",
        "NPM_TOKEN is required",
        "npm access list packages",
        "verify-release-artifacts.py",
        "verify_npm_package.py",
        "verify_wheel.sh",
        "Rebuild and verify exact package contents against the clean checkout",
        "Reverify Python archive contents against the clean checkout",
        "Rebuild and verify npm archive contents against the clean checkout",
        "verify-published-packages.py",
        "--attempts 8 --initial-delay 2 --max-delay 20",
        "attach-release-assets.py",
        "registry-verification.json",
    ):
        assert expected in publish
    assert (
        publish.count("Revalidate downloaded filenames, sizes, hashes, and commit") == 3
    )
    assert publish.count("uses: ./.github/actions/verify-kaji-beta-tag") == 3
    assert publish.count("environment: kaji-beta-publish") == 3
    assert (
        publish.count(
            "needs: [verify-tag, supply-chain, registry-preflight, publisher-preflight]"
        )
        == 2
    )
    assert "needs: [verify-tag, supply-chain, publication-status]" in publish
    assert "if-no-files-found: error" in publish
    assert "--clobber" not in publish
    for reverify, mutation in (
        (
            "Reverify signed tag immediately before PyPI publication",
            "Publish exact Python beta through trusted publishing",
        ),
        (
            "Reverify signed tag immediately before npm publication",
            "Publish exact npm beta with provenance",
        ),
        (
            "Reverify signed tag immediately before release attachment",
            "Create or verify prerelease and attach only missing digest-matched assets",
        ),
    ):
        between = publish.split(reverify, 1)[1].split(mutation, 1)[0]
        assert between.count("uses: ./.github/actions/verify-kaji-beta-tag") == 1
        assert between.count("      - name:") == 1
    assert (
        "needs: [verify-tag, offline-gates, performance, python-compat, node-compat]"
        in publish
    )
    assert (
        "needs: [verify-tag, offline-gates, performance, keyed-proof, python-compat, node-compat]"
        in publish
    )
    for dependency in (
        "verify-tag",
        "offline-gates",
        "performance",
        "keyed-proof",
        "python-compat",
        "node-compat",
    ):
        assert f"needs.{dependency}.result == 'success'" in publish
    _assert_external_actions_are_sha_pinned(publish)

    attach = _read("kaji/scripts/attach-release-assets.py")
    assert "unexpected = set(existing) - set(desired)" in attach
    assert "set(final_assets) != set(desired)" in attach
    assert re.search(r'"gh",\s*"release",\s*"upload"', attach)
    assert "--clobber" not in attach
    assert "release asset digest mismatch" in attach
    assert 'prefix="kaji-release-final-"' in attach
    assert attach.count("verify_remote_asset(") >= 3

    registry = _read("kaji/scripts/verify-published-packages.py")
    assert "PyPI digest/size mismatch" in registry
    assert "downloaded npm tarball differs from manifest" in registry
    assert "downloaded npm tarball fails registry integrity" in registry
    assert "time.sleep(delay)" in registry
    assert "VerificationMismatch," in registry
    for evidence_field in (
        '"manifestCommit"',
        '"packages"',
        '"filename"',
        '"sha256"',
        '"size"',
        '"integrity"',
    ):
        assert evidence_field in registry

    artifact_verifier = _read("kaji/scripts/verify-release-artifacts.py")
    assert (
        'EXPECTED_BUILD_AUDIT = "kaji/sdk/build-requirements.txt"' in artifact_verifier
    )
    assert 'set(build_audit) != {"file", "sha256"}' in artifact_verifier

    tag_verifier = _read(".github/actions/verify-kaji-beta-tag/action.yml")
    assert "using: composite" in tag_verifier
    assert ".verification.verified == true" in tag_verifier
    assert '.verification.reason == "valid"' in tag_verifier
    assert ".tag == $tag" in tag_verifier
    assert ".tagger.email == $tagger" in tag_verifier
    assert "EXPECTED_TAGGER_EMAIL" in tag_verifier
    assert '.object.type == "commit" and .object.sha == $commit' in tag_verifier


def test_release_composite_actions_are_sha_pinned() -> None:
    for relative in (
        ".github/actions/setup-python-uv/action.yml",
        ".github/actions/setup-bun-cache/action.yml",
    ):
        _assert_external_actions_are_sha_pinned(_read(relative))


def test_release_runbook_has_fail_closed_rollback_contract() -> None:
    runbook = _read("docs/kaji/releasing.md")

    for expected in (
        "signed beta tag",
        "protected `kaji-beta` environment",
        "yank",
        "npm deprecate",
        "preserve",
        "never reuse",
        "No keyed provider or publisher evidence is claimed",
        "`kaji-beta-publish`",
        "Protect `kaji-v*-beta.*` tags against update and deletion",
        "annotated tag object SHA",
        "never click **Re-run failed jobs**",
        "partial_or_ambiguous",
        "never reuse either old version",
        "npm deprecate @kaji/sdk@0.2.0-beta.1",
        "compares every existing asset's",
        "SHA-256 digest",
        "`KAJI_RELEASE_SIGNER_EMAIL`",
        "does not claim a separately",
    ):
        assert expected in runbook


def test_release_metadata_rejects_non_commit_provenance() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "kaji/scripts/verify-package-metadata.py"),
            "--release",
            "--commit",
            "not-a-commit",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "exactly 40 hexadecimal characters" in result.stderr


def test_release_metadata_queries_and_records_actual_build_tool_versions() -> None:
    verifier = _read("kaji/scripts/verify-package-metadata.py")
    setup = _read(".github/actions/setup-python-uv/action.yml")

    assert 'version: "0.11.25"' in setup
    for command in ("bun", "node", "npm", "uv"):
        assert f'tool_version("{command}", "--version")' in verifier
        assert f'"{command}": actual_tools["{command}"]' in verifier
    assert 'BUN_VERSION = "1.3.11"' in verifier
    assert 'UV_VERSION = "0.11.25"' in verifier


def test_downloaded_release_artifact_verifier_fails_closed(tmp_path: Path) -> None:
    artifacts = tmp_path / "release"
    artifacts.mkdir()
    commit = "a" * 40
    payloads = {
        "kaji-0.2.0b1-py3-none-any.whl": b"wheel",
        "kaji-0.2.0b1.tar.gz": b"sdist",
        "kaji-sdk-0.2.0-beta.1.tgz": b"npm",
    }
    entries = []
    for name, payload in payloads.items():
        (artifacts / name).write_bytes(payload)
        package = "typescript" if name.endswith(".tgz") else "python"
        version = "0.2.0-beta.1" if package == "typescript" else "0.2.0b1"
        entries.append(
            {
                "commit": commit,
                "contractVersion": "1.0.0",
                "file": name,
                "package": package,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "version": version,
            }
        )
    manifest = {
        "schemaVersion": 1,
        "commit": commit,
        "buildTools": {
            "bun": "1.3.11",
            "editables": "0.6",
            "node": "24.4.1",
            "npm": "11.4.2",
            "setuptools": "83.0.0",
            "uv": "0.11.25",
        },
        "buildAudit": {
            "file": "kaji/sdk/build-requirements.txt",
            "sha256": hashlib.sha256(
                (REPO_ROOT / "kaji/sdk/build-requirements.txt").read_bytes()
            ).hexdigest(),
        },
        "packages": {
            "contract": "1.0.0",
            "python": "0.2.0b1",
            "typescript": "0.2.0-beta.1",
        },
        "artifacts": entries,
    }
    (artifacts / "manifest.json").write_text(json.dumps(manifest))
    (artifacts / "SHA256SUMS").write_text(
        "".join(f"{entry['sha256']}  {entry['file']}\n" for entry in entries)
    )
    command = [
        sys.executable,
        str(REPO_ROOT / "kaji/scripts/verify-release-artifacts.py"),
        "--artifacts-dir",
        str(artifacts),
        "--expected-commit",
        commit,
    ]

    assert subprocess.run(command, check=False).returncode == 0
    (artifacts / "kaji-sdk-0.2.0-beta.1.tgz").write_bytes(b"tampered")
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    assert result.returncode != 0
    assert "size/hash mismatch" in result.stderr
