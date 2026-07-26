from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PERFORMANCE = WORKFLOWS / "kaji.performance.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_reusable_performance_workflow_runs_three_independent_replicas() -> None:
    workflow = _read(PERFORMANCE)

    assert "workflow_call:" in workflow
    preflight = workflow.split("  candidate-artifact:", 1)[1].split(
        "  paired-replica:", 1
    )[0]
    for binding in (
        "getArtifact",
        "artifact.id !== Number(process.env.CANDIDATE_ARTIFACT_ID)",
        'artifact.name !== "kaji-beta-artifacts"',
        "artifact.expired",
        "`sha256:${process.env.CANDIDATE_ARTIFACT_DIGEST}`",
        "artifact.workflow_run?.id !== context.runId",
        "artifact.workflow_run?.head_sha !== process.env.KAJI_RELEASE_COMMIT",
        '"X-GitHub-Api-Version": "2026-03-10"',
        'process.env.RUN_PAIRED !== "true" && process.env.RUN_SOAK !== "true"',
        "RUN_ATTEMPT: ${{ github.run_attempt }}",
        "const runAttempt = Number(process.env.RUN_ATTEMPT)",
        "!Number.isSafeInteger(runAttempt) || runAttempt !== 1",
        "dispatch a new workflow run",
    ):
        assert binding in preflight
    assert "GITHUB_RUN_ATTEMPT:" not in preflight
    assert "context.runAttempt" not in preflight
    assert "actions: read" in preflight

    paired = workflow.split("  paired-replica:", 1)[1].split("  paired-aggregate:", 1)[
        0
    ]
    assert "needs: candidate-artifact" in paired
    assert "runs-on: macos-15" in paired
    assert "timeout-minutes: 90" in paired
    assert "fail-fast: false" in paired
    assert "replica: [1, 2, 3]" in paired
    assert paired.count("kaji/scripts/paired_benchmark.py") == 1
    assert '--replica "${{ matrix.replica }}"' in paired
    assert '--runner-image-data "$HOME/imagedata.json"' in paired
    assert (
        'cp "$HOME/imagedata.json" '
        '"$KAJI_PAIRED_DIR/replica-${{ matrix.replica }}-imagedata.json"' in paired
    )
    assert "run-id: 30081423771" in paired
    assert "name: kaji-beta-artifacts" in paired
    assert "github-token: ${{ github.token }}" in paired
    assert "actions: read" in paired
    assert "artifact-ids: ${{ inputs.candidate-artifact-id }}" in paired


def test_paired_workflow_verifies_reference_before_default_candidate() -> None:
    workflow = _read(PERFORMANCE)
    paired = workflow.split("  paired-replica:", 1)[1].split("  paired-aggregate:", 1)[
        0
    ]
    verify_step = paired.split(
        "- name: Verify exact reference and candidate artifacts", 1
    )[1].split("- name: Measure protected paired replica", 1)[0]
    verifier = "python3 kaji/scripts/verify_release_artifacts.py"
    calls = verify_step.split(verifier)[1:]

    assert len(calls) == 2
    assert workflow.count("--artifact-contract beta2-reference") == 1
    assert "--artifacts-dir .artifacts/kaji-reference" in calls[0]
    assert "--artifact-contract beta2-reference" in calls[0]
    assert "--artifacts-dir .artifacts/kaji-candidate" in calls[1]
    assert "--artifact-contract" not in calls[1]


def test_reusable_performance_workflow_retains_raw_receipts_and_aggregates_once() -> (
    None
):
    workflow = _read(PERFORMANCE)
    paired = workflow.split("  paired-replica:", 1)[1].split("  paired-aggregate:", 1)[
        0
    ]
    aggregate = workflow.split("  paired-aggregate:", 1)[1].split("  soak:", 1)[0]

    assert "if: ${{ always() && github.run_attempt == 1 }}" in paired
    assert "name: kaji-paired-replica-${{ matrix.replica }}" in paired
    assert "if-no-files-found: error" in paired
    assert "needs: paired-replica" in aggregate
    assert "if: ${{ always() && inputs.run-paired }}" in aggregate
    assert aggregate.count("--replica-report") == 3
    assert aggregate.count("kaji/scripts/aggregate_benchmarks.py") == 1
    assert "name: kaji-paired-aggregate" in aggregate
    assert "if: ${{ always() && github.run_attempt == 1 }}" in aggregate


