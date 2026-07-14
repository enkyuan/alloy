"""Executable contract checks for the production-beta documentation."""

from __future__ import annotations

import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs" / "kaji"
PRODUCTION_BETA = DOCS / "production-beta.md"
MIGRATION = DOCS / "migrating-to-beta.md"
CONTRACT = REPO_ROOT / "kaji" / "contracts" / "beta-core-v1.json"
INDEX_SCHEMA = REPO_ROOT / "kaji" / "contracts" / "integrations" / "index.schema.json"
MANIFEST_SCHEMA = (
    REPO_ROOT / "kaji" / "contracts" / "integrations" / "manifest.schema.json"
)


def _snippet(path: Path, name: str, language: str) -> str:
    text = path.read_text()
    match = re.search(
        rf"<!-- {re.escape(name)}:start -->\s*```{language}\n(.*?)\n```\s*"
        rf"<!-- {re.escape(name)}:end -->",
        text,
        flags=re.DOTALL,
    )
    assert match is not None, f"missing {name} in {path}"
    return match.group(1)


def test_exact_installed_python_quickstart_runs() -> None:
    source = _snippet(PRODUCTION_BETA, "installed-quickstart:python", "python")
    assert "kaji.ToolExecutionContext" in source
    assert "kaji.ToolContext" not in source
    exec(compile(source, str(PRODUCTION_BETA), "exec"), {"__name__": "__main__"})


def test_python_migration_examples_execute() -> None:
    names = (
        "docs-test:python-migration-after",
        "docs-test:python-approval-after",
        "docs-test:python-risk-context-before",
        "docs-test:python-risk-context-after",
        "docs-test:python-cursor-before",
        "docs-test:python-cursor-after",
    )
    for name in names:
        source = _snippet(MIGRATION, name, "python")
        exec(compile(source, f"{MIGRATION}:{name}", "exec"), {"__name__": "__main__"})


def test_manifest_and_index_migrations_are_executable_contract_cases() -> None:
    manifest_before = json.loads(
        _snippet(MIGRATION, "docs-test:manifest-before", "json")
    )
    manifest_after = json.loads(_snippet(MIGRATION, "docs-test:manifest-after", "json"))
    index_before = json.loads(_snippet(MIGRATION, "docs-test:index-before", "json"))
    index_after = json.loads(_snippet(MIGRATION, "docs-test:index-after", "json"))
    manifest_validator = Draft202012Validator(
        json.loads(MANIFEST_SCHEMA.read_text()), format_checker=FormatChecker()
    )
    index_validator = Draft202012Validator(
        json.loads(INDEX_SCHEMA.read_text()), format_checker=FormatChecker()
    )

    assert list(manifest_validator.iter_errors(manifest_before))
    assert list(manifest_validator.iter_errors(manifest_after)) == []
    assert list(index_validator.iter_errors(index_before))
    assert list(index_validator.iter_errors(index_after)) == []


def test_rendered_default_table_matches_machine_contract() -> None:
    contract = json.loads(CONTRACT.read_text())
    text = PRODUCTION_BETA.read_text()
    expected_rows = (
        f"| Tool iterations per turn | {contract['runtime']['maxToolIterations']} |",
        f"| Complete context turns | {contract['runtime']['contextWindowTurns']} |",
        f"| Context characters | {contract['runtime']['contextWindowCharacters']:,} |",
        f"| Turn work timeout | {contract['runtime']['turnTimeoutMs'] // 1000} seconds |",
        f"| Provider cancellation grace | {contract['runtime']['providerCancellationGraceMs'] // 1000} seconds |",
        f"| Provider text | {contract['runtime']['providerTextMaxBytes']:,} UTF-8 bytes |",
        f"| Provider tool arguments | {contract['runtime']['providerToolArgumentsMaxBytes']:,} UTF-8 bytes |",
        f"| Provider response | {contract['runtime']['providerResponseMaxBytes']:,} UTF-8 bytes |",
        f"| Provider tool calls | {contract['runtime']['providerToolCallsMax']:,} |",
        f"| Parallel tool handlers | {contract['tools']['maxConcurrency']} |",
        f"| Tool queue-to-completion timeout | {contract['tools']['timeoutMs'] // 1000} seconds |",
        f"| Approval timeout | {contract['tools']['approvalTimeoutMs'] // 1000} seconds |",
        f"| Subscriber queue | {contract['events']['subscriberQueueCapacity']:,} events |",
        f"| Durable tool arguments | {contract['events']['maxDurableToolArgumentBytes']:,} UTF-8 bytes |",
        f"| Durable tool results | {contract['events']['maxDurableToolResultBytes']:,} UTF-8 bytes |",
        f"| Durable event | {contract['events']['maxDurableEventBytes']:,} UTF-8 bytes |",
        f"| In-memory sessions | {contract['events']['inMemoryStoreMaxSessions']:,} |",
        f"| Events per in-memory session | {contract['events']['inMemoryStoreMaxEventsPerSession']:,} |",
        f"| Idempotency entries | {contract['tools']['idempotencyMaxEntries']:,} |",
        f"| Completed idempotency TTL | {contract['tools']['idempotencyCompletedTtlSeconds']:,} seconds |",
    )
    for row in expected_rows:
        assert row in text
    assert "runtime.effective_limits()" in text
    assert "runtime.effectiveLimits()" in text
    assert "EffectiveRuntimeLimits" in text
    assert "from kaji.runtime.agents import AgentStrategy, ContextWindow" in text


