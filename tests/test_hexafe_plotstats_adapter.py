from __future__ import annotations

from dataclasses import dataclass
import sys
from types import ModuleType, SimpleNamespace

from modules.hexafe_plotstats_adapter import (
    PLOTSTATS_EXPORT_CHARTS_ENV_VAR,
    _fallback_dashboard_plotly_spec,
    build_chart_artifact,
    build_dashboard_plotly_spec,
    build_histogram_stats_table,
    build_plotstats_dashboard_spec,
    plotstats_export_charts_enabled,
    render_chart_artifact_png,
    render_histogram_png,
)


def test_histogram_stats_table_uses_export_style_rows() -> None:
    table = build_histogram_stats_table([1.0, 2.0, 3.0], title="Cycle Time")

    assert table is not None
    assert table.title == "Cycle Time"
    rows = dict(table.rows)
    assert rows["Mean"] == "2.000"
    assert rows["Samples"] == "3"


def test_render_histogram_png_uses_hexafe_plotstats_when_available(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeHistogramConfig:
        def __init__(self, *, bins, density, include_fit):
            calls["config"] = {
                "bins": bins,
                "density": density,
                "include_fit": include_fit,
            }

    @dataclass(frozen=True)
    class FakeSpecLimits:
        lsl: float | None = None
        nominal: float | None = None
        usl: float | None = None

    @dataclass(frozen=True)
    class FakePayload:
        table_rows: tuple = ()

    @dataclass(frozen=True)
    class FakeTableRow:
        label: str
        value: str
        kind: str

    def fake_build_histogram_payload(values, *, spec_limits=None, config, metadata):
        calls["values"] = tuple(values)
        calls["spec_limits"] = spec_limits
        calls["metadata"] = metadata
        return FakePayload()

    def fake_render_histogram(payload, *, backend):
        import matplotlib.pyplot as plt

        calls["backend"] = backend
        calls["table_rows"] = payload.table_rows
        fig, ax = plt.subplots()
        ax.hist([1.0, 2.0, 3.0])
        return SimpleNamespace(fig=fig, ax=ax)

    package = ModuleType("hexafe_plotstats")
    package.HistogramConfig = FakeHistogramConfig
    package.build_histogram_payload = fake_build_histogram_payload
    package.render_histogram = fake_render_histogram
    models = ModuleType("hexafe_plotstats.models")
    payloads = ModuleType("hexafe_plotstats.models.payloads")
    common = ModuleType("hexafe_plotstats.models.common")
    payloads.TableRow = FakeTableRow
    common.SpecLimits = FakeSpecLimits
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.models", models)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.models.payloads", payloads)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.models.common", common)

    result = render_histogram_png(
        [1.0, 2.0, 3.0],
        title="Cycle Time distribution",
        metric_label="Cycle Time",
        bin_count=4,
    )

    assert result is not None
    assert result.backend == "hexafe-plotstats"
    assert result.png_bytes.startswith(b"\x89PNG")
    assert calls["backend"] == "matplotlib"
    assert calls["config"] == {"bins": 4, "density": False, "include_fit": True}
    assert calls["spec_limits"] == FakeSpecLimits()
    assert calls["metadata"]["axis_labels"] == {"x": "Cycle Time", "y": "Count"}
    assert any(row.label == "Mean" and row.value == "2.000" for row in calls["table_rows"])


