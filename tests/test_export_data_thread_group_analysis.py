import os
import re
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
from modules.export_html_dashboard import resolve_html_dashboard_path  # noqa: E402
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


def _xlsx_sheet_relationships(xlsx_path, target_sheet_name):
    ns_main = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    ns_rel = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}

    with zipfile.ZipFile(xlsx_path, 'r') as workbook_zip:
        workbook_xml = ET.fromstring(workbook_zip.read('xl/workbook.xml'))
        workbook_rels = ET.fromstring(workbook_zip.read('xl/_rels/workbook.xml.rels'))
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
            return ''

        sheet_rel_name = sheet_path.rsplit('/', 1)[-1] + '.rels'
        sheet_rel_path = f"xl/worksheets/_rels/{sheet_rel_name}"
        if sheet_rel_path not in workbook_zip.namelist():
            return ''
        return workbook_zip.read(sheet_rel_path).decode('utf-8', errors='replace')


def _sheet_cell_text_map(sheet_xml, xlsx_path):
    ns_main = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    text_map = {}
    with zipfile.ZipFile(xlsx_path, 'r') as workbook_zip:
        shared_strings = []
        if 'xl/sharedStrings.xml' in workbook_zip.namelist():
            sst = ET.fromstring(workbook_zip.read('xl/sharedStrings.xml'))
            for si in sst.findall('x:si', ns_main):
                text_parts = [node.text or '' for node in si.findall('.//x:t', ns_main)]
                shared_strings.append(''.join(text_parts))
        for cell in sheet_xml.findall('x:sheetData/x:row/x:c', ns_main):
            ref = cell.attrib.get('r')
            cell_type = cell.attrib.get('t')
            value = None
            if cell_type == 's':
                idx_node = cell.find('x:v', ns_main)
                if idx_node is not None and idx_node.text and idx_node.text.isdigit():
                    idx = int(idx_node.text)
                    if 0 <= idx < len(shared_strings):
                        value = shared_strings[idx]
            elif cell_type == 'inlineStr':
                text_node = cell.find('x:is/x:t', ns_main)
                if text_node is not None:
                    value = text_node.text or ''
            else:
                value_node = cell.find('x:v', ns_main)
                if value_node is not None:
                    value = value_node.text
            if ref and value is not None:
                text_map[ref] = value
    return text_map


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


def _xlsx_sheet_hyperlinks(xlsx_path, target_sheet_name):
    ns_main = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    sheet_xml, _styles_xml = _xlsx_sheet_xml_details(xlsx_path, target_sheet_name)
    return [link.attrib for link in sheet_xml.findall('x:hyperlinks/x:hyperlink', ns_main)]


def _xlsx_sheet_formulas(xlsx_path, target_sheet_name):
    ns_main = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    sheet_xml, _styles_xml = _xlsx_sheet_xml_details(xlsx_path, target_sheet_name)
    formulas = {}
    for cell in sheet_xml.findall('x:sheetData/x:row/x:c', ns_main):
        formula = cell.find('x:f', ns_main)
        if formula is not None and formula.text is not None:
            formulas[cell.attrib.get('r')] = formula.text
    return formulas


