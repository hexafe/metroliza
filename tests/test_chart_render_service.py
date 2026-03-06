import unittest

import pandas as pd

from modules.chart_render_service import (
    BoundedWorkerPool,
    build_violin_payload_vectorized,
    deterministic_downsample_frame,
    resolve_chart_sampling_policy,
    sample_frame_for_chart,
)


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


if __name__ == '__main__':
    unittest.main()
