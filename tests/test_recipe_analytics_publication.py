"""Real native analytics replacement preserves the last published dashboard."""
from pathlib import Path
from uuid import uuid4

import pytest

from metroliza.industrial.contracts import IndustrialAnalyticsRequest
from metroliza.industrial.industrial_analytics_state import ProductionChartSelection, ProductionMetricSelection
from metroliza.industrial import industrial_analytics_workflow as workflow
from metroliza.recipes.bindings import resolve_plan
from metroliza.recipes.contracts import RecipeError
from metroliza.recipes.ports import StepContext, StepStatus
from metroliza.recipes.tabular_adapter import AnalyticsRecipePorts, capture


def _context(plan):
    return StepContext(plan.flow_id, plan.run_id, str(uuid4()), lambda: False, lambda *_args: None)


def _request(tmp_path, source_kind="tabular_file"):
    if source_kind == "production_cache":
        from tests.industrial_analytics_fixtures import seed_production_analytics_cache
        source = tmp_path / "cache.db"
        seed_production_analytics_cache(str(source))
        metric = "cycle_time_s"
    else:
        source = tmp_path / "measurements.csv"
        source.write_text("timestamp,reference,length_mm\n"
                          "2026-11-15 10:00:00,R1,1.0\n2026-11-15 10:01:00,R1,1.1\n"
                          "2026-11-15 10:02:00,R1,1.2\n2026-11-15 10:03:00,R1,1.3\n", encoding="utf-8")
        metric = "length_mm"
    return IndustrialAnalyticsRequest(
        source_kind=source_kind, input_file=str(source) if source_kind == "tabular_file" else "",
        db_file=str(source) if source_kind == "production_cache" else "",
        output_dashboard_file=str(tmp_path / "result.html"),
        output_workbook_file=str(tmp_path / "result.xlsx"),
        metric_selection=(ProductionMetricSelection(metric),),
        chart_selection=ProductionChartSelection(time_series=True, histogram=True),
        separate_parameter_sheets=False)


def _legacy_native_result(request):
    kwargs = dict(output_dashboard_file=request.output_dashboard_file,
                  output_workbook_file=request.output_workbook_file,
                  metric_selection=request.metric_selection, chart_selection=request.chart_selection,
                  separate_parameter_sheets=request.separate_parameter_sheets)
    if request.source_kind == "tabular_file":
        return workflow.run_tabular_file_analytics(input_file=request.input_file, **kwargs)
    return workflow.run_production_cache_analytics(db_file=request.db_file, **kwargs)


def _asset_bytes(path):
    return {str(item.relative_to(path)): item.read_bytes() for item in path.rglob("*") if item.is_file()}


def _assert_generation_references(target, assets):
    import re
    references = re.findall(r'(?:src|href)="([^"]+)"', target.read_text(encoding="utf-8"))
    local = [reference for reference in references if reference.startswith(assets.name + "/")]
    assert local and all((target.parent / reference).is_file() for reference in local)


def _approve_replacement(entry):
    plan = resolve_plan(entry.definition, entry.binding)
    ports = AnalyticsRecipePorts()
    assert ports.preflight(plan, _context(plan)).requires_decision
    assert ports.approve(plan, "continue")
    assert ports.preflight(plan, _context(plan)).ready
    assert ports.execute(plan.definition.steps[0], plan, _context(plan)).status is StepStatus.COMPLETED
    return ports, plan


@pytest.mark.parametrize("source_kind", ["tabular_file", "production_cache"])
def test_native_replacement_commits_unique_assets_then_retires_previous_generation(tmp_path, monkeypatch, source_kind):
    from metroliza.industrial import tabular_output_publication as output_publication
    request = _request(tmp_path, source_kind)
    legacy = _legacy_native_result(request)
    target = Path(request.output_dashboard_file)
    previous_assets = Path(legacy.html_dashboard_assets_path)
    assert previous_assets.name == "result_assets"
    assert _asset_bytes(previous_assets)  # A nonempty existing directory caused the reported defect.
    foreign = tmp_path / "unrelated_assets.generation-preserve"
    foreign.mkdir()
    (foreign / "sentinel").write_bytes(b"unrelated complete dashboard asset")
    entry = capture(request)
    publish = output_publication.publish_output
    for _attempt in range(2):  # Fixed legacy assets, then a previous generated assets directory.
        before_html, before_assets = target.read_bytes(), _asset_bytes(previous_assets)
        old_assets = previous_assets
        transitions = []

        def observed_publish(temporary, destination, **kwargs):
            if Path(destination) != target:
                return publish(temporary, destination, **kwargs)
            assert target.read_bytes() == before_html
            assert _asset_bytes(old_assets) == before_assets
            transitions.append("old_complete")
            result = publish(temporary, destination, **kwargs)
            assert old_assets.is_dir()  # Retirement must follow the HTML commit.
            transitions.append("new_html_committed")
            return result

        monkeypatch.setattr(output_publication, "publish_output", observed_publish)
        ports, plan = _approve_replacement(entry)
        result = ports.execute(plan.definition.steps[1], plan, _context(plan))
        assert result.status in (StepStatus.COMPLETED, StepStatus.PARTIAL)
        native = ports._results[plan.run_id]
        previous_assets = Path(native.html_dashboard_assets_path)
        assert result.dashboard_assets_path == str(previous_assets)
        assert previous_assets.name.startswith(plan.assets_dir.name + ".generation-")
        assert previous_assets != old_assets and _asset_bytes(previous_assets)
        assert previous_assets.name.encode() in target.read_bytes()
        _assert_generation_references(target, previous_assets)
        assert native.html_dashboard_path == str(target)
        assert native.workbook_path == request.output_workbook_file
        assert not old_assets.exists()
        assert transitions == ["old_complete", "new_html_committed"]
        assert ports.execute(plan.definition.steps[2], plan, _context(plan)).artifact_verified
        assert (foreign / "sentinel").read_bytes() == b"unrelated complete dashboard asset"
        ports.finish(plan)


