"""One place that decides how many worker processes each compute pool may start.

Pool kinds: ``import_prepare`` (report import preparation), ``render`` (Extended plots),
``review`` (metadata review scan) and ``chart`` (export chart executor).

Budget: the logical CPU count minus one, never below one, so the GUI keeps a core.
``METROLIZA_COMPUTE_WORKERS`` replaces that number for every pool. A pool's own
variable keeps precedence over it and over the defaults:

* ``METROLIZA_IMPORT_PREPARE_WORKERS`` / ``METROLIZA_IMPORT_PREPARE_MIN_REPORTS``
* ``METROLIZA_REVIEW_WORKERS`` / ``METROLIZA_REVIEW_MIN_FILES``
* ``METROLIZA_EXPORT_GROUP_WORKERS`` / ``METROLIZA_EXPORT_GROUP_MIN_GROUPS`` (packaged Windows)

Each pool keeps its own ceiling (``IMPORT_PREPARE_MAX_AUTO``, ``REVIEW_MAX_AUTO``, the
render cap and the requested ``chart_worker_count``); the global variable can lower the
render and chart counts and sets the automatic import-prepare and review count (up to
``MAX_EXPLICIT_WORKERS``). A pool's own variable is how to exceed a ceiling.

Frozen builds: workers start only when ``compute_workers_available()`` validates the
packaged compute executable, including explicit counts. In the packaged Windows app the
import-prepare and review pools stay off (0) unless their own variable enables them
(Issue #1136); the global variable never switches them on there.

The review count is used by the review-scan pool: source default ``min(4, budget)`` for at
least ``REVIEW_DEFAULT_MIN_FILES`` files (200 in the packaged Windows app, where it is opt-in).

Pool workers also start with one math-library thread; see
``metroliza.shared.compute_worker.worker_thread_environment``.

This module must stay Qt-free and light: spawned workers import it.
"""

from __future__ import annotations

import os
from typing import Callable

from metroliza.shared.compute_worker import compute_workers_available, frozen_windows
from metroliza.shared.env_utils import env_int, env_value

GLOBAL_WORKERS_ENV = "METROLIZA_COMPUTE_WORKERS"

IMPORT_PREPARE_WORKERS_ENV = "METROLIZA_IMPORT_PREPARE_WORKERS"
IMPORT_PREPARE_MIN_REPORTS_ENV = "METROLIZA_IMPORT_PREPARE_MIN_REPORTS"
IMPORT_PREPARE_DEFAULT_MIN_REPORTS = 64
IMPORT_PREPARE_FROZEN_MIN_REPORTS = 200
IMPORT_PREPARE_MAX_AUTO = 3

REVIEW_WORKERS_ENV = "METROLIZA_REVIEW_WORKERS"
REVIEW_MIN_FILES_ENV = "METROLIZA_REVIEW_MIN_FILES"
REVIEW_DEFAULT_MIN_FILES = 64
REVIEW_FROZEN_MIN_FILES = 200
REVIEW_MAX_AUTO = 4

RENDER_MAX_WORKERS = 4
RENDER_FROZEN_WORKERS_ENV = "METROLIZA_EXPORT_GROUP_WORKERS"
RENDER_FROZEN_DEFAULT_WORKERS = 2
RENDER_MIN_GROUPS = 8
RENDER_FROZEN_MIN_GROUPS_ENV = "METROLIZA_EXPORT_GROUP_MIN_GROUPS"
RENDER_FROZEN_DEFAULT_MIN_GROUPS = 40

MAX_EXPLICIT_WORKERS = 16

POOL_KINDS = ("import_prepare", "render", "review", "chart")


def logical_cpus() -> int:
    return os.cpu_count() or 1


def global_override() -> int | None:
    """Return ``METROLIZA_COMPUTE_WORKERS`` when it is a positive integer, else ``None``."""

    try:
        value = env_int(GLOBAL_WORKERS_ENV)
    except ValueError:
        return None
    return min(value, MAX_EXPLICIT_WORKERS) if value and value > 0 else None


def worker_budget() -> int:
    """Worker processes the machine can run next to the GUI (at least one)."""

    return global_override() or max(1, logical_cpus() - 1)


def _gated(workers: int, available: Callable[[], bool] | None) -> int:
    # Validate the package identity (it hashes the packaged executables) only when a
    # worker would actually start, so serial runs never pay for it.
    check = compute_workers_available if available is None else available
    return workers if workers and check() else 0


def _minimum(name: str, default: int) -> int:
    try:
        return max(2, env_int(name, default=default) or default)
    except ValueError:
        return default


