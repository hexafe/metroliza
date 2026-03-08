import sys
import tempfile
import types
import unittest
import zipfile
import xml.etree.ElementTree as ET

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

custom_logger_stub = types.ModuleType('modules.CustomLogger')


class _DummyLogger:
    def __init__(self, *args, **kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyLogger
sys.modules.setdefault('modules.CustomLogger', custom_logger_stub)
from modules.ExportDataThread import ExportDataThread  # noqa: E402
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
            self.assertNotIn('Diagnostics', sheet_names)

    def test_light_mode_does_not_emit_standard_chart_insertion_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = self._run_export(temp_dir, level='light')
            sheet_names = _xlsx_sheet_names(out_path)
            self.assertIn('Group Analysis', sheet_names)
            self.assertIn('Diagnostics', sheet_names)

            analysis_values = _xlsx_sheet_text_values(out_path, 'Group Analysis')
            self.assertNotIn('Standard plot slots', analysis_values)
            self.assertNotIn('Chart inserted', analysis_values)
            self.assertNotIn('INSERTED', analysis_values)

    def test_standard_mode_inserts_plots_and_diagnostics_remain_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = self._run_export(temp_dir, level='standard')

            analysis_values = _xlsx_sheet_text_values(out_path, 'Group Analysis')
            self.assertIn('Standard plot slots', analysis_values)
            self.assertIn('INSERTED', analysis_values)
            self.assertIn('Chart inserted', analysis_values)
            self.assertNotIn('asset_missing', analysis_values)

            diagnostics_values = _xlsx_sheet_text_values(out_path, 'Diagnostics')
            self.assertIn('ran', diagnostics_values)
            self.assertIn('standard', diagnostics_values)
            self.assertIn('EXACT_MATCH', diagnostics_values)
            self.assertIn('1', diagnostics_values)
            self.assertIn('0', diagnostics_values)

            with zipfile.ZipFile(out_path, 'r') as workbook_zip:
                media_files = sorted(name for name in workbook_zip.namelist() if name.startswith('xl/media/'))
            self.assertGreaterEqual(len(media_files), 2)


if __name__ == '__main__':
    unittest.main()
