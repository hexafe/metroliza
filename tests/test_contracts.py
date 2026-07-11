import importlib
import json
import os
import subprocess
import sys
import unittest

from modules.contracts import (
    AppPaths,
    DashboardInteractivityOptions,
    ExportOptions,
    IndustrialAnalyticsRequest,
    ParseRequest,
    ExportRequest,
    GroupingAssignment,
    validate_export_options,
    validate_export_request,
    validate_grouping_df,
    validate_industrial_analytics_request,
    validate_parse_request,
    validate_paths,
)
from modules.industrial_analytics_state import ProductionMetricSelection
from modules.tabular_analytics_service import TabularColumnFilter


class TestContractOwnership(unittest.TestCase):
    def test_compatibility_aliases_preserve_owner_object_identity(self):
        legacy = importlib.import_module("modules.contracts")
        shared = importlib.import_module("metroliza.shared.contracts")
        exporting = importlib.import_module("metroliza.exporting.contracts")
        industrial = importlib.import_module("metroliza.industrial.contracts")
        tabular = importlib.import_module("metroliza.tabular.contracts")

        self.assertIs(legacy, shared)
        self.assertIs(shared.AppPaths, exporting.AppPaths)
        self.assertIs(shared.ExportOptions, exporting.ExportOptions)
        self.assertIs(shared.ExportRequest, exporting.ExportRequest)
        self.assertIs(shared.validate_export_request, exporting.validate_export_request)
        self.assertIs(shared.IndustrialAnalyticsRequest, industrial.IndustrialAnalyticsRequest)
        self.assertIs(
            shared.validate_industrial_analytics_request,
            industrial.validate_industrial_analytics_request,
        )
        self.assertIs(shared.GroupingAssignment, tabular.GroupingAssignment)
        self.assertIs(shared.validate_grouping_df, tabular.validate_grouping_df)

    def test_cold_shared_contract_import_does_not_load_feature_packages(self):
        script = """
import importlib
import json
import sys

contracts = importlib.import_module("metroliza.shared.contracts")
print(json.dumps({
    "feature_packages": {
        name: name in sys.modules
        for name in (
            "metroliza.charts",
            "metroliza.exporting",
            "metroliza.industrial",
            "metroliza.tabular",
        )
    },
    "parse_request_available": hasattr(contracts, "ParseRequest"),
}))
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            env={**os.environ, "PYTHONPATH": "src:."},
            text=True,
            capture_output=True,
        )
        evidence = json.loads(result.stdout)

        self.assertEqual(
            evidence["feature_packages"],
            {
                "metroliza.charts": False,
                "metroliza.exporting": False,
                "metroliza.industrial": False,
                "metroliza.tabular": False,
            },
        )
        self.assertTrue(evidence["parse_request_available"])


class TestValidateParseRequest(unittest.TestCase):
    def test_accepts_valid_request(self):
        request = ParseRequest(source_directory='reports', db_file='test.db')
        validated = validate_parse_request(request)
        self.assertEqual(validated.source_directory, 'reports')
        self.assertEqual(validated.metadata_parsing_mode, 'complete')
        self.assertFalse(validated.run_background_metadata_enrichment)

    def test_normalizes_metadata_parsing_mode_alias(self):
        request = ParseRequest(source_directory='reports', db_file='test.db', metadata_parsing_mode='Fast')
        validated = validate_parse_request(request)
        self.assertEqual(validated.metadata_parsing_mode, 'light')

    def test_accepts_all_metadata_parsing_modes_used_by_parser_ui(self):
        cases = {
            'light': 'light',
            'fast': 'light',
            'complete': 'complete',
        }
        for input_mode, expected_mode in cases.items():
            with self.subTest(input_mode=input_mode):
                request = ParseRequest(
                    source_directory='reports',
                    db_file='test.db',
                    metadata_parsing_mode=input_mode,
                )
                validated = validate_parse_request(request)
                self.assertEqual(validated.metadata_parsing_mode, expected_mode)

    def test_accepts_background_metadata_enrichment_flag(self):
        request = ParseRequest(
            source_directory='reports',
            db_file='test.db',
            metadata_parsing_mode='light',
            run_background_metadata_enrichment=True,
        )
        validated = validate_parse_request(request)
        self.assertTrue(validated.run_background_metadata_enrichment)

    def test_rejects_empty_source_directory(self):
        with self.assertRaises(ValueError):
            validate_parse_request(ParseRequest(source_directory='   ', db_file='test.db'))

    def test_rejects_non_parse_request_input(self):
        with self.assertRaises(ValueError):
            validate_parse_request('reports')

    def test_rejects_unknown_metadata_parsing_mode(self):
        with self.assertRaises(ValueError):
            validate_parse_request(
                ParseRequest(source_directory='reports', db_file='test.db', metadata_parsing_mode='deep')
            )

    def test_rejects_non_boolean_background_metadata_enrichment_flag(self):
        with self.assertRaises(ValueError):
            validate_parse_request(
                ParseRequest(
                    source_directory='reports',
                    db_file='test.db',
                    run_background_metadata_enrichment='yes',
                )
            )


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
                generate_html_dashboard=1,
            )
        )

        self.assertEqual(options.preset, 'full_report')
        self.assertEqual(options.export_type, 'line')
        self.assertEqual(options.export_target, 'excel_xlsx')
        self.assertEqual(options.backend_target, 'excel')
        self.assertEqual(options.sorting_parameter, 'sample #')
        self.assertEqual(options.violin_plot_min_samplesize, 2)
        self.assertEqual(options.summary_plot_scale, 0)
        self.assertTrue(options.hide_ok_results)
        self.assertFalse(options.generate_summary_sheet)
        self.assertTrue(options.generate_html_dashboard)
        self.assertFalse(options.allow_non_essential_chart_skipping)
        self.assertEqual(options.chart_worker_count, 2)
        self.assertEqual(options.chart_worker_queue_size, 4)

    def test_normalizes_allow_non_essential_chart_skipping_flag(self):
        options = validate_export_options(ExportOptions(allow_non_essential_chart_skipping=1))
        self.assertTrue(options.allow_non_essential_chart_skipping)


    def test_clamps_chart_worker_settings(self):
        options = validate_export_options(ExportOptions(chart_worker_count=0, chart_worker_queue_size=0))
        self.assertEqual(options.chart_worker_count, 1)
        self.assertEqual(options.chart_worker_queue_size, 1)

    def test_rejects_unknown_export_type(self):
        with self.assertRaises(ValueError):
            validate_export_options(ExportOptions(export_type='bar'))


    def test_rejects_non_string_export_type(self):
        with self.assertRaises(ValueError):
            validate_export_options(ExportOptions(export_type=123))

    def test_rejects_non_string_export_target(self):
        with self.assertRaises(ValueError):
            validate_export_options(ExportOptions(export_target=123))

    def test_rejects_non_string_sorting_parameter(self):
        with self.assertRaises(ValueError):
            validate_export_options(ExportOptions(sorting_parameter=123))


    def test_normalizes_backend_target_aliases(self):
        options = validate_export_options(ExportOptions(backend_target='Google_Sheets'))
        self.assertEqual(options.backend_target, 'google')

    def test_defaults_unknown_backend_target_to_excel(self):
        options = validate_export_options(ExportOptions(backend_target='csv'))
        self.assertEqual(options.backend_target, 'excel')

    def test_normalizes_export_target_case(self):
        options = validate_export_options(ExportOptions(export_target='Excel_XLSX'))
        self.assertEqual(options.export_target, 'excel_xlsx')

    def test_rejects_unknown_export_target(self):
        with self.assertRaises(ValueError):
            validate_export_options(ExportOptions(export_target='csv'))

    def test_accepts_google_drive_conversion_target(self):
        options = validate_export_options(ExportOptions(export_target='google_sheets_drive_convert'))
        self.assertEqual(options.export_target, 'google_sheets_drive_convert')
        self.assertEqual(options.backend_target, 'google')

    def test_accepts_html_dashboard_target_and_forces_dashboard_flags(self):
        options = validate_export_options(
            ExportOptions(
                export_target='HTML_Dashboard',
                generate_summary_sheet=False,
                generate_html_dashboard=False,
            )
        )
        self.assertEqual(options.export_target, 'html_dashboard')
        self.assertEqual(options.backend_target, 'html')
        self.assertTrue(options.generate_summary_sheet)
        self.assertTrue(options.generate_html_dashboard)

    def test_normalizes_group_analysis_options(self):
        options = validate_export_options(
            ExportOptions(
                group_analysis_level='Light',
                group_analysis_scope='Single-reference',
            )
        )
        self.assertEqual(options.group_analysis_level, 'light')
        self.assertEqual(options.group_analysis_scope, 'single_reference')

    def test_rejects_unknown_group_analysis_level(self):
        with self.assertRaises(ValueError):
            validate_export_options(ExportOptions(group_analysis_level='full'))

    def test_rejects_unknown_group_analysis_scope(self):
        with self.assertRaises(ValueError):
            validate_export_options(ExportOptions(group_analysis_scope='local'))


class TestValidatePaths(unittest.TestCase):
    def test_accepts_xlsx_target(self):
        validated = validate_paths(AppPaths(db_file='test.db', excel_file='out.xlsx'))
        self.assertEqual(validated.excel_file, 'out.xlsx')

    def test_rejects_non_xlsx_target(self):
        with self.assertRaises(ValueError):
            validate_paths(AppPaths(db_file='test.db', excel_file='out.csv'))

    def test_accepts_html_dashboard_target(self):
        validated = validate_paths(AppPaths(db_file='test.db', html_dashboard_file='out.html'))
        self.assertEqual(validated.html_dashboard_file, 'out.html')

    def test_rejects_non_html_dashboard_target(self):
        with self.assertRaises(ValueError):
            validate_paths(AppPaths(db_file='test.db', html_dashboard_file='out.xlsx'))


class TestValidateGroupingDf(unittest.TestCase):
    def test_accepts_report_id_identity(self):
        rows = [{'REPORT_ID': 1, 'GROUP': 'A'}]
        validated = validate_grouping_df(rows)
        self.assertEqual(validated[0].group, 'A')
        self.assertEqual(validated[0].report_id, 1)

    def test_rejects_missing_identity_columns(self):
        rows = [{'GROUP': 'A', 'REFERENCE': 'R1'}]
        with self.assertRaises(ValueError):
            validate_grouping_df(rows)

    def test_accepts_integral_decimal_report_id(self):
        validated = validate_grouping_df([{'REPORT_ID': '2.0', 'GROUP': 'A'}])

        self.assertEqual(validated[0].report_id, 2)

    def test_rejects_fractional_boolean_and_out_of_range_report_ids(self):
        for report_id in (1.9, True, 0, -1, 2**63, 'Infinity'):
            with self.subTest(report_id=report_id), self.assertRaises(ValueError):
                validate_grouping_df([{'REPORT_ID': report_id, 'GROUP': 'A'}])


class TestValidateExportRequest(unittest.TestCase):
    def test_validates_nested_contracts(self):
        request = ExportRequest(
            paths=AppPaths(db_file='test.db', excel_file='out.xlsx'),
            options=ExportOptions(export_type='Scatter', sorting_parameter='Part #', violin_plot_min_samplesize=1),
            grouping_df=(GroupingAssignment(report_id=1, group='NOK'),),
        )

        validated = validate_export_request(request)

        self.assertEqual(validated.options.export_type, 'scatter')
        self.assertEqual(validated.options.export_target, 'excel_xlsx')
        self.assertEqual(validated.options.backend_target, 'excel')
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

    def test_html_dashboard_export_requires_html_path_and_no_workbook_path(self):
        request = ExportRequest(
            paths=AppPaths(db_file='test.db', html_dashboard_file='dashboard.html'),
            options=ExportOptions(export_target='html_dashboard'),
        )

        validated = validate_export_request(request)

        self.assertIsNone(validated.paths.excel_file)
        self.assertEqual(validated.paths.html_dashboard_file, 'dashboard.html')
        self.assertEqual(validated.options.backend_target, 'html')


class TestValidateIndustrialAnalyticsRequest(unittest.TestCase):
    def test_defaults_dashboard_interactivity_options(self):
        validated = validate_industrial_analytics_request(
            IndustrialAnalyticsRequest(
                source_kind='production_cache',
                output_dashboard_file='dashboard.html',
            )
        )

        self.assertEqual(
            validated.dashboard_interactivity_options,
            DashboardInteractivityOptions(
                mode='auto',
                sample_size=50000,
                population_layer_mode='auto',
                large_group_layer_mode='auto',
                large_group_static_threshold=5000,
                large_group_total_static_threshold=50000,
            ),
        )

    def test_normalizes_dashboard_interactivity_options_mapping(self):
        validated = validate_industrial_analytics_request(
            IndustrialAnalyticsRequest(
                source_kind='production_cache',
                output_dashboard_file='dashboard.html',
                dashboard_interactivity_options={
                    'mode': ' Sampled ',
                    'sample_size': '75000',
                    'population_layer_mode': ' Static ',
                    'large_group_static_threshold': '6000',
                    'large_group_total_static_threshold': '60000',
                    'size_limit_mode': ' Custom ',
                    'size_limit_mb': '128',
                },
            )
        )

        self.assertEqual(
            validated.dashboard_interactivity_options,
            DashboardInteractivityOptions(
                mode='sampled',
                sample_size=75000,
                population_layer_mode='static',
                large_group_layer_mode='static',
                large_group_static_threshold=6000,
                large_group_total_static_threshold=60000,
                size_limit_mode='custom',
                size_limit_mb=128,
            ),
        )

    def test_normalizes_dashboard_interactivity_population_layer_camel_case_alias(self):
        validated = validate_industrial_analytics_request(
            IndustrialAnalyticsRequest(
                source_kind='production_cache',
                output_dashboard_file='dashboard.html',
                dashboard_interactivity_options={
                    'mode': 'auto',
                    'sample_size': 50000,
                    'populationLayerMode': 'Interactive',
                },
            )
        )

        self.assertEqual(
            validated.dashboard_interactivity_options,
            DashboardInteractivityOptions(
                mode='auto',
                sample_size=50000,
                population_layer_mode='interactive',
                large_group_layer_mode='interactive',
            ),
        )

    def test_rejects_unknown_dashboard_interactivity_mode(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported dashboard interactivity mode'):
            validate_industrial_analytics_request(
                IndustrialAnalyticsRequest(
                    source_kind='production_cache',
                    output_dashboard_file='dashboard.html',
                    dashboard_interactivity_options={'mode': 'animated'},
                )
            )

    def test_rejects_unknown_dashboard_population_layer_mode(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported dashboard large group layer mode'):
            validate_industrial_analytics_request(
                IndustrialAnalyticsRequest(
                    source_kind='production_cache',
                    output_dashboard_file='dashboard.html',
                    dashboard_interactivity_options={'population_layer_mode': 'animated'},
                )
            )

    def test_rejects_invalid_dashboard_large_group_threshold(self):
        with self.assertRaisesRegex(ValueError, 'Dashboard Large Group Static Threshold'):
            validate_industrial_analytics_request(
                IndustrialAnalyticsRequest(
                    source_kind='production_cache',
                    output_dashboard_file='dashboard.html',
                    dashboard_interactivity_options={'large_group_static_threshold': 0},
                )
            )

    def test_rejects_dashboard_interactivity_sample_size_outside_bounds(self):
        with self.assertRaisesRegex(ValueError, 'between 5000 and 200000'):
            validate_industrial_analytics_request(
                IndustrialAnalyticsRequest(
                    source_kind='production_cache',
                    output_dashboard_file='dashboard.html',
                    dashboard_interactivity_options={'mode': 'sampled', 'sample_size': 4999},
                )
            )

    def test_normalizes_dashboard_interactivity_size_limit_unlimited_alias(self):
        validated = validate_industrial_analytics_request(
            IndustrialAnalyticsRequest(
                source_kind='production_cache',
                output_dashboard_file='dashboard.html',
                dashboard_interactivity_options={
                    'dashboardSizeLimitMode': 'No Limit',
                    'dashboardSizeLimitMb': 4096,
                },
            )
        )

        self.assertEqual(validated.dashboard_interactivity_options.size_limit_mode, 'unlimited')
        self.assertEqual(validated.dashboard_interactivity_options.size_limit_mb, 4096)

    def test_rejects_unknown_dashboard_size_limit_mode(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported dashboard size limit mode'):
            validate_industrial_analytics_request(
                IndustrialAnalyticsRequest(
                    source_kind='production_cache',
                    output_dashboard_file='dashboard.html',
                    dashboard_interactivity_options={'size_limit_mode': 'massive-ish'},
                )
            )

    def test_rejects_dashboard_size_limit_below_minimum(self):
        with self.assertRaisesRegex(ValueError, 'at least 1 MB'):
            validate_industrial_analytics_request(
                IndustrialAnalyticsRequest(
                    source_kind='production_cache',
                    output_dashboard_file='dashboard.html',
                    dashboard_interactivity_options={'size_limit_mode': 'custom', 'size_limit_mb': 0},
                )
            )

    def test_defaults_dashboard_detail_mode_to_full(self):
        validated = validate_industrial_analytics_request(
            IndustrialAnalyticsRequest(
                source_kind='production_cache',
                output_dashboard_file='dashboard.html',
            )
        )

        self.assertEqual(validated.dashboard_detail_mode, 'full')

    def test_normalizes_dashboard_detail_mode(self):
        validated = validate_industrial_analytics_request(
            IndustrialAnalyticsRequest(
                source_kind='production_cache',
                output_dashboard_file='dashboard.html',
                dashboard_detail_mode=' Full ',
            )
        )

        self.assertEqual(validated.dashboard_detail_mode, 'full')

    def test_rejects_unknown_dashboard_detail_mode(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported dashboard rendering mode'):
            validate_industrial_analytics_request(
                IndustrialAnalyticsRequest(
                    source_kind='production_cache',
                    output_dashboard_file='dashboard.html',
                    dashboard_detail_mode='deep',
                )
            )

    def test_normalizes_tabular_request_paths_filters_and_grouping(self):
        grouping_assignments = (GroupingAssignment(report_id=1, group='POPULATION'),)
        request = IndustrialAnalyticsRequest(
            source_kind='Tabular_File',
            input_file=' table.csv ',
            output_dashboard_file='dashboard',
            output_workbook_file='workbook',
            metric_selection=(ProductionMetricSelection('length_mm'),),
            tabular_filter_columns=['tracecode'],
            tabular_filter_keys=[['TC-001']],
            tabular_column_filters=[TabularColumnFilter('line', selected_values=('L1',))],
            grouping_df=grouping_assignments,
        )

        validated = validate_industrial_analytics_request(request, require_runnable=True)

        self.assertEqual(validated.source_kind, 'tabular_file')
        self.assertEqual(validated.input_file, 'table.csv')
        self.assertEqual(validated.output_dashboard_file, 'dashboard.html')
        self.assertEqual(validated.output_workbook_file, 'workbook.xlsx')
        self.assertEqual(validated.tabular_filter_columns, ('tracecode',))
        self.assertEqual(validated.tabular_filter_keys, (('TC-001',),))
        self.assertEqual(validated.tabular_column_filters, (TabularColumnFilter('line', selected_values=('L1',)),))
        self.assertEqual(validated.grouping_df, grouping_assignments)

    def test_rejects_runnable_tabular_request_without_input(self):
        with self.assertRaisesRegex(ValueError, 'Select a CSV or Excel file'):
            validate_industrial_analytics_request(
                IndustrialAnalyticsRequest(
                    source_kind='tabular_file',
                    output_dashboard_file='dashboard.html',
                ),
                require_runnable=True,
            )

    def test_rejects_wrong_dashboard_suffix(self):
        with self.assertRaisesRegex(ValueError, 'Dashboard output path'):
            validate_industrial_analytics_request(
                IndustrialAnalyticsRequest(
                    source_kind='production_cache',
                    db_file='production.db',
                    output_dashboard_file='dashboard.txt',
                ),
                require_runnable=True,
            )


if __name__ == '__main__':
    unittest.main()