def _xlsx_sheet_drawing_cnvpr_attrs(xlsx_path, target_sheet_name):
    ns_main = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    ns_rel = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
    ns_draw = {'xdr': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'}

    with zipfile.ZipFile(xlsx_path, 'r') as workbook_zip:
        workbook_xml = ET.fromstring(workbook_zip.read('xl/workbook.xml'))
        workbook_rels = ET.fromstring(workbook_zip.read('xl/_rels/workbook.xml.rels'))
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

        sheet_rel_name = sheet_path.rsplit('/', 1)[-1] + '.rels'
        sheet_rel_path = f"xl/worksheets/_rels/{sheet_rel_name}"
        if sheet_rel_path not in workbook_zip.namelist():
            return []

        sheet_rels = ET.fromstring(workbook_zip.read(sheet_rel_path))
        drawing_target = None
        for rel in sheet_rels.findall('r:Relationship', ns_rel):
            rel_type = rel.attrib.get('Type', '')
            if rel_type.endswith('/drawing'):
                drawing_target = rel.attrib.get('Target', '')
                break
        if not drawing_target:
            return []

        drawing_path = drawing_target
        if drawing_path.startswith('../'):
            drawing_path = f"xl/{drawing_path[3:]}"
        elif not drawing_path.startswith('xl/'):
            drawing_path = f"xl/worksheets/{drawing_path}"
        drawing_path = drawing_path.replace('xl/worksheets/drawings/', 'xl/drawings/')
        drawing_xml = ET.fromstring(workbook_zip.read(drawing_path))
        return [dict(node.attrib) for node in drawing_xml.findall('.//xdr:cNvPr', ns_draw)]


def _style_maps(styles_xml):
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    style_to_alignment = {}
    style_to_border = {}
    style_to_fill = {}
    cell_xfs = styles_xml.findall('x:cellXfs/x:xf', ns)
    for idx, xf in enumerate(cell_xfs):
        alignment = xf.find('x:alignment', ns)
        style_to_alignment[str(idx)] = alignment.attrib if alignment is not None else {}
        style_to_border[str(idx)] = xf.attrib.get('borderId', '0')
        style_to_fill[str(idx)] = xf.attrib.get('fillId', '0')
    return style_to_alignment, style_to_border, style_to_fill


def _column_width_for(cols, target_idx):
    for min_idx, max_idx, width in cols:
        if min_idx <= target_idx <= max_idx:
            return width
    raise KeyError(target_idx)


def _row_heights(sheet_xml):
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    return {
        int(row.attrib['r']): float(row.attrib['ht'])
        for row in sheet_xml.findall('x:sheetData/x:row', ns)
        if row.attrib.get('ht')
    }


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

    def test_light_mode_exports_group_analysis_only_without_default_debug_sheets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = self._run_export(temp_dir, level='light')
            sheet_names = _xlsx_sheet_names(out_path)
            self.assertIn('Group Analysis', sheet_names)
            self.assertNotIn('Group Comparison', sheet_names)
            self.assertNotIn('Diagnostics', sheet_names)

            analysis_values = _xlsx_sheet_text_values(out_path, 'Group Analysis')
            self.assertIn('Group Analysis', analysis_values)
            self.assertIn('Metric index', analysis_values)
            self.assertIn('Descriptive stats', analysis_values)
            self.assertIn('Pairwise comparisons', analysis_values)
            self.assertTrue(any(isinstance(value, str) and 'Shape note: no clear distribution-shape difference after correction.' in value for value in analysis_values))
            self.assertNotIn('Plots', analysis_values)
            self.assertNotIn('Shown below.', analysis_values)
            self.assertNotIn('Shown', analysis_values)

    def test_standard_mode_exports_group_analysis_only_with_plots_and_no_default_debug_sheets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = self._run_export(temp_dir, level='standard')

            sheet_names = _xlsx_sheet_names(out_path)
            self.assertIn('Group Analysis', sheet_names)
            self.assertIn('Group Analysis Plots', sheet_names)
            self.assertNotIn('Group Comparison', sheet_names)
            self.assertNotIn('Diagnostics', sheet_names)

            analysis_values = _xlsx_sheet_text_values(out_path, 'Group Analysis')
            plot_values = _xlsx_sheet_text_values(out_path, 'Group Analysis Plots')
            self.assertIn('Metric index', analysis_values)
            self.assertNotIn('Plots', analysis_values)
            self.assertNotIn('Violin', analysis_values)
            self.assertNotIn('Histogram', analysis_values)
            self.assertIn('Group Analysis Plots', plot_values)
            self.assertIn('Plots', plot_values)
            self.assertIn('Violin', plot_values)
            self.assertIn('Histogram', plot_values)
            self.assertIn('Test / why', analysis_values)
            self.assertTrue(any(isinstance(value, str) and 'Why:' in value for value in analysis_values))
            self.assertNotIn('Shown', analysis_values)
            self.assertNotIn('Shown below.', analysis_values)
            self.assertNotIn('Detail', analysis_values)
            self.assertNotIn('AD p-value estimated via KS proxy; set monte_carlo_gof_samples>0 for bootstrap.', analysis_values)
            self.assertNotIn('Plot could not be shown because the image asset is unavailable.', analysis_values)

            with zipfile.ZipFile(out_path, 'r') as workbook_zip:
                media_files = sorted(name for name in workbook_zip.namelist() if name.startswith('xl/media/'))
            self.assertGreaterEqual(len(media_files), 2)


    def test_group_analysis_internal_diagnostics_can_be_enabled_only_by_internal_debug_policy(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {'METROLIZA_EXPORT_GROUP_ANALYSIS_DIAGNOSTICS': '1'}):
            out_path = self._run_export(temp_dir, level='light')
            sheet_names = _xlsx_sheet_names(out_path)
            self.assertIn('Group Analysis', sheet_names)
            self.assertIn('Diagnostics', sheet_names)
            self.assertNotIn('Group Comparison', sheet_names)

            diagnostics_values = _xlsx_sheet_text_values(out_path, 'Diagnostics')
            self.assertIn('ran', diagnostics_values)
            self.assertIn('light', diagnostics_values)

    def test_standard_mode_group_analysis_sheet_has_persisted_layout_and_content_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = self._run_export(temp_dir, level='standard')
            analysis_values = _xlsx_sheet_text_values(out_path, 'Group Analysis')
            plot_values = _xlsx_sheet_text_values(out_path, 'Group Analysis Plots')
            sheet_xml, styles_xml = _xlsx_sheet_xml_details(out_path, 'Group Analysis')
            plots_sheet_xml, _plots_styles_xml = _xlsx_sheet_xml_details(out_path, 'Group Analysis Plots')
            ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

            self.assertIn('Group Analysis', analysis_values)
            self.assertIn('Status', analysis_values)
            self.assertTrue(any(isinstance(value, str) and 'Standard | Single Reference' in value for value in analysis_values))
            self.assertTrue(any(isinstance(value, str) and '2 groups across 1 reference' in value for value in analysis_values))
            self.assertTrue(any(isinstance(value, str) and value.startswith('DIFFERENCE\n1 metric') for value in analysis_values))
            self.assertTrue(any(isinstance(value, str) and 'Top:' in value for value in analysis_values))
            self.assertTrue(any(isinstance(value, str) and 'adj p=' in value for value in analysis_values))
            self.assertIn('Open Markdown manual', analysis_values)
            self.assertIn('Open PDF manual', analysis_values)
            self.assertIn('Metric index', analysis_values)
            self.assertIn('Priority signal', analysis_values)
            self.assertIn('Stat signal', analysis_values)
            self.assertIn('Next step', analysis_values)
            self.assertIn('Capability summary', analysis_values)
            self.assertIn('Key insights', analysis_values)
            self.assertIn('Descriptive stats', analysis_values)
            self.assertIn('Distribution / capability note', analysis_values)
            self.assertTrue(any(isinstance(value, str) and '95% CI' in value for value in analysis_values))
            self.assertIn('Pairwise comparisons', analysis_values)
            self.assertTrue(any(isinstance(value, str) and 'Shape note:' in value for value in analysis_values))
            self.assertIn('Recommended action', analysis_values)
            self.assertIn('Takeaway', analysis_values)
            self.assertIn('Action', analysis_values)
            self.assertIn('Test / why', analysis_values)
            self.assertTrue(any(isinstance(value, str) and 'Caution:' in value for value in analysis_values))
            self.assertTrue(any(isinstance(value, str) and 'Why:' in value for value in analysis_values))
            self.assertTrue(any(isinstance(value, str) and 'Shape note: no clear distribution-shape difference after correction.' in value for value in analysis_values))
            self.assertNotIn('Plots', analysis_values)
            self.assertNotIn('Violin', analysis_values)
            self.assertNotIn('Histogram', analysis_values)
            self.assertIn('Go to metric', analysis_values)
            self.assertIn('DIFFERENCE', analysis_values)
            self.assertIn('Group Analysis Plots', plot_values)
            self.assertIn('Plots', plot_values)
            self.assertIn('Violin', plot_values)
            self.assertIn('Histogram', plot_values)

            cols = [
                (int(col.attrib['min']), int(col.attrib['max']), float(col.attrib['width']))
                for col in sheet_xml.findall('x:cols/x:col', ns)
            ]
            self.assertAlmostEqual(_column_width_for(cols, 1), 20.7109375, places=3)
            self.assertAlmostEqual(_column_width_for(cols, 2), 12.7109375, places=3)
            self.assertAlmostEqual(_column_width_for(cols, 11), 16.7109375, places=3)
            self.assertAlmostEqual(_column_width_for(cols, 12), 18.7109375, places=3)
            self.assertAlmostEqual(_column_width_for(cols, 15), 18.7109375, places=3)

            pane = sheet_xml.find('x:sheetViews/x:sheetView/x:pane', ns)
            self.assertIsNone(pane)
            self.assertGreaterEqual(len(sheet_xml.findall('x:conditionalFormatting', ns)), 1)

            row_heights = _row_heights(sheet_xml)
            self.assertGreaterEqual(row_heights.get(1, 0), 28)
            self.assertTrue(any(height >= 22 for height in row_heights.values()))
            self.assertTrue(any(height >= 30 for height in row_heights.values()))

            alignment_by_style, border_by_style, fill_by_style = _style_maps(styles_xml)

            self.assertTrue(any(attrs.get('wrapText') == '1' for attrs in alignment_by_style.values()))
            self.assertTrue(any(attrs.get('vertical') == 'top' for attrs in alignment_by_style.values()))
            self.assertTrue(any(border_id != '0' for border_id in border_by_style.values()))
            self.assertTrue(any(border_id == '0' for border_id in border_by_style.values()))
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
            self.assertIn('A1:O1', merge_refs)
            self.assertIn('A2:C2', merge_refs)
            self.assertIn('D2:F2', merge_refs)
            self.assertIn('G2:H2', merge_refs)
            self.assertIn('I2:J2', merge_refs)
            self.assertIn('K2:L2', merge_refs)
            self.assertIn('M2:O2', merge_refs)
            self.assertIn('A3:C3', merge_refs)
            self.assertIn('D3:L3', merge_refs)
            self.assertIn('A4:I4', merge_refs)
            self.assertIn('E5:I5', merge_refs)
            self.assertIn('J5:O5', merge_refs)

            drawing = sheet_xml.find('x:drawing', ns)
            self.assertIsNone(drawing)
            plots_drawing = plots_sheet_xml.find('x:drawing', ns)
            self.assertIsNotNone(plots_drawing)
            analysis_page_setup = sheet_xml.find('x:pageSetup', ns)
            plots_page_setup = plots_sheet_xml.find('x:pageSetup', ns)
            self.assertIsNotNone(analysis_page_setup)
            self.assertIsNotNone(plots_page_setup)
            self.assertEqual(analysis_page_setup.attrib.get('orientation'), 'landscape')
            self.assertEqual(plots_page_setup.attrib.get('orientation'), 'landscape')
            drawing_cnvpr_attrs = _xlsx_sheet_drawing_cnvpr_attrs(out_path, 'Group Analysis Plots')
            described_pictures = [attrs for attrs in drawing_cnvpr_attrs if attrs.get('name', '').startswith('Picture')]
            self.assertGreaterEqual(len(described_pictures), 2)
            self.assertTrue(all(attrs.get('descr') for attrs in described_pictures))
            analysis_hyperlinks = _xlsx_sheet_hyperlinks(out_path, 'Group Analysis')
            plots_hyperlinks = _xlsx_sheet_hyperlinks(out_path, 'Group Analysis Plots')
            self.assertTrue(any(link.get('display') == 'Open plots sheet' for link in analysis_hyperlinks))
            self.assertTrue(any(link.get('display') == 'Back to Group Analysis' for link in plots_hyperlinks))

            formulas = _xlsx_sheet_formulas(out_path, 'Group Analysis')
            self.assertTrue(any(ref.startswith('C') and 'HYPERLINK(' in formula for ref, formula in formulas.items()))
            cell_text_map = _sheet_cell_text_map(sheet_xml, out_path)
            metric_title_targets = [
                int(match.group(1))
                for row_ref, formula in formulas.items()
                if row_ref.startswith('C')
                for match in [re.search(r"#'Group Analysis'!A(\d+)", formula)]
                if match
            ]
            metric_title_rows = {
                ref
                for ref, value in cell_text_map.items()
                if isinstance(value, str) and value.startswith('Metric: FEATURE_1')
            }
            self.assertTrue(metric_title_rows)
            self.assertTrue(any(f'D{target_row}' in metric_title_rows for target_row in metric_title_targets))
            outline_rows = [
                row.attrib
                for row in sheet_xml.findall('x:sheetData/x:row', ns)
                if row.attrib.get('outlineLevel') == '1'
            ]
            self.assertTrue(outline_rows)

            styled_cells = sheet_xml.findall('x:sheetData/x:row/x:c', ns)
            wrap_styles = {
                cell.attrib.get('r'): alignment_by_style.get(cell.attrib.get('s', '0'), {})
                for cell in styled_cells
            }
            self.assertEqual(wrap_styles.get('A1', {}).get('wrapText'), None)
            self.assertTrue(any(ref.startswith('H') and attrs.get('wrapText') == '1' for ref, attrs in wrap_styles.items()))
            self.assertTrue(any(ref.startswith('I') and attrs.get('wrapText') == '1' for ref, attrs in wrap_styles.items()))
            self.assertTrue(any(ref.startswith('J') and attrs.get('wrapText') == '1' for ref, attrs in wrap_styles.items()))
            self.assertTrue(any(ref.startswith('L') and attrs.get('wrapText') == '1' for ref, attrs in wrap_styles.items()))

            jump_header_row = next(int(ref[1:]) for ref, value in cell_text_map.items() if value == 'Jump')
            self.assertGreaterEqual(row_heights.get(jump_header_row, 0), 24)

            feature_metric_row = next(
                int(ref[1:])
                for ref, value in cell_text_map.items()
                if isinstance(value, str) and value.startswith('Metric: FEATURE_1')
            )
            linked_targets = [
                int(match.group(1))
                for formula in formulas.values()
                for match in [re.search(r"#'Group Analysis'!A(\d+)", formula)]
                if match
            ]
            self.assertIn(feature_metric_row, linked_targets)

            descriptive_wrapped_rows = [
                int(ref[1:])
                for ref, attrs in wrap_styles.items()
                if ref.startswith(('J', 'K', 'L', 'M', 'N', 'O')) and attrs.get('wrapText') == '1'
            ]
            self.assertTrue(descriptive_wrapped_rows)
            self.assertTrue(any(row_heights.get(row, 0) > 22 for row in descriptive_wrapped_rows))

            pairwise_wrapped_rows = [
                int(ref[1:])
                for ref, attrs in wrap_styles.items()
                if ref.startswith(('E', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O')) and attrs.get('wrapText') == '1'
            ]
            self.assertTrue(pairwise_wrapped_rows)
            self.assertTrue(any(row_heights.get(row, 0) > 22 for row in pairwise_wrapped_rows))

    def test_group_analysis_violin_uses_horizontal_spec_lines_with_annotations(self):
        metric_row = {
            'metric': 'M1',
            'capability_allowed': True,
            'capability': {
                'cp': 1.10,
                'cpk': 1.00,
                'capability': 1.00,
                'capability_type': 'Cpk',
                'capability_ci': {'cp': {'lower': 0.9, 'upper': 1.3}, 'cpk': {'lower': 0.75, 'upper': 1.2}},
                'status': 'ok',
            },
            'chart_payload': {
                'groups': [
                    {'group': 'A', 'values': [1.01, 1.02, 1.03]},
                    {'group': 'B', 'values': [1.00, 1.01, 1.02]},
                ],
                'spec_limits': {'lsl': 0.95, 'nominal': 1.00, 'usl': 1.05},
            },
        }

        captured_axes = []
        original_subplots = export_data_thread_module.plt.subplots

        def _capture_subplots(*args, **kwargs):
            fig, ax = original_subplots(*args, **kwargs)
            captured_axes.append(ax)
            return fig, ax

        with (
            patch.object(export_data_thread_module, '_HAS_SEABORN', False),
            patch('modules.export_data_thread.plt.subplots', side_effect=_capture_subplots),
        ):
            result = ExportDataThread._render_group_analysis_plot_asset(metric_row, 'violin')

        self.assertIn('image_data', result)
        self.assertIn('description', result)
        self.assertIn('A n=3, mean=1.020', result['description'])
        self.assertIn('Capability summary: marginal. Cp=1.100, Cpk=1.000.', result['description'])
        self.assertEqual(len(captured_axes), 1)
        ax = captured_axes[0]
        horizontal_levels = {
            round(float(line.get_ydata()[0]), 3)
            for line in ax.lines
            if len(line.get_ydata()) >= 2 and abs(float(line.get_ydata()[0]) - float(line.get_ydata()[-1])) < 1e-9
        }
        self.assertTrue({0.95, 1.0, 1.05}.issubset(horizontal_levels))
        annotation_texts = [text.get_text() for text in ax.texts]
        self.assertIn('USL=1.050', annotation_texts)
        self.assertIn('Nominal=1.000', annotation_texts)
        self.assertIn('LSL=0.950', annotation_texts)
        self.assertTrue(any(str(text).startswith('μ=') for text in annotation_texts))
        self.assertTrue(any('Capability: Marginal' in str(text) for text in annotation_texts))
        self.assertTrue(any('95% CI 0.750 to 1.200' in str(text) for text in annotation_texts))

    def test_group_analysis_histogram_keeps_vertical_spec_lines(self):
        metric_row = {
            'metric': 'M1',
            'capability_allowed': True,
            'capability': {
                'cp': 1.10,
                'cpk': 1.00,
                'capability': 1.00,
                'capability_type': 'Cpk',
                'capability_ci': {'cp': {'lower': 0.9, 'upper': 1.3}, 'cpk': {'lower': 0.75, 'upper': 1.2}},
                'status': 'ok',
            },
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
        self.assertIn('description', result)
        self.assertIn('Capability summary: marginal. Cp=1.100, Cpk=1.000.', result['description'])
        self.assertEqual(ax.axvline.call_count, 5)
        ax.axhline.assert_not_called()
        histogram_labels = [kwargs.get('label') for _args, kwargs in ax.hist.call_args_list]
        self.assertEqual(histogram_labels, ['A (n=3, μ=1.020)', 'B (n=3, μ=1.010)'])
        histogram_note_texts = [args[2] for args, _kwargs in ax.text.call_args_list if len(args) >= 3]
        self.assertTrue(any('Capability: Marginal' in str(text) for text in histogram_note_texts))
        self.assertTrue(any('95% CI 0.750 to 1.200' in str(text) for text in histogram_note_texts))

    def test_standard_mode_html_dashboard_includes_group_analysis_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / 'metroliza.sqlite')
            out_path = str(Path(temp_dir) / 'export_standard.xlsx')
            grouping_df = _seed_grouped_measurements(db_path)

            request = ExportRequest(
                paths=AppPaths(db_file=db_path, excel_file=out_path),
                options=ExportOptions(
                    generate_summary_sheet=False,
                    generate_html_dashboard=True,
                    group_analysis_level='standard',
                ),
                grouping_df=grouping_df,
            )
            thread = ExportDataThread(request)
            thread.run()

            html_path = resolve_html_dashboard_path(out_path)
            self.assertTrue(Path(html_path).exists())
            html_text = Path(html_path).read_text(encoding='utf-8')

            self.assertIn('Group Analysis', html_text)
            self.assertIn('FEATURE_1', html_text)
            self.assertIn('Descriptive stats', html_text)
            self.assertIn('Pairwise comparisons', html_text)
            self.assertNotIn('No extended summary charts were generated.', html_text)


if __name__ == '__main__':
    unittest.main()
