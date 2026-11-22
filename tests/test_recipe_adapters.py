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
from metroliza.recipes.ports import ResultCode, StepContext, StepStatus
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


def test_multifile_recipe_roundtrips_every_source_through_native_runner(tmp_path):
    from metroliza.recipes.runner import RecipeRunner, RunState
    from metroliza.recipes.storage import RecipeStore
    from metroliza.tabular.tabular_analytics_service import cleanup_tabular_load_result, load_tabular_analytics_files

    data = tmp_path / "data"
    data.mkdir()
    first, second = data / "day, one.csv", data / "day two.csv"
    for path in (first, second):
        source(path)
    with second.open("a", encoding="utf-8") as stream:
        stream.write("\n2026-11-15 10:04:00,R2,7.5\n")
    output = tmp_path / "result.html"
    loaded = load_tabular_analytics_files((first, second))
    try:
        item = capture(replace(request_for(first, output), tabular_load_result=loaded))
    finally:
        cleanup_tabular_load_result(loaded)
    store = RecipeStore(tmp_path / "private")
    store.save(item.definition, item.binding, expected_revision=None)
    saved = store.load(item.definition.recipe_id)
    assert saved.binding.value(ParameterKey.SOURCE_FILES) == (str(first), str(second))

    class RecordingPorts(AnalyticsRecipePorts):
        def _run(self, request, loaded, consents, cancelled, context):
            self.loaded_count = loaded.row_count
            self.loaded_files = loaded.source_files
            return super()._run(request, loaded, consents, cancelled, context)

    ports = RecordingPorts()
    plan = resolve_plan(saved.definition, saved.binding)
    record = RecipeRunner(ports).start(plan)
    assert ports.loaded_files == (str(first), str(second))
    assert ports.loaded_count == 9
    assert record.state is RunState.COMPLETED
    assert output.is_file() and output.with_suffix(".xlsx").is_file()


def test_workbook_publish_failure_reports_new_excel_missing_and_keeps_previous(tmp_path, monkeypatch):
    from metroliza.recipes.runner import RecipeRunner, RunState
    from metroliza.recipes import tabular_adapter

    path, output = tmp_path / "table.csv", tmp_path / "result.html"
    source(path)
    workbook = output.with_suffix(".xlsx")
    workbook.write_bytes(b"previous workbook remains")
    entry = capture(request_for(path, output))
    plan = resolve_plan(entry.definition, entry.binding)

    def failed_publication(_file, target, **_kwargs):
        assert target == str(workbook)
        raise PermissionError("Excel is holding the file")

    monkeypatch.setattr(tabular_adapter, "publish_output", failed_publication)
    runner = RecipeRunner(AnalyticsRecipePorts())
    assert runner.start(plan).state is RunState.REQUIRES_DECISION
    result = runner.resume("continue")
    assert (result.state, result.code) == (RunState.PARTIAL, ResultCode.WORKBOOK_NOT_PUBLISHED)
    assert output.is_file()
    assert workbook.read_bytes() == b"previous workbook remains"


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


def xlsx_source(path):
    from xlsxwriter import Workbook
    with Workbook(str(path)) as workbook:
        sheet = workbook.add_worksheet("Measurements")
        sheet.write_row(0, 0, ("timestamp", "reference", "length_mm"))
        for index, value in enumerate((1.0, 1.1, 1.2, 1.3), start=1):
            sheet.write_row(index, 0, (f"2026-11-15 10:0{index}:00", "R1", value))


