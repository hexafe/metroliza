"""Literal dashboard controls, also executable against a frozen original source."""
from __future__ import annotations

from copy import deepcopy
import ast
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import pytest

from metroliza.industrial import industrial_analytics_dashboard as canonical


@pytest.fixture
def dashboard():
    source = os.environ.get("METROLIZA_DASHBOARD_CONTROL_SOURCE")
    if not source:
        return canonical
    path = Path(source).resolve(strict=True)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == os.environ.get(
        "METROLIZA_DASHBOARD_CONTROL_SOURCE_SHA256",
        "e73c2e5d68bcb1058203ded1c24181169662d3ef5bc04c7a7007566889148a01",
    )
    spec = importlib.util.spec_from_file_location("metroliza.industrial._original_dashboard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert Path(module.__file__).resolve() == path
    assert module is not canonical
    # Relocation of the frozen source must not relocate its bundled runtime asset.
    module.PLOTLY_ASSET_SOURCE = canonical.PLOTLY_ASSET_SOURCE
    return module


def _manifest():
    return {
        "schema": canonical.DASHBOARD_SCHEMA,
        "summary": {"source_rows": 6, "rows": 6, "metric_count": 1, "chart_count": 4},
        "metrics": [{"field_name": "v", "display_label": "Żółć", "source_kind": "csv"}],
        "charts": [
            {"id": str(i), "title": "Żółć", "chart_type": "time_series",
             "notes": ["original"],
             "plotly_spec": {"data": [{"x": ["2026-01-01"], "y": [i, -0.0]}],
                             "layout": {"title": "Żółć"}}}
            for i in range(3)
        ] + [{"id": "empty", "plotly_spec": {}, "notes": []}],
        "groupstats": {"metrics": []}, "diagnostics": [],
    }


@pytest.mark.parametrize("count", [None, 0, 1, 2, 3, 4])
@pytest.mark.parametrize("offset", [-1, 0, 1, None])
def test_budget_boundary_complete_manifest_and_independence(dashboard, count, offset):
    source = _manifest()
    original = deepcopy(source)
    size = len(json.dumps(source["charts"][0]["plotly_spec"], ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8"))
    budget = None if offset is None else size + offset
    rendered, status, reason = dashboard._copy_manifest_with_plotly_budget(
        source, count_budget=count, json_bytes_budget=budget,
    )
    allowed = 3 if count is None else min(3, count)
    if budget is not None:
        allowed = min(allowed, budget // size)
    expected = deepcopy(original)
    note = ("Interactive chart replaced with an image snapshot because this chart would make "
            "the saved dashboard too large; summary content remains available.")
    for chart in expected["charts"][allowed:3]:
        chart.pop("plotly_spec")
        chart["notes"].append(note)
    reasons = []
    if count is not None and 3 > count:
        reasons.append(f"spec_count>{count}")
    if budget is not None and 3 * size > budget:
        reasons.append(f"serialized_json_bytes>{budget}")
    assert rendered == expected
    assert (status, reason) == (("over_budget", ",".join(reasons)) if reasons else
                                ("within_budget", ""))
    assert source == original
    for index in range(allowed):
        assert rendered["charts"][index]["notes"] is source["charts"][index]["notes"]
    for chart in rendered["charts"]:
        if chart.get("plotly_spec"):
            chart["plotly_spec"]["data"][0]["y"].append(999)
    assert source == original


@pytest.mark.parametrize(("counts", "limit", "expected"), [
    ([], 4, []), ([0, -1, 0], 1, [0, 0, 0]), ([1, 2], 0, [0, 0]),
    ([1, 2], 3, [1, 2]), ([2, 2, 2], 4, [1, 1, 2]),
    ([10, 1, 1], 3, [1, 1, 1]), ([1, 1, 1], 2, [1, 1, 0]),
    ([0, 4, 4, 0], 3, [0, 1, 2, 0]), ([100, 2, 3], 8, [6, 1, 1]),
])
def test_allocation_literal_order_and_remainders(dashboard, counts, limit, expected):
    assert dashboard._sample_allocations(counts, limit) == expected


@pytest.mark.parametrize("dtype", ["float64", "float32", "int64", "int8", "bool", "Int64"])
def test_json_values_numeric_types_and_nonfinite(dashboard, dtype):
    raw = [1, 0, -1] if dtype not in {"bool", "Int64"} else [1, 0, 1]
    series = pd.Series(raw, dtype=dtype)
    assert dashboard._json_values(series) == series.tolist()
    values = dashboard._json_values(pd.Series([None, np.nan, np.inf, -np.inf, -0.0]))
    assert values[:4] == [None, None, np.inf, -np.inf]
    assert np.signbit(values[4])


@pytest.mark.parametrize(("bucket", "expected"), [
    (None, "2026-01-02T03:04:00+01:00"), ("none", "2026-01-02T03:04:00+01:00"),
    ("year", "2026"), ("month", "2026-01"), ("day", "2026-01-02"),
    ("week", "Week of 2026-01-02"), ("hour", "2026-01-02 02:00"),
    ("custom", "2026-01-02T02:04:00"),
])
def test_json_values_timestamp_buckets(dashboard, bucket, expected):
    series = pd.Series([pd.Timestamp("2026-01-02T03:04:00+01:00"), pd.NaT])
    assert dashboard._json_values(series, time_bucket=bucket) == [expected, None]


def test_json_values_general_objects_errors_and_callbacks(dashboard):
    events = []

    class Value:
        def isoformat(self):
            events.append("isoformat")
            return "callback"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert dashboard._json_values(pd.Series([Value(), None, pd.NA, pd.NaT], dtype=object)) == [
            "callback", None, None, None,
        ]
    assert events == ["isoformat"]
    assert caught == []
    with pytest.raises(ValueError, match="truth value of an array"):
        dashboard._json_values(pd.Series([[1, 2]], dtype=object))


@pytest.mark.parametrize("mode", ["manager_subclass", "manager_instance", "manager_replaced"])
def test_json_values_preserves_raw_manager_callbacks(dashboard, mode):
    series = pd.Series([1.0, 2.0])
    manager = series._mgr
    events = []

    def observed(read):
        events.append("internal_values")
        warnings.warn("manager-probe", UserWarning)
        values = read()
        if mode == "manager_replaced":
            object.__setattr__(series, "_mgr", pd.Series([np.nan, np.nan])._mgr)
        return values

    if mode == "manager_instance":
        read = manager.internal_values
        manager.internal_values = lambda: observed(read)
    else:
        class Manager(type(manager)):
            def internal_values(self):
                return observed(super().internal_values)

        object.__setattr__(series, "_mgr", Manager(manager.blocks[0], manager.axes[0]))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = dashboard._json_values(series)
    assert result == [1.0, 2.0]
    assert [type(value) for value in result] == [float, float]
    assert events == ["internal_values"]
    assert [(type(item.message), str(item.message)) for item in caught] == [(UserWarning, "manager-probe")]


@pytest.mark.parametrize("mode", ["axes_subclass", "blocks_subclass", "axes_length", "cached_block"])
def test_json_values_declines_non_native_manager_containers(dashboard, mode):
    series = pd.Series([1.0, np.nan])
    manager = series._mgr
    block = manager.blocks[0]
    manager.__dict__["_block"] = block
    events = []

    class Axes(list):
        def __len__(self):
            events.append("axes-length")
            return super().__len__()

    class Blocks(tuple):
        def __getitem__(self, key):
            events.append("blocks-lookup")
            return super().__getitem__(key)

    expected = [1.0, None]
    if mode == "axes_subclass":
        manager.axes = Axes(manager.axes)
    elif mode == "blocks_subclass":
        manager.blocks = Blocks(manager.blocks)
    elif mode == "axes_length":
        manager.axes = manager.axes * 2
    else:
        manager.__dict__["_block"] = pd.Series([9.0, np.nan])._mgr.blocks[0]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = dashboard._json_values(series)
        if hasattr(dashboard, "_plain_json_values_array"):
            assert dashboard._plain_json_values_array(series) is None
    assert result == expected
    assert [type(value) for value in result] == [float, type(None)]
    assert events == (["blocks-lookup"] if mode == "blocks_subclass" else [])
    assert caught == []


def _original_trace_values(module, frame, y_series):
    # Execute the exact original conversion statements at the extracted seam.
    # The dashboard fixture binds the full original file to its immutable hash.
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_time_series_traces")
    assignments = [node for node in ast.walk(function) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id in {"x_values", "y_values"}
                           for target in node.targets)]
    assert len(assignments) == 2
    namespace = dict(module.__dict__, group=frame, y_series=y_series, x_column="x", time_bucket=None)
    exec(compile(ast.Module(body=assignments, type_ignores=[]), module.__file__, "exec"), namespace)
    return namespace["x_values"], namespace["y_values"]


@pytest.mark.parametrize("mode", ["frame", "index", "flags", "series", "frame_key"])
def test_raw_metadata_declines_without_new_dictionary_callbacks(dashboard, mode):
    frame = pd.DataFrame({"x": pd.Series(["2026-01-01", "2026-01-02"], dtype=object),
                          "y": [3.0, 4.0]})
    y_series = frame["y"]
    assert frame.columns.is_unique
    frame.columns.get_loc("x")
    events = []
    armed = False

    def record(operation):
        if armed:
            events.append(operation)
            warnings.warn("raw-state-probe", UserWarning)

    class State(dict):
        def keys(self):
            record("keys")
            return super().keys()

        def get(self, key, default=None):
            record("get")
            return super().get(key, default)

        def __contains__(self, key):
            record("contains")
            return super().__contains__(key)

    class Key(str):
        def __hash__(self):
            record("hash")
            return super().__hash__()

        def __eq__(self, other):
            record("eq")
            return super().__eq__(other)

    if mode == "frame_key":
        frame.__dict__[Key("raw_metadata")] = True
    else:
        owners = {"frame": frame, "index": frame.columns, "flags": frame.flags, "series": y_series}
        owner = owners[mode]
        object.__setattr__(owner, "__dict__", State(owner.__dict__))
    armed = True
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if hasattr(dashboard, "_time_series_trace_values"):
            result = dashboard._time_series_trace_values(frame, y_series, "x", "y", None, materialize=False)
        else:
            result = _original_trace_values(dashboard, frame, y_series)
    assert result == (["2026-01-01", "2026-01-02"], [3.0, 4.0])
    assert [[type(value) for value in column] for column in result] == [[str, str], [float, float]]
    assert events == []
    assert caught == []


@pytest.mark.parametrize("mode", ["instance", "axis", "storage"])
def test_snapshot_omission_declines_before_unsupported_lookup_callbacks(dashboard, mode):
    frame = pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]})
    y_series = frame["y"]
    events = []

    def record():
        events.append("lookup")
        warnings.warn("lookup-probe", UserWarning)

    if mode == "instance":
        read = frame._get_item

        def get_item(key):
            record()
            return read(key)

        object.__setattr__(frame, "_get_item", get_item)
    elif mode == "axis":
        class Axis(type(frame.columns)):
            def get_loc(self, key):
                record()
                return super().get_loc(key)

        frame.columns = Axis._simple_new(frame.columns._values, name=frame.columns.name)
    else:
        manager = frame._mgr
        block = manager.blocks[0]

        class Block(type(block)):
            def iget(self, key):
                record()
                return super().iget(key)

        custom_block = Block(block.values, placement=block._mgr_locs, ndim=block.ndim, refs=block.refs)
        object.__setattr__(frame, "_mgr", type(manager)((custom_block,), manager.axes))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if hasattr(dashboard, "_time_series_trace_values"):
            result = dashboard._time_series_trace_values(frame, y_series, "x", "y", None, materialize=False)
        else:
            result = _original_trace_values(dashboard, frame, y_series)
    assert result == ([1.0, 2.0], [3.0, 4.0])
    assert [[type(value) for value in column] for column in result] == [[float, float], [float, float]]
    assert events == ["lookup"]
    assert [(type(item.message), str(item.message)) for item in caught] == [(UserWarning, "lookup-probe")]


