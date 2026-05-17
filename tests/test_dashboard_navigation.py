from modules.dashboard_navigation import (
    render_back_to_section,
    render_section_navigation_css,
    render_section_nav,
)


def test_section_nav_escapes_labels_and_skips_empty_items() -> None:
    html = render_section_nav(
        [
            {"id": "alpha", "label": "Alpha"},
            {"id": "", "label": "Empty"},
            {"id": "beta", "label": "<Beta>"},
        ]
    )

    assert '<a class="section-chip" href="#alpha">Alpha</a>' in html
    assert "&lt;Beta&gt;" in html
    assert "Empty" not in html


def test_back_to_section_targets_requested_anchor() -> None:
    assert render_back_to_section("#group-analysis", "Back") == (
        '<a class="section-chip section-chip--back" href="#group-analysis" role="button">'
        "Back</a>"
    )


def test_navigation_css_variants_share_class_names() -> None:
    standard = render_section_navigation_css()
    compact = render_section_navigation_css("compact")

    assert ".section-nav" in standard
    assert ".section-chip--back" in compact
    assert "var(--accent-soft)" in standard
    assert "min-height: 30px" in compact
