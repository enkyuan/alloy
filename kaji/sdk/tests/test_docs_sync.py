"""Docs/SDK surface sync: every public name in ``kaji.__all__`` should be
mentioned in at least one user-facing doc.

This catches drift when a public name is added/renamed/removed in the SDK
without the docs being updated. The check is intentionally loose: we just
look for the literal name anywhere in the doc text. It doesn't validate
that the doc *explains* the name well, only that there's a reference the
author can revisit when the name changes.

Scope of "user-facing docs":
- ``kaji/README.md`` -- the shared concepts overview
- ``kaji/sdk/README.md`` -- the python SDK README
- ``kaji/serve/README.md`` -- the reference-service README
- ``kaji/ts/README.md`` -- the TypeScript SDK README
- ``kaji/docs/*.md`` -- compact shared compatibility references
- ``docs/MVP.md`` -- the SDK MVP contract and readiness snapshot
- ``docs/kaji/*.md`` -- the canonical production-beta operating contract
- ``apps/docs/content/**/*.mdx`` -- the Fumadocs site

Plan/spec files under ``docs/superpowers/`` are excluded -- those are
point-in-time records.

Names exempt from the check (rare; document each exemption):
- ``EventStore`` / ``EventBus`` are referenced in the docs by their concrete
  in-memory implementations (``InMemoryEventBus`` / ``InMemoryEventStore``)
  so the abstract base classes aren't always spelled out; we still want them
  mentioned, so they stay in the sync set.

Add an entry to ``EXEMPT`` only when a name is genuinely an internal type
not worth documenting (typically protocol subclasses or helper aliases).
"""

from __future__ import annotations

import re
from pathlib import Path

import kaji


REPO_ROOT = Path(__file__).resolve().parents[3]
FUMADOCS_CONTENT = REPO_ROOT / "apps" / "docs" / "content"


def _user_facing_docs() -> list[Path]:
    paths: list[Path] = [
        REPO_ROOT / "kaji" / "README.md",
        REPO_ROOT / "kaji" / "sdk" / "README.md",
        REPO_ROOT / "kaji" / "serve" / "README.md",
        REPO_ROOT / "kaji" / "ts" / "README.md",
        REPO_ROOT / "docs" / "MVP.md",
    ]
    paths.extend(sorted((REPO_ROOT / "kaji" / "docs").glob("*.md")))
    paths.extend(sorted((REPO_ROOT / "docs" / "kaji").glob("*.md")))
    paths.extend(sorted(FUMADOCS_CONTENT.rglob("*.mdx")))
    return paths


USER_FACING_DOCS = _user_facing_docs()

# Names that are public but, by design, are not headlined in the prose. Keep
# this set small. Every entry should be defensible in a code review.
EXEMPT: set[str] = set()


def _doc_haystack() -> str:
    parts: list[str] = []
    for path in USER_FACING_DOCS:
        if not path.exists():
            raise AssertionError(f"User-facing doc missing: {path}")
        parts.append(path.read_text())
    return "\n".join(parts)


def test_every_public_name_is_referenced_in_user_facing_docs() -> None:
    haystack = _doc_haystack()
    missing: list[str] = []
    for name in kaji.__all__:
        if name.startswith("_"):
            continue
        if name in EXEMPT:
            continue
        # Word-boundary match so e.g. "tool" doesn't trivially match inside
        # "tool_spec". Acceptable false negatives are caught when reviewing
        # the docs.
        if not re.search(rf"\b{re.escape(name)}\b", haystack):
            missing.append(name)
    assert not missing, (
        "Public names not referenced in any user-facing doc "
        f"({len(USER_FACING_DOCS)} files scanned):\n  "
        + "\n  ".join(missing)
        + "\nAdd a reference, or add a justified entry to EXEMPT in this test."
    )


def test_docs_dont_reference_removed_uppercamel_aliases() -> None:
    """Catches stale doc text referring to the dropped UpperCamel decorator
    aliases (Tool, FunctionTool, RegisterTool, GetProvider, etc.)."""
    removed_aliases = {
        "ReplaySession",
        # Decorator/helper aliases removed by the PEP 8 cleanup.
        "RegisterTool",
        "ListToolSpecs",
        "GetProvider",
        "RegisterProvider",
    }
    # Note: bare ``Tool`` and ``FunctionTool`` are too generic to grep
    # safely; they collide with valid prose like "Tool registry" and
    # "Function tool". The set above is the unambiguous removed names.
    offenses: dict[str, list[str]] = {}
    for path in USER_FACING_DOCS:
        text = path.read_text()
        for name in removed_aliases:
            if re.search(rf"\b{re.escape(name)}\b", text):
                offenses.setdefault(path.name, []).append(name)
    assert not offenses, (
        "Docs still reference removed UpperCamel aliases:\n  "
        + "\n  ".join(f"{p}: {', '.join(names)}" for p, names in offenses.items())
    )


def test_no_em_dashes_in_user_facing_docs() -> None:
    """Em-dashes are banned per the project writing-style memo. This guards
    against them creeping back into the user-facing docs."""
    offenders: dict[str, int] = {}
    for path in USER_FACING_DOCS:
        text = path.read_text()
        count = text.count("—")  # em dash
        if count:
            offenders[str(path.relative_to(REPO_ROOT))] = count
    assert not offenders, f"Em-dashes found: {offenders}. Replace with -- or a comma."


def test_user_facing_docs_reference_existing_relative_markdown_links() -> None:
    """Relative markdown links in user-facing docs must resolve."""
    missing: list[str] = []
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

    for path in USER_FACING_DOCS:
        text = path.read_text()
        for raw_target in link_pattern.findall(text):
            target = raw_target.split()[0].split("#", 1)[0]
            if not target:
                continue
            if target.startswith(("http://", "https://", "mailto:", "#", "/")):
                continue

            candidate = (path.parent / target).resolve()
            if not candidate.exists():
                missing.append(f"{path.relative_to(REPO_ROOT)}: {raw_target}")

    assert missing == []


def test_typescript_readme_matches_provider_factory_parity() -> None:
    ts_readme = (REPO_ROOT / "kaji" / "ts" / "README.md").read_text()
    factory = (
        REPO_ROOT / "kaji" / "ts" / "src" / "providers" / "factory.ts"
    ).read_text()

    assert "export function kimi" in factory
    assert "export function gemini" in factory
    assert "| Kimi / Gemini providers | Yes | Yes" in ts_readme


def test_user_facing_docs_include_stability_contract() -> None:
    haystack = _doc_haystack()
    for phrase in (
        "Stable core",
        "Experimental Python-only",
        "TS not ported",
        "Redis realtime",
        "voice/TTS",
        "DocumentRAG",
        "OpenAI-compatible factories",
        "scripts/release_smoke.py",
    ):
        assert phrase in haystack


def test_mvp_manifest_status_is_current() -> None:
    mvp = (REPO_ROOT / "docs" / "MVP.md").read_text()

    assert "Catalog contract implemented" in mvp
    assert (
        "Plan 3 - Define the first-party integration catalog contract (implemented)"
        in mvp
    )
    assert "no shared manifest/auth/credential shape" not in mvp
    assert "Catalog contract still open" not in mvp
