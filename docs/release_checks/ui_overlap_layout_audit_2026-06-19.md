# UI Overlap And Layout Audit - 2026-06-19

Scope: detailed UI geometry and UX guardrail pass for PyQt dialogs, generated
HTML dashboards, realtime dashboard tables, native chart geometry, and workbook
chart image placement.

## Audit Split

| Slice | Scope | Result |
|---|---|---|
| PyQt dialogs | High-risk desktop dialogs with dense forms, long paths, long labels, fixed heights, and scroll areas. | Added reusable geometry probes and screen-bounded sizing checks. |
| HTML dashboards | Export dashboard controls, point-mark controls, lightbox overlays, realtime dashboard tables, and long text policies. | Added static CSS/markup gates and table text wrapping fixes. |
| Chart/export visuals | Native distribution/IQR/trend geometry, parity fixtures, and workbook image placement. | Fixed legend and workbook-slot defects; added geometry/package-level tests. |

## Findings And Implementation

| Finding | Risk | Resolution |
|---|---|---|
| Several top-level dialogs requested minimum widths larger than the available offscreen/narrow desktop. | Dialogs could open clipped or wider than the screen on small displays. | `configure_window_size()` now clamps minimum and initial size to the available screen budget before applying maximum size. |
| PyQt layout tests checked only coarse size/labels, not visible sibling overlap or controls escaping parent bounds. | Regressions in dense forms could pass until noticed manually. | Added `tests/ui_geometry_audit.py` and high-risk dialog probes in `tests/test_pyqt_ui_geometry_audit.py`. |
| Export dashboard and realtime dashboard tables did not consistently enforce long-token wrapping. | Long station names, trace codes, paths, or identifiers could push table content out of place. | Added `overflow-wrap: anywhere` and `word-break: break-word` to export and realtime dashboard table cells. |
| Dashboard point controls and lightbox overlays had no regression gates for viewport containment. | Future CSS changes could place controls over chart content or let overlays exceed the viewport. | Added static CSS/JS assertions for lightbox bounds, inline point-control layout, short-viewport rules, and scroll containment. |
| Resolved distribution/IQR legend geometry could fall into the plot band as legend item count grew. | Native rendered legends could collide with the plot area. | Anchored estimated legend geometry above the plot band and updated chart parity planner fixtures. |
| Dense rotated trend tick labels were not strictly capped to the requested maximum length. | Long tick labels could overflow the lower chart band. | Fixed tick truncation to respect the full `max_label_chars` budget including ellipsis. |
| Analytics workbook PNG charts were inserted at raw size. | Exported histogram/distribution images could exceed their reserved worksheet chart slot. | Added `insert_image_fit_to_slot()` and applied it to rendered histogram and distribution workbook images. |

## Validation

Focused UI/export gate:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest \
  tests/test_pyqt_ui_geometry_audit.py \
  tests/test_ui_revamp_foundation_layout.py \
  tests/test_export_dialog_layout.py \
  tests/test_filter_dialog_layout.py \
  tests/test_industrial_data_dialog.py \
  tests/test_realtime_monitoring_dialog.py \
  tests/test_dashboard_visual_options_dialog.py \
  tests/test_dashboard_html_controls.py \
  tests/test_export_html_dashboard.py \
  tests/test_realtime_dashboard_html.py \
  tests/test_chart_render_spec.py \
  tests/test_native_chart_renderer_smoke.py \
  tests/test_industrial_analytics_workbook_charts.py \
  tests/test_export_histogram_layout.py \
  tests/test_export_workbook_planning_helpers.py \
  tests/test_chart_renderer.py \
  tests/test_characteristic_mapping_dialog.py \
  tests/test_tabular_analytics_filter_dialog.py \
  tests/test_industrial_sync_dialog.py \
  tests/test_industrial_analytics_dialog.py -q
```

Result: `338 passed, 6 warnings`.

Full local gate:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest -q
```

Result: `2135 passed, 320 skipped, 6 warnings, 83 subtests passed`.

Focused lint/syntax/whitespace:

```bash
PYTHONPATH=src:. python -m ruff check <UI audit touched Python files>
PYTHONPATH=src:. python -m py_compile <UI audit touched Python files>
git diff --check
```

Result: all passed.

Security and coverage:

```bash
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
```

Result: no known vulnerabilities; existing Bandit findings remain the
report-only baseline.

```bash
python -m coverage erase
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q \
  --cov=src/metroliza --cov=modules --cov=scripts --cov-report= --cov-fail-under=0
# followed by the isolated UI coverage append shards from .github/workflows/ci.yml
python -m coverage report --fail-under=80
python -m coverage xml -o coverage.xml
```

Result: `2135 passed, 320 skipped, 103 warnings, 83 subtests passed`; isolated
UI shards passed (`24`, `40`, `78`, `12`, `79`, `82`, and `37` tests);
coverage passed at `81%`.

## Release Status

- Build identity: unchanged at `2026.06 RC1 (build 260617)`.
- Local release/QA validation: passed.
- Push and green GitHub Actions CI for this integrated closeout: pending final
  rc2 publication.
- Promotion remains blocked on the standing manual release gates: packaging
  smoke, Windows clean-machine launch/startup evidence, Google conversion smoke,
  third-party notice artifact evidence, and security-owner triage/waiver for any
  report-only findings.

## Residual Risk

The dashboard/browser checks are deterministic static CSS/markup/JS gates
because Playwright/browser binaries were not available in this environment.
They guard the highest-risk CSS contracts, but they do not replace a rendered
browser capture pass for exact Plotly legend/control bounding boxes.
