"""Chart data sampling and bounded background execution primitives.

This module provides deterministic frame downsampling helpers used by chart
payload builders and a small worker pool that applies queue backpressure for
bounded concurrent rendering workloads.
"""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from queue import Queue
from threading import Thread
from typing import Any, Callable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ChartSamplingPolicy:
    """Per-chart row limits used before building chart payloads.

    Attributes:
        distribution_limit: Maximum rows for distribution chart sampling.
        iqr_limit: Maximum rows for IQR chart sampling.
        histogram_limit: Maximum rows for histogram chart sampling.
        trend_limit: Maximum rows for trend chart sampling.
    """

    distribution_limit: int
    iqr_limit: int
    histogram_limit: int
    trend_limit: int


def resolve_chart_sampling_policy(*, density_mode: str) -> ChartSamplingPolicy:
    """Resolve chart sampling limits for the requested density mode.

    Args:
        density_mode: Requested density profile.

    Returns:
        A :class:`ChartSamplingPolicy` with per-chart row limits.
    """

    if density_mode == 'reduced':
        return ChartSamplingPolicy(distribution_limit=900, iqr_limit=750, histogram_limit=900, trend_limit=900)
    return ChartSamplingPolicy(distribution_limit=1500, iqr_limit=1200, histogram_limit=1500, trend_limit=1500)


def deterministic_downsample_frame(df: pd.DataFrame, sample_limit: int, *, preserve_extrema: bool = False, value_column: str = 'MEAS') -> pd.DataFrame:
    """Deterministically downsample a frame with optional local-extrema preservation.

    Args:
        df: Source frame.
        sample_limit: Maximum row count to retain.
        preserve_extrema: When ``True``, retain local minima/maxima candidates for
            trend-like charts in addition to evenly spaced coverage points.
        value_column: Numeric column used for extrema detection.

    Returns:
        The original frame when no sampling is required, otherwise a copy of the
        selected rows.
    """

    if sample_limit <= 0 or len(df) <= sample_limit:
        return df

    if not preserve_extrema or value_column not in df.columns:
        indexes = np.linspace(0, len(df) - 1, sample_limit, dtype=int)
        return df.iloc[indexes].copy()

    numeric_values = pd.to_numeric(df[value_column], errors='coerce').to_numpy(dtype=float, copy=False)
    if numeric_values.size <= 2 or not np.isfinite(numeric_values).any():
        indexes = np.linspace(0, len(df) - 1, sample_limit, dtype=int)
        return df.iloc[indexes].copy()

    finite_indexes = np.flatnonzero(np.isfinite(numeric_values))
    protected_indexes: set[int] = {0, len(df) - 1}
    selected_indexes: set[int] = set(protected_indexes)
    if finite_indexes.size:
        finite_values = numeric_values[finite_indexes]
        protected_indexes.add(int(finite_indexes[int(np.argmin(finite_values))]))
        protected_indexes.add(int(finite_indexes[int(np.argmax(finite_values))]))
        selected_indexes.update(protected_indexes)

    segment_edges = np.linspace(0, len(df), sample_limit + 1, dtype=int)
    for start, stop in zip(segment_edges[:-1], segment_edges[1:]):
        if start >= len(df):
            continue
        stop = max(start + 1, min(len(df), stop))
        segment_values = numeric_values[start:stop]
        finite_mask = np.isfinite(segment_values)
        if not finite_mask.any():
            selected_indexes.add(start)
            continue

        finite_positions = np.flatnonzero(finite_mask)
        finite_values = segment_values[finite_mask]
        min_pos = finite_positions[int(np.argmin(finite_values))]
        max_pos = finite_positions[int(np.argmax(finite_values))]
        selected_indexes.update({start + int(min_pos), start + int(max_pos)})
        selected_indexes.add(start + int(finite_positions[0]))
        selected_indexes.add(start + int(finite_positions[-1]))

    ordered_indexes = sorted(selected_indexes)
    if len(ordered_indexes) > sample_limit:
        coverage_indexes = [int(index) for index in np.linspace(0, len(df) - 1, sample_limit, dtype=int).tolist()]
        trimmed_indexes = set(protected_indexes)

        def _extrema_priority(idx):
            value = numeric_values[idx]
            if not np.isfinite(value):
                return 0.0
            left = numeric_values[idx - 1] if idx > 0 else value
            right = numeric_values[idx + 1] if idx < len(numeric_values) - 1 else value
            left_delta = abs(float(value) - float(left)) if np.isfinite(left) else 0.0
            right_delta = abs(float(value) - float(right)) if np.isfinite(right) else 0.0
            return max(left_delta, right_delta)

        extrema_candidates = [index for index in ordered_indexes if index not in trimmed_indexes]
        ranked_candidates = sorted(
            extrema_candidates,
            key=lambda idx: (_extrema_priority(idx), abs(float(numeric_values[idx])) if np.isfinite(numeric_values[idx]) else 0.0),
            reverse=True,
        )
        for index in ranked_candidates:
            if len(trimmed_indexes) >= sample_limit:
                break
            trimmed_indexes.add(index)
        if len(trimmed_indexes) < sample_limit:
            for index in coverage_indexes:
                if len(trimmed_indexes) >= sample_limit:
                    break
                trimmed_indexes.add(index)
        if len(trimmed_indexes) < sample_limit:
            for index in ordered_indexes:
                if len(trimmed_indexes) >= sample_limit:
                    break
                trimmed_indexes.add(index)
        ordered_indexes = sorted(trimmed_indexes)

    return df.iloc[ordered_indexes].copy()