@pytest.mark.parametrize("interruption", ["failure", "cancel", "publication"])
def test_failed_or_cancelled_native_render_preserves_old_html_assets_and_workbook(tmp_path, monkeypatch, interruption):
    request = _request(tmp_path)
    legacy = _legacy_native_result(request)
    target = Path(request.output_dashboard_file)
    assets = Path(legacy.html_dashboard_assets_path)
    workbook = Path(request.output_workbook_file)
    before = target.read_bytes(), _asset_bytes(assets), workbook.read_bytes()
    assert before[1]
    with Path(request.input_file).open("a", encoding="utf-8") as source:
        source.write("2026-11-15 10:04:00,R1,2.0\n")
    ports, plan = _approve_replacement(capture(request))
    render = workflow.write_production_dashboard
    publication_observations = []

    def interrupted_render(*args, **kwargs):
        result = render(*args, **kwargs)  # Complete a real staged native rendering first.
        assert target.read_bytes() == before[0]
        assert _asset_bytes(assets) == before[1]
        if interruption == "failure":
            raise RuntimeError("synthetic render failure before publication")
        if interruption == "cancel":
            ports.cancel()
        return result

    if interruption == "publication":
        from metroliza.industrial import tabular_output_publication as output_publication

        publish = output_publication.publish_output

        def reject_publication(temporary, destination, **kwargs):
            if Path(destination) != target:
                return publish(temporary, destination, **kwargs)
            publication_observations.append((target.read_bytes(), _asset_bytes(assets), workbook.read_bytes()))
            raise RuntimeError("synthetic failure before HTML publication")

        monkeypatch.setattr(output_publication, "publish_output", reject_publication)
    monkeypatch.setattr(workflow, "write_production_dashboard", interrupted_render)
    result = ports.execute(plan.definition.steps[1], plan, _context(plan))
    expected = StepStatus.CANCELLED if interruption == "cancel" else StepStatus.FAILED
    assert result.status is expected
    if interruption == "publication":
        (old_html, old_assets, new_workbook), = publication_observations
        assert (old_html, old_assets) == before[:2]
        assert new_workbook.startswith(b"PK") and new_workbook != before[2]
    assert (target.read_bytes(), _asset_bytes(assets), workbook.read_bytes()) == before
    assert not tuple(tmp_path.glob(plan.assets_dir.name + ".generation-*"))
    assert not tuple(tmp_path.glob(".metroliza-export-*"))
    assert not tuple(tmp_path.glob(".recipe-analytics-*"))
    assert not tuple(tmp_path.glob(".mza-*"))
    assert not tuple(tmp_path.glob(".metroliza-previous-*"))
    ports.finish(plan)



def test_replacement_leaves_legacy_directory_with_unowned_content(tmp_path):
    request = _request(tmp_path)
    legacy = _legacy_native_result(request)
    assets = Path(legacy.html_dashboard_assets_path)
    (assets / "user.txt").write_bytes(b"do not delete")
    before = _asset_bytes(assets)

    ports, plan = _approve_replacement(capture(request))
    try:
        result = ports.execute(plan.definition.steps[1], plan, _context(plan))
        assert result.status is StepStatus.COMPLETED
        assert _asset_bytes(assets) == before
        _assert_generation_references(Path(request.output_dashboard_file), Path(result.dashboard_assets_path))
    finally:
        ports.finish(plan)


@pytest.mark.parametrize("generation", [False, True])
@pytest.mark.parametrize("symlink", [False, True])
def test_source_below_retired_analytics_assets_is_rejected_before_consent(tmp_path, generation, symlink):
    name = "result_assets" + (".generation-" + "a" * 32 if generation else "")
    retired = tmp_path / name
    retired.mkdir()
    if symlink:
        real = tmp_path / "source-directory"
        try:
            real.symlink_to(retired, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("directory symlink creation unavailable")
    else:
        real = retired
    source = real / "measurements.csv"
    source.write_text("timestamp,reference,length_mm\n2026-11-15,R1,1.0\n", encoding="utf-8")
    before = source.read_bytes()
    request = IndustrialAnalyticsRequest(source_kind="tabular_file", input_file=str(source),
        output_dashboard_file=str(tmp_path / "result.html"))
    entry = capture(request)
    with pytest.raises(RecipeError, match="source_alias"):
        resolve_plan(entry.definition, entry.binding)
    assert source.read_bytes() == before and retired.is_dir()
