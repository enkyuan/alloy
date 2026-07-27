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
    provider_markers = (
        "OPENAI_API_KEY",
        'get_provider("openai")',
        "new OpenAIProvider",
    )
    present_provider_markers = [marker for marker in provider_markers if marker in text]
    assert present_provider_markers
    first_provider_setup = min(
        text.index(marker) for marker in present_provider_markers
    )
    assert no_key < first_provider_setup


def test_public_site_states_the_openai_only_beta_provider_boundary() -> None:
    docs_root = REPO_ROOT / "apps" / "docs"
    providers = (docs_root / "content" / "concepts" / "providers.mdx").read_text()
    install = (docs_root / "content" / "install.mdx").read_text()
    getting_started = (docs_root / "content" / "getting-started.mdx").read_text()
    troubleshooting = (docs_root / "content" / "troubleshooting.mdx").read_text()
    overview = (docs_root / "src" / "pages" / "index.astro").read_text()
    combined = "\n".join(
        [
            providers,
            install,
            getting_started,
            troubleshooting,
            overview,
        ]
    )

    feature_tiers = json.loads(
        (REPO_ROOT / "kaji/contracts/feature-tiers-v1.json").read_text()
    )
    assert (
        feature_tiers["packageSubpaths"]["typescript"]["./openai"]["tier"] == "stable"
    )
    assert (
        feature_tiers["packageSubpaths"]["typescript"]["./anthropic"]["tier"]
        == "experimental"
    )
    assert re.search(r"\|\s*`openai`\s*.*\|\s*Stable\s*\|", providers)
    for provider in ("anthropic", "kimi", "gemini"):
        assert f"| `{provider}`" in providers
    assert providers.count("| WIP") >= 3
    for source in (install, getting_started, troubleshooting):
        assert "WIP" in source
        assert "`experimental`" in source
    assert "stable live-provider" in " ".join(overview.split())
    assert 'pip install "kaji-sdk==0.2.0b1"' not in overview
    assert "OpenAI and Anthropic are the beta-core model adapters" not in combined
    assert "both stable-core providers" not in combined
    assert "OpenAI and Anthropic share one stable streaming boundary" not in combined