def sample_frame_for_chart(df: pd.DataFrame, chart_type: str, policy: ChartSamplingPolicy) -> pd.DataFrame:
    """Sample a frame using the limit associated with a chart type.

    Args:
        df: Source frame.
        chart_type: Chart type key.
        policy: Sampling policy containing per-chart limits.

    Returns:
        A sampled frame constrained by the chart-specific limit.
    """

    limit_by_chart = {
        'distribution': policy.distribution_limit,
        'iqr': policy.iqr_limit,
        'histogram': policy.histogram_limit,
        'trend': policy.trend_limit,
    }
    return deterministic_downsample_frame(
        df,
        limit_by_chart.get(chart_type, policy.distribution_limit),
        preserve_extrema=chart_type == 'trend',
    )


def build_violin_payload_vectorized(sampled_group: pd.DataFrame, grouping_key: str, min_samplesize: int) -> tuple[list[str], list[list[float]], bool]:
    """Build vectorized violin payload data grouped by a column.

    Args:
        sampled_group: Input frame containing ``MEAS`` and optional grouping
            column.
        grouping_key: Column used to split violin series.
        min_samplesize: Minimum rows required per group to render violin plots.

    Returns:
        A tuple ``(labels, values, can_render_violin)`` where ``labels`` are
        group names, ``values`` are per-group numeric arrays, and
        ``can_render_violin`` indicates whether all groups meet
        ``min_samplesize``.
    """

    if sampled_group.empty or grouping_key not in sampled_group.columns:
        cleaned_values = pd.to_numeric(sampled_group.get('MEAS', pd.Series(dtype=float)), errors='coerce').dropna()
        values = cleaned_values.tolist()
        return ['All'], [values], len(cleaned_values) >= min_samplesize

    work_df = sampled_group[[grouping_key, 'MEAS']].dropna(how='all', subset=[grouping_key, 'MEAS']).copy()
    work_df = work_df.dropna(subset=['MEAS'])
    if pd.api.types.is_string_dtype(work_df[grouping_key]) or pd.api.types.is_object_dtype(work_df[grouping_key]):
        work_df[grouping_key] = work_df[grouping_key].str.strip()
    work_df = work_df[work_df[grouping_key].notna()]
    work_df = work_df[work_df[grouping_key] != '']
    work_df[grouping_key] = work_df[grouping_key].astype(str)

    grouped = work_df.groupby(grouping_key, sort=False)['MEAS']
    group_sizes = grouped.size()
    labels = group_sizes.index.tolist()
    values = [series.to_numpy(dtype=float).tolist() for _, series in grouped]
    can_render_violin = bool((group_sizes >= int(min_samplesize)).all()) if len(group_sizes) else False
    return labels, values, can_render_violin


class BoundedWorkerPool:
    """Bounded worker queue that applies backpressure to submitters.

    The queue has a fixed capacity; once full, :meth:`submit` blocks until a
    worker consumes an item. This prevents unbounded task accumulation.
    """

    def __init__(self, *, max_workers: int, max_queue_size: int):
        self._max_workers = max(1, int(max_workers))
        self._queue: Queue[tuple[Future, Callable[..., Any], tuple[Any, ...], dict[str, Any]] | None] = Queue(maxsize=max(1, int(max_queue_size)))
        self._threads: list[Thread] = []
        self._closed = False
        for idx in range(self._max_workers):
            worker = Thread(target=self._worker_loop, name=f'chart-worker-{idx}', daemon=True)
            worker.start()
            self._threads.append(worker)

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        """Submit a task for execution.

        Args:
            fn: Callable to execute in a worker thread.
            *args: Positional arguments for ``fn``.
            **kwargs: Keyword arguments for ``fn``.

        Returns:
            A :class:`concurrent.futures.Future` for the task.

        Raises:
            RuntimeError: If called after shutdown has begun.

        Notes:
            Submission uses a blocking queue ``put`` to enforce backpressure when
            the queue is full.
        """

        if self._closed:
            raise RuntimeError('Worker pool is closed.')
        future: Future = Future()
        self._queue.put((future, fn, args, kwargs), block=True)
        return future

    def _worker_loop(self):
        """Continuously execute queued tasks until a shutdown sentinel is seen."""

        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            future, fn, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                self._queue.task_done()
                continue
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - exercised indirectly
                future.set_exception(exc)
            else:
                future.set_result(result)
            finally:
                self._queue.task_done()

    def shutdown(self, wait: bool = True):
        """Shut down the pool and optionally wait for worker termination.

        Args:
            wait: Whether to join worker threads before returning.

        Notes:
            Shutdown is idempotent; repeated calls after closure are no-ops.
            A sentinel is enqueued per worker so each thread exits cleanly.
        """

        if self._closed:
            return
        self._closed = True
        for _ in self._threads:
            self._queue.put(None, block=True)
        if wait:
            for worker in self._threads:
                worker.join()
