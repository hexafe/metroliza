import posixpath
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from xlsxwriter.utility import quote_sheetname, xl_col_to_name

from metroliza.charts.export_chart_writer import insert_measurement_chart
from metroliza.exporting.execution import ExportOutcomeKind
from modules.contracts import AppPaths, ExportOptions, ExportRequest
from modules.report_repository import ReportRepository
from modules.report_schema import ensure_report_schema
from tests.test_export_workbook_output import _load_export_thread_type


NS_MAIN = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
NS_CHART = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
NS_PACKAGE = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
NS_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def _xml(workbook_zip, path):
    return ET.fromstring(workbook_zip.read(path))


def _package_path(base_path, target):
    return posixpath.normpath(str(PurePosixPath(PurePosixPath(base_path).parent, target)))


def _sheet_path(workbook_zip, sheet_name):
    workbook = _xml(workbook_zip, 'xl/workbook.xml')
    relationships = _xml(workbook_zip, 'xl/_rels/workbook.xml.rels')
    relationship_targets = {
        relation.attrib['Id']: relation.attrib['Target']
        for relation in relationships.findall('r:Relationship', NS_PACKAGE)
    }
    for sheet in workbook.findall('x:sheets/x:sheet', NS_MAIN):
        if sheet.attrib.get('name') == sheet_name:
            return 'xl/' + relationship_targets[sheet.attrib[f'{{{NS_REL}}}id']]
    raise AssertionError(f'Missing worksheet: {sheet_name}')


def _chart_paths(workbook_zip, sheet_path):
    worksheet_rels = _xml(workbook_zip, f"xl/worksheets/_rels/{Path(sheet_path).name}.rels")
    drawing_target = next(
        relation.attrib['Target']
        for relation in worksheet_rels.findall('r:Relationship', NS_PACKAGE)
        if relation.attrib['Type'].endswith('/drawing')
    )
    drawing_path = _package_path(sheet_path, drawing_target)
    drawing_rels = _xml(workbook_zip, _package_path(drawing_path, f'_rels/{Path(drawing_path).name}.rels'))
    return [
        _package_path(drawing_path, relation.attrib['Target'])
        for relation in drawing_rels.findall('r:Relationship', NS_PACKAGE)
        if relation.attrib['Type'].endswith('/chart')
    ]


def _shared_strings(workbook_zip):
    if 'xl/sharedStrings.xml' not in workbook_zip.namelist():
        return []
    return [
        ''.join(node.itertext())
        for node in _xml(workbook_zip, 'xl/sharedStrings.xml').findall('x:si', NS_MAIN)
    ]


def _cell_value(worksheet, cell_reference, shared_strings):
    cell = worksheet.find(f".//x:c[@r='{cell_reference}']", NS_MAIN)
    if cell is None:
        raise AssertionError(f'Missing worksheet cell: {cell_reference}')
    value = cell.findtext('x:v', namespaces=NS_MAIN)
    if cell.attrib.get('t') == 's':
        return shared_strings[int(value)]
    if cell.attrib.get('t') == 'inlineStr':
        return ''.join(cell.find('x:is', NS_MAIN).itertext())
    return value


def _persist_measurement(repository, source_dir, *, report_id, sample_number, header, ax, measurement, reference='REF-1'):
    source_path = source_dir / f'part_{report_id}.pdf'
    source_path.write_bytes(f'report-content-{report_id}'.encode('utf-8'))
    repository.persist_parsed_report(
        source_path=source_path,
        parser_id='cmm', parser_version='1.0', template_family='cmm_pdf_header_box',
        template_variant='cmm_pdf_header_box_serial_variant', parse_status='parsed_with_warnings',
        metadata={
            'reference': reference, 'reference_raw': reference,
            'report_date': f'2024-01-{((report_id - 1) % 28) + 1:02d}',
            'part_name': 'Part', 'revision': 'A', 'sample_number': str(sample_number),
            'sample_number_kind': 'explicit_sample_number', 'stats_count_raw': str(sample_number),
            'stats_count_int': sample_number, 'operator_name': 'Operator', 'comment': None,
        },
        measurements=[{
            'page_number': 1, 'row_order': 1, 'header': header, 'section_name': header,
            'feature_label': header, 'characteristic_name': 'LOC', 'characteristic_family': 'LOC',
            'description': 'Feature LOC', 'ax': ax, 'nominal': 10.0, 'tol_plus': 0.5,
            'tol_minus': -0.5, 'bonus': 0.0, 'meas': measurement, 'dev': measurement - 10.0,
            'outtol': 0, 'is_nok': False, 'status_code': 'ok',
        }],
        candidates=[], warnings=[], metadata_version='report_metadata_v1',
        metadata_profile_id='cmm_pdf_header_box', metadata_profile_version='1', page_count=1,
        measurement_count=1, has_nok=False, nok_count=0, metadata_confidence=0.9,
        identity_hash=f'identity-{report_id}',
    )