def test_post_beta_migration_uses_the_canonical_tool_context_type() -> None:
    after = _snippet(MIGRATION, "docs-test:python-risk-context-after", "python")

    assert "kaji.ToolExecutionContext" in after
    assert "kaji.ToolContext" not in after


def test_task16_docs_cover_the_operating_contract_without_promotion_claims() -> None:
    required = {
        "README.md",
        "api-parity.md",
        "cli.md",
        "production-beta.md",
        "concurrency-and-ordering.md",
        "tool-contracts.md",
        "integration-manifests.md",
        "migrating-to-beta.md",
        "releasing.md",
        "testing.md",
        "troubleshooting.md",
    }
    assert required.issubset({path.name for path in DOCS.glob("*.md")})
    combined = "\n".join((DOCS / name).read_text() for name in sorted(required))
    for phrase in (
        "same session",
        "sequence order",
        "process-local",
        "complete turns",
        "Draft 2020-12",
        "unknown outcome",
        "idempotency",
        "Subscriber overflow",
        "Echo is the only beta",
        "experimental",
        "30-minute soak",
        "Zod 4",
        "Removed pre-beta compatibility",
    ):
        assert phrase.lower() in combined.lower()

    repository_status_docs = [
        REPO_ROOT / "kaji" / "RELEASE_MATRIX.md",
        REPO_ROOT / "kaji" / "CHANGELOG.md",
        REPO_ROOT / "kaji" / "ts" / "CHANGELOG.md",
        REPO_ROOT / "docs" / "MVP.md",
    ]
    status = "\n".join(path.read_text() for path in repository_status_docs)
    assert "production beta candidate" not in status.lower()
    assert "beta candidate for the core" not in status.lower()
    assert "ToolPlanner.execute_scatter_gather" not in status
    assert "ToolPlanner.executeScatterGather" not in status
    assert "promotion is blocked" in status.lower()


def test_package_readmes_have_permanent_status_neutral_canonical_links() -> None:
    expected = (
        "> Canonical documentation: "
        "https://github.com/enkyuan/alloy/blob/main/docs/kaji/README.md\n"
        "> Release status and evidence: "
        "https://github.com/enkyuan/alloy/blob/main/kaji/RELEASE_MATRIX.md"
    )
    blocks: list[str] = []
    for path in (
        REPO_ROOT / "kaji" / "README.md",
        REPO_ROOT / "kaji" / "ts" / "README.md",
    ):
        text = path.read_text()
        marker = re.search(
            r"<!-- canonical-status-links:start -->\n(.*?)\n"
            r"<!-- canonical-status-links:end -->",
            text,
            re.DOTALL,
        )
        assert marker is not None
        blocks.append(marker.group(1))
        assert "> **Status:**" not in text
        assert "promotion is blocked" not in text.lower()
        assert "pre-beta release implementation" not in text.lower()
        assert re.search(r"\]\(\.\./", text) is None
    assert blocks == [expected, expected]

    typescript_readme = (REPO_ROOT / "kaji" / "ts" / "README.md").read_text()
    assert "Node 22 or 24" in typescript_readme
    assert "Node 22+" not in typescript_readme
    assert "TypeScript 5.7" in typescript_readme
    assert "current TypeScript 6" in typescript_readme