def test_astro_docs_keep_status_motion_and_icon_contracts_explicit() -> None:
    docs_root = REPO_ROOT / "apps" / "docs"
    navigation = (docs_root / "src" / "data" / "navigation.ts").read_text()
    sidebar = (
        docs_root / "src" / "components" / "navigation" / "sidebar.astro"
    ).read_text()
    mobile = (
        docs_root / "src" / "components" / "navigation" / "mobile.astro"
    ).read_text()
    wordmark = (
        docs_root / "src" / "components" / "site" / "wordmark.astro"
    ).read_text()
    runtime = (docs_root / "src" / "components" / "site" / "demo.astro").read_text()
    overview = (docs_root / "src" / "pages" / "index.astro").read_text()
    scripts = (
        docs_root / "src" / "components" / "content" / "scripts.astro"
    ).read_text()
    diagram = (
        docs_root / "src" / "components" / "content" / "diagram.astro"
    ).read_text()
    diagram_lib = (docs_root / "src" / "lib" / "diagram.ts").read_text()
    toc_lib = (docs_root / "src" / "lib" / "toc.ts").read_text()
    toc_tests = (docs_root / "src" / "lib" / "toc.test.ts").read_text()
    diagram_styles = (docs_root / "src" / "styles" / "diagram.css").read_text()
    astro_config = (docs_root / "astro.config.mjs").read_text()
    agentation_patch_path = REPO_ROOT / "patches" / "agentation@3.0.2.patch"
    base = (docs_root / "src" / "layouts" / "base.astro").read_text()
    docs_layout = (docs_root / "src" / "layouts" / "docs.astro").read_text()
    styles = (docs_root / "src" / "styles" / "global.css").read_text()
    architecture = (docs_root / "content" / "architecture.mdx").read_text()
    error_page = (docs_root / "src" / "pages" / "404.astro").read_text()
    logo = (docs_root / "public" / "logo.svg").read_text()

    assert (
        '{ href: "/docs/integrations/github", label: "GitHub", status: "wip" }'
        in navigation
    )
    assert (
        '{ href: "/docs/reference-service", label: "Reference Service", status: "wip" }'
        in navigation
    )
    assert '{ href: "/docs/install", label: "Install", status: "wip" }' in navigation
    assert (
        '{ href: "/docs/getting-started", label: "Getting Started", status: "wip" }'
        in navigation
    )
    for shell in (sidebar, mobile):
        assert '<sup class="nav-wip" aria-label="work in progress">' in shell

    assert runtime.isascii()
    for codepoint in (
        r"\u2500",
        r"\u2502",
        r"\u250c",
        r"\u2510",
        r"\u2514",
        r"\u2518",
        r"\u252c",
        r"\u25bc",
    ):
        assert codepoint in runtime
    assert "-->" not in runtime
    assert "<--" not in runtime
    assert '{ text: glyph.vertical, stage: 1, kind: "connector" }' in runtime
    assert '{ text: glyph.arrowDown, stage: 1.5, kind: "connector" }' in runtime
    assert "--runtime-start: 1780ms" in runtime
    sequence = (
        "session.created",
        "user.message",
        "agent.reasoning.started",
        "tool.call.requested",
        "tool.call.started",
        "tool.call.completed",
        "agent.message.completed",
    )
    positions = [runtime.index(event) for event in sequence]
    assert positions == sorted(positions)
    assert 'class="runtime-line"' in runtime
    assert "runtime-line-reveal" in runtime
    assert 'data-kaji-once="runtime-demo"' in runtime
    assert "data-kaji-duration={runtimeDuration}" in runtime
    assert "data-kaji-first-duration={firstVisitRuntimeDuration}" in runtime
    assert "calculateRuntimeDuration(runtimeStartMs)" in runtime
    assert "calculateRuntimeDuration(firstVisitRuntimeStartMs)" in runtime
    assert "countDiagramTokens(line.text)" in runtime
    assert "runtimeTokenDurationMs = 260" in runtime
    assert "diagramTokenMarkup(line.text)" in runtime
    assert "DIAGRAM_TOKEN_STEP_MS" in runtime
    runtime_line_styles = runtime.split(
        ".runtime-diagram :global(.runtime-line) {", maxsplit=1
    )[1].split("}", maxsplit=1)[0]
    assert "animation:" not in runtime_line_styles
    assert (
        '.runtime-line[data-kind="connector"]) {\n    animation: runtime-line-reveal 360ms'
        in runtime
    )
    assert "var(--runtime-stage) * 160ms" in runtime
    assert "return stage + 8;" in runtime
    assert "prefers-reduced-motion: reduce" in runtime
    assert "--runtime-line-color: var(--sumi-iro)" in runtime
    keyframes = runtime.split("@keyframes runtime-line-reveal", maxsplit=1)[1]
    assert "color:" not in keyframes.split("@media", maxsplit=1)[0]

    assert '<span class="wordmark-glyph">鍛</span>' in wordmark
    assert '<span class="wordmark-glyph">冶</span>' in wordmark
    assert "tabindex=" not in wordmark
    assert "wordmark-write" in styles
    assert ".kaji-wordmark[data-press-feedback]" in styles
    assert "transform: scale(0.96)" in styles
    assert "transform: scale(0.25)" in styles
    assert "transform: scale(0.92)" not in styles
    assert "clip-path: inset(0 100% 100% 0)" in styles
    assert "@keyframes nav-enter" not in styles
    assert "--nav-delay:" not in sidebar
    assert "navStartMs" not in sidebar
    assert "navStepMs" not in sidebar
    assert "html[data-kaji-first-visit] .doc-article" not in styles
    assert "html[data-kaji-first-visit] .overview-article > section" not in styles
    assert "animation-delay: 0ms !important" in styles
    assert "--focus-color: var(--konjo-iro)" in styles
    assert "color-scheme: only light" in styles
    assert "scroll-behavior: smooth" not in styles
    skip_link_styles = styles.split(".skip-link {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "transition:" not in skip_link_styles
    assert 'const visitKey = "kaji:visited"' in base
    assert "window.sessionStorage.getItem(visitKey)" in base
    assert 'import { ClientRouter } from "astro:transitions";' in base
    assert "const clientRouting = import.meta.env.PROD;" not in base
    assert '<ClientRouter fallback="swap" />' in base
    assert "<script is:inline data-astro-rerun>" in base
    assert 'transition:animate="none"' in base
    assert 'data-kaji-motion={standalone ? undefined : ""}' not in base
    assert "window.sessionStorage.getItem(visitKey)) {" in base
    assert 'root.dataset.kajiMotion = ""' in base
    assert base.index('root.dataset.kajiMotion = ""') < base.index(
        'root.dataset.kajiFirstVisit = ""'
    )
    assert 'root.removeAttribute("data-kaji-first-visit")' in base
    assert "Without it, render the shell and diagrams statically." in base
    first_visit_fallback = base.split(
        'window.sessionStorage.setItem(visitKey, "true");', maxsplit=1
    )[1].split("if (!root.hasAttribute", maxsplit=1)[0]
    assert 'root.dataset.kajiFirstVisit = ""' not in first_visit_fallback
    assert 'root.removeAttribute("data-kaji-motion")' in first_visit_fallback
    assert 'root.removeAttribute("data-kaji-first-visit")' in first_visit_fallback
    assert 'import { setupDiagramMotion } from "@/lib/diagram";' in base
    assert 'document.addEventListener("astro:page-load", setupDiagrams)' in base
    assert "if (main === diagramDocument) return;" in base
    assert "setupDiagrams();" in base
    assert "kaji:motion:" in diagram_lib
    assert '"IntersectionObserver" in window' in diagram_lib
    assert 'target.getAttribute("data-kaji-first-duration")' in diagram_lib
    assert '"pagehide"' in base
    assert "observer?.disconnect()" in diagram_lib
    reveal = diagram_lib.split("const key = `kaji:motion:${id}`;", maxsplit=1)[1]
    before_animation, scheduled_reveal = reveal.split(
        'target.dataset.kajiAnimate = "";', maxsplit=1
    )
    completion = scheduled_reveal.split("const timer = window.setTimeout", maxsplit=1)[
        1
    ].split("timers.add(timer)", maxsplit=1)[0]
    assert before_animation.count('storage.setItem(key, "true")') == 1
    assert completion.count('storage.setItem(key, "true")') == 1
    assert 'target.removeAttribute("data-kaji-ready")' in diagram_lib
    assert 'import Demo from "@/components/site/demo.astro";' in overview
    assert "<Demo />" in overview
    assert not (
        docs_root / "src" / "components" / "site" / "runtime-demo.astro"
    ).exists()

    assert "sketchy-underline" not in overview + styles
    assert "pen-underline" not in overview + styles
    assert 'class="hero-stop"' in overview
    assert 'class="forged-underline"' in overview
    assert "forge-rule-enter" in styles
    assert "html[data-kaji-first-visit] .forged-underline::after" in styles

    assert architecture.count("<Diagram") == 2
    assert "```" not in architecture
    assert 'id="architecture-runtime"' in architecture
    assert 'id="architecture-modality"' in architecture
    architecture_runtime = architecture.split('id="architecture-runtime"', maxsplit=1)[
        1
    ].split("/>", maxsplit=1)[0]
    runtime_rows = re.findall(r'text: "([^"]+)"', architecture_runtime)
    assert {len(row) for row in (*runtime_rows[:4], *runtime_rows[5:12])} == {54}
    assert "<pre" not in diagram
    assert "<code" not in diagram
    assert "diagram-frame-reveal" in diagram
    assert "diagram-connector-reveal" in diagram
    assert "prefers-reduced-motion: reduce" in diagram
    assert "data-kaji-once={id}" in diagram
    assert "diagramTokenMarkup(row.copy)" in diagram
    assert "diagramConnectorMarkup(row.text)" in diagram
    assert ".diagram-connector :global(.diagram-arrow)" in diagram
    assert "width: 1ch" in diagram
    assert "DIAGRAM_TOKEN_STEP_MS" in diagram
    assert "stepMs = 240" in diagram
    assert "calc(400ms + var(--diagram-stage)" in diagram
    assert "diagram-token-enter 260ms" in diagram_styles
    assert "var(--diagram-token-index)" in diagram_styles
    assert r"\s+|[\p{L}\p{N}_]+|[^\s]" in diagram_lib
    assert 'class="diagram-token"' in diagram_lib
    assert "frameStage: 0,\n      copyStage: 1" in architecture
    assert "│  app-owned memory    │" in architecture
    assert "│  in-memory or   │" not in architecture

    assert 'document.addEventListener("astro:page-load", setupCurrentPage)' in scripts
    assert "if (main === pageDocument) return;" in scripts
    assert "setupCurrentPage();" in scripts
    assert "const controller = new AbortController()" in scripts
    assert 'import { navigate } from "astro:transitions/client";' not in base
    assert "const navigateDocument = (event: MouseEvent) => {" not in base
    assert "void navigate(destination.href)" not in base
    assert 'document.addEventListener("click", navigateDocument)' not in base
    assert "wordmark.dataset.pressFeedback" in scripts
    assert 'querySelector<HTMLAnchorElement>("a.kaji-wordmark")' in scripts
    assert '<span class="nav-link active" aria-current="page">' in sidebar
    assert '<span class="mobile-nav-link active" aria-current="page">' in mobile
    mobile_links_markup = mobile.split(
        '<div\n    class="mobile-nav-links"', maxsplit=1
    )[1].split(">", maxsplit=1)[0]
    assert 'aria-hidden="true"' in mobile_links_markup
    assert "\n    inert" in mobile_links_markup
    assert "mobileLinks.inert = !nextOpen;" in scripts
    assert 'mobileLinks.setAttribute("aria-hidden", String(!nextOpen));' in scripts
    assert '<span class="kaji-wordmark" aria-current="page">' in wordmark
    install_snippet = overview.split('class="install-snippet"', maxsplit=1)[1].split(
        "</a>", maxsplit=1
    )[0]
    assert "<code>Source checkout required</code>" in install_snippet
    assert "aria-label=" not in install_snippet
    assert (
        '<p class="sr-only" role="status" aria-live="polite" data-copy-announcer></p>'
        in scripts
    )
    assert "XCircle" in scripts
    assert "copy-status-icon-error" in scripts
    assert "copy-status-icon-error" in styles
    assert '[data-copy-failed="true"]' in styles
    copy_hit_area = styles.split(".code-copy::before {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "inset: -6px" in copy_hit_area
    mobile_link_styles = styles.split(".mobile-nav-link {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "min-height: 2.5rem" in mobile_link_styles
    github_target_styles = styles.split(".nav-github {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "width: 2.5rem" in github_target_styles
    assert "height: 2.5rem" in github_target_styles
    copy_failure_styles = styles.rsplit(
        '.code-copy[data-copy-failed="true"] {', maxsplit=1
    )[1].split("}", maxsplit=1)[0]
    assert "color: var(--sango-iro-ink)" in copy_failure_styles
    assert (
        "text-wrap: pretty"
        in styles.split(".article li {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    )
    assert "var(--shiro-nezumi) transparent" in diagram
    assert "--shironezumi-iro" not in diagram
    runtime_rail_keyframes = runtime.split(
        "@keyframes runtime-rail-reveal", maxsplit=1
    )[1].split("@keyframes", maxsplit=1)[0]
    assert "clip-path: inset(0 0 100% 0)" in runtime_rail_keyframes
    assert "clip-path: inset(0)" in runtime_rail_keyframes
    assert "<a href={markdownHref} data-astro-reload>Markdown</a>" in docs_layout
    assert "window.innerHeight * 0.7" not in scripts
    assert "atPageEnd" not in scripts
    for toc_label in (
        '"prepare-the-source-checkout": "Prepare source checkout"',
        '"run-with-docker-compose": "Run with docker"',
        '"when-to-use-the-reference-service": "When to use"',
    ):
        assert toc_label in sidebar
    assert '"astro:before-swap"' not in base
    assert '"astro:after-swap"' not in base
    assert 'style[id^="feedback-"]' not in base
    assert re.search(
        r"""vite:\s*\{\s*
        optimizeDeps:\s*\{\s*
        include:\s*\["agentation",\s*"react",\s*"react-dom/client"\],\s*
        noDiscovery:\s*true,\s*
        \},\s*
        \},""",
        astro_config,
        re.VERBOSE,
    )
    assert "<div data-agentation-mount />" in base
    assert 'transition:persist="agentation"' not in base
    assert agentation_patch_path.is_file()
    agentation_patch = agentation_patch_path.read_text()
    assert '"aria-label": "Agentation"' in agentation_patch
    assert '"aria-hidden": "true"' in agentation_patch
    assert "MutationObserver" not in astro_config
    assert 'a[href="https://agentation.com"]' not in astro_config
    assert 'document.querySelector("[data-agentation-mount]")' in astro_config
    assert 'document.createElement("div")' not in astro_config
    assert "document.body.append" not in astro_config
    assert "let agentationRoot;" in astro_config
    assert "const mountAgentation = () => {" in astro_config
    assert "const unmountAgentation = () => {" in astro_config
    assert "agentationRoot?.unmount();" in astro_config
    assert 'style[id^="feedback-"], style#agentation-color-tokens' in astro_config
    assert "event.newDocument.head.append(style.cloneNode(true))" in astro_config
    assert (
        'document.addEventListener("astro:before-swap", prepareAgentationSwap)'
        in astro_config
    )
    assert (
        'document.addEventListener("astro:page-load", mountAgentation)' in astro_config
    )
    assert "mountAgentation();" in astro_config
    assert 'import { activeTocIndex } from "@/lib/toc";' in scripts
    assert "new ResizeObserver(scheduleTocUpdate)" in scripts
    assert '"hashchange", setPreferredTocFromHash' in scripts
    assert '"wheel", clearPreferredToc' in scripts
    assert '"touchstart", clearPreferredToc' in scripts
    assert 'closest("[data-toc-link]")' in scripts
    assert "keepTocLinkVisible(activeLink)" in scripts
    assert "window.requestAnimationFrame" in scripts
    assert "MAX_ACTIVATION_LINE = 240" in toc_lib
    assert "PAGE_END_TOLERANCE = 2" in toc_lib
    assert "tailStart = Math.max(0, maxScrollY - tailRange)" in toc_lib
    assert "keeps the first heading active at the top of the page" in toc_tests
    assert "without skipping short sections" in toc_tests
    assert "each short tail section" in toc_tests
    assert ".inline-link,\n.error-return" in styles
    assert ".inline-link .inline-icon,\n.error-return .inline-icon" in styles
    assert "align-items: center" in styles
    assert "vertical-align: -0.15em" in styles
    assert "inset-block-start: 2px" not in styles
    assert (
        "display: inline-block"
        not in styles.split(".error-return {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    )
    assert "transform: translateY(0.04em)" not in styles
    assert 'class="error-return"' in error_page

    assert 'import { CheckCircle, Copy, XCircle } from "reicon";' in scripts
    assert 'setCopyState(button, "copied", "Copied")' in scripts
    for color in (
        "--kuro-iro: oklch(0.194 0.006 55.987)",
        "--sumi-iro: oklch(0.256 0.009 53.056)",
        "--torinoko-iro: oklch(0.825 0.059 62.604)",
        "--gofun-iro: oklch(0.999 0.004 106.471)",
        "--washi-iro: oklch(0.985 0.008 81.557)",
        "--sango-iro: oklch(0.692 0.183 31.544)",
        "--gunjo-iro: oklch(0.62 0.073 240.838)",
        "--konjo-iro: oklch(0.328 0.121 257.941)",
        "--matsuba-iro: oklch(0.405 0.044 121.792)",
    ):
        assert color in styles
    for family in ("Noto Sans JP", "Noto Serif JP", "M PLUS 1 Code", "Yuji Syuku"):
        assert family in styles
        assert family.replace(" ", "+") in base
    assert "rgb(" not in styles
    assert "#" not in styles
    assert 'content="oklch(0.985 0.008 81.557)"' in base
    assert logo.count('fill="oklch(0.692 0.183 31.544)"') == 2
    assert "#" not in logo
    assert ".reicon path" in styles


def test_public_onboarding_is_source_only_before_registry_verification() -> None:
    docs_root = REPO_ROOT / "apps" / "docs"
    paths = (
        docs_root / "content" / "getting-started.mdx",
        docs_root / "content" / "install.mdx",
        docs_root / "content" / "troubleshooting.mdx",
        docs_root / "src" / "pages" / "index.astro",
    )
    combined = "\n".join(path.read_text() for path in paths)
    combined_compact = " ".join(combined.split())

    assert "0.2.0-beta.7" in combined
    assert "kaji-sdk@0.2.0-beta.2" not in combined
    assert "kaji-sdk@0.2.0-beta.3" not in combined
    assert "git clone https://github.com/enkyuan/alloy.git" in combined
    assert "bun install --frozen-lockfile" in combined
    assert "Source checkout required" in combined
    assert "not publicly available yet" in combined
    assert "registry-byte verification" in combined_compact
    assert "PyPI" in combined
    assert "deferred" in combined
    assert re.search(r"(?:npm install|bun add)\s+kaji-sdk@", combined) is None
    assert 'pip install "kaji-sdk==0.2.0b1"' not in combined
    assert 'pip install "kaji-sdk[openai]==0.2.0b1"' not in combined


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
    assert "0.2.0-beta.7" in getting_started
    assert "bun install --frozen-lockfile" in getting_started
    assert re.search(r"(?:npm install|bun add)\s+kaji-sdk@", getting_started) is None
    assert 'risk="read"' in getting_started
    assert 'risk: "read"' in getting_started
    assert "principal_id=" in getting_started
    assert "principalId:" in getting_started
    getting_started_compact = " ".join(getting_started.split())
    assert (
        "`AgentBuilder` wires a provider and tools to the runtime's event journal"
        in getting_started_compact
    )
    assert "in-memory bus + store" not in getting_started

    cli = paths[2].read_text()
    for heading in (
        "Python SDK CLI",
        "TypeScript SDK CLI",
        "Standalone cross-language CLI",
    ):
        assert heading in cli
    assert re.search(r"\|\s*`add`\s*\|\s*Yes\s*\|\s*Yes\s*\|\s*No\s*\|", cli)
    assert re.search(r"\|\s*`replay`\s*\|\s*Yes\s*\|\s*No\s*\|\s*No\s*\|", cli)
    assert re.search(r"\|\s*`mcp`\s*\|\s*No\s*\|\s*No\s*\|\s*WIP;", cli)
    assert "not available from PyPI for this release" in cli
    assert "pip install" not in cli
    for code in range(7):
        assert re.search(rf"\|\s*`{code}`\s*\|", cli)

    tool_registry = paths[5].read_text()
    assert "sequentially by default" in tool_registry
    assert "parallel_safe" in tool_registry
    assert "detached, validated, readonly `ToolExecutionContext`" in tool_registry

    architecture = paths[-1].read_text()
    architecture_compact = " ".join(architecture.split())
    assert "execute tool calls sequentially by default" in architecture_compact
    assert "marked `parallel_safe` may overlap" in architecture_compact
    assert "bounded by the configured tool concurrency" in architecture_compact
    assert "execute tool calls scatter-gather" not in architecture_compact
    assert "run concurrently" not in architecture_compact
    assert "audio → STT → [runtime loop]" not in architecture


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


def test_release_docs_enforce_the_npm_only_registry_boundary() -> None:
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
    assert "kaji-sdk@0.2.0-beta.7" in combined
    assert "kaji-sdk@0.2.0-beta.2" not in combined
    assert "kaji-sdk@0.2.0-beta.3" not in combined

    unpinned_typescript = re.compile(
        r"(?:npm install|bun add)\s+kaji-sdk(?!@0\.2\.0-beta\.7)(?:\s|$)"
    )
    assert re.search(r"pip install [^\n`]*kaji-sdk", combined) is None
    assert unpinned_typescript.search(combined) is None
    assert (
        "uv sync --project kaji --extra openai"
        in documents[REPO_ROOT / "docs" / "MVP.md"]
    )
    assert (
        "uv run --project kaji kaji init --provider openai"
        in documents[REPO_ROOT / "docs" / "ROADMAP.md"]
    )
    public_docs = "\n".join(
        documents[path]
        for path in documents
        if path.is_relative_to(REPO_ROOT / "apps" / "docs")
    )
    assert "0.2.0-beta.7" in public_docs
    assert re.search(r"(?:npm install|bun add)\s+kaji-sdk@", public_docs) is None
    assert re.search(r"pip install [^\n`]*kaji-sdk", public_docs) is None
    typescript_readme = documents[REPO_ROOT / "kaji" / "ts" / "README.md"]
    assert "npm install kaji-sdk@0.2.0-beta.7" in typescript_readme


def test_event_and_cli_docs_do_not_claim_reserved_or_removed_behavior() -> None:
    events = (
        REPO_ROOT / "apps" / "docs" / "content" / "concepts" / "events.mdx"
    ).read_text()
    cli = (REPO_ROOT / "apps" / "docs" / "content" / "cli.mdx").read_text()

    assert events.count("Reserved; no embedded runtime producer") == 10
    assert "schema presence" in events
    assert "temporarily accepts deprecated" not in cli
    assert "`init` does not accept `--out`" in cli