def test_reusable_performance_workflow_keeps_soak_independent_and_hard() -> None:
    workflow = _read(PERFORMANCE)
    soak = workflow.split("  soak:", 1)[1].split("  performance-evidence:", 1)[0]

    assert "needs: candidate-artifact" in soak
    assert "runs-on: macos-15" in soak
    assert "run_beta_soak.py" in soak
    assert "--minutes 30 --protected" in soak
    assert "continue-on-error" not in soak
    assert "name: kaji-soak-receipt" in soak
    assert "if: ${{ always() && github.run_attempt == 1 }}" in soak


def test_performance_binder_requires_paired_and_soak_candidate_identity() -> None:
    workflow = _read(PERFORMANCE)
    binder = workflow.split("  performance-evidence:", 1)[1]

    assert "needs: [paired-replica, paired-aggregate, soak]" in binder
    assert "if: ${{ always() && github.run_attempt == 1 }}" in binder
    assert "paired-benchmark-results.json" in binder
    assert "soak-results.json" in binder
    assert "releaseManifestSha256" in binder
    assert "reportReceiptSha256" in binder
    assert "candidate.artifacts.pythonWheel" in binder
    assert "candidate.artifacts.typescript" in binder
    assert "name: kaji-performance-evidence" in binder
    assert "if-no-files-found: error" in binder
    assert "raw/raw" not in binder
    assert "runnerName] | unique" not in binder


def test_replica_post_measurement_failure_cannot_produce_passed_status() -> None:
    workflow = _read(PERFORMANCE)
    aggregate = workflow.split("  paired-aggregate:", 1)[1].split("  soak:", 1)[0]
    binder = workflow.split("  performance-evidence:", 1)[1]

    assert "REPLICA_JOB_OUTCOME: ${{ needs.paired-replica.result }}" in aggregate
    assert 'if [ "$REPLICA_JOB_OUTCOME" != success ]; then' in aggregate
    assert "failure_code=paired_replica_not_passed" in aggregate

    assert "PAIRED_REPLICA_JOB_OUTCOME: ${{ needs.paired-replica.result }}" in binder
    replica_failure = 'elif [ "$PAIRED_REPLICA_JOB_OUTCOME" != success ]; then'
    aggregate_failure = 'elif [ "$PAIRED_AGGREGATE_JOB_OUTCOME" != success ]; then'
    assert replica_failure in binder
    assert binder.index(replica_failure) < binder.index(aggregate_failure)
    assert 'benchmark_outcome="$PAIRED_REPLICA_JOB_OUTCOME"' in binder


def test_every_protected_job_rejects_partial_reruns_before_work() -> None:
    workflow = _read(PERFORMANCE)
    boundaries = (
        ("paired-replica", "paired-aggregate"),
        ("paired-aggregate", "soak"),
        ("soak", "performance-evidence"),
        ("performance-evidence", None),
    )

    for job, next_job in boundaries:
        section = workflow.split(f"  {job}:", 1)[1]
        if next_job is not None:
            section = section.split(f"  {next_job}:", 1)[0]
        guard = section.index("- name: Reject protected rerun attempt")
        initialize = section.index("- name: Initialize")
        assert guard < initialize
        assert "if: ${{ github.run_attempt != 1 }}" in section
        assert "        if: ${{ always() }}" not in section
        assert "always() && github.run_attempt == 1" in section