def test_trust_and_feedback_surfaces_are_complete() -> None:
    security = (REPO_ROOT / "SECURITY.md").read_text()
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text()
    support = (REPO_ROOT / "SUPPORT.md").read_text()
    issue = (REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "kaji-sdk-bug.yml").read_text()

    for phrase in ("private", "supported beta versions", "response", "redact"):
        assert phrase in security.lower()
    for phrase in ("stable", "experimental", "local checks"):
        assert phrase in contributing.lower()
    for phrase in ("best effort", "support boundary", "30-day"):
        assert phrase in support.lower()
    for phrase in (
        "SDK language",
        "SDK version",
        "runtime",
        "compiler",
        "package manager",
        "operating system",
        "minimal reproduction",
        "error code",
        "redacted event excerpt",
    ):
        assert phrase.lower() in issue.lower()


def test_maintained_public_docs_reject_pre_beta_contract_guidance() -> None:
    paths = (
        REPO_ROOT / "apps" / "docs" / "content" / "getting-started.mdx",
        REPO_ROOT / "apps" / "docs" / "content" / "install.mdx",
        REPO_ROOT / "apps" / "docs" / "content" / "cli.mdx",
        REPO_ROOT / "apps" / "docs" / "content" / "troubleshooting.mdx",
        REPO_ROOT / "apps" / "docs" / "content" / "concepts" / "runtime.mdx",
        REPO_ROOT / "apps" / "docs" / "content" / "concepts" / "tool-registry.mdx",
        REPO_ROOT / "kaji" / "README.md",
        REPO_ROOT / "apps" / "docs" / "content" / "architecture.mdx",
    )
    combined = "\n".join(path.read_text() for path in paths).lower()
    for stale in (
        "risk=none",
        "responsetext",
        "same cli commands",
        "matching cli commands",
        "both clis expose the same",
        "all independent calls execute concurrently",
        "all tool calls execute concurrently",
        "unbounded scatter-gather",
        "in-memory bus + store",
        "zod as a runtime dependency",
        "runtime dependency on zod",
    ):
        assert stale not in combined

    getting_started = paths[0].read_text()
    assert 'bun add @kaji/sdk "zod@>=4.3 <5"' in getting_started
    assert "peer dependency" in getting_started
    assert 'risk="read"' in getting_started
    assert 'risk: "read"' in getting_started
    assert "principal_id=" in getting_started
    assert "principalId:" in getting_started
    getting_started_compact = " ".join(getting_started.split())
    assert (
        "`AgentBuilder` wires a provider and tools to the runtime's event "
        "journal/committer" in getting_started_compact
    )
    assert "in-memory bus + store" not in getting_started

    cli = paths[2].read_text()
    for heading in (
        "Python SDK CLI",
        "Embedded TypeScript SDK CLI",
        "Standalone cross-language CLI",
    ):
        assert heading in cli
    assert re.search(r"\|\s*`add`\s*\|\s*Yes\s*\|\s*Yes\s*\|\s*No\s*\|", cli)
    assert re.search(r"\|\s*`replay`\s*\|\s*No\s*\|\s*Yes\s*\|\s*No\s*\|", cli)
    assert re.search(r"\|\s*`mcp`\s*\|\s*No\s*\|\s*No\s*\|\s*Status only", cli)

    tool_registry = paths[5].read_text()
    assert "sequentially by default" in tool_registry
    assert "parallel_safe" in tool_registry
    assert "immutable `ToolExecutionContext`" in tool_registry

    architecture = paths[-1].read_text()
    architecture_compact = " ".join(architecture.split())
    assert "execute tool calls sequentially by default" in architecture_compact
    assert "marked `parallel_safe` may overlap" in architecture_compact
    assert "bounded by the configured tool concurrency" in architecture_compact
    assert "execute tool calls scatter-gather" not in architecture_compact
    assert "run concurrently" not in architecture_compact


def test_release_smokes_execute_the_marked_quickstart_blocks() -> None:
    python_smoke = (REPO_ROOT / "kaji" / "scripts" / "smoke_install.py").read_text()
    ts_smoke = (REPO_ROOT / "kaji" / "ts" / "scripts" / "smoke_package.mts").read_text()
    assert "installed-quickstart:python:start" in python_smoke
    assert "exec(compile(match.group(1)" in python_smoke
    assert "installed-quickstart:typescript:start" in ts_smoke
    assert re.search(
        r'runCommand\(\s*"docs:compile-typescript-current",\s*nodeBinary,\s*'
        r'\[\s*tsc,\s*"--project",\s*"tsconfig\.docs\.json"\s*,?\s*\]\s*\)',
        ts_smoke,
    )
    assert re.search(
        r'runCommand\(\s*"docs:run",\s*nodeBinary,\s*'
        r'\[\s*"compiled-docs/docs-quickstart\.mjs"\s*\]\s*\)',
        ts_smoke,
    )
