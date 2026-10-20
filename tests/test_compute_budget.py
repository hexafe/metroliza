"""Worker budget arithmetic, environment precedence, frozen policy and worker thread limits."""

from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
import sys
import threading

import pytest

from metroliza.shared import compute_budget as budget
from metroliza.shared import compute_worker

OWN_VARIABLES = (
    budget.GLOBAL_WORKERS_ENV,
    budget.IMPORT_PREPARE_WORKERS_ENV,
    budget.IMPORT_PREPARE_MIN_REPORTS_ENV,
    budget.REVIEW_WORKERS_ENV,
    budget.REVIEW_MIN_FILES_ENV,
    budget.RENDER_FROZEN_WORKERS_ENV,
    budget.RENDER_FROZEN_MIN_GROUPS_ENV,
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in OWN_VARIABLES + compute_worker.WORKER_THREAD_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "cpu_count", lambda: 12)


def _packaged_windows(monkeypatch, *, available=True):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(budget, "compute_workers_available", lambda: available)


# --- budget arithmetic -------------------------------------------------------------


@pytest.mark.parametrize("cpus,expected", [(None, 1), (1, 1), (2, 1), (4, 3), (12, 11), (64, 63)])
def test_budget_is_logical_cpus_minus_one_but_never_below_one(monkeypatch, cpus, expected):
    monkeypatch.setattr(os, "cpu_count", lambda: cpus)
    assert budget.worker_budget() == expected


@pytest.mark.parametrize("value,expected", [("6", 6), (" 3 ", 3), ("99", budget.MAX_EXPLICIT_WORKERS)])
def test_global_override_replaces_the_cpu_budget(monkeypatch, value, expected):
    monkeypatch.setenv(budget.GLOBAL_WORKERS_ENV, value)
    assert budget.global_override() == expected
    assert budget.worker_budget() == expected


@pytest.mark.parametrize("value", ["", "0", "-2", "many", "1.5"])
def test_invalid_global_override_is_ignored(monkeypatch, value):
    monkeypatch.setenv(budget.GLOBAL_WORKERS_ENV, value)
    assert budget.global_override() is None
    assert budget.worker_budget() == 11


# --- import prepare ----------------------------------------------------------------


def test_import_prepare_defaults_are_unchanged():
    assert budget.import_prepare_workers(63) == 0
    assert budget.import_prepare_workers(64) == budget.IMPORT_PREPARE_MAX_AUTO == 3
    assert budget.import_prepare_workers(5000) == 3


@pytest.mark.parametrize("cpus,expected", [(1, 0), (2, 0), (3, 2), (4, 3), (64, 3)])
def test_import_prepare_auto_follows_the_budget_up_to_its_ceiling(monkeypatch, cpus, expected):
    monkeypatch.setattr(os, "cpu_count", lambda: cpus)
    assert budget.import_prepare_workers(500) == expected


def test_import_prepare_global_override_sets_the_automatic_count(monkeypatch):
    monkeypatch.setenv(budget.GLOBAL_WORKERS_ENV, "8")
    assert budget.import_prepare_workers(500) == 8
    assert budget.import_prepare_workers(5) == 0  # below the batch threshold
    monkeypatch.setenv(budget.IMPORT_PREPARE_MIN_REPORTS_ENV, "2")
    assert budget.import_prepare_workers(5) == 5  # never more workers than reports
    monkeypatch.setenv(budget.GLOBAL_WORKERS_ENV, "1")
    assert budget.import_prepare_workers(500) == 0  # one worker never pays off


def test_import_prepare_own_variable_beats_the_global_override(monkeypatch):
    monkeypatch.setenv(budget.GLOBAL_WORKERS_ENV, "8")
    monkeypatch.setenv(budget.IMPORT_PREPARE_WORKERS_ENV, "2")
    assert budget.import_prepare_workers(500) == 2
    monkeypatch.setenv(budget.IMPORT_PREPARE_WORKERS_ENV, "0")
    assert budget.import_prepare_workers(500) == 0
    monkeypatch.setenv(budget.IMPORT_PREPARE_WORKERS_ENV, "garbage")
    assert budget.import_prepare_workers(500) == 0
    monkeypatch.setenv(budget.IMPORT_PREPARE_WORKERS_ENV, "100")
    assert budget.import_prepare_workers(500) == budget.MAX_EXPLICIT_WORKERS


def test_import_prepare_minimum_comes_from_its_variable(monkeypatch):
    monkeypatch.setenv(budget.IMPORT_PREPARE_MIN_REPORTS_ENV, "10")
    assert budget.import_prepare_workers(9) == 0
    assert budget.import_prepare_workers(10) == 3
    monkeypatch.setenv(budget.IMPORT_PREPARE_MIN_REPORTS_ENV, "garbage")
    assert budget.import_prepare_workers(63) == 0
    assert budget.import_prepare_workers(64) == 3


