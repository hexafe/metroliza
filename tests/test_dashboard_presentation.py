"""Presentation partitions existing evidence; component commands remain local."""
from copy import deepcopy
import json
import re
import shutil
import subprocess

import pytest

from metroliza.charts.dashboard_html_controls import (
    render_dashboard_component_keys_js,
    render_dashboard_visual_dialog,
    render_dashboard_visual_runtime_js,
)
from metroliza.charts.export_html_dashboard import _render_dashboard_html
from metroliza.industrial.industrial_analytics_dashboard import (
    _render_dashboard_html as _render_csv_html, _summary_card_rows,
)


def _csv_manifest(*, sampled=False, static=False):
    return {
        "summary": {
            "dashboard_title": "CSV Summary", "rows": 3, "source_rows": 12 if sampled else 3,
            "aggregate_rows": 2, "metric_count": 1, "chart_count": 1,
            "aggregation_methods": ["mean"], "group_fields": ["manual_group"],
            "dashboard_context": {"source_label": "Żółć <source>.csv", "sheet_label": "Sheet & 1",
                                  "filter_label": "None", "chart_detail": "Auto; 24 MB size limit",
                                  "population_layer_detail": "Auto"},
            "static_population_layer": {"applied_chart_count": 1 if static else 0},
        },
        "diagnostics": [{"severity": "warning", "message": "Specification limits missing: Cpk unavailable."}],
        "charts": [{"id": "metric-1", "title": "Metric <1>",
                    "notes": ["Plot shows 3 sampled points from 12 rows."] if sampled else [],
                    "plotly_spec": {"data": [{"x": [1, 2, 3], "y": [0, None, -1.25]}],
                                    "layout": {"title": "Exact values"}}}],
    }


@pytest.mark.parametrize("sampled,static", [(False, False), (True, False), (True, True)])
def test_csv_hero_moves_only_technical_choices_without_changing_evidence(sampled, static):
    manifest = _csv_manifest(sampled=sampled, static=static)
    original = deepcopy(manifest)
    rows = _summary_card_rows(manifest["summary"])
    page = _render_csv_html(manifest, asset_directory_name="private_assets")
    assert manifest == original and _summary_card_rows(manifest["summary"]) == rows
    hero = page.split('<header class="hero"', 1)[1].split('</header>', 1)[0]
    notes = page.split('<details id="run-notes"', 1)[1].split('</details>', 1)[0]
    assert '<h1>Żółć &lt;source&gt;.csv</h1>' in hero
    assert 'class="dashboard-context"' in hero and 'Sheet &amp; 1' in hero
    assert '<dt>Aggregation</dt><dd>Mean</dd>' in hero
    assert 'Rows rendered' in hero and 'Metrics' in hero and 'Charts' in hero
    assert 'Dashboard interactivity' not in hero and '24 MB' not in hero
    assert 'Dashboard interactivity: Auto; 24 MB size limit' in notes
    assert 'href="#run-notes"' in hero
    assert 'Specification limits missing: Cpk unavailable.' in page
    assert '<details id="attention-needed" class="dashboard-messages attention-needed" open>' in page
    if sampled:
        assert 'Source rows' in hero and '>12</span>' in hero
        assert 'Plot shows 3 sampled points from 12 rows.' in page
    if static:
        assert 'Static image in 1 chart(s)' in hero
    else:
        assert 'Large group layers: Auto' in notes
    payload = re.search(r'id="production-dashboard-charts" type="application/json">(.*?)</script>', page, re.S)
    assert json.loads(payload.group(1)) == [{
        "id": "metric-1", "title": "Metric <1>",
        "plotly_spec": {"data": [{"x": [1, 2, 3], "y": [0, None, -1.25]}],
                        "layout": {"title": "Exact values"}},
    }]


def test_empty_csv_keeps_missing_counts_missing_and_configuration_discoverable():
    page = _render_csv_html({"summary": {"dashboard_context": {"chart_detail": "Static"}}, "charts": []},
                        asset_directory_name="assets")
    assert '<span class="metric-value-line">n/a</span>' in page
    assert '<span class="metric-value-line">0</span>' not in page
    assert 'href="#run-notes"' in page and 'Dashboard interactivity: Static' in page
    assert 'id="production-dashboard-charts"' not in page


def test_group_comparison_navigation_and_values_survive_compact_shell():
    manifest = {
        "source_label": "Synthetic groups", "sections": [], "section_count": 0, "chart_count": 0,
        "group_analysis": {
            "metrics": [{"id": "metric-diameter", "metric": "Diameter", "group_count": 2,
                         "summary_rows": [{"label": "Mean shift", "value": "-1.25"},
                                          {"label": "Cpk", "value": "n/a"}]}],
            "warning_messages": ["Specification unavailable; no capability conclusion."],
        },
    }
    original = deepcopy(manifest)
    page = _render_dashboard_html(manifest)
    assert manifest == original
    assert 'href="#group-analysis">Group comparison</a>' in page
    assert 'href="#metric-diameter">Diameter</a>' in page
    assert 'id="group-analysis"' in page and 'id="metric-diameter"' in page
    assert '>Mean shift</td><td>-1.25</td>' in page
    assert '>Cpk</td><td>n/a</td>' in page
    assert 'Specification unavailable; no capability conclusion.' in page


