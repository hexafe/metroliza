"""Native analytics recipe parity and invalid-source protection."""
from dataclasses import replace
from uuid import uuid4

import pytest

from metroliza.industrial.contracts import IndustrialAnalyticsRequest
from metroliza.industrial.industrial_analytics_state import (
    ProductionAggregationState, ProductionChartSelection, ProductionMetricSelection,
)
from metroliza.recipes.bindings import resolve_plan
from metroliza.recipes.contracts import ParameterKey, RecipeError
from metroliza.recipes.ports import StepContext, StepStatus
from metroliza.tabular.contracts import GroupingAssignment
from metroliza.recipes.tabular_adapter import AnalyticsRecipePorts, capture, resolve


def source(path, *, column="length_mm", numeric=True):
    values = ("1.0", "1.1", "1.2", "1.3") if numeric else ("one", "two", "three", "four")
    path.write_text("timestamp,reference," + column + "\n" + "\n".join(
        f"2026-11-15 10:0{index}:00,R1,{value}" for index, value in enumerate(values)), encoding="utf-8")


def request_for(path, output):
    return IndustrialAnalyticsRequest(
        source_kind="tabular_file", input_file=str(path), output_dashboard_file=str(output),
        output_workbook_file=str(output.with_suffix(".xlsx")),
        metric_selection=(ProductionMetricSelection("length_mm", "Length"),),
        aggregation_state=ProductionAggregationState(group_fields=("reference",)),
        chart_selection=ProductionChartSelection(time_series=False, histogram=False),
        separate_parameter_sheets=False,
    )


def ctx(plan):
    return StepContext(plan.flow_id, plan.run_id, str(uuid4()), lambda: False, lambda *_args: None)


def bind_source(entry, path, output, *, remapping=()):
    values = dict(entry.binding.values)
    values[ParameterKey.SOURCE_FILE] = str(path)
    values[ParameterKey.OUTPUT_FILE] = str(output)
    if remapping:
        values[ParameterKey.COLUMN_ROLES] = remapping
    return resolve_plan(entry.definition, replace(entry.binding, values=tuple(values.items())))


def test_private_capture_preserves_native_request_and_both_output_targets(tmp_path):
    path = tmp_path / "table.csv"
    source(path)
    original = request_for(path, tmp_path / "result.html")
    entry = capture(original)
    plan = resolve_plan(entry.definition, entry.binding)
    effective = resolve(plan)
    assert effective.metric_selection == original.metric_selection
    assert effective.aggregation_state == original.aggregation_state
    assert effective.chart_selection == original.chart_selection
    assert effective.separate_parameter_sheets is False
    assert effective.output_workbook_file == str(tmp_path / "result.xlsx")
    assert effective.tabular_load_result is None
    assert str(path) not in repr(entry.definition)


def test_same_recipe_accepts_compatible_sources_and_requires_explicit_remap(tmp_path):
    first, second, renamed = (tmp_path / name for name in ("first.csv", "second.csv", "renamed.csv"))
    source(first)
    source(second)
    source(renamed, column="width_mm")
    entry = capture(request_for(first, tmp_path / "out.html"))
    ports = AnalyticsRecipePorts()
    for index, path in enumerate((first, second)):
        plan = bind_source(entry, path, tmp_path / f"out{index}.html")
        assert ports.preflight(plan, ctx(plan)).ready
        assert ports.execute(plan.definition.steps[0], plan, ctx(plan)).status is StepStatus.COMPLETED
        ports.finish(plan)
    plan = bind_source(entry, renamed, tmp_path / "renamed.html")
    assert ports.preflight(plan, ctx(plan)).ready
    assert ports.execute(plan.definition.steps[0], plan, ctx(plan)).status is StepStatus.FAILED
    ports.finish(plan)
    plan = bind_source(entry, renamed, tmp_path / "remapped.html", remapping=("length_mm=width_mm",))
    assert ports.preflight(plan, ctx(plan)).ready
    assert ports.execute(plan.definition.steps[0], plan, ctx(plan)).status is StepStatus.COMPLETED
    ports.finish(plan)


