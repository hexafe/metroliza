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


def render_back_to_dashboard_start(label: str = "Back to dashboard start") -> str:
    return (
        '<a class="section-chip section-chip--back" href="#dashboard-start" role="button">'
        f"{html.escape(label)}</a>"
    )


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