def test_packaged_windows_import_prepare_stays_off_by_default(monkeypatch):
    _packaged_windows(monkeypatch)
    monkeypatch.setenv(budget.GLOBAL_WORKERS_ENV, "8")  # the global value never opens it
    assert [budget.import_prepare_workers(n) for n in (199, 200, 5000)] == [0, 0, 0]
    monkeypatch.setenv(budget.IMPORT_PREPARE_WORKERS_ENV, "3")
    assert budget.import_prepare_workers(199) == 0  # packaged minimum is 200
    assert budget.import_prepare_workers(5000) == 3


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_frozen_builds_need_a_validated_compute_executable(monkeypatch, platform):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv(budget.IMPORT_PREPARE_WORKERS_ENV, "3")
    monkeypatch.setenv(budget.REVIEW_WORKERS_ENV, "3")
    calls = []
    unavailable = lambda: calls.append(1) or False  # noqa: E731
    assert budget.import_prepare_workers(5000, available=unavailable) == 0
    assert budget.review_workers(5000, available=unavailable) == 0
    assert calls == [1, 1]
    assert budget.import_prepare_workers(5000, available=lambda: True) == 3


def test_serial_decisions_never_validate_the_package(monkeypatch):
    _packaged_windows(monkeypatch)
    calls = []
    monkeypatch.setattr(budget, "compute_workers_available", lambda: calls.append(1) or True)
    for configured in ("auto", "0", "garbage"):
        monkeypatch.setenv(budget.IMPORT_PREPARE_WORKERS_ENV, configured)
        assert budget.import_prepare_workers(5000) == 0
    assert budget.import_prepare_workers(5) == 0
    assert calls == []


# --- review ------------------------------------------------------------------------


def test_review_source_default_is_four_workers_above_the_file_threshold():
    assert budget.review_workers(budget.REVIEW_DEFAULT_MIN_FILES - 1) == 0
    assert budget.review_workers(budget.REVIEW_DEFAULT_MIN_FILES) == 4
    assert budget.review_workers(1500) == 4


@pytest.mark.parametrize("cpus,expected", [(1, 0), (2, 0), (3, 2), (4, 3), (5, 4), (64, 4)])
def test_review_auto_is_min_of_four_and_the_budget(monkeypatch, cpus, expected):
    monkeypatch.setattr(os, "cpu_count", lambda: cpus)
    assert budget.review_workers(1500) == expected


def test_review_variables_and_global_override(monkeypatch):
    monkeypatch.setenv(budget.GLOBAL_WORKERS_ENV, "6")
    assert budget.review_workers(1500) == 6
    monkeypatch.setenv(budget.REVIEW_WORKERS_ENV, "2")
    assert budget.review_workers(1500) == 2
    monkeypatch.setenv(budget.REVIEW_MIN_FILES_ENV, "2000")
    assert budget.review_workers(1500) == 0
    monkeypatch.setenv(budget.REVIEW_WORKERS_ENV, "0")
    assert budget.review_workers(5000) == 0


def test_review_is_opt_in_in_the_packaged_windows_app(monkeypatch):
    _packaged_windows(monkeypatch)
    monkeypatch.setenv(budget.GLOBAL_WORKERS_ENV, "8")
    assert budget.review_workers(5000) == 0
    monkeypatch.setenv(budget.REVIEW_WORKERS_ENV, "4")
    assert budget.review_workers(199) == 0
    assert budget.review_workers(200) == 4
    monkeypatch.setattr(budget, "compute_workers_available", lambda: False)
    assert budget.review_workers(5000) == 0


# --- render and chart --------------------------------------------------------------


@pytest.mark.parametrize("requested,entries,expected", [
    (2, 48, 2), (4, 48, 4), (99, 48, 4), (4, 3, 2), (2, 2, 1), (1, 48, 1),
])
def test_render_request_is_capped_by_cpu_budget(
    monkeypatch, requested, entries, expected,
):
    assert budget.render_workers(requested, entries) == expected
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    assert budget.render_workers(requested, entries) == 1


def test_render_cap_can_be_lifted_by_the_caller_and_lowered_by_the_global_override(monkeypatch):
    assert budget.render_workers(8, 48, cap=8) == 8
    monkeypatch.setenv(budget.GLOBAL_WORKERS_ENV, "3")
    assert budget.render_workers(4, 48) == 3
    assert budget.render_workers(2, 48) == 2  # the override only lowers


def test_render_packaged_windows_limit_and_minimum(monkeypatch):
    _packaged_windows(monkeypatch)
    assert budget.render_min_groups() == 40
    assert budget.render_workers(4, 48) == 2
    monkeypatch.setenv(budget.RENDER_FROZEN_WORKERS_ENV, "3")
    monkeypatch.setenv(budget.RENDER_FROZEN_MIN_GROUPS_ENV, "12")
    assert budget.render_workers(4, 48) == 3
    assert budget.render_min_groups() == 12
    monkeypatch.setenv(budget.RENDER_FROZEN_WORKERS_ENV, "0")
    monkeypatch.setenv(budget.RENDER_FROZEN_MIN_GROUPS_ENV, "garbage")
    assert budget.render_workers(4, 48) == 2
    assert budget.render_min_groups() == 40