@pytest.mark.parametrize("points", [0, 1, 5, 6])
@pytest.mark.parametrize("include", [True, False])
@pytest.mark.parametrize("population_mode", ["auto", "interactive"])
def test_time_series_omission_and_hybrid_boundaries(
    dashboard, monkeypatch, points, include, population_mode,
):
    monkeypatch.setattr(dashboard, "DASHBOARD_RAW_POINT_LIMIT", 5)
    monkeypatch.setattr(dashboard, "plotstats_export_charts_enabled", lambda: False)
    rendered = []

    def render(x, y, **kwargs):
        rendered.append({"x": x.tolist(), "y": y.tolist(), **kwargs})
        return b"fixed test raster"

    monkeypatch.setattr(dashboard, "_render_time_series_raw_layer_png", render)
    frame = pd.DataFrame({"process_datetime": pd.date_range("2026-01-01", periods=points),
                          "v": np.arange(points, dtype=float)})
    original = frame.copy(deep=True)
    charts = dashboard._build_time_series_charts(
        dashboard.ProductionMetricSelection("v", "Value"), raw_frame=frame,
        aggregate_frame=pd.DataFrame(), aggregation=dashboard.ProductionAggregationState(),
        include_plotly_specs=include, population_layer_mode=population_mode,
    )
    pd.testing.assert_frame_equal(frame, original)
    assert len(charts) == int(points > 0)
    if charts:
        assert ("plotly_spec" in charts[0]) is include
    assert bool(rendered) is (points > 5 and population_mode != "interactive")
    evidence = os.environ.get("METROLIZA_DASHBOARD_CONTROL_OUTPUT")
    if evidence:
        destination = Path(evidence) / f"traces-{points}-{include}-{population_mode}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({"charts": charts, "rendered": rendered},
                                          sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("mode", ["auto", "static"])