def _automatic_workers(ceiling: int, items: int) -> int:
    override = global_override()
    workers = min(override, items) if override else min(ceiling, worker_budget())
    return workers if workers >= 2 else 0


def _count_for_batch(
    items: int,
    *,
    workers_env: str,
    min_env: str,
    default_minimum: int,
    frozen_minimum: int,
    ceiling: int,
    available: Callable[[], bool] | None,
) -> int:
    configured = (env_value(workers_env) or "auto").lower()
    minimum = _minimum(min_env, frozen_minimum if frozen_windows() else default_minimum)
    if items < minimum:
        return 0
    if configured != "auto":
        try:
            workers = max(0, min(int(configured), MAX_EXPLICIT_WORKERS, items))
        except ValueError:
            return 0
        return _gated(workers, available)
    if frozen_windows():
        return 0
    return _gated(_automatic_workers(ceiling, items), available)


def import_prepare_workers(report_count: int, *, available: Callable[[], bool] | None = None) -> int:
    """Worker processes for preparing ``report_count`` reports; 0 means in-process.

    ``METROLIZA_IMPORT_PREPARE_WORKERS`` is ``auto`` (default), ``0`` or an explicit count.
    Small batches stay serial because process start-up would dominate. Frozen builds stay
    serial, even with an explicit count, unless the compute executable validates.
    """

    return _count_for_batch(
        report_count,
        workers_env=IMPORT_PREPARE_WORKERS_ENV,
        min_env=IMPORT_PREPARE_MIN_REPORTS_ENV,
        default_minimum=IMPORT_PREPARE_DEFAULT_MIN_REPORTS,
        frozen_minimum=IMPORT_PREPARE_FROZEN_MIN_REPORTS,
        ceiling=IMPORT_PREPARE_MAX_AUTO,
        available=available,
    )


def review_workers(file_count: int, *, available: Callable[[], bool] | None = None) -> int:
    """Worker processes for scanning ``file_count`` files in the review dialog; 0 = in-process.

    Same rules as import preparation with ``METROLIZA_REVIEW_WORKERS`` and
    ``METROLIZA_REVIEW_MIN_FILES``: source default ``min(4, budget)`` from
    ``REVIEW_DEFAULT_MIN_FILES`` files; packaged Windows default 0 (opt-in).
    """

    return _count_for_batch(
        file_count,
        workers_env=REVIEW_WORKERS_ENV,
        min_env=REVIEW_MIN_FILES_ENV,
        default_minimum=REVIEW_DEFAULT_MIN_FILES,
        frozen_minimum=REVIEW_FROZEN_MIN_FILES,
        ceiling=REVIEW_MAX_AUTO,
        available=available,
    )


def render_min_groups() -> int:
    """Smallest group count that uses the Extended-plots pool (8; packaged Windows 40, overridable)."""

    if not frozen_windows():
        return RENDER_MIN_GROUPS
    try:
        return env_int(RENDER_FROZEN_MIN_GROUPS_ENV, default=RENDER_FROZEN_DEFAULT_MIN_GROUPS)
    except ValueError:
        return RENDER_FROZEN_DEFAULT_MIN_GROUPS


def render_workers(requested: int, entry_count: int, *, cap: int = RENDER_MAX_WORKERS) -> int:
    """Worker processes for Extended plots: the requested count, the cap and one group less
    than the entries (the first group is rendered by the caller), plus the packaged Windows
    limit and the optional global override as upper bounds."""

    workers = min(cap, requested, entry_count - 1)
    if frozen_windows():
        try:
            configured = env_int(RENDER_FROZEN_WORKERS_ENV, default=RENDER_FROZEN_DEFAULT_WORKERS)
        except ValueError:
            configured = RENDER_FROZEN_DEFAULT_WORKERS
        workers = min(workers, max(1, configured or RENDER_FROZEN_DEFAULT_WORKERS))
    override = global_override()
    return min(workers, override) if override else workers


def chart_workers(requested: int) -> int:
    """Worker processes for the export chart executor (the requested count, at least one)."""

    workers = max(1, int(requested))
    override = global_override()
    return min(workers, override) if override else workers


def resolve_workers(kind: str, *, items: int = 0, requested: int = 1,
                    available: Callable[[], bool] | None = None) -> int:
    """Dispatch to the pool kind's rule (``items`` is the batch size)."""

    if kind == "import_prepare":
        return import_prepare_workers(items, available=available)
    if kind == "review":
        return review_workers(items, available=available)
    if kind == "render":
        return render_workers(requested, items)
    if kind == "chart":
        return chart_workers(requested)
    raise ValueError(f"unknown compute pool kind: {kind!r}")