def test_analytics_derived_workbook_cannot_replace_xlsx_input_even_with_consent(tmp_path, monkeypatch):
    from metroliza.exporting.output_publication import OutputConsent
    from metroliza.recipes.ports import ResultCode
    from metroliza.recipes.tabular_adapter import analytics_output_family
    path = tmp_path / "measurements.xlsx"
    xlsx_source(path)
    before = path.read_bytes()
    entry = capture(request_for(path, tmp_path / "measurements.html"))
    with pytest.raises(RecipeError, match="source_alias"):
        resolve_plan(entry.definition, entry.binding)

    safe = bind_source(entry, path, tmp_path / "different.html")
    ports = AnalyticsRecipePorts()
    assert ports.preflight(safe, ctx(safe)).ready
    # A stale/forged caller must not bypass the same boundary by retaining run_id
    # and supplying a real identity-bound consent for the input workbook.
    values = dict(safe.binding.values)
    values[ParameterKey.OUTPUT_FILE] = str(tmp_path / "measurements.html")
    binding = replace(safe.binding, values=tuple(values.items()))
    family = analytics_output_family(binding, tmp_path / "measurements.html")
    unsafe = replace(safe, binding=binding, output_file=family.dashboard, assets_dir=family.assets)
    ports._consents[safe.run_id] = (OutputConsent.for_path(path),)

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("source alias must stop before rendering or publication")

    monkeypatch.setattr(ports, "_run", must_not_run)
    rejected = ports.preflight(unsafe, ctx(unsafe))
    assert not rejected.ready and not rejected.requires_decision
    assert rejected.code is ResultCode.INVALID_PLAN
    assert not ports.approve(unsafe, "continue")
    result = ports.execute(unsafe.definition.steps[1], unsafe, ctx(unsafe))
    assert result.status is StepStatus.FAILED and result.code is ResultCode.INVALID_PLAN
    assert path.read_bytes() == before
    assert not family.dashboard.exists() and not family.assets.exists()
    ports.finish(safe)


def test_real_xlsx_source_uses_distinct_complete_output_family_and_is_preserved(tmp_path):
    from metroliza.recipes.bindings import _target_paths
    from metroliza.recipes.tabular_adapter import analytics_output_family
    path = tmp_path / "measurements.xlsx"
    xlsx_source(path)
    before = path.read_bytes()
    entry = capture(request_for(path, tmp_path / "result.html"))
    plan = resolve_plan(entry.definition, entry.binding)
    outputs = analytics_output_family(plan.binding, plan.output_file)
    effective = resolve(plan)
    assert outputs.dashboard == tmp_path / "result.html"
    assert outputs.workbook == tmp_path / "result.xlsx"
    assert outputs.assets == plan.assets_dir
    assert set(_target_paths(plan)) == {outputs.dashboard, outputs.workbook, outputs.assets}
    assert effective.output_dashboard_file == str(outputs.dashboard)
    assert effective.output_workbook_file == str(outputs.workbook)
    ports = AnalyticsRecipePorts()
    assert ports.preflight(plan, ctx(plan)).ready
    assert ports.execute(plan.definition.steps[0], plan, ctx(plan)).status is StepStatus.COMPLETED
    assert ports.execute(plan.definition.steps[1], plan, ctx(plan)).status in (StepStatus.COMPLETED, StepStatus.PARTIAL)
    assert ports.execute(plan.definition.steps[2], plan, ctx(plan)).artifact_verified
    assert path.read_bytes() == before
    assert outputs.dashboard.is_file() and outputs.workbook.is_file()
    ports.finish(plan)


def test_disabled_analytics_workbook_is_not_a_target_or_source_collision(tmp_path):
    from metroliza.recipes.bindings import _target_paths
    from metroliza.recipes.tabular_adapter import analytics_output_family
    path = tmp_path / "measurements.xlsx"
    xlsx_source(path)
    before = path.read_bytes()
    request = replace(request_for(path, tmp_path / "measurements.html"), output_workbook_file="")
    entry = capture(request)
    plan = resolve_plan(entry.definition, entry.binding)
    outputs = analytics_output_family(plan.binding, plan.output_file)
    assert outputs.workbook is None
    assert path not in _target_paths(plan)
    assert resolve(plan).output_workbook_file == ""
    ports = AnalyticsRecipePorts()
    assert ports.preflight(plan, ctx(plan)).ready
    assert path.read_bytes() == before
    ports.finish(plan)