@pytest.mark.parametrize("runtime", [True, False])
@pytest.mark.parametrize("count", [0, 1, 3])
def test_writer_complete_consumed_output(dashboard, monkeypatch, tmp_path, mode, runtime, count):
    source = _manifest()
    original = deepcopy(source)
    consumed = []
    monkeypatch.setattr(dashboard, "perf_counter", lambda: 0.0)
    real_render = dashboard._render_dashboard_html

    def render(manifest, **kwargs):
        consumed.append(deepcopy(manifest))
        return real_render(manifest, **kwargs)

    monkeypatch.setattr(dashboard, "_render_dashboard_html", render)
    if not runtime:
        monkeypatch.setattr(dashboard, "_copy_plotly_runtime_asset", lambda _: None)
    result = dashboard.write_production_dashboard(
        source, tmp_path / "dashboard.html", plotly_spec_count_budget=count,
        dashboard_interactivity_options={"mode": mode, "large_group_layer_mode": "interactive"},
    )
    assert source == original
    assert len(consumed) == 1
    expected_embedded = min(count, 3) if runtime and mode != "static" else 0
    assert result["html_dashboard_embedded_plotly_spec_count"] == expected_embedded
    assert result["html_dashboard_plotly_spec_count"] == 3
    assert result["html_dashboard_html_bytes"] == len((tmp_path / "dashboard.html").read_bytes())
    evidence = os.environ.get("METROLIZA_DASHBOARD_CONTROL_OUTPUT")
    if evidence:
        destination = Path(evidence) / f"{mode}-{runtime}-{count}"
        destination.mkdir(parents=True)
        (destination / "dashboard.html").write_bytes((tmp_path / "dashboard.html").read_bytes())
        assets = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (tmp_path / "dashboard_assets").iterdir()}
        result["html_dashboard_path"] = Path(result["html_dashboard_path"]).name
        result["html_dashboard_assets_path"] = Path(result["html_dashboard_assets_path"]).name
        (destination / "consumed.json").write_text(json.dumps(
            {"manifest": consumed[0], "result": result, "assets": assets},
            ensure_ascii=False, sort_keys=True, allow_nan=True), encoding="utf-8")