def test_candidate_artifacts_are_flat_and_evidence_starts_after_checkout() -> None:
    workflow = _read(PERFORMANCE)
    boundaries = (
        ("paired-replica", "paired-aggregate"),
        ("paired-aggregate", "soak"),
        ("soak", "performance-evidence"),
    )

    for job, next_job in boundaries:
        section = workflow.split(f"  {job}:", 1)[1].split(f"  {next_job}:", 1)[0]
        rerun_rejection = section.index("- name: Reject protected rerun attempt")
        checkout = section.index("- id: checkout")
        initialize = section.index("- name: Initialize")
        initialization = section[initialize:].split("\n      - ", 1)[0]
        assert rerun_rejection < checkout < initialize
        assert "if: ${{ always() && github.run_attempt == 1 }}" in initialization

    for job, next_job in (
        ("paired-replica", "paired-aggregate"),
        ("soak", "performance-evidence"),
    ):
        section = workflow.split(f"  {job}:", 1)[1].split(f"  {next_job}:", 1)[0]
        candidate = section.split("- name: Download immutable candidate artifact", 1)[
            1
        ].split("- name:", 1)[0]
        assert "artifact-ids: ${{ inputs.candidate-artifact-id }}" in candidate
        assert "path: .artifacts/kaji-candidate" in candidate
        assert "merge-multiple: true" in candidate


def test_authoritative_workflows_call_shared_performance_without_legacy_full_gate() -> (
    None
):
    expected_commits = {
        "kaji.benchmark.yml": "${{ needs.release-artifacts.outputs.commit }}",
        "kaji.rehearsal.yml": "${{ github.sha }}",
        "kaji.publish.yml": "${{ needs.verify-tag.outputs.commit }}",
    }
    for filename, commit in expected_commits.items():
        workflow = _read(WORKFLOWS / filename)
        assert "uses: ./.github/workflows/kaji.performance.yml" in workflow
        assert f"candidate-commit: {commit}" in workflow
        assert "candidate-artifact-id:" in workflow
        assert "candidate-artifact-digest:" in workflow
        assert "run_beta_benchmarks.py --full --protected" not in workflow
        assert "baselineFingerprint" not in workflow

    benchmark = _read(WORKFLOWS / "kaji.benchmark.yml")
    assert "calibrate" not in benchmark
    assert "run_beta_benchmarks.py" not in benchmark


def test_publish_attests_and_validates_paired_aggregate_and_soak_receipts() -> None:
    publish = _read(WORKFLOWS / "kaji.publish.yml")

    assert (
        "--benchmark-results "
        ".artifacts/kaji-evidence/paired-benchmark-results.json" in publish
    )
    assert ".artifacts/kaji-evidence/paired-benchmark-results.json" in publish
    assert ".artifacts/kaji-evidence/soak-results.json" in publish
    assert ".artifacts/kaji-evidence/raw/benchmarks/replica-1.json" in publish
    assert ".artifacts/kaji-evidence/raw/benchmarks/replica-2.json" in publish
    assert ".artifacts/kaji-evidence/raw/benchmarks/replica-3.json" in publish
    for replica in (1, 2, 3):
        assert (
            f".artifacts/kaji-evidence/raw/benchmarks/"
            f"replica-{replica}-imagedata.json" in publish
        )


def test_paired_protocol_hash_covers_workflow_and_setup_inputs() -> None:
    script = _read(ROOT / "kaji" / "scripts" / "paired_benchmark.py")

    for path in (
        ".github/workflows/kaji.performance.yml",
        ".github/actions/setup-python-uv/action.yml",
        ".github/actions/setup-bun-cache/action.yml",
    ):
        assert f'Path("{path}")' in script


def test_release_evidence_validator_consumes_paired_aggregate_not_numeric_baseline() -> (
    None
):
    validator = _read(ROOT / "kaji" / "scripts" / "validate_release_evidence.py")

    assert "kaji-beta-paired-benchmark-aggregate" in validator
    assert "validate_paired_benchmark" in validator
    assert "baselineFingerprint" not in validator
