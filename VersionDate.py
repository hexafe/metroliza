RELEASE_VERSION = "2026.03rc3"
VERSION_DATE = "260329"
VERSION_LABEL = f"{RELEASE_VERSION}({VERSION_DATE})"
CURRENT_RELEASE_HIGHLIGHT = (
    "Exports are faster and easier to review, with an updated Group Analysis sheet and optional HTML dashboard output when selected."
)

release_notes = f"""
    <br><b>Current version {VERSION_LABEL}:</b><br>
    - Faster export/report generation<br>
    - Export setup screens are easier to use, with fewer layout issues in common window sizes<br>
    - Saved export presets now load more reliably for repeat workflows<br>
    - The updated Group Analysis sheet is easier to scan, compare, and interpret during routine review<br>
    - Added optional HTML dashboard output with extended plots and group analysis, when selected<br>

    <br><b>Archive:</b><br>

    <br><b>Version 2026.03rc2 (build 260322):</b><br>
    - Group Analysis became easier to read and interpret in grouped export workflows<br>
    - User manuals were expanded for clearer grouped export setup and worksheet reading<br>

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