def test_uncancelled_writer_literal_outputs_and_input_state(dashboard, monkeypatch, tmp_path):
    """Cancellation work must preserve every consumed byte and the caller's manifest."""
    manifest = _manifest()
    before = deepcopy(manifest)
    monkeypatch.setattr(dashboard, "perf_counter", lambda: 0.0)
    results, outputs = [], []
    for name in ("first", "second"):
        root = tmp_path / name
        result = dashboard.write_production_dashboard(manifest, root / "dashboard.html")
        results.append({key: Path(value).name if key.endswith("_path") else value
                        for key, value in result.items()})
        outputs.append({str(path.relative_to(root)): path.read_bytes()
                        for path in root.rglob("*") if path.is_file()})
    assert results[0] == results[1]
    assert outputs[0] == outputs[1]
    assert manifest == before


@pytest.mark.parametrize("stage", ["manifest", "serialization", "render"])
def test_cancel_after_real_dashboard_stage_stops_later_work(dashboard, monkeypatch, tmp_path, stage):
    entered = []
    if stage == "manifest":
        def chart(*args, **kwargs):
            entered.append("chart")
            return {"id": "first"}
        monkeypatch.setattr(dashboard, "_build_histogram_chart", chart)
        with pytest.raises(RuntimeError):
            dashboard.build_production_dashboard_manifest(
                frame=pd.DataFrame({"v": [1., 2.], "w": [3., 4.]}),
                metric_selection=(dashboard.ProductionMetricSelection("v"),
                                  dashboard.ProductionMetricSelection("w")),
                chart_selection=dashboard.ProductionChartSelection(
                    time_series=False, histogram=True, violin=False, box=False),
                **({"cancel_check": lambda: bool(entered)}
                   if "cancel_check" in inspect.signature(dashboard.build_production_dashboard_manifest).parameters
                   else {}),
            )
        assert entered == ["chart"]
    else:
        helper = "_measure_plotly_spec_json_bytes" if stage == "serialization" else "_render_chart_section"
        original = getattr(dashboard, helper)
        def observed(*args, **kwargs):
            entered.append(stage)
            return original(*args, **kwargs)
        monkeypatch.setattr(dashboard, helper, observed)
        with pytest.raises(RuntimeError):
            dashboard.write_production_dashboard(
                _manifest(), tmp_path / "cancelled.html",
                **({"cancel_check": lambda: bool(entered)}
                   if "cancel_check" in inspect.signature(dashboard.write_production_dashboard).parameters
                   else {}))
        assert entered == [stage]
        assert not (tmp_path / "cancelled.html").exists()
