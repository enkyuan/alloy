"""Executable contract checks for the production-beta documentation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

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
    escaped = re.escape(name)

    def marker(edge: str) -> str:
        return rf"(?:<!-- {escaped}:{edge} -->|\{{/\* {escaped}:{edge} \*/\}})"

    matches = re.findall(
        rf"{marker('start')}\s*```{language}\n"
        rf"(.*?)\n[ \t]*```\s*{marker('end')}",
        text,
        flags=re.DOTALL,
    )
    assert len(matches) == 1, f"expected exactly one {name} in {path}"
    return textwrap.dedent(matches[0])


def test_exact_getting_started_python_no_key_snippet_runs(tmp_path: Path) -> None:
    guide = REPO_ROOT / "apps/docs/content/getting-started.mdx"
    source = _snippet(guide, "getting-started:no-key:python", "python")
    script = tmp_path / "getting_started.py"
    script.write_text(source)
    environment = os.environ.copy()
    for name in (
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        environment.pop(name, None)
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "mock"


def test_getting_started_proves_no_key_success_before_provider_setup() -> None:
    guide = REPO_ROOT / "apps/docs/content/getting-started.mdx"
    text = guide.read_text()
    no_key = text.index("{/* getting-started:no-key:python:start */}")
    first_provider_setup = min(
        text.index("OPENAI_API_KEY"),
        text.index('get_provider("openai")'),
        text.index("new OpenAIProvider"),
    )
    assert no_key < first_provider_setup


def test_public_site_states_the_openai_only_beta_provider_boundary() -> None:
    docs_root = REPO_ROOT / "apps" / "docs"
    providers = (docs_root / "content" / "concepts" / "providers.mdx").read_text()
    install = (docs_root / "content" / "install.mdx").read_text()
    getting_started = (docs_root / "content" / "getting-started.mdx").read_text()
    troubleshooting = (docs_root / "content" / "troubleshooting.mdx").read_text()
    provider_cards = (
        docs_root / "components" / "landing" / "providers" / "data.tsx"
    ).read_text()
    hero = (docs_root / "components" / "landing" / "hero" / "readme.tsx").read_text()
    combined = "\n".join(
        [
            providers,
            install,
            getting_started,
            troubleshooting,
            provider_cards,
            hero,
        ]
    )

    assert (
        "OpenAI is the only external provider in the protected beta proof." in providers
    )
    assert "| `anthropic` | Native adapter | Native adapter" in providers
    assert "| Experimental/WIP |" in providers
    assert "# experimental/WIP adapter" in install
    assert "remain experimental/WIP" in getting_started
    assert "experimental/WIP adapters" in troubleshooting
    assert 'tier: "experimental / WIP"' in provider_cards
    assert "Anthropic remains experimental/WIP" in hero
    assert "OpenAI and Anthropic are the beta-core model adapters" not in combined
    assert "both stable-core providers" not in combined
    assert "OpenAI and Anthropic share one stable streaming boundary" not in combined


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
    assert 'bun add kaji-sdk@0.2.0-beta.2 "zod@>=4.3 <5"' in getting_started
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
    for code in range(7):
        assert re.search(rf"\|\s*`{code}`\s*\|", cli)

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
    assert '"getting-started:no-key:python"' in python_smoke
    assert '"tthw-echo:python"' in python_smoke
    assert 'cli_main(["--no-color", "add", "echo"' in python_smoke
    assert "installed-quickstart:typescript:start" in ts_smoke
    assert '"getting-started:no-key:typescript"' in ts_smoke
    assert '"tthw-echo:typescript"' in ts_smoke
    assert "docs-getting-started-run" in ts_smoke
    assert "docs-tthw-echo-run" in ts_smoke
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


def test_tthw_typescript_echo_instructions_use_the_certified_toolchain() -> None:
    guide = (REPO_ROOT / "docs" / "kaji" / "tthw-evidence.md").read_text()

    assert (
        'npm install "$KAJI_TARBALL" zod@4.3.6 tsx typescript@6.0.3 @types/node'
        in guide
    )
    assert "bun remove typescript" in guide
    assert 'bun add "$KAJI_TARBALL" zod@4.3.6 tsx @types/node' in guide
    assert "bun add --dev typescript@6.0.3" in guide
    assert "Save the following as `echo-loop.mts`." in guide
    assert "`./node_modules/.bin/tsx echo-loop.mts` for npm or" in guide
    assert "`bun --no-install echo-loop.mts` for Bun:" in guide
    assert "echo-loop.ts`" not in guide


def test_typescript_readme_quick_start_uses_an_esm_filename() -> None:
    readme = (REPO_ROOT / "kaji" / "ts" / "README.md").read_text()
    normalized = " ".join(readme.split())

    assert "Save this example as `quickstart.mts`" in normalized
    assert "quickstart.ts`" not in readme


def test_public_beta_install_paths_select_the_prerelease_artifacts() -> None:
    documents = {
        path: path.read_text()
        for path in (
            REPO_ROOT / "kaji" / "README.md",
            REPO_ROOT / "kaji" / "ts" / "README.md",
            REPO_ROOT / "docs" / "MVP.md",
            REPO_ROOT / "docs" / "ROADMAP.md",
            REPO_ROOT / "apps" / "docs" / "content" / "getting-started.mdx",
            REPO_ROOT / "apps" / "docs" / "content" / "install.mdx",
            REPO_ROOT / "apps" / "docs" / "content" / "cli.mdx",
            REPO_ROOT / "apps" / "docs" / "content" / "troubleshooting.mdx",
        )
    }
    combined = "\n".join(documents.values())
    assert "kaji-sdk==0.2.0b1" in combined
    assert "kaji-sdk[openai]==0.2.0b1" in combined
    assert "kaji-sdk@0.2.0-beta.2" in combined

    unpinned_python = re.compile(
        r"pip install [^\n`]*kaji-sdk(?:\[[^\]]+\])?(?!==0\.2\.0b1)(?:['\"]|\s|$)"
    )
    unpinned_typescript = re.compile(
        r"(?:npm install|bun add)\s+kaji-sdk(?!@0\.2\.0-beta\.2)(?:\s|$)"
    )
    assert unpinned_python.search(combined) is None
    assert unpinned_typescript.search(combined) is None


def test_event_and_cli_docs_do_not_claim_reserved_or_removed_behavior() -> None:
    events = (
        REPO_ROOT / "apps" / "docs" / "content" / "concepts" / "events.mdx"
    ).read_text()
    cli = (REPO_ROOT / "apps" / "docs" / "content" / "cli.mdx").read_text()

    assert events.count("Reserved; no embedded runtime producer") == 9
    assert "schema presence" in events
    assert "temporarily accepts deprecated" not in cli
    assert "removed `--out` alias is rejected" in cli