def test_build_dashboard_plotly_spec_uses_plotstats_metroliza_adapter(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_plotly_spec(payload, *, title, theme, static):
        calls["payload"] = payload
        calls["title"] = title
        calls["theme"] = theme
        calls["static"] = static
        return {
            "data": [{"type": "bar", "x": [1], "y": [2]}],
            "layout": {"title": {"text": title}},
            "config": {"staticPlot": True},
            "metadata": {"backend": "plotstats"},
            "resolved": {"large": "not included in Metroliza manifest"},
        }

    package = ModuleType("hexafe_plotstats")
    adapters = ModuleType("hexafe_plotstats.adapters")
    adapters.plotly_spec_from_metroliza_dashboard_payload = fake_plotly_spec
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.adapters", adapters)

    spec = build_dashboard_plotly_spec(
        {"type": "histogram", "values": [1.0, 2.0]},
        title="Cycle Time",
        theme="compact_report",
        static=True,
    )

    assert spec["data"][0]["type"] == "bar"
    assert spec["data"][0]["y"] == [1.0]
    assert spec["layout"]["title"]["text"] == "Cycle Time"
    assert spec["layout"]["yaxis"]["title"]["text"] == "Frequency (%)"
    assert spec["layout"]["yaxis"]["tickformat"] == ".0%"
    assert spec["config"] == {"staticPlot": True}
    assert spec["metadata"] == {
        "backend": "plotstats",
        "kind": "histogram",
        "histogram_y_mode": "percent",
    }
    assert calls["payload"] == {"type": "histogram", "values": [1.0, 2.0], "bin_count": 3}
    assert calls["title"] == "Cycle Time"
    assert calls["theme"] == "compact_report"
    assert calls["static"] is True


def test_plotstats_export_charts_enabled_defaults_on_with_opt_out(monkeypatch) -> None:
    monkeypatch.delenv(PLOTSTATS_EXPORT_CHARTS_ENV_VAR, raising=False)
    assert plotstats_export_charts_enabled() is True

    for enabled_value in ("1", "true", "yes", "on", "all", "*"):
        monkeypatch.setenv(PLOTSTATS_EXPORT_CHARTS_ENV_VAR, enabled_value)
        assert plotstats_export_charts_enabled() is True

    for disabled_value in ("0", "false", "no", "off", "disabled", "metroliza", "legacy"):
        monkeypatch.setenv(PLOTSTATS_EXPORT_CHARTS_ENV_VAR, disabled_value)
        assert plotstats_export_charts_enabled() is False


def test_build_chart_artifact_uses_plotstats_metroliza_artifact_adapter(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_artifact(payload, *, target, theme, backend, include_plotly, include_png, static):
        calls["payload"] = payload
        calls["target"] = target
        calls["theme"] = theme
        calls["backend"] = backend
        calls["include_plotly"] = include_plotly
        calls["include_png"] = include_png
        calls["static"] = static
        return {
            "plotly_spec": {
                "data": [{"type": "bar", "x": [1], "y": [2]}],
                "layout": {},
                "config": {},
                "metadata": {"backend": "plotstats"},
            },
            "png_bytes": b"png",
            "backend": "hexafe-plotstats:matplotlib",
        }

    package = ModuleType("hexafe_plotstats")
    adapters = ModuleType("hexafe_plotstats.adapters")
    adapters.chart_artifact_from_metroliza_payload = fake_artifact
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.adapters", adapters)

    artifact = build_chart_artifact(
        {"type": "trend", "x": [1], "y": [2]},
        target="html_dashboard",
        title="Trend",
        theme="dark",
        include_plotly=True,
        include_png=True,
        static=False,
    )

    assert artifact is not None
    assert artifact["backend"] == "hexafe-plotstats:matplotlib"
    assert calls["payload"] == {"type": "trend", "x": [1], "y": [2], "title": "Trend"}
    assert calls["target"] == "html_dashboard"
    assert calls["theme"] == "dark"
    assert calls["include_png"] is True
    assert calls["static"] is False


def test_plotstats_dashboard_spec_normalizes_histogram_plotly_semantics(monkeypatch) -> None:
    def fake_artifact(_payload, **_kwargs):
        return {
            "plotly_spec": {
                "data": [
                    {
                        "type": "bar",
                        "name": "A",
                        "x": ["123 - 5.97e+03", "5.97e+03 - 1.18e+04"],
                        "y": [0.4, 0.6],
                        "customdata": [[4], [6]],
                    },
                    {
                        "type": "scatter",
                        "mode": "lines",
                        "name": "LSL",
                        "x": [123.0, 123.0],
                        "y": [0.0, 1.0],
                        "line": {"color": "#dc2626"},
                    },
                    {
                        "type": "scatter",
                        "mode": "lines",
                        "name": "Mean",
                        "x": [1000.0, 1000.0],
                        "y": [0.0, 1.0],
                        "line": {"color": "#111827"},
                    },
                ],
                "layout": {
                    "yaxis": {
                        "title": {"text": "Density"},
                        "tickvals": [0.0, 0.5, 1.0],
                        "ticktext": ["0", "0.5", "1"],
                        "nticks": 3,
                    },
                    "xaxis": {"title": {"text": "Bins"}},
                    "annotations": [{"text": "legacy", "bgcolor": "rgba(255,255,255,0.4)"}],
                },
                "config": {"responsive": True},
                "metadata": {"kind": "histogram", "histogram_y_mode": "relative_percent"},
            }
        }

    package = ModuleType("hexafe_plotstats")
    adapters = ModuleType("hexafe_plotstats.adapters")
    adapters.chart_artifact_from_metroliza_payload = fake_artifact
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.adapters", adapters)

    spec = build_plotstats_dashboard_spec(
        {"type": "histogram", "values": [1.0, 2.0]},
        title="Histogram",
        static=False,
    )

    assert spec is not None
    yaxis = spec["layout"]["yaxis"]
    assert yaxis["title"]["text"] == "Frequency (%)"
    assert yaxis["tickformat"] == ".0%"
    assert "range" not in yaxis
    assert "tickvals" not in yaxis
    assert spec["layout"]["xaxis"]["tickformat"] == ".4~g"
    bar_trace = spec["data"][0]
    assert bar_trace["x"] == [3046.5, 8885.0]
    assert bar_trace["width"] == [5847.0, 5830.0]
    assert bar_trace["customdata"][0] == [123.0, 5970.0, 4, "123 - 5.97e+03"]
    assert spec["data"][1]["name"] == "LSL=123.000"
    assert spec["data"][2]["name"] == "Mean=1000.0000"
    annotation_texts = {annotation["text"] for annotation in spec["layout"]["annotations"]}
    assert {"legacy", "LSL=123.000", "Mean=1000.0000"}.issubset(annotation_texts)
    assert all(annotation["bgcolor"] == "#ffffff" for annotation in spec["layout"]["annotations"])
    assert all(annotation["bordercolor"] == "#cbd5e1" for annotation in spec["layout"]["annotations"])
    assert all(annotation["borderwidth"] >= 1 for annotation in spec["layout"]["annotations"])
    assert all(annotation["opacity"] == 1.0 for annotation in spec["layout"]["annotations"])


def test_dashboard_plotly_fallback_builds_percent_histogram_with_reference_values() -> None:
    spec = _fallback_dashboard_plotly_spec(
        {
            "type": "histogram",
            "values": [1.0, 2.0, 3.0, 4.0],
            "limits": {"lsl": 1.5, "usl": 3.5},
            "style": {"axis_label_x": "Length"},
        },
        title="Length distribution",
        static=False,
    )

    assert spec is not None
    assert spec["layout"]["yaxis"]["title"]["text"] == "Frequency (%)"
    assert "range" not in spec["layout"]["yaxis"]
    assert spec["layout"]["xaxis"]["title"]["text"] == "Length"
    assert spec["config"]["staticPlot"] is False
    histogram_trace = spec["data"][0]
    assert histogram_trace["type"] == "bar"
    assert all(isinstance(value, float) for value in histogram_trace["x"])
    assert histogram_trace["hovertemplate"].startswith("bin=%{customdata[0]:.4g}")
    trace_names = {trace["name"] for trace in spec["data"][1:]}
    assert {
        "Min=1.000",
        "Q1=1.750",
        "Median=2.500",
        "Mean=2.5000",
        "Q3=3.250",
        "Max=4.000",
        "LSL=1.500",
        "USL=3.500",
    }.issubset(trace_names)
    annotation_texts = {annotation["text"] for annotation in spec["layout"]["annotations"]}
    assert {"LSL=1.500", "USL=3.500", "Mean=2.5000"}.issubset(annotation_texts)
    assert all(annotation["bgcolor"] == "#ffffff" for annotation in spec["layout"]["annotations"])
    assert all(annotation["bordercolor"] == "#cbd5e1" for annotation in spec["layout"]["annotations"])
    assert all(annotation["borderwidth"] >= 1 for annotation in spec["layout"]["annotations"])
    assert all(annotation["opacity"] == 1.0 for annotation in spec["layout"]["annotations"])


def test_plotstats_dashboard_spec_normalizes_generic_histogram_overlays(monkeypatch) -> None:
    def fake_artifact(_payload, **_kwargs):
        return {
            "plotly_spec": {
                "data": [
                    {"type": "bar", "x": [1.0, 2.0], "y": [4, 6], "width": [0.5, 0.5]},
                    {
                        "type": "scatter",
                        "mode": "lines",
                        "name": "overlay 1",
                        "x": [1.0, 1.5, 2.0],
                        "y": [0.2, 3.0, 0.2],
                    },
                    {
                        "type": "scatter",
                        "mode": "lines",
                        "name": "overlay 2",
                        "x": [1.0, 1.5, 2.0],
                        "y": [0.1, 2.0, 0.1],
                        "line": {"dash": "dash"},
                    },
                    {
                        "type": "scatter",
                        "mode": "lines",
                        "name": "Limit 1",
                        "x": [1.25, 1.25],
                        "y": [0.0, 1.0],
                    },
                ],
                "layout": {"yaxis": {"range": [0.0, 1.0]}},
                "config": {"responsive": True},
                "metadata": {"kind": "histogram"},
            }
        }

    package = ModuleType("hexafe_plotstats")
    adapters = ModuleType("hexafe_plotstats.adapters")
    adapters.chart_artifact_from_metroliza_payload = fake_artifact
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.adapters", adapters)

    spec = build_plotstats_dashboard_spec(
        {"type": "histogram", "values": [1.0, 2.0], "limits": {"lsl": 1.25}},
        title="Histogram",
        static=False,
    )

    assert spec is not None
    trace_names = [trace.get("name") for trace in spec["data"]]
    assert "overlay 1" not in trace_names
    assert "overlay 2" not in trace_names
    assert "Selected model curve" in trace_names
    assert "KDE reference" in trace_names
    assert "LSL=1.250" in trace_names
    assert "range" not in spec["layout"]["yaxis"]
    assert spec["data"][0]["y"] == [0.4, 0.6]
    for trace in spec["data"]:
        if trace.get("name") in {"Selected model curve", "KDE reference"}:
            assert max(trace["y"]) <= 1.0


def test_plotstats_dashboard_spec_scales_low_raw_density_overlays_by_bin_width(monkeypatch) -> None:
    def fake_artifact(_payload, **_kwargs):
        return {
            "plotly_spec": {
                "data": [
                    {"type": "bar", "x": [1.0, 2.0], "y": [0.5, 0.5], "width": [0.25, 0.25]},
                    {
                        "type": "scatter",
                        "mode": "lines",
                        "name": "overlay 1",
                        "x": [1.0, 1.5, 2.0],
                        "y": [0.2, 0.8, 0.2],
                    },
                ],
                "layout": {"yaxis": {"range": [0.0, 1.0]}},
                "metadata": {"kind": "histogram"},
            }
        }

    package = ModuleType("hexafe_plotstats")
    adapters = ModuleType("hexafe_plotstats.adapters")
    adapters.chart_artifact_from_metroliza_payload = fake_artifact
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.adapters", adapters)

    spec = build_plotstats_dashboard_spec(
        {"type": "histogram", "values": [1.0, 2.0]},
        title="Histogram",
        static=False,
    )

    curve = next(trace for trace in spec["data"] if trace.get("name") == "Selected model curve")
    assert curve["y"] == [0.05, 0.2, 0.05]
    assert "range" not in spec["layout"]["yaxis"]


def test_plotstats_dashboard_spec_adds_group_mean_annotations_with_matching_colors(monkeypatch) -> None:
    def fake_artifact(_payload, **_kwargs):
        return {
            "plotly_spec": {
                "data": [
                    {
                        "type": "bar",
                        "name": "A",
                        "x": [1.0, 2.0],
                        "y": [2, 2],
                        "width": [0.5, 0.5],
                        "marker": {"color": "#0072B2"},
                    },
                    {
                        "type": "bar",
                        "name": "B",
                        "x": [1.0, 2.0],
                        "y": [1, 3],
                        "width": [0.5, 0.5],
                        "marker": {"color": "#D55E00"},
                    },
                ],
                "layout": {"annotations": []},
                "metadata": {"kind": "histogram"},
            }
        }

    package = ModuleType("hexafe_plotstats")
    adapters = ModuleType("hexafe_plotstats.adapters")
    adapters.chart_artifact_from_metroliza_payload = fake_artifact
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.adapters", adapters)

    spec = build_plotstats_dashboard_spec(
        {
            "type": "histogram",
            "groups": [
                {"group": "A", "values": [1.0, 2.0]},
                {"group": "B", "values": [1.0, 2.0]},
            ],
        },
        title="Grouped histogram",
        static=False,
    )

    annotations = spec["layout"]["annotations"]
    by_text = {annotation["text"]: annotation for annotation in annotations}
    assert by_text["A mean=1.5000"]["bgcolor"] == "#ffffff"
    assert by_text["A mean=1.5000"]["font"]["color"] == "#0072B2"
    assert by_text["B mean=1.5000"]["bgcolor"] == "#ffffff"
    assert by_text["B mean=1.5000"]["font"]["color"] == "#D55E00"
    assert by_text["A mean=1.5000"]["y"] != by_text["B mean=1.5000"]["y"]
    assert spec["layout"]["margin"]["t"] >= 100
    assert [trace["name"] for trace in spec["data"] if trace["type"] == "bar"] == ["A", "B"]


def test_plotstats_dashboard_spec_adds_distribution_group_stats_to_legend(monkeypatch) -> None:
    def fake_artifact(_payload, **_kwargs):
        return {
            "plotly_spec": {
                "data": [
                    {"type": "violin", "name": "A", "y": [1.0, 2.0, 3.0]},
                    {"type": "violin", "name": "B", "y": [10.0, 12.0, 16.0]},
                ],
                "layout": {},
            }
        }

    package = ModuleType("hexafe_plotstats")
    adapters = ModuleType("hexafe_plotstats.adapters")
    adapters.chart_artifact_from_metroliza_payload = fake_artifact
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.adapters", adapters)

    spec = build_plotstats_dashboard_spec(
        {
            "type": "distribution",
            "labels": ["A", "B"],
            "series": [[1.0, 2.0, 3.0], [10.0, 12.0, 16.0]],
        },
        title="Violin",
        static=False,
    )

    assert spec["data"][0]["name"] == "A (n=3)"
    assert spec["data"][1]["name"] == "B (n=3)"
    trace_names = {trace["name"] for trace in spec["data"]}
    assert {"A Mean=2.0000", "A Q1=1.500", "B Mean=12.6667", "B Max=16.000"}.issubset(
        trace_names
    )
    assert all(
        trace["visible"] == "legendonly"
        for trace in spec["data"][2:]
        if trace["name"].startswith(("A ", "B "))
    )


def test_plotstats_dashboard_spec_adds_iqr_group_stats_to_legend(monkeypatch) -> None:
    def fake_artifact(_payload, **_kwargs):
        return {
            "plotly_spec": {
                "data": [
                    {"type": "box", "name": "A", "y": [1.0, 2.0, 3.0]},
                    {"type": "box", "name": "B", "y": [10.0, 12.0, 16.0]},
                ],
                "layout": {},
            }
        }

    package = ModuleType("hexafe_plotstats")
    adapters = ModuleType("hexafe_plotstats.adapters")
    adapters.chart_artifact_from_metroliza_payload = fake_artifact
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.adapters", adapters)

    spec = build_plotstats_dashboard_spec(
        {
            "type": "iqr",
            "labels": ["A", "B"],
            "series": [[1.0, 2.0, 3.0], [10.0, 12.0, 16.0]],
        },
        title="IQR",
        static=False,
    )

    assert spec["data"][0]["name"] == "A (n=3)"
    assert spec["data"][1]["name"] == "B (n=3)"
    trace_names = {trace["name"] for trace in spec["data"]}
    assert {"A Median=2.000", "A Mean=2.0000", "B Q3=14.000", "B Max=16.000"}.issubset(
        trace_names
    )


def test_plotstats_dashboard_spec_values_existing_single_group_semantic_legend_items(
    monkeypatch,
) -> None:
    def fake_artifact(_payload, **_kwargs):
        return {
            "plotly_spec": {
                "data": [
                    {"type": "box", "name": "A", "y": [6.469, 6.495, 6.501, 6.687]},
                    {"type": "scatter", "mode": "markers", "name": "Minimum", "y": [6.469]},
                    {"type": "scatter", "mode": "markers", "name": "Maximum", "y": [6.687]},
                    {
                        "type": "scatter",
                        "mode": "lines",
                        "name": "Nominal",
                        "x": [0.0, 1.0],
                        "y": [6.5, 6.5],
                    },
                ],
                "layout": {},
            }
        }

    package = ModuleType("hexafe_plotstats")
    adapters = ModuleType("hexafe_plotstats.adapters")
    adapters.chart_artifact_from_metroliza_payload = fake_artifact
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.adapters", adapters)

    spec = build_plotstats_dashboard_spec(
        {
            "type": "iqr",
            "labels": ["A"],
            "series": [[6.469, 6.495, 6.501, 6.687]],
            "limits": {"nominal": 6.5},
        },
        title="IQR",
        static=False,
    )

    trace_names = {trace["name"] for trace in spec["data"]}
    assert "A (n=4)" in trace_names
    assert "Min=6.469" in trace_names
    assert "Mean=6.5380" in trace_names
    assert "Max=6.687" in trace_names
    assert "Nominal=6.500" in trace_names
    assert "Minimum" not in trace_names
    assert "Maximum" not in trace_names


def test_dashboard_plotly_spec_renames_generic_limit_traces(monkeypatch) -> None:
    def fake_spec(_payload, *, title, theme, static):
        return {
            "data": [
                {"type": "bar", "x": [1.0], "y": [1.0]},
                {
                    "type": "scatter",
                    "mode": "lines",
                    "name": "Limit 1",
                    "x": [1.5, 1.5],
                    "y": [0.0, 1.0],
                },
                {
                    "type": "scatter",
                    "mode": "lines",
                    "name": "Limit 2",
                    "x": [3.5, 3.5],
                    "y": [0.0, 1.0],
                },
            ],
            "layout": {},
            "config": {"staticPlot": static},
            "metadata": {"kind": "histogram"},
        }

    package = ModuleType("hexafe_plotstats")
    adapters = ModuleType("hexafe_plotstats.adapters")
    adapters.plotly_spec_from_metroliza_dashboard_payload = fake_spec
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.adapters", adapters)

    spec = build_dashboard_plotly_spec(
        {"type": "histogram", "values": [1.0, 2.0], "limits": {"lsl": 1.5, "usl": 3.5}},
        title="Histogram",
        static=False,
    )

    assert spec is not None
    assert {trace["name"] for trace in spec["data"][1:]} == {"LSL=1.500", "USL=3.500"}
    annotation_texts = {annotation["text"] for annotation in spec["layout"]["annotations"]}
    assert {"LSL=1.500", "USL=3.500"}.issubset(annotation_texts)


def test_render_chart_artifact_png_returns_bytes(monkeypatch) -> None:
    def fake_artifact(payload, **_kwargs):
        return {
            "png_bytes": b"\x89PNG\r\n",
            "backend": "hexafe-plotstats:matplotlib",
            "payload_summary": {"type": payload.get("type")},
        }

    package = ModuleType("hexafe_plotstats")
    adapters = ModuleType("hexafe_plotstats.adapters")
    adapters.chart_artifact_from_metroliza_payload = fake_artifact
    monkeypatch.setitem(sys.modules, "hexafe_plotstats", package)
    monkeypatch.setitem(sys.modules, "hexafe_plotstats.adapters", adapters)

    result = render_chart_artifact_png({"type": "histogram", "values": [1.0, 2.0]})

    assert result is not None
    assert result.png_bytes.startswith(b"\x89PNG")
    assert result.backend == "hexafe-plotstats:matplotlib"