def test_type_drift_and_stale_manual_row_membership_are_rejected(tmp_path):
    first, changed = tmp_path / "first.csv", tmp_path / "changed.csv"
    source(first)
    source(changed, numeric=False)
    entry = capture(request_for(first, tmp_path / "out.html"))
    plan = bind_source(entry, changed, tmp_path / "changed.html")
    ports = AnalyticsRecipePorts()
    assert ports.preflight(plan, ctx(plan)).ready
    assert ports.execute(plan.definition.steps[0], plan, ctx(plan)).status is StepStatus.FAILED
    ports.finish(plan)
    manual = replace(request_for(first, tmp_path / "out.html"),
                     grouping_df=(GroupingAssignment(group="A", report_id=1),))
    entry = capture(manual)
    plan = bind_source(entry, changed, tmp_path / "changed.html")
    with pytest.raises(RecipeError, match="stale_manual_grouping"):
        resolve(plan)


def test_real_native_tabular_flow_writes_verified_pair_and_retains_numeric_scope(tmp_path):
    path = tmp_path / "table.csv"
    source(path)
    entry = capture(request_for(path, tmp_path / "result.html"))
    plan = resolve_plan(entry.definition, entry.binding)
    ports = AnalyticsRecipePorts()
    assert ports.preflight(plan, ctx(plan)).ready
    assert ports.execute(plan.definition.steps[0], plan, ctx(plan)).status is StepStatus.COMPLETED
    execution = ports.execute(plan.definition.steps[1], plan, ctx(plan))
    assert execution.status in (StepStatus.COMPLETED, StepStatus.PARTIAL)
    native = ports._results[plan.run_id]
    assert native.row_count == 4 and native.metric_count == 1
    verified = ports.execute(plan.definition.steps[2], plan, ctx(plan))
    assert verified.artifact_verified
    assert not ports._loaded
    ports.finish(plan)


def test_industrial_uses_only_existing_local_cache_and_preserves_filters(tmp_path):
    from tests.industrial_analytics_fixtures import seed_production_analytics_cache
    from metroliza.recipes.industrial_adapter import capture as capture_industrial
    from metroliza.industrial.industrial_analytics_state import ProductionFilterState
    database = tmp_path / "cache.db"
    seed_production_analytics_cache(str(database))
    request = IndustrialAnalyticsRequest(
        source_kind="production_cache", db_file=str(database),
        output_dashboard_file=str(tmp_path / "industrial.html"),
        metric_selection=(ProductionMetricSelection("cycle_time_s"),),
        filter_state=ProductionFilterState(references=("REF-100",)),
        chart_selection=ProductionChartSelection(time_series=False, histogram=False))
    entry = capture_industrial(request)
    plan = resolve_plan(entry.definition, entry.binding)
    assert resolve(plan).filter_state == request.filter_state
    ports = AnalyticsRecipePorts()
    assert ports.preflight(plan, ctx(plan)).ready
    assert ports.execute(plan.definition.steps[0], plan, ctx(plan)).status is StepStatus.COMPLETED
    ports.finish(plan)
    database.unlink()
    assert ports.preflight(plan, ctx(plan)).requires_decision
    assert not database.exists()


def test_native_option_codec_preserves_palette_lists_and_typed_tuples():
    from metroliza.recipes.tabular_adapter import _decode, _encode
    original = {"palette": ["#112233", "#445566"],
                "filters": (ProductionMetricSelection("length_mm"),)}
    decoded = _decode(_encode(original))
    assert decoded == original
    assert type(decoded["palette"]) is list
    assert type(decoded["filters"]) is tuple
    assert type(decoded["filters"][0]) is ProductionMetricSelection
