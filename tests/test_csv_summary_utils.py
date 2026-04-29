import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import pandas as pd

from modules.csv_summary_utils import (
    build_csv_summary_preset_key,
    build_default_plot_toggles,
    estimate_enabled_chart_count,
    compute_column_summary_stats,
    load_csv_summary_presets,
    migrate_csv_summary_presets,
    load_csv_with_fallbacks,
    normalize_column_spec_limits,
    normalize_plot_toggles,
    recommend_extended_plots_default,
    resolve_default_data_columns,
    save_csv_summary_presets,
)

class CsvSummaryUtilsTests(unittest.TestCase):
    def test_load_csv_with_semicolon_decimal_comma(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / 'sample.csv'
            csv_path.write_text('PART;LENGTH;WIDTH\nA;10,5;2,0\nB;11,0;2,1\n', encoding='utf-8')

            df, config = load_csv_with_fallbacks(csv_path)

            self.assertEqual(['PART', 'LENGTH', 'WIDTH'], list(df.columns))
            self.assertEqual(';', config['delimiter'])
            self.assertEqual(',', config['decimal'])

    def test_resolve_default_data_columns_prefers_numeric(self):
        df = pd.DataFrame(
            {
                'SERIAL': ['A', 'B', 'C'],
                'MATERIAL': ['X', 'Y', 'Z'],
                'THICKNESS': ['1.1', '1.2', '1.3'],
                'WEIGHT': ['5', '6', '7'],
            }
        )

        selected = resolve_default_data_columns(df, ['SERIAL'])

        self.assertEqual(['THICKNESS', 'WEIGHT'], selected)


    def test_compute_column_summary_stats_uses_spec_limits(self):
        stats = compute_column_summary_stats(
            pd.Series([9.8, 10.0, 10.2]),
            nom=10.0,
            usl=0.5,
            lsl=-0.5,
        )

        self.assertEqual(3, stats['sample_size'])
        self.assertEqual(10.0, stats['nom'])
        self.assertEqual(0.5, stats['usl'])
        self.assertEqual(-0.5, stats['lsl'])
        self.assertNotEqual('N/A', stats['cp'])
        self.assertNotEqual('N/A', stats['cpk'])
        self.assertTrue(stats['spec_limits_valid'])
        self.assertEqual('', stats['spec_limits_note'])


    def test_compute_column_summary_stats_invalid_spec_limit_order_sets_na(self):
        stats = compute_column_summary_stats(
            pd.Series([9.8, 10.0, 10.2]),
            nom=10.0,
            usl=0.5,
            lsl=0.6,
        )

        self.assertFalse(stats['spec_limits_valid'])
        self.assertEqual('N/A', stats['cp'])
        self.assertEqual('N/A', stats['cpk'])
        self.assertFalse(stats['spec_limits_valid'])
        self.assertIn('Invalid spec limits', stats['spec_limits_note'])

    def test_compute_column_summary_stats_handles_empty_series(self):
        stats = compute_column_summary_stats(pd.Series(['x', None]))

        self.assertEqual(0, stats['sample_size'])
        self.assertEqual('N/A', stats['cp'])
        self.assertEqual('N/A', stats['cpk'])
        self.assertTrue(stats['spec_limits_valid'])


    def test_build_default_plot_toggles_full_report(self):
        toggles = build_default_plot_toggles(['LENGTH', 'WIDTH'])

        self.assertEqual(
            {
                'LENGTH': {'histogram': True, 'boxplot': True},
                'WIDTH': {'histogram': True, 'boxplot': True},
            },
            toggles,
        )

    def test_normalize_plot_toggles_quick_look_with_override(self):
        toggles = normalize_plot_toggles(
            ['LENGTH', 'WIDTH'],
            {'WIDTH': {'histogram': True}},
            full_report=False,
        )

        self.assertEqual(False, toggles['LENGTH']['histogram'])
        self.assertEqual(False, toggles['LENGTH']['boxplot'])
        self.assertEqual(True, toggles['WIDTH']['histogram'])
        self.assertEqual(False, toggles['WIDTH']['boxplot'])

    def test_recommend_extended_plots_default_tunes_for_large_column_sets(self):
        self.assertTrue(recommend_extended_plots_default(['A'] * 20))
        self.assertFalse(recommend_extended_plots_default(['A'] * 21))

    def test_estimate_enabled_chart_count_accounts_for_toggles_and_modes(self):
        self.assertEqual(0, estimate_enabled_chart_count(['LENGTH'], {}, full_report=False))
        self.assertEqual(0, estimate_enabled_chart_count(['LENGTH'], {}, summary_only=True))

        count = estimate_enabled_chart_count(
            ['LENGTH', 'WIDTH'],
            {'WIDTH': {'histogram': False, 'boxplot': True}},
            full_report=True,
        )
        self.assertEqual(3, count)

    def test_load_csv_with_fallbacks_handles_wide_semicolon_decimal_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / 'wide.csv'
            row_count = 1200
            numeric_columns = 160
            text_columns = 20
            headers = [f'N{i}' for i in range(numeric_columns)] + [f'T{i}' for i in range(text_columns)]

            with csv_path.open('w', encoding='utf-8', newline='') as handle:
                handle.write(';'.join(headers) + '\n')
                for row in range(row_count):
                    numeric_values = [f"{(row + idx) / 10:.1f}".replace('.', ',') for idx in range(numeric_columns)]
                    text_values = [f'TXT{(row + idx) % 97}' for idx in range(text_columns)]
                    handle.write(';'.join(numeric_values + text_values) + '\n')

            df, config = load_csv_with_fallbacks(csv_path)

            self.assertEqual(df.shape, (row_count, numeric_columns + text_columns))
            self.assertEqual({'delimiter': ';', 'decimal': ','}, config)
            self.assertEqual(list(df.columns[:3]), ['N0', 'N1', 'N2'])

    def test_load_csv_with_preferred_config_is_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / 'sample.csv'
            csv_path.write_text('PART;LENGTH\nA;10,5\nB;11,0\n', encoding='utf-8')

            _, config = load_csv_with_fallbacks(csv_path, preferred_config={'delimiter': ';', 'decimal': ','})

            self.assertEqual(';', config['delimiter'])
            self.assertEqual(',', config['decimal'])

    def test_preset_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            preset_path = Path(tmpdir) / 'presets.json'
            payload = {
                'sample.csv': {
                    'selected_indexes': ['PART'],
                    'selected_data_columns': ['LENGTH'],
                    'csv_config': {'delimiter': ';', 'decimal': ','},
                }
            }

            save_csv_summary_presets(preset_path, payload)
            loaded = load_csv_summary_presets(preset_path)

            self.assertEqual(payload, loaded)


    def test_load_csv_summary_presets_malformed_json_logs_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            preset_path = Path(tmpdir) / 'presets.json'
            preset_path.write_text('{"line.csv":', encoding='utf-8')

            with patch('modules.csv_summary_utils.logger.warning') as warning_mock:
                loaded = load_csv_summary_presets(preset_path)

            self.assertEqual({}, loaded)
            warning_mock.assert_called_once()
            args = warning_mock.call_args.args
            self.assertEqual(preset_path, args[1])
            self.assertEqual('JSONDecodeError', args[2])

    def test_load_csv_summary_presets_unreadable_logs_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            preset_path = Path(tmpdir) / 'presets.json'
            preset_path.write_text('{}', encoding='utf-8')

            with patch('pathlib.Path.open', side_effect=OSError('permission denied')):
                with patch('modules.csv_summary_utils.logger.warning') as warning_mock:
                    loaded = load_csv_summary_presets(preset_path)

            self.assertEqual({}, loaded)
            warning_mock.assert_called_once()
            args = warning_mock.call_args.args
            self.assertEqual(preset_path, args[1])
            self.assertEqual('OSError', args[2])


    def test_normalize_column_spec_limits_defaults_and_casts(self):
        limits = normalize_column_spec_limits(
            ['LENGTH', 'WIDTH'],
            {'LENGTH': {'nom': '10', 'usl': 0.5}},
        )

        self.assertEqual({'nom': 10.0, 'usl': 0.5, 'lsl': 0.0}, limits['LENGTH'])
        self.assertEqual({'nom': 0.0, 'usl': 0.0, 'lsl': 0.0}, limits['WIDTH'])


    def test_migrate_csv_summary_presets_upgrades_legacy_payload(self):
        presets = {
            'line.csv': {
                'selected_indexes': ['PART'],
                'selected_data_columns': ['LENGTH'],
                'csv_config': {'delimiter': ';', 'decimal': ','},
            }
        }

        migrated, changed = migrate_csv_summary_presets(presets)

        self.assertTrue(changed)
        self.assertIn('line.csv', migrated)
        payload = migrated['line.csv']
        self.assertEqual(False, payload['summary_only'])
        self.assertIn('column_spec_limits', payload)
        self.assertIn('plot_toggles', payload)

    def test_migrate_csv_summary_presets_no_change_for_current_schema(self):
        presets = {
            'line.csv': {
                'selected_indexes': ['PART'],
                'selected_data_columns': ['LENGTH'],
                'csv_config': {'delimiter': ';', 'decimal': ','},
                'column_spec_limits': {'LENGTH': {'nom': 10.0, 'usl': 0.5, 'lsl': -0.5}},
                'include_extended_plots': False,
                'summary_only': True,
                'plot_toggles': {'LENGTH': {'histogram': False, 'boxplot': False}},
            }
        }

        migrated, changed = migrate_csv_summary_presets(presets)

        self.assertFalse(changed)
        self.assertEqual(presets, migrated)

    def test_build_csv_summary_preset_key(self):
        key = build_csv_summary_preset_key('/tmp/Line_01_Report.csv')
        self.assertEqual('line_01_report.csv', key)


if __name__ == '__main__':
    unittest.main()
