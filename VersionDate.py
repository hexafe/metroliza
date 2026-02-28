RELEASE_VERSION = "2026.02"
VERSION_DATE = "260228"
CURRENT_RELEASE_HIGHLIGHT = (
    "Google Sheets export messaging is clearer, `.xlsx` fallback is explicit, "
    "and chart-heavy exports remain faster for daily use."
)

release_notes = f"""
    <br><b>Current version {RELEASE_VERSION} (build {VERSION_DATE}):</b><br>
    - Google Sheets export (`google_sheets_drive_convert`) now has clearer sign-in and completion messaging<br>
    - Safe fallback remains guaranteed: if conversion fails, the generated Excel file stays available<br>
    - Large report and CSV Summary exports remain faster for day-to-day use<br>

    <br><b>Version 2026.02 (build 260227):</b><br>
    - More stable Google Sheets export with clearer completion messages<br>
    - Safe fallback: if conversion fails, the generated Excel file remains available<br>
    - Faster export for large reports and chart-heavy outputs<br>
    - CSV Summary improvements (clearer summaries and better limit validation)<br>

    <br><b>Version 2026.02 (build 260223):</b><br>
    - Performance improvements<br>

    <br><b>Version 2026.02 (build 260216):</b><br>
    - Bug fixes and module-level integration improvements<br>

    <br><b>Version 2024.02 (build 240225):</b><br>
    - Added CSV Summary module (prototype release)<br>

    <br><b>Version 2024.02 (build 240218):</b><br>
    - First release<br>
    """
