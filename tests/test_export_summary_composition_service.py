import unittest

from modules.export_summary_composition_service import (
    build_summary_table_composition,
    classify_capability_status,
    classify_normality_status,
)


class TestExportSummaryCompositionService(unittest.TestCase):
    def test_build_summary_table_composition_returns_badges_and_subtitle_contract(self):
        summary_stats = {
            'cp': 1.45,
            'cpk': 1.21,
            'normality_status': 'not_normal',
            'nok_pct': 0.012,
            'sample_size': 84,
        }
        histogram_table_payload = {
            'capability_rows': {
                'Cp': {'label': 'Cp', 'classification_value': 1.45},
                'Cpk': {'label': 'Cpk', 'classification_value': 1.21},
            },
            'summary_metrics': {'nok_pct_abs_diff': 0.03, 'nok_pct_discrepancy_threshold': 0.02},
        }

        result = build_summary_table_composition(summary_stats, histogram_table_payload)

        self.assertEqual(result['capability_badge']['palette_key'], 'quality_marginal')
        self.assertEqual(result['histogram_row_badges']['Normality']['palette_key'], 'normality_not_normal')
        self.assertEqual(result['histogram_row_badges']['NOK %']['palette_key'], 'quality_marginal')
        self.assertEqual(result['histogram_row_badges']['NOK % Δ (abs/rel)']['palette_key'], 'quality_risk')
        self.assertEqual(result['panel_subtitle'], 'n=84 • NOK=1.2%')


    def test_build_summary_table_composition_marks_low_n_rows_as_low_confidence(self):
        summary_stats = {
            'cp': 1.45,
            'cpk': 1.21,
            'normality_status': 'not_normal',
            'nok_pct': 0.012,
            'sample_size': 20,
        }
        histogram_table_payload = {
            'sample_confidence': {'is_low_n': True, 'severity': 'warning'},
            'capability_rows': {
                'Cp': {'label': 'Cp ⚠', 'classification_value': 1.45},
                'Cpk': {'label': 'Cpk ⚠', 'classification_value': 1.21},
            }
        }

        result = build_summary_table_composition(summary_stats, histogram_table_payload)

        self.assertEqual(result['capability_badge']['label'], '! Capability low confidence')
        self.assertIn('Samples', result['histogram_row_badges'])
        self.assertEqual(result['histogram_row_badges']['Cp ⚠']['palette_key'], 'quality_marginal')

    def test_classification_contracts_remain_stable_for_unknown_inputs(self):
        self.assertEqual(classify_capability_status('N/A', 'N/A')['palette_key'], 'quality_unknown')
        self.assertEqual(classify_normality_status('unexpected')['palette_key'], 'normality_unknown')


if __name__ == '__main__':
    unittest.main()
