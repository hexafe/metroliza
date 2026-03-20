import os
import sys
import tempfile
import types
import unittest
import zipfile
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pandas as pd

from pathlib import Path

from modules.db import execute_with_retry  # noqa: E402


qtcore_stub = sys.modules.get('PyQt6.QtCore') or types.ModuleType('PyQt6.QtCore')


class _DummyThread:
    def __init__(self, *args, **kwargs):
        pass


class _DummyCoreApp:
    @staticmethod
    def processEvents():
        return None


def _dummy_signal(*args, **kwargs):
    class _Signal:
        def emit(self, *a, **k):
            return None

    return _Signal()


qtcore_stub.QCoreApplication = getattr(qtcore_stub, 'QCoreApplication', _DummyCoreApp)
qtcore_stub.QThread = getattr(qtcore_stub, 'QThread', _DummyThread)
qtcore_stub.pyqtSignal = getattr(qtcore_stub, 'pyqtSignal', _dummy_signal)
sys.modules['PyQt6.QtCore'] = qtcore_stub

custom_logger_stub = types.ModuleType('modules.custom_logger')


class _DummyLogger:
    def __init__(self, *args, **kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyLogger
sys.modules.setdefault('modules.custom_logger', custom_logger_stub)
from modules.export_data_thread import ExportDataThread  # noqa: E402
import modules.export_data_thread as export_data_thread_module  # noqa: E402
from modules.contracts import AppPaths, ExportOptions, ExportRequest  # noqa: E402


def _xlsx_sheet_names(xlsx_path):
    with zipfile.ZipFile(xlsx_path, 'r') as workbook_zip:
        workbook_xml = ET.fromstring(workbook_zip.read('xl/workbook.xml'))
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    return [sheet.attrib.get('name') for sheet in workbook_xml.findall('x:sheets/x:sheet', ns)]


def _xlsx_sheet_text_values(xlsx_path, target_sheet_name):
    ns_main = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    ns_rel = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}

    with zipfile.ZipFile(xlsx_path, 'r') as workbook_zip:
        workbook_xml = ET.fromstring(workbook_zip.read('xl/workbook.xml'))
        workbook_rels = ET.fromstring(workbook_zip.read('xl/_rels/workbook.xml.rels'))

        shared_strings = []
        if 'xl/sharedStrings.xml' in workbook_zip.namelist():
            sst = ET.fromstring(workbook_zip.read('xl/sharedStrings.xml'))
            for si in sst.findall('x:si', ns_main):
                text_parts = [node.text or '' for node in si.findall('.//x:t', ns_main)]
                shared_strings.append(''.join(text_parts))

        rel_map = {rel.attrib['Id']: rel.attrib['Target'] for rel in workbook_rels.findall('r:Relationship', ns_rel)}
        sheet_path = None
        for sheet in workbook_xml.findall('x:sheets/x:sheet', ns_main):
            if sheet.attrib.get('name') != target_sheet_name:
                continue
            rel_id = sheet.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            target = rel_map.get(rel_id, '')
            sheet_path = f"xl/{target}" if not target.startswith('xl/') else target
            break

        if not sheet_path:
            return []

        sheet_xml = ET.fromstring(workbook_zip.read(sheet_path))
        values = []
        for cell in sheet_xml.findall('.//x:c', ns_main):
            cell_type = cell.attrib.get('t')
            if cell_type == 's':
                idx_node = cell.find('x:v', ns_main)
                if idx_node is not None and idx_node.text and idx_node.text.isdigit():
                    idx = int(idx_node.text)
                    if 0 <= idx < len(shared_strings):
                        values.append(shared_strings[idx])
            elif cell_type == 'inlineStr':
                text_node = cell.find('x:is/x:t', ns_main)
                if text_node is not None and text_node.text is not None:
                    values.append(text_node.text)
            else:
                value_node = cell.find('x:v', ns_main)
                if value_node is not None and value_node.text is not None:
                    values.append(value_node.text)

        return values