def _scratch_export_thread(temp_path, header, export_thread_type):
    db_path = temp_path / f'{len(header)}-metroliza.sqlite'
    out_path = temp_path / 'export.xlsx'
    ensure_report_schema(str(db_path))
    repository = ReportRepository(str(db_path))
    source_dir = temp_path / f'{len(header)}-reports'
    source_dir.mkdir()
    _persist_measurement(repository, source_dir, report_id=1, sample_number=1, header=header, ax='X', measurement=10.1)
    _persist_measurement(repository, source_dir, report_id=2, sample_number=2, header=header, ax='X', measurement=10.2)
    request = ExportRequest(
        paths=AppPaths(db_file=str(db_path), excel_file=str(out_path)),
        options=ExportOptions(generate_summary_sheet=False),
    )
    return export_thread_type(request), out_path


def _directory_snapshot(path):
    return {entry.name for entry in path.iterdir()}


class TestMeasurementChartLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The shared loader performs the inert Qt import once; repeated dynamic
        # imports reinitialize NumPy extension modules in the same process.
        cls.ExportDataThread = _load_export_thread_type()

    def test_reference_looking_imported_label_uses_local_literal_header_cell(self):
        """The actual backend must keep imported names out of chart formulas."""
        imported_header = '=Data!A1'
        expected_label = '=Data!A1 - X'

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            db_path = temp_path / 'metroliza.sqlite'
            out_path = temp_path / 'export.xlsx'
            ensure_report_schema(str(db_path))
            repository = ReportRepository(str(db_path))
            source_dir = temp_path / 'reports'
            source_dir.mkdir()
            _persist_measurement(repository, source_dir, report_id=1, sample_number=1, header=imported_header, ax='X', measurement=10.1)
            _persist_measurement(repository, source_dir, report_id=2, sample_number=2, header=imported_header, ax='X', measurement=10.2)

            request = ExportRequest(
                paths=AppPaths(db_file=str(db_path), excel_file=str(out_path)),
                options=ExportOptions(generate_summary_sheet=False),
            )
            thread = self.ExportDataThread(request)
            outcome = thread.get_export_backend().run(thread)
            self.assertEqual(outcome.kind, ExportOutcomeKind.COMPLETED)

            with zipfile.ZipFile(out_path) as workbook_zip:
                sheet_path = _sheet_path(workbook_zip, 'REF-1')
                chart_path = _chart_paths(workbook_zip, sheet_path)[0]
                chart = _xml(workbook_zip, chart_path)
                worksheet = _xml(workbook_zip, sheet_path)
                shared_strings = _shared_strings(workbook_zip)
                title_refs = [node.text for node in chart.findall('.//c:title//c:strRef/c:f', NS_CHART)]
                series_refs = [node.text for node in chart.findall('.//c:ser/c:tx/c:strRef/c:f', NS_CHART)]
                title_caches = [node.text for node in chart.findall('.//c:title//c:strCache/c:pt/c:v', NS_CHART)]
                series_caches = [node.text for node in chart.findall('.//c:ser/c:tx/c:strRef/c:strCache/c:pt/c:v', NS_CHART)]
                data_formula_nodes = chart.findall('.//c:numRef/c:f', NS_CHART)

            # These six formulas deliberately target the three charted data
            # series. The imported label must use the measurement header cell.
            self.assertEqual(
                [node.text for node in data_formula_nodes],
                [
                    "'REF-1'!$B22:B23", "'REF-1'!$C22:C23",
                    "'REF-1'!$B22:B23", "'REF-1'!$D22:D23",
                    "'REF-1'!$B22:B23", "'REF-1'!$E22:E23",
                ],
            )
            expected_local_name_ref = "'REF-1'!$C$21"
            self.assertEqual(title_refs, [expected_local_name_ref])
            self.assertEqual(series_refs, [expected_local_name_ref])
            self.assertEqual(_cell_value(worksheet, 'C21', shared_strings), expected_label)
            self.assertEqual(title_caches, [expected_label])
            self.assertEqual(series_caches, [expected_label])

    def test_multiple_measurement_charts_preserve_text_labels_on_quoted_sheets(self):
        labels_by_reference = {
            'REF-1': ('Diameter', '=Data!A1', '+leading', '-offset', '@marker', 'Żółć "quotes"'),
            "O'Brien": ('=Data!A1', 'same label'),
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            db_path = temp_path / 'metroliza.sqlite'
            out_path = temp_path / 'export.xlsx'
            ensure_report_schema(str(db_path))
            repository = ReportRepository(str(db_path))
            source_dir = temp_path / 'reports'
            source_dir.mkdir()
            report_id = 0
            for reference, labels in labels_by_reference.items():
                for label in labels:
                    for sample_number, measurement in ((1, 10.1), (2, 10.2)):
                        report_id += 1
                        _persist_measurement(
                            repository, source_dir, report_id=report_id, sample_number=sample_number,
                            header=label, ax='X', measurement=measurement, reference=reference,
                        )

            request = ExportRequest(
                paths=AppPaths(db_file=str(db_path), excel_file=str(out_path)),
                options=ExportOptions(generate_summary_sheet=False),
            )
            thread = self.ExportDataThread(request)
            outcome = thread.get_export_backend().run(thread)
            self.assertEqual(outcome.kind, ExportOutcomeKind.COMPLETED)

            with zipfile.ZipFile(out_path) as workbook_zip:
                self.assertIsNone(workbook_zip.testzip())
                shared_strings = _shared_strings(workbook_zip)
                for reference, labels in labels_by_reference.items():
                    sheet_path = _sheet_path(workbook_zip, reference)
                    worksheet = _xml(workbook_zip, sheet_path)
                    chart_paths = _chart_paths(workbook_zip, sheet_path)
                    self.assertEqual(len(chart_paths), len(labels))
                    quoted_sheet = quote_sheetname(reference)
                    observed_labels = []
                    for index, chart_path in enumerate(chart_paths):
                        chart = _xml(workbook_zip, chart_path)
                        column_name = xl_col_to_name(2 + (index * 5))
                        header_cell = f'{column_name}21'
                        expected_ref = f'{quoted_sheet}!${column_name}$21'
                        label = _cell_value(worksheet, header_cell, shared_strings)
                        observed_labels.append(label)
                        self.assertEqual(
                            [node.text for node in chart.findall('.//c:title//c:strRef/c:f', NS_CHART)],
                            [expected_ref],
                        )
                        self.assertEqual(
                            [node.text for node in chart.findall('.//c:ser/c:tx/c:strRef/c:f', NS_CHART)],
                            [expected_ref],
                        )
                        header_node = worksheet.find(f".//x:c[@r='{header_cell}']", NS_MAIN)
                        self.assertIsNone(header_node.find('x:f', NS_MAIN))
                        self.assertEqual(
                            [node.text for node in chart.findall('.//c:title//c:strCache/c:pt/c:v', NS_CHART)],
                            [label],
                        )
                        self.assertEqual(
                            [node.text for node in chart.findall('.//c:ser/c:tx/c:strRef/c:strCache/c:pt/c:v', NS_CHART)],
                            [label],
                        )
                        summary_column = xl_col_to_name(1 + (index * 5))
                        expected_ranges = [
                            f'{quoted_sheet}!${summary_column}22:{summary_column}23',
                            f'{quoted_sheet}!${column_name}22:{column_name}23',
                            f'{quoted_sheet}!${summary_column}22:{summary_column}23',
                            f'{quoted_sheet}!${xl_col_to_name(3 + (index * 5))}22:{xl_col_to_name(3 + (index * 5))}23',
                            f'{quoted_sheet}!${summary_column}22:{summary_column}23',
                            f'{quoted_sheet}!${xl_col_to_name(4 + (index * 5))}22:{xl_col_to_name(4 + (index * 5))}23',
                        ]
                        self.assertEqual([node.text for node in chart.findall('.//c:numRef/c:f', NS_CHART)], expected_ranges)
                        series = chart.findall('.//c:ser', NS_CHART)
                        self.assertEqual([item.findtext('c:tx/c:v', namespaces=NS_CHART) for item in series[1:]], ['USL', 'LSL'])
                        primary_series = series[0]
                        self.assertEqual(
                            [node.text for node in primary_series.findall('c:val/c:numRef/c:numCache/c:pt/c:v', NS_CHART)],
                            ['10.1', '10.2'],
                        )
                        self.assertEqual(
                            [_cell_value(worksheet, f'{column_name}{row}', shared_strings) for row in (22, 23)],
                            ['10.1', '10.2'],
                        )
                        self.assertEqual(
                            [node.text for node in series[1].findall('c:val/c:numRef/c:numCache/c:pt/c:v', NS_CHART)],
                            ['10.5', '10.5'],
                        )
                        self.assertEqual(
                            [node.text for node in series[2].findall('c:val/c:numRef/c:numCache/c:pt/c:v', NS_CHART)],
                            ['9.5', '9.5'],
                        )
                    self.assertEqual(observed_labels, [f'{label} - X' for label in sorted(labels)])

    def test_backend_retains_last_complete_workbook_when_actual_pipeline_cancels_or_rejects_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            completed_thread, out_path = _scratch_export_thread(temp_path, 'Diameter', self.ExportDataThread)
            completed_outcome = completed_thread.get_export_backend().run(completed_thread)
            self.assertEqual(completed_outcome.kind, ExportOutcomeKind.COMPLETED)
            with zipfile.ZipFile(out_path) as completed_zip:
                self.assertIsNone(completed_zip.testzip())
            completed_bytes = out_path.read_bytes()

            cancelled_thread, _ = _scratch_export_thread(temp_path, 'Cancelled measurement', self.ExportDataThread)
            cancelled_thread.export_canceled = True
            before_cancel = _directory_snapshot(temp_path)
            cancelled_outcome = cancelled_thread.get_export_backend().run(cancelled_thread)
            self.assertEqual(cancelled_outcome.kind, ExportOutcomeKind.CANCELED)
            self.assertEqual(out_path.read_bytes(), completed_bytes)
            self.assertEqual(_directory_snapshot(temp_path), before_cancel)

            rejected_thread, _ = _scratch_export_thread(temp_path, 'x' * 32768, self.ExportDataThread)
            before_rejection = _directory_snapshot(temp_path)
            with self.assertRaisesRegex(ValueError, 'Measurement chart label must contain 1 to 32767 characters'):
                rejected_thread.get_export_backend().run(rejected_thread)
            self.assertEqual(out_path.read_bytes(), completed_bytes)
            self.assertEqual(_directory_snapshot(temp_path), before_rejection)

    def test_chart_name_binding_rejects_unrepresentable_and_mismatched_sheet_inputs(self):
        measurement_plan = {'data_header_row': 20, 'y_column': 2}
        matching_sheet = types.SimpleNamespace(name='REF-1')
        with self.assertRaisesRegex(ValueError, 'Measurement chart label contains unsupported Unicode'):
            insert_measurement_chart(
                object(), matching_sheet, chart_type='line', header='\ud800', sheet_name='REF-1',
                measurement_plan=measurement_plan, chart_anchor_col=0,
            )
        with self.assertRaisesRegex(ValueError, 'Measurement chart worksheet does not match its data sheet'):
            insert_measurement_chart(
                object(), matching_sheet, chart_type='line', header='Diameter', sheet_name='other-sheet',
                measurement_plan=measurement_plan, chart_anchor_col=0,
            )


if __name__ == '__main__':
    unittest.main()
