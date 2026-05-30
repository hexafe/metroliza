# HTML Dashboard Assets

This directory holds vendored runtime assets that the HTML dashboard exporter copies into each `*_dashboard_assets/` folder.

- `plotly-2.27.0.min.js`: fetched from `https://cdn.plot.ly/plotly-2.27.0.min.js`

Keep the filename stable with:

- `modules/export_html_dashboard.py`
- `packaging/metroliza_onefile.spec`
- `packaging/build_nuitka.ps1`
- packaging regression tests in `tests/test_packaged_pdf_parser_validation.py`
