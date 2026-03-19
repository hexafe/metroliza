import importlib.util
import sys
import tempfile
import types
import unittest
import zipfile
import xml.etree.ElementTree as ET

import posixpath

from pathlib import Path, PurePosixPath
from unittest.mock import patch

from modules.contracts import AppPaths, ExportOptions, ExportRequest  # noqa: E402
from modules.db import execute_with_retry  # noqa: E402


NS_MAIN = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
NS_PACKAGE = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
NS_DRAWING = {'xdr': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'}


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


class _DummyLogger:
    def __init__(self, *args, **kwargs):
        pass


def _load_export_thread_type():
    qtcore_stub = types.ModuleType('PyQt6.QtCore')
    qtcore_stub.QCoreApplication = _DummyCoreApp
    qtcore_stub.QThread = _DummyThread
    qtcore_stub.pyqtSignal = _dummy_signal

    custom_logger_stub = types.ModuleType('modules.custom_logger')
    custom_logger_stub.CustomLogger = _DummyLogger

    module_name = '_test_export_data_thread_workbook_output'
    module_path = Path(__file__).resolve().parents[1] / 'modules' / 'export_data_thread.py'

    with patch.dict(
        sys.modules,
        {
            'PyQt6.QtCore': qtcore_stub,
            'modules.custom_logger': custom_logger_stub,
        },
    ):
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        export_module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = export_module
        try:
            spec.loader.exec_module(export_module)
        finally:
            sys.modules.pop(module_name, None)

    return export_module.ExportDataThread


def _target_to_xl_path(target):
    return f"xl/{target}" if not target.startswith('xl/') else target


def _normalize_package_path(base_path, target):
    return posixpath.normpath(str(PurePosixPath(PurePosixPath(base_path).parent, target)))


def _load_package_xml(workbook_zip, xml_path):
    return ET.fromstring(workbook_zip.read(xml_path))


def _resolve_sheet_parts(workbook_zip, target_sheet_name):
    workbook_xml = _load_package_xml(workbook_zip, 'xl/workbook.xml')
    workbook_rels = _load_package_xml(workbook_zip, 'xl/_rels/workbook.xml.rels')
    rel_map = {rel.attrib['Id']: rel.attrib['Target'] for rel in workbook_rels.findall('r:Relationship', NS_PACKAGE)}

    for sheet in workbook_xml.findall('x:sheets/x:sheet', NS_MAIN):
        if sheet.attrib.get('name') != target_sheet_name:
            continue
        rel_id = sheet.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        sheet_path = _target_to_xl_path(rel_map[rel_id])
        return workbook_xml, sheet_path

    raise AssertionError(f"Worksheet '{target_sheet_name}' not found in workbook package.")


class TestExportWorkbookOutput(unittest.TestCase):
    def test_measurement_workbook_package_preserves_conditional_formatting_and_chart_anchor_layout(self):
        ExportDataThread = _load_export_thread_type()

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / 'metroliza.sqlite')
            out_path = str(Path(temp_dir) / 'export.xlsx')

            execute_with_retry(
                db_path,
                'CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REFERENCE TEXT, FILELOC TEXT, FILENAME TEXT, DATE TEXT, SAMPLE_NUMBER TEXT)',
            )
            execute_with_retry(
                db_path,
                'CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REPORT_ID INTEGER, AX TEXT, NOM REAL, "+TOL" REAL, "-TOL" REAL, BONUS REAL, MEAS REAL, DEV REAL, OUTTOL INTEGER, HEADER TEXT)',
            )

            rows = [
                (1, 'REF-1', 'part_1.pdf', '2024-01-01', '1', 'X', 10.0, 0.5, -0.5, 0.0, 10.1, 0.1, 0, 'FEATURE_1'),
                (2, 'REF-1', 'part_2.pdf', '2024-01-02', '2', 'X', 10.0, 0.5, -0.5, 0.0, 10.7, 0.7, 1, 'FEATURE_1'),
                (3, 'REF-1', 'part_3.pdf', '2024-01-03', '3', 'X', 10.0, 0.5, -0.5, 0.0, 9.2, -0.8, 1, 'FEATURE_1'),
            ]
            for report_id, reference, filename, report_date, sample_number, ax, nom, plus_tol, minus_tol, bonus, meas, dev, outtol, header in rows:
                execute_with_retry(
                    db_path,
                    'INSERT INTO REPORTS (ID, REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?, ?)',
                    (report_id, reference, '/fake/reports', filename, report_date, sample_number),
                )
                execute_with_retry(
                    db_path,
                    'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (report_id, ax, nom, plus_tol, minus_tol, bonus, meas, dev, outtol, header),
                )

            request = ExportRequest(
                paths=AppPaths(db_file=db_path, excel_file=out_path),
                options=ExportOptions(generate_summary_sheet=False),
            )
            thread = ExportDataThread(request)

            self.assertTrue(thread.get_export_backend().run(thread))
            self.assertTrue(Path(out_path).exists())

            with zipfile.ZipFile(out_path, 'r') as workbook_zip:
                workbook_xml, sheet_path = _resolve_sheet_parts(workbook_zip, 'REF-1')
                workbook_sheet_names = [sheet.attrib.get('name') for sheet in workbook_xml.findall('x:sheets/x:sheet', NS_MAIN)]
                self.assertEqual(workbook_sheet_names[:2], ['REF-1', 'MEASUREMENTS'])

                worksheet_root = _load_package_xml(workbook_zip, sheet_path)
                cf_nodes = worksheet_root.findall('x:conditionalFormatting', NS_MAIN)
                cf_rules = [rule for node in cf_nodes for rule in node.findall('x:cfRule', NS_MAIN)]
                self.assertGreaterEqual(len(cf_rules), 3)

                sqrefs = [node.attrib.get('sqref', '') for node in cf_nodes]
                self.assertIn('C22:C24', sqrefs)
                self.assertIn('B7', sqrefs)

                formulas_by_sqref = {
                    node.attrib.get('sqref', ''): [
                        formula.text or ''
                        for rule in node.findall('x:cfRule', NS_MAIN)
                        for formula in rule.findall('x:formula', NS_MAIN)
                    ]
                    for node in cf_nodes
                }
                measurement_formulas = formulas_by_sqref.get('C22:C24', [])
                self.assertGreaterEqual(len(measurement_formulas), 2)
                self.assertTrue(any('$B$1+$B$2' in formula for formula in measurement_formulas))
                self.assertTrue(any('$B$1+$B$3' in formula for formula in measurement_formulas))
                self.assertIn('0', formulas_by_sqref.get('B7', []))

                sheet_rels_path = f"xl/worksheets/_rels/{Path(sheet_path).name}.rels"
                worksheet_rels = _load_package_xml(workbook_zip, sheet_rels_path)
                drawing_target = next(
                    rel.attrib['Target']
                    for rel in worksheet_rels.findall('r:Relationship', NS_PACKAGE)
                    if rel.attrib['Type'].endswith('/drawing')
                )
                drawing_path = _normalize_package_path(sheet_path, drawing_target)
                drawing_root = _load_package_xml(workbook_zip, drawing_path)

                anchor_from = drawing_root.find('xdr:twoCellAnchor/xdr:from', NS_DRAWING)
                self.assertIsNotNone(anchor_from)
                self.assertEqual(anchor_from.find('xdr:row', NS_DRAWING).text, '7')
                self.assertEqual(anchor_from.find('xdr:col', NS_DRAWING).text, '0')

                col_off = anchor_from.find('xdr:colOff', NS_DRAWING)
                row_off = anchor_from.find('xdr:rowOff', NS_DRAWING)
                self.assertIn(None if col_off is None else col_off.text, {None, '57150'})
                self.assertIn(None if row_off is None else row_off.text, {None, '19050'})

                drawing_rels_path = _normalize_package_path(drawing_path, f"_rels/{Path(drawing_path).name}.rels")
                drawing_rels = _load_package_xml(workbook_zip, drawing_rels_path)
                chart_target = next(
                    rel.attrib['Target']
                    for rel in drawing_rels.findall('r:Relationship', NS_PACKAGE)
                    if rel.attrib['Type'].endswith('/chart')
                )
                chart_path = _normalize_package_path(drawing_path, chart_target)
                chart_xml = workbook_zip.read(chart_path).decode('utf-8')

                self.assertIn('REF-1!$B22:B24', chart_xml)
                self.assertIn('REF-1!$C22:C24', chart_xml)
                self.assertIn('REF-1!$D22:D24', chart_xml)
                self.assertIn('REF-1!$E22:E24', chart_xml)
                self.assertNotIn('REF-1!$XFB1:XFB2', chart_xml)


if __name__ == '__main__':
    unittest.main()