def test_render_minimum_in_source_is_eight_groups():
    assert budget.render_min_groups() == budget.RENDER_MIN_GROUPS == 8


def test_chart_workers_follow_the_request(monkeypatch):
    assert [budget.chart_workers(n) for n in (0, 1, 2, 7)] == [1, 1, 2, 7]
    monkeypatch.setenv(budget.GLOBAL_WORKERS_ENV, "3")
    assert [budget.chart_workers(n) for n in (1, 2, 7)] == [1, 2, 3]


def test_resolve_workers_dispatches_every_kind_and_rejects_unknown():
    assert budget.resolve_workers("import_prepare", items=500) == 3
    assert budget.resolve_workers("review", items=500) == 4
    assert budget.resolve_workers("render", items=48, requested=2) == 2
    assert budget.resolve_workers("chart", requested=5) == 5
    assert set(budget.POOL_KINDS) == {"import_prepare", "render", "review", "chart"}
    with pytest.raises(ValueError):
        budget.resolve_workers("other")


# --- worker thread environment -----------------------------------------------------


def test_thread_environment_adds_only_missing_variables_and_restores_exactly(monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "5")
    environ = dict(os.environ)
    snapshot = dict(environ)
    with compute_worker.worker_thread_environment(environ) as added:
        assert set(added) == {"OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"}
        assert environ["OMP_NUM_THREADS"] == "5"
        assert all(environ[name] == "1" for name in added)
    assert environ == snapshot


def test_thread_environment_restores_after_an_error_and_keeps_foreign_edits():
    environ = {}
    with pytest.raises(RuntimeError):
        with compute_worker.worker_thread_environment(environ):
            assert len(environ) == len(compute_worker.WORKER_THREAD_VARIABLES)
            environ["MKL_NUM_THREADS"] = "7"  # someone else changed it meanwhile
            raise RuntimeError("worker start failed")
    assert environ == {"MKL_NUM_THREADS": "7"}


def test_concurrent_worker_starts_leave_the_environment_untouched():
    before = dict(os.environ)
    errors = []

    def start_many():
        try:
            for _ in range(200):
                with compute_worker.worker_thread_environment():
                    assert os.environ["OMP_NUM_THREADS"] == "1"
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=start_many) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert dict(os.environ) == before


def _blas_threads():
    """Thread count the loaded OpenBLAS reports, or None when none can be queried."""

    import ctypes

    import numpy  # noqa: F401 - loads the bundled math library

    try:
        with open("/proc/self/maps", encoding="utf-8") as maps:
            libraries = sorted({line.split()[-1] for line in maps if "openblas" in line.lower()})
    except OSError:
        return None
    for path in libraries:
        library = ctypes.CDLL(path)
        for symbol in ("scipy_openblas_get_num_threads64_", "scipy_openblas_get_num_threads",
                       "openblas_get_num_threads64_", "openblas_get_num_threads"):
            function = getattr(library, symbol, None)
            if function is not None:
                function.restype = ctypes.c_int
                return function()
    return None


def worker_report():
    """Spawn-importable: what the worker's math libraries were configured with."""

    return {name: os.environ.get(name) for name in compute_worker.WORKER_THREAD_VARIABLES} | {
        "blas_threads": _blas_threads()
    }


def _run_in(context):
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
        return executor.submit(worker_report).result(timeout=120)


def test_spawn_worker_runs_with_one_math_thread_and_the_parent_is_untouched():
    before = dict(os.environ)
    report = _run_in(compute_worker.spawn_context())
    assert {name: report[name] for name in compute_worker.WORKER_THREAD_VARIABLES} == {
        name: "1" for name in compute_worker.WORKER_THREAD_VARIABLES
    }
    if report["blas_threads"] is not None:
        assert report["blas_threads"] == 1
    assert dict(os.environ) == before
    assert all(name not in os.environ for name in compute_worker.WORKER_THREAD_VARIABLES)


def test_plain_spawn_worker_does_not_get_the_limit():
    # Control: the budget context, and not the platform, is what limits the threads.
    report = _run_in(multiprocessing.get_context("spawn"))
    assert all(report[name] is None for name in compute_worker.WORKER_THREAD_VARIABLES)
    cores = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else 1
    if report["blas_threads"] is not None and cores > 1:
        assert report["blas_threads"] > 1


def test_user_thread_settings_reach_the_worker_unchanged(monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "2")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "2")
    report = _run_in(compute_worker.spawn_context())
    assert report["OMP_NUM_THREADS"] == report["OPENBLAS_NUM_THREADS"] == "2"
    assert report["MKL_NUM_THREADS"] == "1"
    if report["blas_threads"] is not None:
        assert report["blas_threads"] == 2


def test_spawn_context_keeps_the_context_api_pools_rely_on():
    context = compute_worker.spawn_context()
    assert context.get_start_method() == "spawn"
    assert context.Event().is_set() is False
    assert context.Process is not multiprocessing.get_context("spawn").Process
    assert issubclass(context.Process, multiprocessing.get_context("spawn").Process)
