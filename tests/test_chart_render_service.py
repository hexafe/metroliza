import unittest
import threading
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from modules.chart_render_service import (
    BoundedWorkerPool,
    build_violin_payload_vectorized,
    deterministic_downsample_frame,
    resolve_chart_sampling_policy,
    sample_frame_for_chart,
)


def test_nonwaiting_shutdown_never_uses_blocking_queue_api():
    calls = []
    pool = BoundedWorkerPool.__new__(BoundedWorkerPool)
    pool._closed, pool._threads = False, [object()]
    pool._admission = threading.Condition()
    pool._queue = SimpleNamespace(
        put=lambda *args, **kwargs: calls.append("blocking"),
        put_nowait=lambda *args: calls.append("nonblocking"),
    )
    pool.shutdown(wait=False)
    assert calls == ["nonblocking"]


def test_nonwaiting_shutdown_with_full_queue_drains_and_joins_normally():
    entered, release = threading.Event(), threading.Event()
    pool = BoundedWorkerPool(max_workers=3, max_queue_size=1)
    def work():
        entered.set()
        release.wait(5)
        return 7
    futures = [pool.submit(work) for _ in range(3)]
    assert entered.wait(2)
    pending = pool.submit(lambda: 9)
    try:
        pool.shutdown(wait=False)
    finally:
        release.set()
        pool.shutdown(wait=True)
    assert all(future.result() == 7 for future in futures)
    assert pending.result() == 9
    assert not any(worker.is_alive() for worker in pool._threads)
    pool.shutdown(wait=True)


def test_module_shutdown_tracks_real_chart_workers_without_starting_pools():
    from metroliza.charts import chart_render_service as service

    pool = BoundedWorkerPool(max_workers=2, max_queue_size=1)
    try:
        assert all(thread.name.startswith("chart-worker-") and thread.daemon for thread in pool._threads)
        assert service.shutdown(deadline=time.monotonic() + 2)
        assert not any(worker.is_alive() for worker in pool._threads)
    finally:
        pool.shutdown(wait=True)
    assert service.shutdown(deadline=time.monotonic()) is True


def test_module_shutdown_requests_all_pools_before_joining_with_one_deadline(monkeypatch):
    from metroliza.charts import chart_render_service as service

    calls, clock = [], iter([10.0, 11.0, 15.0])
    workers = [SimpleNamespace(join=lambda *, timeout, i=i: calls.append((i, timeout)),
                               is_alive=lambda: False) for i in range(3)]
    pools = [SimpleNamespace(shutdown=lambda *, wait, i=i: calls.append(("stop", i, wait)),
                             _threads=group) for i, group in enumerate([workers[:2], workers[2:]])]
    monkeypatch.setattr(service, "_POOLS", pools)
    monkeypatch.setattr(service.time, "monotonic", lambda: next(clock))
    assert service.shutdown(deadline=12.0)
    assert calls == [("stop", 0, False), ("stop", 1, False), (0, 2.0), (1, 1.0), (2, 0.0)]


def test_module_shutdown_reports_live_worker_after_expired_deadline(monkeypatch):
    from metroliza.charts import chart_render_service as service

    timeouts = []
    worker = SimpleNamespace(join=lambda *, timeout: timeouts.append(timeout), is_alive=lambda: True)
    monkeypatch.setattr(service, "_POOLS", [SimpleNamespace(shutdown=lambda *, wait: None, _threads=[worker])])
    monkeypatch.setattr(service.time, "monotonic", lambda: 20.0)
    assert service.shutdown(deadline=12.0) is False
    assert timeouts == [0.0]


def test_submit_racing_close_cannot_block_on_leftover_sentinel(monkeypatch):
    from concurrent.futures import Future
    from metroliza.charts import chart_render_service as service

    pool = BoundedWorkerPool(max_workers=1, max_queue_size=1)
    errors = []
    def close_during_admission():
        pool.shutdown(wait=True)
        assert pool._queue.full()  # final worker passes on the sentinel
        return Future()
    monkeypatch.setattr(service, "Future", close_during_admission)
    def submit():
        try:
            pool.submit(lambda: 7)
        except RuntimeError as error:
            errors.append(str(error))
    submitter = threading.Thread(target=submit)
    submitter.start()
    submitter.join(1)
    stuck = submitter.is_alive()
    if stuck:
        # Release the RED submitter normally; never leave a blocked real thread.
        pool._queue.get_nowait()
        pool._queue.task_done()
    submitter.join(2)
    pool.shutdown(wait=True)
    assert not submitter.is_alive()
    assert not stuck, "submit blocked after shutdown on a leftover sentinel"
    assert errors == ["Worker pool is closed."]
    with pytest.raises(RuntimeError, match="closed"):
        pool.submit(lambda: 9)


