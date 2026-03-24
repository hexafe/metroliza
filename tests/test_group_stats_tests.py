import unittest
from unittest import mock

import numpy as np

import modules.group_stats_native as native_helper
from modules.group_stats_tests import preprocess_group, select_group_stat_test




class TestGroupStatsNativeCoercion(unittest.TestCase):
    def test_coerce_sequence_to_float64_marks_non_coercible_as_nan(self):
        arr = native_helper.coerce_sequence_to_float64([1, '2.5', 'bad', None, float('nan')])

        self.assertEqual(arr.dtype, np.float64)
        self.assertTrue(arr.flags.c_contiguous)
        np.testing.assert_allclose(arr[:2], np.array([1.0, 2.5]))
        self.assertTrue(np.isnan(arr[2]))
        self.assertTrue(np.isnan(arr[3]))
        self.assertTrue(np.isnan(arr[4]))


class TestGroupStatsTests(unittest.TestCase):
    def test_preprocess_group_coerces_numeric_and_drops_nan(self):
        result = preprocess_group('A', [1, '2.5', 'bad', None, float('nan')])

        self.assertEqual(result.label, 'A')
        self.assertEqual(result.sample_size, 2)
        self.assertFalse(result.is_empty)
        self.assertFalse(result.is_constant)

    def test_preprocess_group_uses_python_fallback_when_helper_raises(self):
        with mock.patch('modules.group_stats_tests.coerce_sequence_to_float64', side_effect=RuntimeError('boom')):
            result = preprocess_group('A', [1, '2.5', 'bad', None, float('nan')])

        self.assertEqual(result.label, 'A')
        self.assertEqual(result.sample_size, 2)
        self.assertFalse(result.is_empty)
        self.assertFalse(result.is_constant)


    def test_two_group_student_t_selected_when_normal_and_homoscedastic(self):
        labels = ['A', 'B']
        values = [
            [9.8, 10.1, 10.3, 10.0, 9.9],
            [10.2, 10.4, 10.5, 10.3, 10.1],
        ]

        result = select_group_stat_test(labels, values)

        self.assertEqual(result['test_name'], 'Student t-test')
        self.assertIsNotNone(result['p_value'])

    def test_two_group_welch_t_selected_when_variances_differ(self):
        labels = ['A', 'B']
        values = [
            [10.0, 10.01, 9.99, 10.0, 10.02, 9.98],
            [9.0, 12.0, 8.0, 13.0, 7.5, 12.5],
        ]

        result = select_group_stat_test(labels, values)

        self.assertEqual(result['test_name'], 'Welch t-test')
        self.assertIsNotNone(result['p_value'])

    def test_two_group_mann_whitney_selected_when_normality_fails(self):
        labels = ['A', 'B']
        values = [
            [0.0, 0.0, 0.0, 10.0, 10.0],
            [1.0, 1.0, 1.0, 11.0, 11.0],
        ]

        result = select_group_stat_test(labels, values)

        self.assertEqual(result['test_name'], 'Mann-Whitney U')
        self.assertIsNotNone(result['p_value'])

    def test_multi_group_anova_selected_when_assumptions_pass(self):
        labels = ['A', 'B', 'C']
        values = [
            [10.1, 10.0, 9.9, 10.2, 10.1],
            [10.3, 10.2, 10.4, 10.1, 10.2],
            [10.5, 10.4, 10.3, 10.6, 10.5],
        ]

        result = select_group_stat_test(labels, values)

        self.assertEqual(result['test_name'], 'ANOVA')
        self.assertEqual(result['assumption_outcomes']['selection_mode'], 'parametric_equal_variance')
        self.assertEqual(result['assumption_outcomes']['normality'], 'passed')
        self.assertEqual(result['assumption_outcomes']['variance_homogeneity'], 'passed')

    def test_multi_group_welch_anova_selected_when_variances_differ(self):
        labels = ['A', 'B', 'C']
        values = [
            [10.0, 10.01, 9.99, 10.0, 10.02, 9.98],
            [9.0, 12.0, 8.0, 13.0, 7.5, 12.5],
            [10.0, 10.5, 11.5, 9.2, 12.1, 8.7],
        ]

        result = select_group_stat_test(labels, values)

        self.assertEqual(result['test_name'], 'Welch ANOVA')
        self.assertEqual(result['assumption_outcomes']['selection_mode'], 'parametric_unequal_variance')
        self.assertEqual(result['assumption_outcomes']['variance_homogeneity'], 'failed')

    def test_multi_group_kruskal_selected_when_normality_fails(self):
        labels = ['A', 'B', 'C']
        values = [
            [0.0, 0.0, 0.0, 10.0, 10.0],
            [1.0, 1.0, 1.0, 11.0, 11.0],
            [2.0, 2.0, 2.0, 12.0, 12.0],
        ]

        result = select_group_stat_test(labels, values)

        self.assertEqual(result['test_name'], 'Kruskal-Wallis')
        self.assertEqual(result['assumption_outcomes']['selection_mode'], 'non_parametric')
        self.assertEqual(result['assumption_outcomes']['normality'], 'failed')


    def test_assumption_driven_selection_prefers_non_parametric_when_normality_skipped_or_failed(self):
        labels = ['A', 'B']
        values = [
            [1.0, 1.0, 1.0, 1.0, 1.0],
            [2.0, 2.0, 2.0, 2.0, 2.0],
        ]

        result = select_group_stat_test(labels, values)

        self.assertEqual(result['test_name'], 'Mann-Whitney U')
        self.assertIn('contains_constant_group', result['warnings'])
        self.assertEqual(result['assumption_outcomes']['normality'], 'skipped')
        self.assertIn('non-parametric path', result['assumption_outcomes']['selection_detail'])


    def test_input_length_mismatch_returns_warning_and_no_partial_processing(self):
        labels = ['A', 'B', 'C']
        values = [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
        ]

        result = select_group_stat_test(labels, values)

        self.assertIsNone(result['test_name'])
        self.assertIsNone(result['p_value'])
        self.assertEqual(result['warnings'], ['input_length_mismatch'])
        self.assertEqual(result['sample_sizes'], {})
        self.assertEqual(result['preprocess'], {})
        self.assertEqual(result['assumptions']['normality'], {})
        self.assertEqual(result['assumptions']['variance_homogeneity']['status'], 'not_checked')
        self.assertEqual(result['assumption_outcomes']['selection_mode'], 'unavailable')

    def test_edge_case_with_empty_and_nan_groups_returns_no_test(self):
        labels = ['A', 'B']
        values = [
            [float('nan'), None, 'bad'],
            [1.0, float('nan')],
        ]

        result = select_group_stat_test(labels, values)

        self.assertIsNone(result['test_name'])
        self.assertIn('fewer_than_two_non_empty_groups', result['warnings'])
        self.assertEqual(result['sample_sizes']['A'], 0)
        self.assertEqual(result['sample_sizes']['B'], 1)

    def test_edge_cases_small_n_constant_and_nan_groups_report_warnings(self):
        labels = ['A', 'B', 'C']
        values = [
            [1.0, 1.0, 1.0],
            [None, 'bad', float('nan')],
            [2.0],
        ]

        result = select_group_stat_test(labels, values)

        self.assertIn('B', result['preprocess'])
        self.assertIn('empty_after_nan_drop', result['preprocess']['B'])
        self.assertIn('contains_group_with_n_lt_2', result['warnings'])
        self.assertEqual(result['assumption_outcomes']['selection_mode'], 'unavailable')
        self.assertIn('fewer than 2 values', result['assumption_outcomes']['selection_detail'])


if __name__ == '__main__':
    unittest.main()
