"""Shared HTML dashboard navigation helpers."""

from __future__ import annotations

import html
import re
from typing import Any


def slugify_html_id(value: Any, *, fallback: str = "section") -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def unique_html_id(value: Any, used_ids: set[str], *, fallback: str = "section") -> str:
    base = slugify_html_id(value, fallback=fallback)
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def render_section_nav(items: list[dict[str, str]]) -> str:
    chips = []
    for item in items:
        section_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or section_id).strip()
        if not section_id or not label:
            continue
        chips.append(
            f'<a class="section-chip" href="#{html.escape(section_id)}">{html.escape(label)}</a>'
        )
    return f'<nav class="section-nav">{"".join(chips)}</nav>' if chips else ""


def render_back_to_section(section_id: str, label: str) -> str:
    """Return a standard dashboard back-link chip."""

    target = str(section_id or "dashboard-start").strip().lstrip("#") or "dashboard-start"
    text = str(label or "Back").strip() or "Back"
    return (
        f'<a class="section-chip section-chip--back" href="#{html.escape(target)}" role="button">'
        f"{html.escape(text)}</a>"
    )


def render_back_to_dashboard_start(label: str = "Back to dashboard start") -> str:
    return render_back_to_section("dashboard-start", label)


def render_section_navigation_css(variant: str = "standard") -> str:
    """Return shared CSS for dashboard section navigation chips."""

    if str(variant or "").strip().lower() == "compact":
        return """
    .section-nav {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 14px 0 4px;
    }
    .section-chip {
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      color: var(--accent);
      background: var(--panel);
      font-size: 12px;
      font-weight: 650;
      text-decoration: none;
    }
    .section-chip--back {
      background: transparent;
    }""".strip()

    return """
    .section-nav {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }
    .section-chip {
      text-decoration: none;
      color: var(--ink);
      background: var(--accent-soft);
      border: 1px solid var(--accent-border);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 13px;
      font-weight: 600;
    }
    .section-chip--back {
      background: var(--teal-soft);
      border-color: var(--teal-border);
      color: var(--teal);
    }""".strip()


def render_section_header(title: str, subtitle: str = "", *, actions: str = "") -> str:
    subtitle_markup = (
        f'<div class="section-meta">{html.escape(subtitle)}</div>' if str(subtitle or "").strip() else ""
    )
    return (
        '<div class="section-top">'
        f"<div><h2>{html.escape(str(title or 'Section'))}</h2>{subtitle_markup}</div>"
        f'<div class="section-actions">{actions}</div>'
        "</div>"
    )