class TestChartRenderService(unittest.TestCase):
    def test_deterministic_downsample_is_stable(self):
        frame = pd.DataFrame({'MEAS': list(range(100))})
        sampled_a = deterministic_downsample_frame(frame, 10)
        sampled_b = deterministic_downsample_frame(frame, 10)

        self.assertEqual(sampled_a['MEAS'].tolist(), sampled_b['MEAS'].tolist())
        self.assertEqual(len(sampled_a), 10)

    def test_policy_changes_limits_for_reduced_mode(self):
        full = resolve_chart_sampling_policy(density_mode='full')
        reduced = resolve_chart_sampling_policy(density_mode='reduced')

        self.assertLess(reduced.histogram_limit, full.histogram_limit)
        self.assertLess(reduced.iqr_limit, full.iqr_limit)

    def test_vectorized_violin_payload_preserves_group_order(self):
        frame = pd.DataFrame(
            {
                'GROUP': ['B', 'B', 'A', 'A'],
                'MEAS': [2.0, 2.2, 1.0, 1.1],
            }
        )

        labels, values, can_render = build_violin_payload_vectorized(frame, 'GROUP', 2)

        self.assertEqual(labels, ['B', 'A'])
        self.assertEqual(values, [[2.0, 2.2], [1.0, 1.1]])
        self.assertTrue(can_render)


    def test_vectorized_violin_payload_ungrouped_nans_only_cannot_render(self):
        frame = pd.DataFrame({'MEAS': [float('nan'), None, float('nan')]})

        labels, values, can_render = build_violin_payload_vectorized(frame, 'GROUP', 1)

        self.assertEqual(labels, ['All'])
        self.assertEqual(values, [[]])
        self.assertFalse(can_render)

    def test_vectorized_violin_payload_ungrouped_drops_nans_for_count_and_values(self):
        frame = pd.DataFrame({'MEAS': [1.0, float('nan'), '2.5', None, 3]})

        labels, values, can_render = build_violin_payload_vectorized(frame, 'GROUP', 3)

        self.assertEqual(labels, ['All'])
        self.assertEqual(values, [[1.0, 2.5, 3.0]])
        self.assertTrue(can_render)

    def test_bounded_worker_pool_executes_work_items(self):
        pool = BoundedWorkerPool(max_workers=1, max_queue_size=1)
        try:
            future = pool.submit(lambda x: x + 1, 4)
            self.assertEqual(future.result(), 5)
        finally:
            pool.shutdown(wait=True)

    def test_sample_frame_for_chart_uses_chart_specific_limit(self):
        frame = pd.DataFrame({'MEAS': list(range(2000))})
        policy = resolve_chart_sampling_policy(density_mode='reduced')
        sampled = sample_frame_for_chart(frame, 'iqr', policy)

        self.assertEqual(len(sampled), policy.iqr_limit)

    def test_vectorized_violin_payload_excludes_null_and_blank_groups(self):
        frame = pd.DataFrame(
            {
                'GROUP': ['A', None, '', '   ', 'B'],
                'MEAS': [1.0, 9.9, 8.8, 7.7, 2.0],
            }
        )

        labels, values, can_render = build_violin_payload_vectorized(frame, 'GROUP', 1)

        self.assertEqual(labels, ['A', 'B'])
        self.assertEqual(values, [[1.0], [2.0]])
        self.assertTrue(can_render)


    def test_unknown_chart_type_falls_back_to_distribution_limit_for_existing_exports(self):
        frame = pd.DataFrame({'MEAS': list(range(2000))})
        policy = resolve_chart_sampling_policy(density_mode='reduced')

        sampled = sample_frame_for_chart(frame, 'summary_scatter', policy)

        self.assertEqual(len(sampled), policy.distribution_limit)

    def test_vectorized_violin_payload_non_grouped_behavior_remains_unchanged(self):
        frame = pd.DataFrame({'MEAS': [1.0, '2.0', None, 3.5]})

        labels, values, can_render = build_violin_payload_vectorized(frame, 'MISSING_GROUP', 3)

        self.assertEqual(labels, ['All'])
        self.assertEqual(values, [[1.0, 2.0, 3.5]])
        self.assertTrue(can_render)

    def test_deterministic_downsample_preserves_local_extrema_for_trends(self):
        frame = pd.DataFrame({'MEAS': [0, 1, 0, 10, 0, -8, 0, 1, 0]})

        sampled = deterministic_downsample_frame(frame, 5, preserve_extrema=True)

        self.assertEqual(sampled['MEAS'].tolist()[0], 0)
        self.assertEqual(sampled['MEAS'].tolist()[-1], 0)
        self.assertIn(10, sampled['MEAS'].tolist())
        self.assertIn(-8, sampled['MEAS'].tolist())
        self.assertEqual(len(sampled), 5)


if __name__ == '__main__':
    unittest.main()