def _xlsx_sheet_xml_details(xlsx_path, target_sheet_name):
    ns_main = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    ns_rel = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}

    with zipfile.ZipFile(xlsx_path, 'r') as workbook_zip:
        workbook_xml = ET.fromstring(workbook_zip.read('xl/workbook.xml'))
        workbook_rels = ET.fromstring(workbook_zip.read('xl/_rels/workbook.xml.rels'))
        rel_map = {rel.attrib['Id']: rel.attrib['Target'] for rel in workbook_rels.findall('r:Relationship', ns_rel)}

        sheet_path = None
        for sheet in workbook_xml.findall('x:sheets/x:sheet', ns_main):
            if sheet.attrib.get('name') == target_sheet_name:
                rel_id = sheet.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                target = rel_map.get(rel_id, '')
                sheet_path = f"xl/{target}" if not target.startswith('xl/') else target
                break

        if sheet_path is None:
            raise AssertionError(f'Missing worksheet {target_sheet_name}')

        sheet_xml = ET.fromstring(workbook_zip.read(sheet_path))
        styles_xml = ET.fromstring(workbook_zip.read('xl/styles.xml'))
        return sheet_xml, styles_xml


def _seed_grouped_measurements(db_path):
    execute_with_retry(
        db_path,
        'CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REFERENCE TEXT, FILELOC TEXT, FILENAME TEXT, DATE TEXT, SAMPLE_NUMBER TEXT)',
    )
    execute_with_retry(
        db_path,
        'CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REPORT_ID INTEGER, AX TEXT, NOM REAL, "+TOL" REAL, "-TOL" REAL, BONUS REAL, MEAS REAL, DEV REAL, OUTTOL INTEGER, HEADER TEXT)',
    )

    rows = [
        (1, 'part_1.pdf', '2024-01-01', '1', 'A', 10.10, 0.10),
        (2, 'part_2.pdf', '2024-01-02', '2', 'A', 10.12, 0.12),
        (3, 'part_3.pdf', '2024-01-03', '3', 'A', 10.08, 0.08),
        (4, 'part_4.pdf', '2024-01-04', '4', 'B', 10.42, 0.42),
        (5, 'part_5.pdf', '2024-01-05', '5', 'B', 10.39, 0.39),
        (6, 'part_6.pdf', '2024-01-06', '6', 'B', 10.41, 0.41),
    ]
    for report_id, filename, report_date, sample_number, _group, meas, dev in rows:
        execute_with_retry(
            db_path,
            'INSERT INTO REPORTS (ID, REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?, ?)',
            (report_id, 'REF-1', '/fake/reports', filename, report_date, sample_number),
        )
        execute_with_retry(
            db_path,
            'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (report_id, 'X', 10.0, 0.5, -0.5, 0.0, meas, dev, 0, 'FEATURE_1'),
        )

    return pd.DataFrame(
        [
            {
                'REFERENCE': 'REF-1',
                'FILELOC': '/fake/reports',
                'FILENAME': filename,
                'DATE': report_date,
                'SAMPLE_NUMBER': sample_number,
                'GROUP': group,
            }
            for _report_id, filename, report_date, sample_number, group, _meas, _dev in rows
        ]
    )


