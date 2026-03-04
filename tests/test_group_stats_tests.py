import unittest

from modules.group_stats_tests import preprocess_group, select_group_stat_test


class TestGroupStatsTests(unittest.TestCase):
    def test_preprocess_group_coerces_numeric_and_drops_nan(self):
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

    def test_multi_group_welch_anova_selected_when_variances_differ(self):
        labels = ['A', 'B', 'C']
        values = [
            [10.0, 10.01, 9.99, 10.0, 10.02, 9.98],
            [9.0, 12.0, 8.0, 13.0, 7.5, 12.5],
            [10.0, 10.5, 11.5, 9.2, 12.1, 8.7],
        ]

        result = select_group_stat_test(labels, values)

        self.assertEqual(result['test_name'], 'Welch ANOVA')

    def test_multi_group_kruskal_selected_when_normality_fails(self):
        labels = ['A', 'B', 'C']
        values = [
            [0.0, 0.0, 0.0, 10.0, 10.0],
            [1.0, 1.0, 1.0, 11.0, 11.0],
            [2.0, 2.0, 2.0, 12.0, 12.0],
        ]

        result = select_group_stat_test(labels, values)

        self.assertEqual(result['test_name'], 'Kruskal-Wallis')


    def test_assumption_driven_selection_prefers_non_parametric_when_normality_skipped_or_failed(self):
        labels = ['A', 'B']
        values = [
            [1.0, 1.0, 1.0, 1.0, 1.0],
            [2.0, 2.0, 2.0, 2.0, 2.0],
        ]

        result = select_group_stat_test(labels, values)

        self.assertEqual(result['test_name'], 'Mann-Whitney U')
        self.assertIn('contains_constant_group', result['warnings'])

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


if __name__ == '__main__':
    unittest.main()