def test_analytics_new_copy_reserves_optional_workbook_and_repeat_rechecks_full_family(tmp_path):
    from metroliza.recipes.bindings import new_output_copy
    path = tmp_path / "measurements.xlsx"
    xlsx_source(path)
    entry = capture(request_for(path, tmp_path / "result.html"))
    plan = resolve_plan(entry.definition, entry.binding)
    occupied_workbook = tmp_path / "result (1).xlsx"
    occupied_workbook.write_bytes(b"previous complete workbook")
    copied = new_output_copy(plan)
    assert copied.output_file == tmp_path / "result (2).html"
    assert resolve(copied).output_workbook_file == str(tmp_path / "result (2).xlsx")
    assert copied.run_id != plan.run_id
    ports = AnalyticsRecipePorts()
    plan.output_file.with_suffix(".xlsx").write_bytes(b"previous final workbook")
    decision = ports.preflight(plan, ctx(plan))
    assert decision.requires_decision and not decision.ready
    assert ports.approve(plan, "continue")
    assert decision.review.conflicts == (plan.output_file.with_suffix(".xlsx"),)
    assert ports._consents[plan.run_id].consents[0].path == plan.output_file.with_suffix(".xlsx")
    assert occupied_workbook.read_bytes() == b"previous complete workbook"
    ports.finish(plan)
    without_workbook = capture(replace(request_for(path, tmp_path / "result.html"), output_workbook_file=""))
    no_workbook_plan = resolve_plan(without_workbook.definition, without_workbook.binding)
    assert new_output_copy(no_workbook_plan).output_file == tmp_path / "result (1).html"


def test_industrial_cache_named_xlsx_cannot_be_replaced_by_derived_workbook(tmp_path, monkeypatch):
    from tests.industrial_analytics_fixtures import seed_production_analytics_cache
    from metroliza.exporting.output_publication import OutputConsent
    from metroliza.recipes.ports import ResultCode
    from metroliza.recipes.tabular_adapter import analytics_output_family
    database = tmp_path / "measurements.xlsx"  # SQLite source suffix is not an authorization boundary.
    seed_production_analytics_cache(str(database))
    before = database.read_bytes()
    native = IndustrialAnalyticsRequest(source_kind="production_cache", db_file=str(database),
        output_dashboard_file=str(tmp_path / "measurements.html"),
        output_workbook_file=str(database), metric_selection=(ProductionMetricSelection("cycle_time_s"),))
    entry = capture(native)
    with pytest.raises(RecipeError, match="source_alias"):
        resolve_plan(entry.definition, entry.binding)
    values = dict(entry.binding.values)
    values[ParameterKey.OUTPUT_FILE] = str(tmp_path / "safe.html")
    safe = resolve_plan(entry.definition, replace(entry.binding, values=tuple(values.items())))
    ports = AnalyticsRecipePorts()
    assert ports.preflight(safe, ctx(safe)).ready
    values[ParameterKey.OUTPUT_FILE] = str(tmp_path / "measurements.html")
    binding = replace(safe.binding, values=tuple(values.items()))
    outputs = analytics_output_family(binding, tmp_path / "measurements.html")
    unsafe = replace(safe, binding=binding, output_file=outputs.dashboard, assets_dir=outputs.assets)
    ports._consents[safe.run_id] = (OutputConsent.for_path(database),)

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("read-only Industrial source cannot become a publication target")

    monkeypatch.setattr(ports, "_run", must_not_run)
    assert ports.preflight(unsafe, ctx(unsafe)).code is ResultCode.INVALID_PLAN
    assert not ports.approve(unsafe, "continue")
    result = ports.execute(unsafe.definition.steps[1], unsafe, ctx(unsafe))
    assert result.status is StepStatus.FAILED and result.code is ResultCode.INVALID_PLAN
    assert database.read_bytes() == before
    assert not outputs.dashboard.exists() and not outputs.assets.exists()
    ports.finish(safe)
    disabled = capture(replace(native, output_workbook_file=""))
    html_only = resolve_plan(disabled.definition, disabled.binding)
    assert ports.preflight(html_only, ctx(html_only)).ready
    assert database.read_bytes() == before
    ports.finish(html_only)
