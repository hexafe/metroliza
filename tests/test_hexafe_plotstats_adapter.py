from __future__ import annotations

from dataclasses import dataclass
import sys
from types import ModuleType, SimpleNamespace

from modules.hexafe_plotstats_adapter import (
    PLOTSTATS_EXPORT_CHARTS_ENV_VAR,
    build_chart_artifact,
    build_dashboard_plotly_spec,
    build_histogram_stats_table,
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

    assert spec == {
        "data": [{"type": "bar", "x": [1], "y": [2]}],
        "layout": {"title": {"text": "Cycle Time"}},
        "config": {"staticPlot": True},
        "metadata": {"backend": "plotstats"},
    }
    assert calls["payload"] == {"type": "histogram", "values": [1.0, 2.0]}
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
