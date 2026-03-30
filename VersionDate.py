RELEASE_VERSION = "2026.03rc2"
VERSION_DATE = "260322"
VERSION_LABEL = f"{RELEASE_VERSION}({VERSION_DATE})"
CURRENT_RELEASE_HIGHLIGHT = (
    "Group Analysis is now easier to read, with updated user manuals for grouped export workflows."
)

release_notes = f"""
    <br><b>Current version {VERSION_LABEL}:</b><br>
    - Group Analysis is easier to read and interpret in the grouped export workflow<br>
    - Updated user manuals help users understand grouped export setup and worksheet reading<br>

    <br><b>Version 2026.03rc1 (build 260319):</b><br>
    - Histogram table polishing improved readability and visual consistency<br>
    - Grouping analysis prototype v2 extends grouped-data analysis workflows<br>
    - Clearer histogram and chart layouts for easier reading in dense views<br>
    - Capability results now show confidence intervals for better decision-making<br>
    - New low-sample safeguards and NOK discrepancy warnings to avoid misleading quality conclusions<br>

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