@pytest.mark.parametrize("interactive", [False, True])
def test_both_viewers_wire_local_close_with_visible_equivalent_and_stable_ids(interactive):
    csv_page = _render_csv_html(_csv_manifest(), asset_directory_name="assets")
    export_page = _render_dashboard_html({"sections": [], "group_analysis": {},
                                          "plotly_js_path": "assets/plotly.js" if interactive else ""})
    for page in (csv_page, export_page):
        assert 'id="chart-lightbox"' in page and 'id="chart-lightbox-close"' in page
        assert 'Close (Esc; Q in viewer)' in page
        assert 'bindDashboardComponentKeys(lightbox,' in page
        assert 'data-dashboard-key-component tabindex="-1"' in page
        assert page.count('const bindDashboardComponentKeys =') == 1
    assert 'No extended summary charts were generated.' in export_page


def test_matches_have_visible_local_commands_and_existing_enter_handlers():
    markup = render_dashboard_visual_dialog()
    runtime = render_dashboard_visual_runtime_js()
    assert 'id="dashboard-visual-point-search-results"' in markup
    assert 'Focus results: E next match. Enter in search: next match.' in markup
    assert 'Next (Enter in search)' in markup
    assert 'aria-label="Point search matches" tabindex="0" data-dashboard-key-component' in runtime
    assert "bindDashboardComponentKeys(controls.querySelector('.plotly-point-nav'), { next });" in runtime
    assert "if (!controls || controls.dataset.dashboardPointControlsBound === '1') return;" in runtime
    assert runtime.count("if (event.key === 'Enter')") == 2


def _node(script, payload):
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("Node unavailable: executable JavaScript control NOT_RUN; browser acceptance is separate")
    result = subprocess.run([executable, "-e", script], input=json.dumps(payload), text=True,
                            capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_component_key_dispatch_protects_focus_editors_modifiers_and_rebinding():
    driver = r"""
      const source = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      global.document = { activeElement: null };
      const run = new Function(source + `
        const listeners = [];
        let nextCount = 0, closeCount = 0;
        const component = {
          contains: (target) => target === component || target === editor,
          closest: () => null,
          addEventListener: (type, callback) => listeners.push(callback),
        };
        const editor = { closest: () => ({}) };
        const next = { disabled: false, click: () => nextCount++ };
        const close = { disabled: false, click: () => closeCount++ };
        bindDashboardComponentKeys(component, { next, close });
        bindDashboardComponentKeys(component, { next, close });
        const send = (key, flags = {}, target = component, focused = target) => {
          document.activeElement = focused;
          let prevented = false;
          listeners.forEach((callback) => callback({ key, target,
            preventDefault: () => { prevented = true; }, ...flags }));
          return prevented;
        };
        const accepted = [send('e'), send('q')];
        const protectedKeys = ['a', 'c', 'x', 'v', 'z', 'Enter', 'Escape', 'E'];
        const ignored = protectedKeys.map((key) => send(key));
        for (const flag of ['ctrlKey', 'altKey', 'metaKey', 'shiftKey', 'repeat', 'isComposing', 'defaultPrevented']) {
          ignored.push(send('e', { [flag]: true }), send('q', { [flag]: true }));
        }
        ignored.push(send('e', { getModifierState: (key) => key === 'AltGraph' }));
        ignored.push(send('q', { getModifierState: (key) => key === 'AltGraph' }));
        ignored.push(send('e', {}, editor), send('q', {}, editor));
        ignored.push(send('e', {}, component, {}), send('q', {}, component, {}));
        next.disabled = true; close.disabled = true;
        ignored.push(send('e'), send('q'));
        return { accepted, ignored, nextCount, closeCount, registrations: listeners.length };
      `);
      process.stdout.write(JSON.stringify(run()));
    """
    observed = _node(driver, render_dashboard_component_keys_js())
    assert observed["accepted"] == [True, True]
    assert not any(observed["ignored"])
    assert observed["nextCount"] == observed["closeCount"] == observed["registrations"] == 1


def test_generated_csv_and_export_javascript_parse_including_snapshot_only():
    pages = [_render_csv_html(_csv_manifest(), asset_directory_name="assets")]
    pages += [_render_dashboard_html({"sections": [], "plotly_js_path": asset})
              for asset in ("", "assets/plotly.js")]
    scripts = []
    for page in pages:
        for attributes, source in re.findall(r'<script([^>]*)>(.*?)</script>', page, re.S):
            if 'application/json' not in attributes and source.strip():
                scripts.append(source)
    observed = _node("const scripts = JSON.parse(require('fs').readFileSync(0, 'utf8')); "
                     "scripts.forEach((source) => new Function(source)); "
                     "process.stdout.write(JSON.stringify(scripts.length));", scripts)
    assert observed >= 6
