from __future__ import annotations

from dataclasses import dataclass
import sys
from types import ModuleType, SimpleNamespace

from modules.hexafe_plotstats_adapter import build_histogram_stats_table, render_histogram_png


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
