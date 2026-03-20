import os
import sys
import tempfile
import types
import unittest
import zipfile
import xml.etree.ElementTree as ET
from unittest.mock import patch

import pandas as pd

from pathlib import Path

from modules.db import execute_with_retry  # noqa: E402


# Stubs for optional GUI/parser dependencies pulled in by thread modules.
qtcore_stub = types.ModuleType('PyQt6.QtCore')


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


qtcore_stub.QCoreApplication = _DummyCoreApp
qtcore_stub.QThread = _DummyThread
qtcore_stub.pyqtSignal = _dummy_signal
sys.modules['PyQt6.QtCore'] = qtcore_stub

custom_logger_stub = types.ModuleType('modules.custom_logger')


class _DummyLogger:
    def __init__(self, *args, **kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyLogger
sys.modules['modules.custom_logger'] = custom_logger_stub

cmm_parser_stub = types.ModuleType('modules.cmm_report_parser')
cmm_parser_stub.CMMReportParser = object
sys.modules['modules.cmm_report_parser'] = cmm_parser_stub

from modules.export_data_thread import ExportDataThread, build_export_dataframe, execute_export_query  # noqa: E402
from modules.contracts import AppPaths, ExportOptions, ExportRequest  # noqa: E402
from modules.parse_reports_thread import parse_new_reports  # noqa: E402


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


def _xlsx_sheet_xml(xlsx_path, target_sheet_name):
    ns_main = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    ns_rel = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}

    with zipfile.ZipFile(xlsx_path, 'r') as workbook_zip:
        workbook_xml = ET.fromstring(workbook_zip.read('xl/workbook.xml'))
        workbook_rels = ET.fromstring(workbook_zip.read('xl/_rels/workbook.xml.rels'))
        rel_map = {rel.attrib['Id']: rel.attrib['Target'] for rel in workbook_rels.findall('r:Relationship', ns_rel)}

        for sheet in workbook_xml.findall('x:sheets/x:sheet', ns_main):
            if sheet.attrib.get('name') != target_sheet_name:
                continue
            rel_id = sheet.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            target = rel_map.get(rel_id, '')
            sheet_path = f"xl/{target}" if not target.startswith('xl/') else target
            return workbook_zip.read(sheet_path).decode('utf-8')

    raise AssertionError(f"Worksheet '{target_sheet_name}' not found in workbook: {xlsx_path}")



class _FakeParser:
    def __init__(self, report_name: str):
        self.FILE_PATH = report_name
        self.pdf_reference = 'REF-1'
        self.pdf_file_path = '/fake/reports'
        self.pdf_file_name = report_name
        self.pdf_date = '2024-01-01'
        self.pdf_sample_number = report_name.split('.')[0].split('_')[-1]


