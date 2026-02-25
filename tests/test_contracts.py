import unittest

import pandas as pd

from modules.contracts import (
    AppPaths,
    ExportOptions,
    ParseRequest,
    ExportRequest,
    validate_export_options,
    validate_export_request,
    validate_grouping_df,
    validate_parse_request,
    validate_paths,
)


class TestValidateParseRequest(unittest.TestCase):
    def test_accepts_valid_request(self):
        request = ParseRequest(source_directory='reports', db_file='test.db')
        validated = validate_parse_request(request)
        self.assertEqual(validated.source_directory, 'reports')

    def test_rejects_empty_source_directory(self):
        with self.assertRaises(ValueError):
            validate_parse_request(ParseRequest(source_directory='   ', db_file='test.db'))


class TestValidateExportOptions(unittest.TestCase):
    def test_coerces_bounds_and_normalizes_case(self):
        options = validate_export_options(
            ExportOptions(
                preset='Full_Report',
                export_type='Line',
                sorting_parameter='Sample #',
                violin_plot_min_samplesize=1,
                summary_plot_scale=-3,
                hide_ok_results=1,
                generate_summary_sheet=0,
            )
        )

        self.assertEqual(options.preset, 'full_report')
        self.assertEqual(options.export_type, 'line')
        self.assertEqual(options.export_target, 'excel_xlsx')
        self.assertEqual(options.sorting_parameter, 'sample #')
        self.assertEqual(options.violin_plot_min_samplesize, 2)
        self.assertEqual(options.summary_plot_scale, 0)
        self.assertTrue(options.hide_ok_results)
        self.assertFalse(options.generate_summary_sheet)

    def test_rejects_unknown_export_type(self):
        with self.assertRaises(ValueError):
            validate_export_options(ExportOptions(export_type='bar'))

    def test_normalizes_export_target_case(self):
        options = validate_export_options(ExportOptions(export_target='Excel_XLSX'))
        self.assertEqual(options.export_target, 'excel_xlsx')

    def test_rejects_unknown_export_target(self):
        with self.assertRaises(ValueError):
            validate_export_options(ExportOptions(export_target='csv'))


class TestValidatePaths(unittest.TestCase):
    def test_accepts_xlsx_target(self):
        validated = validate_paths(AppPaths(db_file='test.db', excel_file='out.xlsx'))
        self.assertEqual(validated.excel_file, 'out.xlsx')

    def test_rejects_non_xlsx_target(self):
        with self.assertRaises(ValueError):
            validate_paths(AppPaths(db_file='test.db', excel_file='out.csv'))


class TestValidateGroupingDf(unittest.TestCase):
    def test_accepts_report_id_identity(self):
        df = pd.DataFrame({'REPORT_ID': [1], 'GROUP': ['A']})
        validated = validate_grouping_df(df)
        self.assertEqual(validated['GROUP'].iloc[0], 'A')

    def test_rejects_missing_identity_columns(self):
        df = pd.DataFrame({'GROUP': ['A'], 'REFERENCE': ['R1']})
        with self.assertRaises(ValueError):
            validate_grouping_df(df)


class TestValidateExportRequest(unittest.TestCase):
    def test_validates_nested_contracts(self):
        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(export_type='Scatter', sorting_parameter='Part #', violin_plot_min_samplesize=1),
            grouping_df=pd.DataFrame({'REPORT_ID': [1], 'GROUP': ['NOK']}),
        )

        validated = validate_export_request(request)

        self.assertEqual(validated.options.export_type, 'scatter')
        self.assertEqual(validated.options.export_target, 'excel_xlsx')
        self.assertEqual(validated.options.sorting_parameter, 'part #')
        self.assertEqual(validated.options.violin_plot_min_samplesize, 2)

    def test_rejects_non_string_filter_query(self):
        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(),
            filter_query=123,
        )

        with self.assertRaises(ValueError):
            validate_export_request(request)


if __name__ == '__main__':
    unittest.main()
