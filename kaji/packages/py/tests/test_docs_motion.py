"""Focused regression checks for the Kaji docs entrance-motion scope."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
DOCS_ROOT = REPO_ROOT / "apps" / "docs"
STYLES_PATH = DOCS_ROOT / "src" / "styles" / "global.css"
OVERVIEW_PATH = DOCS_ROOT / "src" / "pages" / "index.astro"
SIDEBAR_PATH = DOCS_ROOT / "src" / "components" / "navigation" / "sidebar.astro"


def _animation_delay_ms(styles: str, selector: str) -> float:
    marker = f"{selector} {{"
    assert marker in styles, f"missing CSS rule: {selector}"
    body = styles.split(marker, maxsplit=1)[1].split("}", maxsplit=1)[0]
    match = re.search(r"animation-delay:\s*(\d+(?:\.\d+)?)ms\s*;", body)
    assert match is not None, f"missing millisecond animation delay: {selector}"
    return float(match.group(1))


def test_home_entrance_targets_copy_without_hiding_the_install_action() -> None:
    styles = STYLES_PATH.read_text()
    overview = OVERVIEW_PATH.read_text()

    assert "html[data-kaji-first-visit] .overview-article .hero-title," in styles
    assert (
        "html[data-kaji-first-visit] .overview-article .heading-container" not in styles
    )
    assert "html[data-kaji-first-visit] .install-snippet" not in styles

    hero_title = overview.split('<h1 class="hero-title">', maxsplit=1)[1].split(
        "</h1>", maxsplit=1
    )[0]
    assert 'class="install-snippet"' not in hero_title


def test_wordmark_stagger_stays_short_and_does_not_hide_linked_navigation() -> None:
    styles = STYLES_PATH.read_text()
    first_selector = (
        "html[data-kaji-first-visit] span.kaji-wordmark .wordmark-glyph:first-child"
    )
    last_selector = (
        "html[data-kaji-first-visit] span.kaji-wordmark .wordmark-glyph:last-child"
    )

    first_delay = _animation_delay_ms(styles, first_selector)
    last_delay = _animation_delay_ms(styles, last_selector)
    inter_glyph_delay = last_delay - first_delay

    assert 0 < inter_glyph_delay <= 80
    assert "html[data-kaji-first-visit] a.kaji-wordmark" not in styles


def test_first_visit_motion_does_not_stagger_navigation_or_reading_sections() -> None:
    styles = STYLES_PATH.read_text()
    sidebar = SIDEBAR_PATH.read_text()

    assert "@keyframes nav-enter" not in styles
    assert "--nav-delay:" not in sidebar
    assert "navStartMs" not in sidebar
    assert "navStepMs" not in sidebar
    assert "html[data-kaji-first-visit] .doc-article" not in styles
    assert "html[data-kaji-first-visit] .overview-article > section" not in styles

    for sidebar_target in (
        ".side-nav",
        ".nav-links",
        ".nav-section",
        ".nav-item-wrapper",
        ".nav-toc",
        ".nav-meta",
    ):
        assert f"html[data-kaji-first-visit] {sidebar_target}" not in styles
