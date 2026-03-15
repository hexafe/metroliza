RELEASE_VERSION = "2026.03rc1"
VERSION_DATE = "260307"
VERSION_LABEL = f"{RELEASE_VERSION}({VERSION_DATE})"
CURRENT_RELEASE_HIGHLIGHT = (
    "Histogram and chart readability upgrade: cleaner layouts, taller summary rows, and better title/axis visibility."
)

release_notes = f"""
    <br><b>Current version {VERSION_LABEL}:</b><br>
    - Histogram dashboards were redesigned for clearer side-table summaries and reduced visual clutter<br>
    - Extended histogram table rows are taller, improving readability for dense metrics<br>
    - Chart titles and axis ranges are now more consistently visible in exports and previews<br>
    - Symbol rendering issues in chart labels were fixed to prevent missing-glyph warnings<br>

    - Group names can be renamed instantly by double-clicking them in the group list<br>

    <br><b>Version 2026.03 (build 260301):</b><br>
    - Google Sheets export implementation with safe `.xlsx` fallback<br>
    - Performance optimizations across reporting and CSV Summary workflows<br>

    <br><b>Version 2026.02 (build 260223):</b><br>
    - Performance improvements<br>

    <br><b>Version 2026.02 (build 260216):</b><br>
    - Bug fixes and module-level integration improvements<br>

    <br><b>Version 2024.02 (build 240225):</b><br>
    - Added CSV Summary module (prototype release)<br>

    <br><b>Version 2024.02 (build 240218):</b><br>
    - First release<br>
    """