class TestPhase4ParseToExportHappyPath(unittest.TestCase):
    def test_parse_to_db_to_export_happy_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / 'metroliza.sqlite')
            execute_with_retry(
                db_path,
                'CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REFERENCE TEXT, FILELOC TEXT, FILENAME TEXT, DATE TEXT, SAMPLE_NUMBER TEXT)',
            )
            execute_with_retry(
                db_path,
                'CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REPORT_ID INTEGER, AX TEXT, NOM REAL, "+TOL" REAL, "-TOL" REAL, BONUS REAL, MEAS REAL, DEV REAL, OUTTOL INTEGER, HEADER TEXT)',
            )

            def persist_report(parser):
                execute_with_retry(
                    db_path,
                    'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                    (
                        parser.pdf_reference,
                        parser.pdf_file_path,
                        parser.pdf_file_name,
                        parser.pdf_date,
                        parser.pdf_sample_number,
                    ),
                )
                report_id = execute_with_retry(db_path, 'SELECT MAX(ID) FROM REPORTS')[0][0]
                execute_with_retry(
                    db_path,
                    'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (report_id, 'X', 10.0, 0.5, -0.5, 0.0, 10.1, 0.1, 0, 'FEATURE_1'),
                )

            parse_result = parse_new_reports(
                report_paths=['part_1.pdf', 'part_2.pdf'],
                report_fingerprints=set(),
                parser_factory=_FakeParser,
                persist_report=persist_report,
            )
            self.assertEqual(parse_result.total_files, 2)
            self.assertEqual(parse_result.parsed_files, 2)

            export_query = '''
                SELECT MEASUREMENTS.AX, MEASUREMENTS.NOM, MEASUREMENTS."+TOL",
                    MEASUREMENTS."-TOL", MEASUREMENTS.BONUS, MEASUREMENTS.MEAS,
                    MEASUREMENTS.DEV, MEASUREMENTS.OUTTOL, MEASUREMENTS.HEADER, REPORTS.REFERENCE,
                    REPORTS.FILELOC, REPORTS.FILENAME, REPORTS.DATE, REPORTS.SAMPLE_NUMBER
                FROM MEASUREMENTS
                JOIN REPORTS ON MEASUREMENTS.REPORT_ID = REPORTS.ID
                ORDER BY REPORTS.ID
            '''

            rows, columns = execute_export_query(db_path, export_query)
            export_df = build_export_dataframe(rows, columns)

            self.assertEqual(len(export_df), 2)
            self.assertEqual(
                list(export_df.columns),
                [
                    'AX',
                    'NOM',
                    '+TOL',
                    '-TOL',
                    'BONUS',
                    'MEAS',
                    'DEV',
                    'OUTTOL',
                    'HEADER',
                    'REFERENCE',
                    'FILELOC',
                    'FILENAME',
                    'DATE',
                    'SAMPLE_NUMBER',
                ],
            )
            self.assertEqual(export_df['SAMPLE_NUMBER'].tolist(), ['1', '2'])
            self.assertEqual(export_df['MEAS'].tolist(), [10.1, 10.1])

    def test_export_pipeline_reads_filtered_dataframe_once_per_run(self):
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
            execute_with_retry(
                db_path,
                'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                ('REF-1', '/fake/reports', 'part_1.pdf', '2024-01-01', '1'),
            )
            execute_with_retry(
                db_path,
                'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (1, 'X', 10.0, 0.5, -0.5, 0.0, 10.1, 0.1, 0, 'FEATURE_1'),
            )

            request = ExportRequest(
                paths=AppPaths(db_file=db_path, excel_file=out_path),
                options=ExportOptions(generate_summary_sheet=False),
            )
            thread = ExportDataThread(request)

            module = __import__('modules.export_data_thread', fromlist=['read_sql_dataframe', 'execute_export_query'])
            previous_reader = module.read_sql_dataframe
            previous_execute = module.execute_export_query
            calls = {'read_sql_dataframe': 0}

            def _counting_reader(*args, **kwargs):
                calls['read_sql_dataframe'] += 1
                return previous_reader(*args, **kwargs)

            module.read_sql_dataframe = _counting_reader
            module.execute_export_query = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('execute_export_query should not be used by export pipeline'))
            try:
                completed = thread.get_export_backend().run(thread)
            finally:
                module.read_sql_dataframe = previous_reader
                module.execute_export_query = previous_execute

            self.assertTrue(completed)
            self.assertEqual(calls['read_sql_dataframe'], 1)

    def test_export_workbook_chart_ranges_match_expected_parity(self):
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

            execute_with_retry(
                db_path,
                'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                ('REF-1', '/fake/reports', 'part_1.pdf', '2024-01-01', '1'),
            )
            execute_with_retry(
                db_path,
                'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                ('REF-1', '/fake/reports', 'part_2.pdf', '2024-01-02', '2'),
            )

            execute_with_retry(
                db_path,
                'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (1, 'X', 10.0, 0.5, -0.5, 0.0, 10.1, 0.1, 0, 'FEATURE_1'),
            )
            execute_with_retry(
                db_path,
                'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (2, 'X', 10.0, 0.5, -0.5, 0.0, 10.2, 0.2, 0, 'FEATURE_1'),
            )

            request = ExportRequest(
                paths=AppPaths(db_file=db_path, excel_file=out_path),
                options=ExportOptions(generate_summary_sheet=False),
            )
            thread = ExportDataThread(request)
            completed = thread.get_export_backend().run(thread)

            self.assertTrue(completed)
            self.assertTrue(Path(out_path).exists())

            with zipfile.ZipFile(out_path, 'r') as workbook_zip:
                chart_xml = workbook_zip.read('xl/charts/chart1.xml').decode('utf-8')
                sheet_xml_candidates = [
                    workbook_zip.read(name).decode('utf-8')
                    for name in workbook_zip.namelist()
                    if name.startswith('xl/worksheets/sheet') and name.endswith('.xml')
                ]

            self.assertIn('REF-1!$B22:B23', chart_xml)
            self.assertIn('REF-1!$C22:C23', chart_xml)
            self.assertIn('REF-1!$D22:D23', chart_xml)
            self.assertIn('REF-1!$E22:E23', chart_xml)
            self.assertNotIn('REF-1!$XFB1:XFB2', chart_xml)
            self.assertTrue(
                any('ROUND(MIN(C22:C23), 3)' in sheet_xml for sheet_xml in sheet_xml_candidates),
                msg='Expected summary formulas were not found in any worksheet XML payload.',
            )
            self.assertTrue(
                any('<v>10.1</v>' in sheet_xml and '<v>10.2</v>' in sheet_xml for sheet_xml in sheet_xml_candidates),
                msg='Expected exported measurement values were not found in worksheet XML payload.',
            )

    def test_measurement_sheet_workbook_xml_keeps_conditional_formatting_ranges_visible(self):
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
            completed = thread.get_export_backend().run(thread)

            self.assertTrue(completed)

            worksheet_xml = _xlsx_sheet_xml(out_path, 'REF-1')
            namespace = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            worksheet_root = ET.fromstring(worksheet_xml)
            cf_nodes = worksheet_root.findall('x:conditionalFormatting', namespace)
            self.assertTrue(cf_nodes, msg='Expected measurement worksheet XML to contain conditionalFormatting nodes.')

            sqrefs = [node.attrib.get('sqref', '') for node in cf_nodes]
            cf_rules = [rule for node in cf_nodes for rule in node.findall('x:cfRule', namespace)]
            self.assertGreaterEqual(
                len(cf_rules),
                3,
                msg='Expected measurement worksheet XML to preserve the three visible conditional-formatting rules.',
            )
            self.assertIn('C22:C24', sqrefs)
            self.assertIn('B7', sqrefs)

            formulas_by_sqref = {
                node.attrib.get('sqref', ''): [
                    formula.text or ''
                    for rule in node.findall('x:cfRule', namespace)
                    for formula in rule.findall('x:formula', namespace)
                ]
                for node in cf_nodes
            }
            self.assertGreaterEqual(len(formulas_by_sqref.get('C22:C24', [])), 2)
            self.assertTrue(any('$B$1+$B$2' in formula for formula in formulas_by_sqref.get('C22:C24', [])))
            self.assertTrue(any('$B$1+$B$3' in formula for formula in formulas_by_sqref.get('C22:C24', [])))
            self.assertIn('0', formulas_by_sqref.get('B7', []))


    def test_group_analysis_level_off_emits_no_group_analysis_sheets(self):
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
            execute_with_retry(
                db_path,
                'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                ('REF-1', '/fake/reports', 'part_1.pdf', '2024-01-01', '1'),
            )
            execute_with_retry(
                db_path,
                'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (1, 'X', 10.0, 0.5, -0.5, 0.0, 10.1, 0.1, 0, 'FEATURE_1'),
            )

            request = ExportRequest(
                paths=AppPaths(db_file=db_path, excel_file=out_path),
                options=ExportOptions(generate_summary_sheet=False, group_analysis_level='off'),
            )
            thread = ExportDataThread(request)
            completed = thread.get_export_backend().run(thread)

            self.assertTrue(completed)
            sheet_names = _xlsx_sheet_names(out_path)
            self.assertNotIn('Group Analysis', sheet_names)
            self.assertNotIn('Diagnostics', sheet_names)

    def test_group_analysis_light_and_standard_emit_analysis_without_default_diagnostics(self):
        for level in ('light', 'standard'):
            with self.subTest(level=level), tempfile.TemporaryDirectory() as temp_dir:
                db_path = str(Path(temp_dir) / 'metroliza.sqlite')
                out_path = str(Path(temp_dir) / f'export_{level}.xlsx')

                execute_with_retry(
                    db_path,
                    'CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REFERENCE TEXT, FILELOC TEXT, FILENAME TEXT, DATE TEXT, SAMPLE_NUMBER TEXT)',
                )
                execute_with_retry(
                    db_path,
                    'CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY AUTOINCREMENT, REPORT_ID INTEGER, AX TEXT, NOM REAL, "+TOL" REAL, "-TOL" REAL, BONUS REAL, MEAS REAL, DEV REAL, OUTTOL INTEGER, HEADER TEXT)',
                )
                report_rows = [
                    (1, 'part_1.pdf', '2024-01-01', '1', 'A', 10.10, 0.10),
                    (2, 'part_2.pdf', '2024-01-02', '2', 'A', 10.12, 0.12),
                    (3, 'part_3.pdf', '2024-01-03', '3', 'A', 10.08, 0.08),
                    (4, 'part_4.pdf', '2024-01-04', '4', 'B', 10.42, 0.42),
                    (5, 'part_5.pdf', '2024-01-05', '5', 'B', 10.39, 0.39),
                    (6, 'part_6.pdf', '2024-01-06', '6', 'B', 10.41, 0.41),
                ]
                for report_id, filename, report_date, sample_number, _group, meas, dev in report_rows:
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

                grouping_df = pd.DataFrame(
                    [
                        {'REPORT_ID': report_id, 'GROUP': group}
                        for report_id, _filename, _report_date, _sample_number, group, _meas, _dev in report_rows
                    ]
                )
                request = ExportRequest(
                    paths=AppPaths(db_file=db_path, excel_file=out_path),
                    options=ExportOptions(generate_summary_sheet=False, group_analysis_level=level),
                    grouping_df=grouping_df,
                )
                thread = ExportDataThread(request)
                completed = thread.get_export_backend().run(thread)

                self.assertTrue(completed)
                sheet_names = _xlsx_sheet_names(out_path)
                self.assertIn('Group Analysis', sheet_names)
                self.assertNotIn('Diagnostics', sheet_names)

    def test_group_analysis_scope_mismatch_writes_exact_message_and_diagnostics(self):
        scenarios = [
            {
                'references': [('REF-1', 'part_1.pdf', '1'), ('REF-1', 'part_2.pdf', '2')],
                'scope': 'multi_reference',
                'expected_code': 'forced_multi_reference_scope_mismatch',
                'expected_message': 'Multi-reference group analysis skipped: grouped rows span only one reference.',
            },
            {
                'references': [('REF-1', 'part_1.pdf', '1'), ('REF-2', 'part_2.pdf', '2')],
                'scope': 'single_reference',
                'expected_code': 'forced_single_reference_scope_mismatch',
                'expected_message': 'Single-reference group analysis skipped: grouped rows span multiple references.',
            },
        ]

        for scenario in scenarios:
            with self.subTest(scope=scenario['scope']), tempfile.TemporaryDirectory() as temp_dir:
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

                for index, (reference, filename, sample_number) in enumerate(scenario['references'], start=1):
                    execute_with_retry(
                        db_path,
                        'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                        (reference, '/fake/reports', filename, f'2024-01-0{index}', sample_number),
                    )
                    execute_with_retry(
                        db_path,
                        'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (index, 'X', 10.0, 0.5, -0.5, 0.0, 10.0 + (0.1 * index), 0.1 * index, 0, 'FEATURE_1'),
                    )

                request = ExportRequest(
                    paths=AppPaths(db_file=db_path, excel_file=out_path),
                    options=ExportOptions(
                        generate_summary_sheet=False,
                        group_analysis_level='light',
                        group_analysis_scope=scenario['scope'],
                    ),
                )
                thread = ExportDataThread(request)
                with patch.dict(os.environ, {'METROLIZA_EXPORT_GROUP_ANALYSIS_DIAGNOSTICS': '1'}):
                    completed = thread.get_export_backend().run(thread)

                self.assertTrue(completed)
                sheet_names = _xlsx_sheet_names(out_path)
                self.assertIn('Group Analysis', sheet_names)
                self.assertIn('Diagnostics', sheet_names)

                analysis_values = _xlsx_sheet_text_values(out_path, 'Group Analysis')
                self.assertIn(scenario['expected_message'], analysis_values)

                diagnostics_values = _xlsx_sheet_text_values(out_path, 'Diagnostics')
                self.assertIn(scenario['expected_code'], diagnostics_values)
                self.assertIn(scenario['expected_message'], diagnostics_values)


    def test_group_analysis_scope_mismatch_internal_diagnostics_use_payload_readiness_only(self):
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
            execute_with_retry(
                db_path,
                'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                ('REF-1', '/fake/reports', 'part_1.pdf', '2024-01-01', '1'),
            )
            execute_with_retry(
                db_path,
                'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (1, 'X', 10.0, 0.5, -0.5, 0.0, 10.1, 0.1, 0, 'FEATURE_1'),
            )

            request = ExportRequest(
                paths=AppPaths(db_file=db_path, excel_file=out_path),
                options=ExportOptions(
                    generate_summary_sheet=False,
                    group_analysis_level='light',
                    group_analysis_scope='multi_reference',
                ),
            )
            thread = ExportDataThread(request)

            module = __import__('modules.export_data_thread', fromlist=['evaluate_group_analysis_readiness'])
            previous_readiness = getattr(module, 'evaluate_group_analysis_readiness', None)
            module.evaluate_group_analysis_readiness = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('Legacy readiness path should not be called from ExportDataThread.')
            )
            try:
                with patch.dict(os.environ, {'METROLIZA_EXPORT_GROUP_ANALYSIS_DIAGNOSTICS': '1'}):
                    completed = thread.get_export_backend().run(thread)
            finally:
                if previous_readiness is None:
                    delattr(module, 'evaluate_group_analysis_readiness')
                else:
                    module.evaluate_group_analysis_readiness = previous_readiness

            self.assertTrue(completed)
            diagnostics_values = _xlsx_sheet_text_values(out_path, 'Diagnostics')
            self.assertIn('forced_multi_reference_scope_mismatch', diagnostics_values)
            self.assertIn('Multi-reference group analysis skipped: grouped rows span only one reference.', diagnostics_values)

    def test_group_analysis_runnable_path_internal_diagnostics_use_payload_readiness_only(self):
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

            grouping_df = pd.DataFrame(
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
            request = ExportRequest(
                paths=AppPaths(db_file=db_path, excel_file=out_path),
                options=ExportOptions(generate_summary_sheet=False, group_analysis_level='light'),
                grouping_df=grouping_df,
            )
            thread = ExportDataThread(request)

            module = __import__('modules.export_data_thread', fromlist=['evaluate_group_analysis_readiness'])
            previous_readiness = getattr(module, 'evaluate_group_analysis_readiness', None)
            module.evaluate_group_analysis_readiness = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError('Legacy readiness path should not be called from ExportDataThread.')
            )
            try:
                with patch.dict(os.environ, {'METROLIZA_EXPORT_GROUP_ANALYSIS_DIAGNOSTICS': '1'}):
                    completed = thread.get_export_backend().run(thread)
            finally:
                if previous_readiness is None:
                    delattr(module, 'evaluate_group_analysis_readiness')
                else:
                    module.evaluate_group_analysis_readiness = previous_readiness

            self.assertTrue(completed)
            diagnostics_values = _xlsx_sheet_text_values(out_path, 'Diagnostics')
            self.assertIn('ran', diagnostics_values)
            self.assertIn('single_reference', diagnostics_values)

    def test_group_analysis_independent_from_extended_plots_toggle(self):
        for summary_enabled in (False, True):
            with self.subTest(generate_summary_sheet=summary_enabled), tempfile.TemporaryDirectory() as temp_dir:
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
                execute_with_retry(
                    db_path,
                    'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                    ('REF-1', '/fake/reports', 'part_1.pdf', '2024-01-01', '1'),
                )
                execute_with_retry(
                    db_path,
                    'INSERT INTO REPORTS (REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER) VALUES (?, ?, ?, ?, ?)',
                    ('REF-1', '/fake/reports', 'part_2.pdf', '2024-01-02', '2'),
                )
                execute_with_retry(
                    db_path,
                    'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (1, 'X', 10.0, 0.5, -0.5, 0.0, 10.1, 0.1, 0, 'FEATURE_1'),
                )
                execute_with_retry(
                    db_path,
                    'INSERT INTO MEASUREMENTS (REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (2, 'X', 10.0, 0.5, -0.5, 0.0, 10.2, 0.2, 0, 'FEATURE_1'),
                )

                request = ExportRequest(
                    paths=AppPaths(db_file=db_path, excel_file=out_path),
                    options=ExportOptions(
                        generate_summary_sheet=summary_enabled,
                        group_analysis_level='off',
                    ),
                )
                thread = ExportDataThread(request)
                completed = thread.get_export_backend().run(thread)

                self.assertTrue(completed)
                sheet_names = _xlsx_sheet_names(out_path)
                self.assertNotIn('Group Analysis', sheet_names)
                self.assertNotIn('Diagnostics', sheet_names)


if __name__ == '__main__':
    unittest.main()