class TestExportDataThreadGroupAnalysis(unittest.TestCase):
    def _run_export(self, temp_dir, *, level):
        db_path = str(Path(temp_dir) / 'metroliza.sqlite')
        out_path = str(Path(temp_dir) / f'export_{level}.xlsx')
        grouping_df = _seed_grouped_measurements(db_path)

        request = ExportRequest(
            paths=AppPaths(db_file=db_path, excel_file=out_path),
            options=ExportOptions(generate_summary_sheet=False, group_analysis_level=level),
            grouping_df=grouping_df,
        )
        thread = ExportDataThread(request)
        self.assertTrue(thread.get_export_backend().run(thread))
        return out_path

    def test_off_mode_emits_no_group_analysis_sheets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = self._run_export(temp_dir, level='off')
            sheet_names = _xlsx_sheet_names(out_path)
            self.assertNotIn('Group Analysis', sheet_names)
            self.assertNotIn('Group Comparison', sheet_names)
            self.assertNotIn('Diagnostics', sheet_names)

    def test_light_mode_does_not_emit_standard_chart_insertion_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = self._run_export(temp_dir, level='light')
            sheet_names = _xlsx_sheet_names(out_path)
            self.assertIn('Group Analysis', sheet_names)
            self.assertNotIn('Group Comparison', sheet_names)
            self.assertNotIn('Diagnostics', sheet_names)

            analysis_values = _xlsx_sheet_text_values(out_path, 'Group Analysis')
            self.assertNotIn('Plots', analysis_values)
            self.assertNotIn('Shown below.', analysis_values)
            self.assertNotIn('Shown', analysis_values)

    def test_standard_mode_inserts_plots_and_diagnostics_remain_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = self._run_export(temp_dir, level='standard')

            sheet_names = _xlsx_sheet_names(out_path)
            self.assertIn('Group Analysis', sheet_names)
            self.assertNotIn('Group Comparison', sheet_names)
            self.assertNotIn('Diagnostics', sheet_names)

            analysis_values = _xlsx_sheet_text_values(out_path, 'Group Analysis')
            self.assertIn('Plots', analysis_values)
            self.assertIn('Violin', analysis_values)
            self.assertIn('Histogram', analysis_values)
            self.assertIn('Why this test', analysis_values)
            self.assertNotIn('Shown', analysis_values)
            self.assertNotIn('Shown below.', analysis_values)
            self.assertNotIn('Detail', analysis_values)
            self.assertNotIn('AD p-value estimated via KS proxy; set monte_carlo_gof_samples>0 for bootstrap.', analysis_values)
            self.assertNotIn('Plot could not be shown because the image asset is unavailable.', analysis_values)

            with zipfile.ZipFile(out_path, 'r') as workbook_zip:
                media_files = sorted(name for name in workbook_zip.namelist() if name.startswith('xl/media/'))
            self.assertGreaterEqual(len(media_files), 2)


    def test_group_analysis_diagnostics_can_be_enabled_for_internal_exports(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {'METROLIZA_EXPORT_GROUP_ANALYSIS_DIAGNOSTICS': '1'}):
            out_path = self._run_export(temp_dir, level='light')
            sheet_names = _xlsx_sheet_names(out_path)
            self.assertIn('Group Analysis', sheet_names)
            self.assertNotIn('Group Comparison', sheet_names)
            self.assertIn('Diagnostics', sheet_names)

            diagnostics_values = _xlsx_sheet_text_values(out_path, 'Diagnostics')
            self.assertIn('ran', diagnostics_values)
            self.assertIn('light', diagnostics_values)

    def test_standard_mode_group_analysis_sheet_has_layout_pass_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = self._run_export(temp_dir, level='standard')
            sheet_xml, styles_xml = _xlsx_sheet_xml_details(out_path, 'Group Analysis')
            ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

            cols = {
                int(col.attrib['min']): float(col.attrib['width'])
                for col in sheet_xml.findall('x:cols/x:col', ns)
            }
            self.assertAlmostEqual(cols[1], 20.7109375, places=3)
            self.assertAlmostEqual(cols[2], 18.7109375, places=3)
            self.assertAlmostEqual(cols[14], 30.7109375, places=3)
            self.assertAlmostEqual(cols[15], 16.7109375, places=3)

            pane = sheet_xml.find('x:sheetViews/x:sheetView/x:pane', ns)
            self.assertIsNotNone(pane)
            self.assertEqual(pane.attrib.get('ySplit'), '5')
            self.assertEqual(pane.attrib.get('topLeftCell'), 'A6')

            auto_filter = sheet_xml.find('x:autoFilter', ns)
            self.assertIsNotNone(auto_filter)
            self.assertIn(auto_filter.attrib.get('ref'), {'A15:O17', 'A20:J21'})
            self.assertGreaterEqual(len(sheet_xml.findall('x:conditionalFormatting', ns)), 1)

            wrapped_row_heights = [
                float(row.attrib['ht'])
                for row in sheet_xml.findall('x:sheetData/x:row', ns)
                if row.attrib.get('ht')
            ]
            self.assertTrue(any(height >= 22 for height in wrapped_row_heights))

            alignment_by_style = {}
            for idx, xf in enumerate(styles_xml.findall('x:cellXfs/x:xf', ns)):
                alignment = xf.find('x:alignment', ns)
                alignment_by_style[str(idx)] = alignment.attrib if alignment is not None else {}

            self.assertTrue(any(attrs.get('wrapText') == '1' for attrs in alignment_by_style.values()))
            styled_rows = [
                row
                for row in sheet_xml.findall('x:sheetData/x:row', ns)
                if row.attrib.get('customHeight') == '1'
            ]
            self.assertTrue(styled_rows)

            fills = styles_xml.findall('x:fills/x:fill', ns)
            self.assertGreaterEqual(len(fills), 6)
            solid_fill_count = sum(1 for fill in fills if fill.find('x:patternFill/x:fgColor', ns) is not None)
            self.assertGreaterEqual(solid_fill_count, 4)

            fonts = styles_xml.findall('x:fonts/x:font', ns)
            self.assertTrue(any(font.find('x:b', ns) is not None for font in fonts))

            merge_refs = {merge.attrib.get('ref') for merge in sheet_xml.findall('x:mergeCells/x:mergeCell', ns)}
            self.assertTrue(any(ref.startswith('A1:O1') for ref in merge_refs))
            self.assertTrue(any(ref.startswith('A7:O7') for ref in merge_refs))

    def test_group_analysis_violin_uses_horizontal_spec_lines_with_annotations(self):
        metric_row = {
            'metric': 'M1',
            'chart_payload': {
                'groups': [
                    {'group': 'A', 'values': [1.01, 1.02, 1.03]},
                    {'group': 'B', 'values': [1.00, 1.01, 1.02]},
                ],
                'spec_limits': {'lsl': 0.95, 'nominal': 1.00, 'usl': 1.05},
            },
        }

        fig = MagicMock()
        ax = MagicMock()
        with (
            patch.object(export_data_thread_module, '_HAS_SEABORN', False),
            patch('modules.export_data_thread.plt.subplots', return_value=(fig, ax)),
            patch('modules.export_data_thread.plt.close'),
        ):
            result = ExportDataThread._render_group_analysis_plot_asset(metric_row, 'violin')

        self.assertIn('image_data', result)
        self.assertEqual(ax.axhline.call_count, 3)
        ax.axvline.assert_not_called()
        annotation_texts = [kwargs.get('text', args[0] if args else '') for args, kwargs in ax.annotate.call_args_list]
        self.assertIn('USL=1.050', annotation_texts)
        self.assertIn('Nominal=1.000', annotation_texts)
        self.assertIn('LSL=0.950', annotation_texts)

    def test_group_analysis_histogram_keeps_vertical_spec_lines(self):
        metric_row = {
            'metric': 'M1',
            'chart_payload': {
                'groups': [
                    {'group': 'A', 'values': [1.01, 1.02, 1.03]},
                    {'group': 'B', 'values': [1.00, 1.01, 1.02]},
                ],
                'spec_limits': {'lsl': 0.95, 'nominal': 1.00, 'usl': 1.05},
            },
        }

        fig = MagicMock()
        ax = MagicMock()
        with (
            patch('modules.export_data_thread.plt.subplots', return_value=(fig, ax)),
            patch('modules.export_data_thread.plt.close'),
        ):
            result = ExportDataThread._render_group_analysis_plot_asset(metric_row, 'histogram')

        self.assertIn('image_data', result)
        self.assertEqual(ax.axvline.call_count, 3)
        ax.axhline.assert_not_called()


if __name__ == '__main__':
    unittest.main()
