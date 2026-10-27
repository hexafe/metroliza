"""Correctness boundaries for request-local histogram reuse and artifact proof."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
from textwrap import dedent
import zipfile

import numpy as np
import openpyxl
import pytest

from metroliza.charts import hexafe_plotstats_adapter as adapter
from scripts.compare_csv_pipeline_artifacts import (
    _normalized_part, artifact_manifest, compare_artifacts,
)


def _count_table_computations(monkeypatch):
    calls = []

    def compute(values, *, lsl=None, usl=None):
        calls.append((tuple(values), lsl, usl))
        return (("Mean", str(float(np.mean(values)))), ("Limits", repr((lsl, usl))))

    monkeypatch.setattr(adapter, "_histogram_table_rows_from_plotstats", compute)
    return calls


def test_request_cache_uses_input_contents_limits_and_separate_titles(monkeypatch):
    calls = _count_table_computations(monkeypatch)
    values = np.array([1.0, 2.0, 3.0])
    with adapter.histogram_stats_request():
        first = adapter.build_histogram_stats_table(values, title="First", lsl=0.0, usl=4.0)
        same = adapter.build_histogram_stats_table(values.copy(), title="Second", lsl=0.0, usl=4.0)
        assert first.rows == same.rows
        assert (first.title, same.title) == ("First", "Second")
        assert len(calls) == 1
        values[0] = 10.0
        changed = adapter.build_histogram_stats_table(values, lsl=0.0, usl=4.0)
        assert changed.rows != first.rows
        reordered = adapter.build_histogram_stats_table(values[::-1], lsl=0.0, usl=4.0)
        assert reordered.rows == changed.rows
        lower = adapter.build_histogram_stats_table(values, lsl=1.0, usl=4.0)
        upper = adapter.build_histogram_stats_table(values, lsl=1.0, usl=5.0)
        assert lower.rows != upper.rows
        assert len(calls) == 5
    with adapter.histogram_stats_request():
        adapter.build_histogram_stats_table(values, lsl=1.0, usl=5.0)
    assert len(calls) == 6
    assert adapter._histogram_table_cache.get() is None


def test_request_cache_preserves_coercion_missing_values_and_empty_input(monkeypatch):
    calls = _count_table_computations(monkeypatch)
    with adapter.histogram_stats_request():
        mixed = adapter.build_histogram_stats_table(["1", None, "bad", np.inf, 2.0, np.nan])
        numeric = adapter.build_histogram_stats_table([1.0, 2.0])
        assert mixed.rows == numeric.rows
        assert adapter.build_histogram_stats_table([None, "bad", np.nan]) is None
        assert len(calls) == 1


def test_request_cache_preserves_signed_zero_in_limit_settings(monkeypatch):
    calls = _count_table_computations(monkeypatch)
    with adapter.histogram_stats_request():
        positive = adapter.build_histogram_stats_table([1.0, 2.0], lsl=0.0, usl=3.0)
        negative = adapter.build_histogram_stats_table([1.0, 2.0], lsl=-0.0, usl=3.0)
        assert positive.rows != negative.rows
        assert len(calls) == 2


@pytest.mark.parametrize("failure", [RuntimeError("render failure"), KeyboardInterrupt()])
def test_request_cache_releases_buffers_and_restores_nested_context(monkeypatch, failure):
    calls = _count_table_computations(monkeypatch)
    with adapter.histogram_stats_request():
        adapter.build_histogram_stats_table([1.0, 2.0])
        outer = adapter._histogram_table_cache.get()
        with pytest.raises(type(failure)):
            with adapter.histogram_stats_request():
                adapter.build_histogram_stats_table([1.0, 2.0])
                inner = adapter._histogram_table_cache.get()
                raise failure
        assert not inner.rows and inner.payload_bytes == 0
        assert adapter._histogram_table_cache.get() is outer
        adapter.build_histogram_stats_table([1.0, 2.0])
        assert len(calls) == 2
    assert not outer.rows and outer.payload_bytes == 0
    assert adapter._histogram_table_cache.get() is None


def test_request_cache_bounds_entries_and_bytes_without_changing_results(monkeypatch):
    calls = _count_table_computations(monkeypatch)
    monkeypatch.setattr(adapter, "_HISTOGRAM_TABLE_CACHE_MAX_ENTRIES", 1)
    with adapter.histogram_stats_request():
        adapter.build_histogram_stats_table([1.0, 2.0])
        expected = adapter.build_histogram_stats_table([3.0, 4.0])
        assert adapter.build_histogram_stats_table([3.0, 4.0]) == expected
        assert len(calls) == 3
        assert len(adapter._histogram_table_cache.get().rows) == 1
    monkeypatch.setattr(adapter, "_HISTOGRAM_TABLE_CACHE_MAX_BYTES", 1)
    with adapter.histogram_stats_request():
        adapter.build_histogram_stats_table([1.0, 2.0])
        adapter.build_histogram_stats_table([1.0, 2.0])
        assert not adapter._histogram_table_cache.get().rows
    assert len(calls) == 5
    # Input fits, but the returned rows exceed the remaining payload budget.
    monkeypatch.setattr(adapter, "_HISTOGRAM_TABLE_CACHE_MAX_BYTES", 16)
    with adapter.histogram_stats_request():
        adapter.build_histogram_stats_table([1.0, 2.0])
        assert not adapter._histogram_table_cache.get().rows


def test_request_cache_does_not_remember_unavailable_backend(monkeypatch):
    monkeypatch.setattr(adapter, "_histogram_table_rows_from_plotstats", lambda *a, **k: ())
    with adapter.histogram_stats_request():
        fallback = adapter.build_histogram_stats_table([1.0, 2.0], backend="python-fallback")
        assert fallback.backend == "python-fallback"
        assert not adapter._histogram_table_cache.get().rows
        calls = _count_table_computations(monkeypatch)
        recovered = adapter.build_histogram_stats_table([1.0, 2.0])
        assert recovered.backend == "hexafe-plotstats"
        assert len(calls) == 1
    monkeypatch.setattr(adapter, "_histogram_table_rows_from_plotstats", lambda *a, **k: ())
    with adapter.histogram_stats_request():
        assert adapter.build_histogram_stats_table([1.0, 2.0], backend="python").backend == "python"


def test_real_histogram_table_is_identical_with_reuse_and_new_requests():
    values = [1.2, 1.4, None, 1.7, "invalid", 2.1, 2.2, 2.6, np.inf]
    for lsl, usl in ((None, None), (1.0, 3.0), (None, 2.0), (-2.0, None)):
        reference = adapter.build_histogram_stats_table(values, lsl=lsl, usl=usl)
        with adapter.histogram_stats_request():
            assert adapter.build_histogram_stats_table(values, lsl=lsl, usl=usl) == reference
            assert adapter.build_histogram_stats_table(list(values), lsl=lsl, usl=usl) == reference


def test_workflow_request_cancellation_clears_cache_before_next_request(tmp_path, monkeypatch):
    from metroliza.industrial.industrial_analytics_workflow import (
        AnalyticsCancelled, run_tabular_file_analytics,
    )

    calls = _count_table_computations(monkeypatch)
    source = tmp_path / "source.csv"
    source.write_text("PART,DIM\nA,1\nB,2\n")
    retained = []

    def cancel():
        adapter.build_histogram_stats_table([1.0, 2.0])
        retained.append(adapter._histogram_table_cache.get())
        return True

    for _ in range(2):
        with pytest.raises(AnalyticsCancelled):
            run_tabular_file_analytics(
                input_file=str(source), output_dashboard_file=str(tmp_path / "dashboard.html"),
                cancel_check=cancel,
            )
        assert adapter._histogram_table_cache.get() is None
        assert not retained[-1].rows and retained[-1].payload_bytes == 0
    assert len(calls) == 2
    assert not (tmp_path / "dashboard.html").exists()


def test_successive_workflows_use_new_data_limits_and_chart_selection(tmp_path):
    from metroliza.industrial.industrial_analytics_state import (
        ProductionChartSelection, ProductionMetricSelection,
    )
    from metroliza.industrial.industrial_analytics_workflow import run_tabular_file_analytics

    source = tmp_path / "source.csv"
    for index, offset in enumerate((0, 10)):
        source.write_text("PART,DIM\n" + "".join(f"P{i},{i + offset}\n" for i in range(1, 5)))
        output = tmp_path / str(index)
        output.mkdir()
        result = run_tabular_file_analytics(
            input_file=str(source), output_dashboard_file=str(output / "dashboard.html"),
            output_workbook_file=str(output / "workbook.xlsx"), reference_column="PART",
            metric_selection=(ProductionMetricSelection(
                "dim", display_label=f"Metric <{index}>", lsl=float(offset), usl=float(offset + 5),
            ),),
            chart_selection=ProductionChartSelection(
                time_series=False, histogram=True, violin=False, box=bool(index), groupstats=False,
            ),
        )
        assert result.row_count == 4
        assert result.html_dashboard_chart_count == index + 1
        assert adapter._histogram_table_cache.get() is None
        html = (output / "dashboard.html").read_text()
        assert f"Metric &lt;{index}&gt;" in html
        assert f"<td>Mean</td><td>{2.5 + offset:.3f}</td>" in html
        workbook = openpyxl.load_workbook(output / "workbook.xlsx", read_only=True)
        try:
            rows = workbook["Table Data"].iter_rows(values_only=True)
            headers = next(rows)
            assert [row[headers.index("dim")] for row in rows] == [offset + i for i in range(1, 5)]
            rows = workbook["Metrics"].iter_rows(values_only=True)
            headers = next(rows)
            assert next(rows)[headers.index("mean")] == offset + 2.5
        finally:
            workbook.close()


def _minimal_artifacts(directory: Path) -> None:
    import xlsxwriter

    directory.mkdir()
    (directory / "runtime.js").write_text("/* synthetic offline asset */")
    (directory / "dashboard.html").write_text('<script src="runtime.js"></script><p>&lt;safe&gt;</p>')
    with xlsxwriter.Workbook(directory / "workbook.xlsx", {"strings_to_formulas": False}) as workbook:
        sheet = workbook.add_worksheet("Table Data")
        sheet.write_row(0, 0, ["Reference", "Value"])
        sheet.write_row(1, 0, ["=1+1", 1.5])
        sheet.write_row(2, 0, ["/tmp/metroliza_csv_summary_original.sqlite", 2.5])
        chart = workbook.add_chart({"type": "column"})
        chart.add_series({"values": "='Table Data'!$B$2:$B$3"})
        sheet.insert_chart("D1", chart)


@pytest.mark.parametrize("mutation", ["cell", "formula", "chart", "asset", "html", "path_text"])
def test_artifact_comparison_rejects_meaningful_output_loss(tmp_path, mutation):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    _minimal_artifacts(baseline)
    shutil.copytree(baseline, candidate)
    assert compare_artifacts(baseline, candidate)["equal"]
    if mutation in {"cell", "formula", "path_text"}:
        workbook = openpyxl.load_workbook(candidate / "workbook.xlsx")
        if mutation == "path_text":
            workbook.active["A3"] = "/tmp/metroliza_csv_summary_changed.sqlite"
        else:
            workbook.active["B2"] = 9.0 if mutation == "cell" else "=1+1"
        workbook.save(candidate / "workbook.xlsx")
        workbook.close()
    elif mutation == "chart":
        path = candidate / "workbook.xlsx"
        with zipfile.ZipFile(path) as archive:
            parts = {n: archive.read(n) for n in archive.namelist()}
        parts["xl/charts/chart1.xml"] = parts["xl/charts/chart1.xml"].replace(b"$B$3", b"$B$2")
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in parts.items():
                archive.writestr(name, content)
    elif mutation == "asset":
        (candidate / "runtime.js").write_text("changed runtime")
    else:
        (candidate / "dashboard.html").write_text("<p>Missing plots</p>")
    assert not compare_artifacts(baseline, candidate)["equal"]


def test_artifact_manifest_requires_offline_assets_and_preserves_literal_formula(tmp_path):
    directory = tmp_path / "artifacts"
    _minimal_artifacts(directory)
    manifest = artifact_manifest(directory)
    assert manifest["sheets"][0]["rows"] == 3
    assert manifest["sheets"][0]["formulas"] == 0
    (directory / "runtime.js").unlink()
    with pytest.raises(ValueError, match="Missing or nonlocal"):
        artifact_manifest(directory)
    (directory / "dashboard.html").write_text('<script src="https://example.invalid/runtime.js"></script>')
    with pytest.raises(ValueError, match="Remote dashboard asset"):
        artifact_manifest(directory)


def test_artifact_metadata_parser_rejects_xml_entities():
    from defusedxml.common import DefusedXmlException

    payload = b'<!DOCTYPE x [<!ENTITY expansion "unexpected">]><x>&expansion;</x>'
    with pytest.raises(DefusedXmlException):
        _normalized_part("docProps/core.xml", payload)


def test_sqlite_normalization_preserves_literal_diagnostic_fragments(tmp_path):
    import xlsxwriter

    def create(name, diagnostic_suffix, literal_suffix):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "dashboard.html").write_text("<p>Synthetic offline output</p>")
        with xlsxwriter.Workbook(directory / "workbook.xlsx") as workbook:
            table = workbook.add_worksheet("Table Data")
            table.write(0, 0, "'sqlite_path': '/tmp/metroliza_csv_summary_"
                        + literal_suffix + ".sqlite'")
            diagnostics = workbook.add_worksheet("Diagnostics")
            diagnostics.write_row(0, 0, ["code", "context"])
            diagnostics.write_row(1, 0, [
                "tabular_sqlite_store_created",
                "{'row_count': 1, 'source_file_count': 1, 'sqlite_path': "
                "'/tmp/metroliza_csv_summary_" + diagnostic_suffix + ".sqlite'}",
            ])
        return directory

    baseline = create("baseline", "real_a", "literal_a")
    legitimate = create("legitimate", "real_b", "literal_a")
    changed_literal = create("changed_literal", "real_c", "literal_b")
    assert compare_artifacts(baseline, legitimate)["equal"]
    comparison = compare_artifacts(baseline, changed_literal)
    assert not comparison["equal"]
    assert "sheets" in comparison["differing_sections"]


@pytest.mark.parametrize("dirty_kind", ["tracked", "staged", "untracked"])
def test_benchmark_rejects_dirty_checkout_before_recording_identity(tmp_path, dirty_kind):
    import subprocess
    from scripts.benchmark_csv_pipeline import (
        _checkout_identity, _sha, _verify_checkout_identity,
    )
    from scripts import benchmark_csv_pipeline as driver

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True)

    git("init", "--quiet")
    source = tmp_path / "source.py"
    source.write_text("value = 1\n")
    git("add", "source.py")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "--quiet", "-m", "fixture")
    identity = _checkout_identity(tmp_path)
    assert identity == tuple(git("rev-parse", "HEAD", "HEAD^{tree}").splitlines())
    target = tmp_path / "extra.py" if dirty_kind == "untracked" else source
    target.write_text("value = 2\n")
    if dirty_kind == "staged":
        git("add", "source.py")
    with pytest.raises(RuntimeError, match="must be clean"):
        _checkout_identity(tmp_path)
    with pytest.raises(RuntimeError, match="must be clean"):
        _verify_checkout_identity(tmp_path, identity, _sha(Path(driver.__file__)))


def test_benchmark_rejects_commit_or_driver_drift(monkeypatch, tmp_path):
    from scripts import benchmark_csv_pipeline as driver

    monkeypatch.setattr(driver, "_checkout_identity", lambda repo: ("head", "tree"))
    monkeypatch.setattr(driver, "_sha", lambda path: "driver")
    driver._verify_checkout_identity(tmp_path, ("head", "tree"), "driver")
    with pytest.raises(RuntimeError, match="changed during measurement"):
        driver._verify_checkout_identity(tmp_path, ("previous", "tree"), "driver")
    with pytest.raises(RuntimeError, match="changed during measurement"):
        driver._verify_checkout_identity(tmp_path, ("head", "tree"), "previous-driver")


def _run_benchmark_without_resource(tmp_path, code):
    # The hook exists only in a fresh isolated child, never during collection.
    preamble = dedent("""\
        import builtins
        from pathlib import Path
        import sys

        repo = Path(sys.argv[1])
        destination = Path(sys.argv[2])
        sys.path.insert(0, str(repo))
        sys.modules.pop("resource", None)
        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "resource" or name.startswith("resource."):
                raise ModuleNotFoundError("resource unavailable for portability regression",
                                          name="resource")
            if (name.split(".")[0] in {"metroliza", "numpy", "pandas", "matplotlib"}
                    or name == "scripts.benchmark_paths"
                    or (name == "scripts" and "benchmark_paths" in fromlist)):
                raise AssertionError("Analytics imported by a platform-neutral operation: " + name)
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = guarded_import
        try:
            import resource
        except ModuleNotFoundError as exc:
            assert exc.name == "resource"
        else:
            raise AssertionError("Unavailable-resource blocker did not take effect")
        """)
    return subprocess.run(
        [sys.executable, "-I", "-c", preamble + dedent(code),
         str(Path(__file__).resolve().parents[1]), str(tmp_path / "output")],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )


def test_benchmark_helpers_import_without_resource(tmp_path):
    result = _run_benchmark_without_resource(tmp_path, """\
        import subprocess
        from scripts import benchmark_csv_pipeline as driver

        subprocess.run(["git", "init", "--quiet", str(destination)], check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "--quiet", "--allow-empty", "-m", "fixture"],
                       cwd=destination, check=True)
        identity = driver._checkout_identity(destination)
        assert len(identity) == 2 and all(len(value) == 40 for value in identity)
        driver._verify_checkout_identity(destination, identity, driver._sha(Path(driver.__file__)))
        assert "resource" not in sys.modules
        print("HELPERS_WITHOUT_RESOURCE_OK")
        """)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HELPERS_WITHOUT_RESOURCE_OK" in result.stdout


def test_benchmark_cli_help_without_resource(tmp_path):
    result = _run_benchmark_without_resource(tmp_path, """\
        import runpy

        driver_path = repo / "scripts" / "benchmark_csv_pipeline.py"
        sys.argv = [str(driver_path), "--help"]
        try:
            runpy.run_path(str(driver_path), run_name="__main__")
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("CLI help did not exit")
        assert "resource" not in sys.modules
        print("HELP_WITHOUT_RESOURCE_OK")
        """)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--worker" in result.stdout and "HELP_WITHOUT_RESOURCE_OK" in result.stdout
    assert not (tmp_path / "output").exists()


def test_benchmark_worker_requires_resource_before_setup(tmp_path):
    result = _run_benchmark_without_resource(tmp_path, """\
        from argparse import Namespace
        from scripts import benchmark_csv_pipeline as driver

        def unexpected_timer():
            raise AssertionError("Worker started its timer without resource")

        driver.time.perf_counter = unexpected_timer
        try:
            driver._worker(Namespace(repo=str(repo), output=str(destination),
                                     case="small", requests=1, profile=False))
        except ModuleNotFoundError as exc:
            assert exc.name == "resource"
        else:
            raise AssertionError("Worker fabricated a successful measurement without resource")
        assert not destination.exists()
        print("WORKER_REQUIRES_RESOURCE_OK")
        """)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WORKER_REQUIRES_RESOURCE_OK" in result.stdout
    assert not (tmp_path / "output").exists()


def test_small_csv_analytics_preserves_complete_artifacts(tmp_path, monkeypatch):
    """Compare all artifacts and require one shared fit per series/population."""
    import importlib

    histogram = importlib.import_module("hexafe_plotstats.payloads.histogram")
    original_fit = histogram.fit_distribution
    fits = []

    def capture_fit(*args, **kwargs):
        result = original_fit(*args, **kwargs)
        fits.append(result)
        return result

    monkeypatch.setattr(histogram, "fit_distribution", capture_fit)
    from metroliza.industrial.industrial_analytics_state import (
        ProductionChartSelection, ProductionMetricSelection,
    )
    from metroliza.industrial.industrial_analytics_workflow import run_tabular_file_analytics

    source = tmp_path / "parity.csv"
    source.write_text("PART,DIM\n" + "".join(
        f"P{i},{value}\n" for i, value in enumerate(
            (1.2, 1.4, 1.7, 2.1, 2.2, 2.6, 1.8, 2.3, 2.7, 1.6), start=1,
        )
    ))
    for name in ("baseline", "candidate"):
        output = tmp_path / name
        output.mkdir()
        fits.clear()
        with monkeypatch.context() as patch:
            if name == "baseline":
                import hexafe_plotstats

                patch.setattr(adapter, "_request_histogram_payload",
                              hexafe_plotstats.build_histogram_payload)
                patch.setattr(adapter, "_request_histogram_table_rows",
                              adapter._histogram_table_rows_from_plotstats)
            run_tabular_file_analytics(
                input_file=str(source), output_dashboard_file=str(output / "dashboard.html"),
                output_workbook_file=str(output / "workbook.xlsx"), reference_column="PART",
                metric_selection=(ProductionMetricSelection("dim", lsl=1.0, usl=3.0),),
                chart_selection=ProductionChartSelection(
                    time_series=True, histogram=True, violin=True, box=True, groupstats=False,
                ),
            )
        assert len(fits) == (3 if name == "baseline" else 1)
        if name == "baseline":
            baseline_fits = tuple(fits)
        else:
            assert all(fit == fits[0] for fit in baseline_fits)
        workbook = openpyxl.load_workbook(output / "workbook.xlsx", read_only=True)
        try:
            assert list(workbook["Metrics"].values)[1][2:] == (
                10, 1.96, 1.95, 0.5015531433014407, 1.2, 2.7,
            )
            rows = workbook["Table Data"].iter_rows(values_only=True)
            headers = next(rows)
            assert [row[headers.index("dim")] for row in rows] == [
                1.2, 1.4, 1.7, 2.1, 2.2, 2.6, 1.8, 2.3, 2.7, 1.6,
            ]
        finally:
            workbook.close()
    assert compare_artifacts(tmp_path / "baseline", tmp_path / "candidate")["equal"]


def test_request_fit_reuses_population_across_bins_and_density(monkeypatch):
    import importlib

    from hexafe_plotstats import HistogramConfig, build_histogram_payload
    from hexafe_plotstats.models.common import SpecLimits

    histogram = importlib.import_module("hexafe_plotstats.payloads.histogram")
    original_fit = histogram.fit_distribution
    calls = []

    def fit(*args, **kwargs):
        calls.append(tuple(args[0]))
        return original_fit(*args, **kwargs)

    values = np.linspace(1.0, 3.0, 25)
    limits = SpecLimits(lsl=0.5, nominal=2.0, usl=3.5)
    configs = [HistogramConfig(bins=3, density=False), HistogramConfig(bins=7, density=True)]
    expected = [build_histogram_payload(values, spec_limits=limits, config=config) for config in configs]
    monkeypatch.setattr(histogram, "fit_distribution", fit)
    # Fit reuse must remain effective even when the table-row cache is full.
    monkeypatch.setattr(adapter, "_HISTOGRAM_TABLE_CACHE_MAX_ENTRIES", 0)
    with adapter.histogram_stats_request():
        for config, reference in zip(configs, expected, strict=True):
            actual = adapter._request_histogram_payload(values, spec_limits=limits, config=config)
            assert actual == reference
        assert len(calls) == 1
        adapter._request_histogram_payload(values[::2], spec_limits=limits, config=configs[0])
        adapter._request_histogram_payload(values[::-1], spec_limits=limits, config=configs[0])
        adapter._request_histogram_payload(values, spec_limits=SpecLimits(), config=configs[0])
        assert len(calls) == 4
        retained = adapter._histogram_table_cache.get()
    assert not retained.fits
    with adapter.histogram_stats_request():
        adapter._request_histogram_payload(values, spec_limits=limits, config=configs[0])
    assert len(calls) == 5


def test_request_fit_single_flight_in_copied_worker_contexts(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    import importlib
    from threading import Event

    from hexafe_plotstats import HistogramConfig
    from hexafe_plotstats.models.common import SpecLimits

    histogram = importlib.import_module("hexafe_plotstats.payloads.histogram")
    original_fit = histogram.fit_distribution
    entered, release = Event(), Event()
    calls = []

    def fit(*args, **kwargs):
        calls.append(tuple(args[0]))
        entered.set()
        assert release.wait(10)
        return original_fit(*args, **kwargs)

    monkeypatch.setattr(histogram, "fit_distribution", fit)
    with adapter.histogram_stats_request(), ThreadPoolExecutor(max_workers=3) as pool:
        def build():
            return adapter._request_histogram_payload(
                np.linspace(1.0, 3.0, 25), spec_limits=SpecLimits(), config=HistogramConfig(),
            )

        first = pool.submit(copy_context().run, build)
        assert entered.wait(10)
        rest = [pool.submit(copy_context().run, build) for _ in range(2)]
        release.set()
        results = [future.result() for future in [first, *rest]]
        assert results[0] == results[1] == results[2]
        assert len(calls) == 1


def test_request_fit_failed_build_is_not_retained(monkeypatch):
    import hexafe_plotstats

    from hexafe_plotstats import HistogramConfig
    from hexafe_plotstats.models.common import SpecLimits

    original = hexafe_plotstats.build_histogram_payload
    calls = []

    def build(*args, **kwargs):
        calls.append(None)
        if len(calls) == 1:
            raise RuntimeError("temporary build failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(hexafe_plotstats, "build_histogram_payload", build)
    with adapter.histogram_stats_request():
        with pytest.raises(RuntimeError, match="temporary build failure"):
            adapter._request_histogram_payload(
                np.array([1.0, 2.0]), spec_limits=SpecLimits(), config=HistogramConfig(),
            )
        assert not adapter._histogram_table_cache.get().fits
        for _ in range(2):
            adapter._request_histogram_payload(
                np.array([1.0, 2.0]), spec_limits=SpecLimits(), config=HistogramConfig(),
            )
        assert len(calls) == 3


def test_concurrent_analytics_requests_do_not_share_fits(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import importlib

    from hexafe_plotstats import HistogramConfig
    from hexafe_plotstats.models.common import SpecLimits

    histogram = importlib.import_module("hexafe_plotstats.payloads.histogram")
    original_fit = histogram.fit_distribution
    calls = []

    def fit(*args, **kwargs):
        calls.append(tuple(args[0]))
        return original_fit(*args, **kwargs)

    def run():
        with adapter.histogram_stats_request():
            payloads = [adapter._request_histogram_payload(
                np.linspace(1.0, 3.0, 25), spec_limits=SpecLimits(), config=HistogramConfig(),
            ) for _ in range(2)]
            assert payloads[0] == payloads[1]
            return payloads[0]

    monkeypatch.setattr(histogram, "fit_distribution", fit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results[0] == results[1]
    assert len(calls) == 2
