"""#1159 Packet C: manual values, one Apply transaction and reviewed alias imports."""

from contextlib import closing
import hashlib
import json
import sqlite3
import threading

import pytest
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QDialog, QMessageBox, QPlainTextEdit, QPushButton

from metroliza.reports import characteristic_alias_service as aliases
from metroliza.reports.db import run_transaction_with_retry
from metroliza.reports.report_curation import load_stored_report_context
from metroliza.reports.report_edit_service import ReportEditService
from metroliza.reports.report_metadata_models import MetadataCandidate, MetadataWarning
from metroliza.reports.report_repository import ReportRepository
from metroliza.ui.modify_db import ModifyDB
from metroliza.ui.modify_db_records import RecordTableModel
from tests.test_report_schema_repository import _persist_basic_report
from tests.test_modifydb_record_updates import _wait_edit


def _database(tmp_path):
    path = str(tmp_path / 'reports.db')
    repository = ReportRepository(path)
    repository.ensure_schema()
    report = _persist_basic_report(tmp_path, repository, outtol=0.25)
    other = _persist_basic_report(tmp_path, repository, file_name='other.pdf', outtol=0.5)
    with closing(sqlite3.connect(path)) as connection:
        ids = [row[0] for row in connection.execute('SELECT id FROM report_measurements ORDER BY id')]
    return path, repository, report, other, ids


def _dump(path):
    """Every logical table, including raw JSON, warnings, overrides and NOK summaries."""
    with closing(sqlite3.connect(path)) as connection:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return {name: sorted(connection.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(), key=repr)
                for (name,) in tables}


def _model(value=10.0):
    return RecordTableModel([
        {'field': 'measurement_id', 'label': 'MEASUREMENT_ID', 'editable': False},
        {'field': 'meas', 'label': 'MEAS', 'editable': True, 'value_type': 'float'},
    ], [(1, value)])


@pytest.mark.parametrize('text,expected', [('10,25', 10.25), ('10.25', 10.25), ('', None)])
def test_f01_preview_equals_persisted_value(tmp_path, qapplication_session, text, expected):
    path, repository, _report, _other, ids = _database(tmp_path)
    model = _model()
    model._rows = [(ids[0], 10.0)]
    model.setData(model.index(0, 1), text)
    table = type('Table', (), {'model': lambda self: model})()
    dialog = ModifyDB.__new__(ModifyDB)
    updates = dialog.collect_record_table_updates(table, 'measurement_id')
    assert updates == [(ids[0], {'meas': expected})]
    summary = dialog.collect_record_table_modifications(table, 'Measurement rows', 'measurement_id')
    assert ('NULL' if expected is None else str(expected)) in summary
    ReportEditService(path).apply_changes(storage_flavor='current', normalization_changes={}, measurement_updates=updates)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute('SELECT meas FROM report_measurements WHERE id=?', (ids[0],)).fetchone() == (expected,)


@pytest.mark.parametrize('text', ['abc', '1,234,5', '1.234,5', '1 234', 'NaN', 'inf', ' '])
def test_f01_invalid_api_edit_preserves_entire_database(tmp_path, text):
    path, repository, _report, _other, ids = _database(tmp_path)
    before = _dump(path)
    with pytest.raises(ValueError, match='Invalid number'):
        repository.update_measurement_fields(ids[0], {'meas': text})
    assert _dump(path) == before


def test_f01_cell_reason_and_untouched_cell(qapplication_session):
    model = _model()
    dialog = ModifyDB.__new__(ModifyDB)
    table = type('Table', (), {'model': lambda self: model})()
    assert dialog.collect_record_table_updates(table, 'measurement_id') == []
    model.setData(model.index(0, 1), 'abc')
    with pytest.raises(ValueError, match='MEASUREMENT_ID=1, MEAS:'):
        dialog.collect_record_table_updates(table, 'measurement_id')
    assert 'Invalid number' in model.data(model.index(0, 1), Qt.ItemDataRole.ToolTipRole)
    assert model.has_edits and model.original_value(0, 1) == 10.0


@pytest.mark.parametrize('text', ['1,234', '12,500', '-999,000', '+12,500', '999,999'])
def test_c2_ambiguous_comma_rejected_by_api(tmp_path, text):
    path, repository, _report, _other, ids = _database(tmp_path)
    before = _dump(path)
    with pytest.raises(ValueError, match='ambiguous: use 1.234 or 1234'):
        repository.update_measurement_fields(ids[0], {'meas': text})
    assert _dump(path) == before


@pytest.mark.parametrize('text', ['1,234', '12,500', '-999,000', '+12,500', '999,999'])
def test_c2_ambiguous_comma_cell_reason(qapplication_session, text):
    model = _model()
    model.setData(model.index(0, 1), text)
    dialog = ModifyDB.__new__(ModifyDB)
    table = type('Table', (), {'model': lambda self: model})()
    with pytest.raises(ValueError, match='MEASUREMENT_ID=1, MEAS:.*ambiguous'):
        dialog.collect_record_table_updates(table, 'measurement_id')
    assert 'ambiguous: use 1.234 or 1234' in model.data(model.index(0, 1), Qt.ItemDataRole.ToolTipRole)


@pytest.mark.parametrize('text,expected', [('10,25', 10.25), ('0,125', .125), ('1,5', 1.5),
                                         ('1234,5', 1234.5), ('1,2345', 1.2345)])
def test_c2_unambiguous_comma_round_trips(tmp_path, qapplication_session, text, expected):
    test_f01_preview_equals_persisted_value(tmp_path, qapplication_session, text, expected)


@pytest.mark.parametrize('field', ['page_number', 'row_order', 'stats_count_int'])
@pytest.mark.parametrize('value', [3.0, '3.0', '3', 3])
def test_c2_integral_number_api_tolerance(tmp_path, field, value):
    path, repository, report, _other, ids = _database(tmp_path)
    if field == 'stats_count_int':
        repository.update_report_metadata_fields(report, {field: value})
        query, key = 'SELECT stats_count_int FROM report_metadata WHERE report_id=?', report
    else:
        repository.update_measurement_fields(ids[0], {field: value})
        query, key = f'SELECT {field} FROM report_measurements WHERE id=?', ids[0]
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(query, (key,)).fetchone() == (3,)


@pytest.mark.parametrize('field', ['page_number', 'row_order', 'stats_count_int'])
@pytest.mark.parametrize('value', [3.5, '3.5', 'bad', 'NaN'])
def test_c2_fractional_integer_api_rejected_atomically(tmp_path, field, value):
    path, repository, report, _other, ids = _database(tmp_path)
    before = _dump(path)
    update, key = ((repository.update_report_metadata_fields, report) if field == 'stats_count_int'
                   else (repository.update_measurement_fields, ids[0]))
    with pytest.raises(ValueError, match='Invalid number'):
        update(key, {field: value})
    assert _dump(path) == before


@pytest.mark.parametrize('text', ['10,25', '10.250', '1.025e1'])
def test_c2_equivalent_numeric_cell_is_not_an_edit(qapplication_session, text):
    model = _model(10.25)
    model.setData(model.index(0, 1), text)
    table = type('Table', (), {'model': lambda self: model})()
    dialog = ModifyDB.__new__(ModifyDB)
    assert dialog.collect_record_table_updates(table, 'measurement_id') == []
    assert not model.has_edits


def test_c2_equivalent_number_apply_leaves_database_and_overrides_unchanged(tmp_path, qapplication_session, monkeypatch):
    from metroliza.ui import modify_db

    path, _repository, _report, _other, _ids = _database(tmp_path)
    before = _dump(path)
    dialog = ModifyDB(db_file=path, modal=False)
    dialog.ensure_record_tables_loaded()
    model = dialog.measurement_records_table.model()
    column = next(i for i, spec in enumerate(model.specs) if spec['field'] == 'meas')
    model.setData(model.index(0, column), '10,0')
    messages = []
    monkeypatch.setattr(modify_db.QMessageBox, 'information', lambda *args: messages.append(args[1:]))
    try:
        dialog.apply_changes()
        _wait_edit(dialog)
        assert messages == [('No changes', 'No changes were detected.')]
        assert not dialog._changes_committed and not model.has_edits
        assert _dump(path) == before
    finally:
        dialog._discard_confirmed = True
        dialog.close()


def test_f02_rollback_after_first_real_measurement_mutation(tmp_path, monkeypatch):
    path, repository, report, _other, ids = _database(tmp_path)
    before = _dump(path)
    original = ReportRepository._apply_measurement_field_updates
    mutations = []

    def fail_second(cursor, measurement_id, values):
        if mutations:
            assert cursor.execute('SELECT meas FROM report_measurements WHERE id=?', (ids[0],)).fetchone() == (20.0,)
            raise RuntimeError('injected after real mutation')
        original(cursor, measurement_id, values)
        mutations.append(measurement_id)

    monkeypatch.setattr(ReportRepository, '_apply_measurement_field_updates', staticmethod(fail_second))
    used_repositories = []

    def repository_factory(database):
        used = ReportRepository(database)
        used_repositories.append(used)
        return used

    with pytest.raises(RuntimeError, match='after real mutation'):
        ReportEditService(path, repository_factory=repository_factory).apply_changes(
            storage_flavor='current', normalization_changes={'header': [('NORMALIZED', 'Feature 1')]},
            report_updates=[(report, {'reference': 'NEW-ID'})],
            measurement_updates=[(ids[0], {'meas': 20, 'outtol': 0}), (ids[1], {'meas': 30})],
        )
    assert mutations == [ids[0]]
    assert _dump(path) == before
    assert len(used_repositories) == 1
    assert used_repositories[0].connection is None


def test_f02_success_updates_raw_json_status_identity_and_duplicates(tmp_path):
    path, _repository, report, other, ids = _database(tmp_path)
    ReportEditService(path).apply_changes(
        storage_flavor='current', normalization_changes={'header': [('NORMALIZED', 'Feature 1')]},
        report_updates=[(report, {'reference': 'NEW-ID'})],
        measurement_updates=[(ids[0], {'meas': '10,25', 'outtol': 0}), (ids[1], {'meas': 30})],
    )
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute('SELECT meas,is_nok,status_code FROM report_measurements ORDER BY id').fetchall() == [
            (10.25, 0, 'ok'), (30.0, 1, 'nok')]
        assert connection.execute('SELECT nok_count FROM parsed_reports ORDER BY id').fetchall() == [(0,), (1,)]
        assert connection.execute('SELECT COUNT(DISTINCT identity_hash) FROM parsed_reports').fetchone() == (2,)
        assert connection.execute('SELECT COUNT(*) FROM report_metadata_warnings WHERE report_id=? AND code=?',
                                  (report, 'semantic_duplicate_identity_hash_detected')).fetchone() == (0,)
        assert connection.execute('SELECT raw_measurement_json FROM report_measurements WHERE id=?', (ids[0],)).fetchone()[0].find('manual_overrides') > 0
        assert other != report


def test_f02_joined_helper_does_not_commit_or_rollback_outer_transaction(tmp_path):
    path = str(tmp_path / 'join.db')
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('CREATE TABLE edits(value)')
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('INSERT INTO edits VALUES (1)')
        run_transaction_with_retry(path, lambda cursor: cursor.execute('INSERT INTO edits VALUES (2)'),
                                   connection=connection, join_transaction=True)
        assert connection.in_transaction
        connection.rollback()
        assert connection.execute('SELECT * FROM edits').fetchall() == []


def test_f02_borrowed_helper_default_still_commits_and_join_error_does_not_rollback(tmp_path):
    path = str(tmp_path / 'default.db')
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('CREATE TABLE edits(value)')
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('INSERT INTO edits VALUES (1)')
        run_transaction_with_retry(path, lambda cursor: cursor.execute('INSERT INTO edits VALUES (2)'), connection=connection)
        assert not connection.in_transaction
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('INSERT INTO edits VALUES (3)')

        def fail(_cursor):
            raise RuntimeError('outer owner handles rollback')

        with pytest.raises(RuntimeError, match='outer owner'):
            run_transaction_with_retry(path, fail, connection=connection, join_transaction=True)
        assert connection.in_transaction
        assert connection.execute('SELECT * FROM edits').fetchall() == [(1,), (2,), (3,)]
        connection.rollback()
        assert connection.execute('SELECT * FROM edits').fetchall() == [(1,), (2,)]


def test_f02_gui_error_says_nothing_saved_and_keeps_pending_grid(tmp_path, qapplication_session, monkeypatch):
    from metroliza.ui import modify_db
    path, _repo, _report, _other, _ids = _database(tmp_path)
    dialog = ModifyDB(db_file=path, modal=False)
    dialog.reference_table.item(0, 1).setText('PENDING')
    before = _dump(path)
    dialog.collect_measurement_record_updates = lambda: [(999999, {'meas': 10})]
    messages = []
    monkeypatch.setattr(modify_db.QMessageBox, 'critical', lambda *args: messages.append(args[1:]))
    monkeypatch.setattr(modify_db, 'CustomLogger', lambda *args, **kwargs: None)
    dialog.apply_changes()
    _wait_edit(dialog)
    assert messages and messages[0][0] == 'Nothing was saved'
    assert 'Pending edits were kept' in messages[0][1]
    assert not dialog._changes_committed and dialog.has_pending_changes()
    assert dialog.reference_table.item(0, 1).text() == 'PENDING'
    assert _dump(path) == before
    dialog._discard_confirmed = True
    dialog.close()


def test_stored_report_review_filters_and_selected_context_are_read_only(tmp_path, qapplication_session):
    path, repository, report, other, _measurements = _database(tmp_path)
    repository.replace_metadata_candidates(report, (
        MetadataCandidate("report_date", "2024-01-01", "2024-01-01", "header_exact", "ocr", 1, "header", None,
                          "ocr:date", 0.9, None, selected=True),
    ))
    ReportEditService(path).apply_changes(
        storage_flavor="current", normalization_changes={}, report_updates=[(report, {"reference": "MANUAL"})],
    )
    repository.replace_metadata_warnings(report, (
        MetadataWarning("ocr_confidence", "report_date", "warning", "Review the date read from the header."),
        MetadataWarning("sample_mismatch", "sample_number", "error", "<b>Double-check the sample.</b>"),
        MetadataWarning("long_note", None, "warning", "x" * 651 + "end-marker"),
        *(MetadataWarning(f"code_{i}", None, "warning", "Stored review evidence.") for i in range(24)),
    ))
    repository.replace_metadata_warnings(other, (MetadataWarning("info_note", None, "info", "Info only."),))
    reference_decision = {
        "decision": "deferred", "value": "OCR-REFERENCE", "source_type": "header_exact",
        "region_name": "page1_header_band_ocr", "page_number": 1, "confidence": 0.79,
        "rule_id": "review:reference", "evidence_text": "unprojected-evidence-sentinel",
    }
    decisions = {
        "reference": reference_decision,
        "revision": {**reference_decision, "decision": "rejected", "value": "B", "confidence": 0.84},
        "comment": {**reference_decision, "value": "line one\nline two\u202e " + "x" * 121 + "tail-sentinel"},
        "operator_name": {**reference_decision, "decision": "accepted", "value": "invalid-status-sentinel"},
        "unknown": {**reference_decision, "value": "unknown-field-sentinel"},
    }
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE parsed_reports SET parser_id = 'other_parser' WHERE id = ?", (other,))
        connection.execute(
            "UPDATE report_metadata SET metadata_profile_id = 'inspection', metadata_profile_version = '3.1', "
            "metadata_json = ? WHERE report_id = ?", (json.dumps({
                "header_text": "unprojected-header-sentinel",
                "metadata_review": {"version": 1, "ocr_decisions": decisions},
            }), report),
        )
        connection.execute("UPDATE report_metadata SET metadata_json = ? WHERE report_id = ?", (json.dumps({
            "metadata_review": {"version": 1, "ocr_decisions": {
                "part_name": {**reference_decision, "decision": "rejected", "value": "OTHER-REPORT-DECISION"},
            }},
        }), other))
    before = _dump(path)
    dialog = ModifyDB(db_file=path, modal=False)
    try:
        dialog.tab_widget.setCurrentWidget(dialog.report_records_tab)
        dialog.ensure_record_tables_loaded()
        model = dialog.report_records_table.model()
        assert model.rowCount() == 2
        for text in (str(tmp_path / "report.pdf"), "cmm", "inspection / 3.1", "manual"):
            dialog.report_filter_edit.setText(text)
            dialog.flush_record_filters()
            assert model.rowCount() == 1
            assert model.index(0, 0).data(Qt.ItemDataRole.UserRole) == report

        dialog.report_filter_edit.setText("other_parser")
        dialog.flush_record_filters()
        assert model.index(0, 0).data(Qt.ItemDataRole.UserRole) == other
        dialog.report_warnings_filter.setChecked(True)
        dialog.flush_record_filters()
        assert model.rowCount() == 0
        dialog.report_filter_edit.clear()
        dialog.flush_record_filters()
        assert model.rowCount() == 1
        assert model.index(0, 0).data(Qt.ItemDataRole.UserRole) == report

        warning_column = dialog._column_index_for_field(model.specs, "review_warning_count")
        assert model.index(0, warning_column).data(Qt.ItemDataRole.UserRole) == 27
        source_column = dialog._column_index_for_field(model.specs, "source_file_id")
        assert dialog.report_records_table.isColumnHidden(source_column)
        for name in ("absolute_path", "parser_id", "parse_status", "metadata_profile", "review_warning_count"):
            column = dialog._column_index_for_field(model.specs, name)
            assert not model.flags(model.index(0, column)) & Qt.ItemFlag.ItemIsEditable

        dialog.report_records_table.setCurrentIndex(model.index(0, 0))
        dialog.report_details_button.click()
        detail_window = next(window for window in dialog.findChildren(QDialog)
                             if window.windowTitle() == f"Report details · #{report}")
        detail_view = detail_window.findChild(QPlainTextEdit)
        assert detail_view.isReadOnly()
        assert detail_view.accessibleName() == "Stored report details"
        detail = detail_view.toPlainText()
        assert f"Source path: {tmp_path / 'report.pdf'}" in detail
        assert f"Source SHA-256: {hashlib.sha256(b'report.pdf-content').hexdigest()}" in detail
        assert "Metadata profile: inspection / 3.1" in detail
        assert "Parser: cmm" in detail and "Parser version: 1.0" in detail and "Parse status: parsed" in detail
        assert "Measurements: 1" in detail and "NOK measurements: 1" in detail
        assert "Review warnings: 27" in detail and "2 more stored warning(s)." in detail
        assert "Warning · ocr_confidence · report_date" in detail
        assert "Error · sample_mismatch · sample_number: <b>Double-check the sample.</b>" in detail
        assert "end-marker" not in detail and "info_note" not in detail
        assert "report_date: 2024-01-01 (header_exact / ocr)" in detail
        assert "reference: MANUAL (Manual /" in detail
        assert "Stored OCR decisions" in detail
        assert "Reference · Deferred · Suggested value: OCR-REFERENCE" in detail
        assert "Revision · Rejected · Suggested value: B" in detail
        assert "header_exact / page1_header_band_ocr / page 1 / 79% confidence" in detail
        assert "Comment · Deferred · Suggested value: line one line two" in detail and "…" in detail
        assert "sentinel" not in detail and "\u202e" not in detail and "OTHER-REPORT-DECISION" not in detail
        detail_window.reject()

        dialog.report_warnings_filter.setChecked(False)
        dialog.report_filter_edit.setText("other_parser")
        dialog.flush_record_filters()
        dialog.report_records_table.setCurrentIndex(model.index(0, 0))
        dialog.report_details_button.click()
        second_window = next(window for window in dialog.findChildren(QDialog)
                             if window.windowTitle() == f"Report details · #{other}")
        other_detail = second_window.findChild(QPlainTextEdit).toPlainText()
        assert "Part name · Rejected · Suggested value: OTHER-REPORT-DECISION" in other_detail
        assert "OCR-REFERENCE" not in other_detail and "Comment · Deferred" not in other_detail
        second_window.reject()
        assert not dialog.has_pending_changes() and _dump(path) == before
    finally:
        dialog.close()


@pytest.mark.parametrize("payload", [
    None, "", b"\x80", "{", "[" * 2000 + "]" * 2000,
    '{"metadata_review":{"version":1,"ocr_fields":["reference"]}}',
    '{"metadata_review":{"version":true,"ocr_decisions":{"reference":{}}}}',
    '{"metadata_review":{"version":2,"ocr_decisions":{"reference":{}}}}',
    '{"metadata_review":{"version":1,"ocr_decisions":[]}}',
    '{"metadata_review":{"version":1,"ocr_decisions":{"reference":{"decision":"deferred","value":7}}}}',
    '{"metadata_review":{"version":1,"ocr_decisions":{"reference":{"decision":"deferred",'
    '"value":"SKIP-OVERLONG", "source_type":"header_exact"}}},"extra":"' + "x" * 300_000 + '"}',
], ids=["missing", "blank", "invalid-utf8", "invalid-json", "deep-json", "pre-disposition", "wrong-version-type",
        "future-version", "invalid-decisions", "invalid-value", "oversized"])
def test_stored_report_context_ignores_unusable_ocr_receipts(tmp_path, payload):
    path, _repository, report, _other, _measurements = _database(tmp_path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE report_metadata SET metadata_json = CAST(? AS TEXT) WHERE report_id = ?",
                           (payload, report))
    before = (tmp_path / "reports.db").read_bytes()
    context = load_stored_report_context(path, report)
    assert context.report["file_name"] == "report.pdf" and context.ocr_decisions == ()
    assert load_stored_report_context(path, 999_999) is None
    assert (tmp_path / "reports.db").read_bytes() == before


def test_stored_report_context_accepts_an_older_database_without_a_receipt_column(tmp_path):
    path = tmp_path / "older.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE report_metadata (report_id INTEGER PRIMARY KEY, reference TEXT)")
        connection.execute("CREATE VIEW vw_report_overview AS SELECT 7 AS report_id, 'legacy.pdf' AS file_name")
    before = path.read_bytes()
    context = load_stored_report_context(str(path), 7)
    assert context.report == {"report_id": 7, "file_name": "legacy.pdf"}
    assert context.ocr_decisions == () and path.read_bytes() == before


def _deferred_reference(tmp_path):
    path, repository, report, other, _measurements = _database(tmp_path)
    proposed = "OCR-" + "X" * 130 + "-TAIL"
    repository.replace_metadata_candidates(report, (
        MetadataCandidate("reference", "original OCR string", proposed, "header_exact", "ocr", 1,
                          "page1_header_band_ocr", "DRAWING No", "ocr:reference", 0.91, "exact evidence"),
    ))
    repository.update_report_metadata_fields(report, {"reference": "KEEP-REF", "part_name": "KEEP-PART"})
    with closing(sqlite3.connect(path)) as connection, connection:
        metadata_json, = connection.execute("SELECT metadata_json FROM report_metadata WHERE report_id = ?",
                                            (report,)).fetchone()
        provenance = json.loads(metadata_json)
        provenance["metadata_review"] = {
            "version": 1, "ocr_fields": [], "accepted_ocr_fields": [], "edited_fields": ["reference", "part_name"],
            "ocr_decisions": {
                "reference": {"decision": "deferred", "value": proposed, "source_type": "header_exact",
                              "page_number": 1, "region_name": "page1_header_band_ocr", "rule_id": "ocr:reference",
                              "confidence": 0.91},
            },
        }
        connection.execute("UPDATE report_metadata SET metadata_json = ? WHERE report_id = ?",
                           (json.dumps(provenance), report))
    return path, repository, report, other, proposed


@pytest.mark.parametrize("change", [
    "candidate", "canonical", "source", "receipt", "ambiguous", "missing", "overlarge-evidence", "other-database",
])
def test_accepting_stored_ocr_rejects_stale_or_ambiguous_evidence(tmp_path, change):
    path, repository, report, _other, _proposed = _deferred_reference(tmp_path)
    decision, = load_stored_report_context(path, report).ocr_decisions
    approval = decision.approval
    assert approval is not None
    if change == "other-database":
        new_path = tmp_path / "different.db"
        with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(new_path)) as target:
            source.backup(target)
        new_path.replace(path)
    else:
        with closing(sqlite3.connect(path)) as connection, connection:
            if change == "candidate":
                connection.execute("UPDATE report_metadata_candidates SET evidence_text = 'changed' WHERE id = ?",
                                   (approval.candidate_id,))
            elif change == "canonical":
                connection.execute("UPDATE report_metadata SET reference = 'CHANGED' WHERE report_id = ?", (report,))
            elif change == "source":
                connection.execute("UPDATE source_files SET sha256 = ? WHERE id = ("
                                   "SELECT source_file_id FROM parsed_reports WHERE id = ?)", ("2" * 64, report))
            elif change == "receipt":
                connection.execute("UPDATE report_metadata SET metadata_json = '{}' WHERE report_id = ?", (report,))
            elif change == "ambiguous":
                connection.execute(
                    "INSERT INTO report_metadata_candidates (report_id, field_name, normalized_value, source_type, "
                    "page_number, region_name, rule_id, confidence, created_at) SELECT report_id, field_name, "
                    "normalized_value, source_type, page_number, region_name, rule_id, confidence, created_at "
                    "FROM report_metadata_candidates WHERE id = ?", (approval.candidate_id,),
                )
            elif change == "overlarge-evidence":
                connection.execute("UPDATE report_metadata_candidates SET evidence_text = ? WHERE id = ?",
                                   ("x" * 300_000, approval.candidate_id))
            else:
                connection.execute("DELETE FROM report_metadata_candidates WHERE id = ?", (approval.candidate_id,))
    if change in {"ambiguous", "missing", "overlarge-evidence"}:
        stored, = load_stored_report_context(path, report).ocr_decisions
        assert stored.approval is None
    before = _dump(path)
    with pytest.raises((ValueError, sqlite3.OperationalError), match="changed|replaced|no longer"):
        repository.accept_deferred_ocr(approval)
    assert _dump(path) == before


def test_stored_ocr_cannot_share_a_save_with_regular_edits(tmp_path):
    path, _repository, report, other, _proposed = _deferred_reference(tmp_path)
    decision, = load_stored_report_context(path, report).ocr_decisions
    assert decision.approval is not None
    before = _dump(path)
    with pytest.raises(ValueError, match="separately from other edits"):
        ReportEditService(path).apply_changes_with_receipt(
            storage_flavor="current", normalization_changes={}, stored_ocr_approval=decision.approval,
            report_updates=[(other, {"reference": "OTHER-CHANGE"})],
        )
    assert _dump(path) == before


def test_accepting_deferred_ocr_from_report_details_preserves_exact_stored_candidate(
    tmp_path, qapplication_session, monkeypatch,
):
    path, _repository, report, other, proposed = _deferred_reference(tmp_path)
    before = _dump(path)
    decision, = load_stored_report_context(path, report).ocr_decisions
    approval = decision.approval
    assert approval is not None and decision.value != proposed  # dialog summary is truncated
    old_evidence = next(row for row in before["report_metadata_candidates"] if row[0] == approval.candidate_id)
    dialog = ModifyDB(db_file=path, modal=False)
    committed, confirmations = [], []
    choices = iter((QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes))

    def confirm(message_box):
        confirmations.append((message_box.text(), message_box.detailedText()))
        return next(choices)

    monkeypatch.setattr(QMessageBox, "exec", confirm)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args: None)
    dialog.database_edited.connect(committed.append)
    try:
        dialog.ensure_record_tables_loaded()
        model = dialog.report_records_table.model()
        dialog.report_records_table.setCurrentIndex(model.index(0, 0))
        assert model.index(0, 0).data(Qt.ItemDataRole.UserRole) == report
        dialog.report_details_button.click()
        details = next(window for window in dialog.findChildren(QDialog)
                       if window.windowTitle() == f"Report details · #{report}")
        accept = next(button for button in details.findChildren(QPushButton) if button.text() == "Use OCR suggestion")

        dialog.reference_table.item(0, 1).setText("UNSAVED")
        accept.click()
        assert not confirmations and not committed and _dump(path) == before
        assert dialog.has_pending_changes()
        dialog.reference_table.item(0, 1).setText(dialog.reference_table.item(0, 1).data(Qt.ItemDataRole.UserRole))
        assert not dialog.has_pending_changes()

        accept.click()
        assert len(confirmations) == 1 and not committed and _dump(path) == before
        accept.click()
        _wait_edit(dialog)
        assert len(confirmations) == 2 and all(proposed in "\n".join(prompt) for prompt in confirmations)
        assert committed == [path]
        context = load_stored_report_context(path, report)
        accepted, = context.ocr_decisions
        assert accepted.decision == "accepted" and accepted.approval is None
        assert "Reference · Accepted · Accepted value: OCR-" in dialog._report_details_text(context)
        with closing(sqlite3.connect(path)) as connection:
            value, part_name, metadata_json = connection.execute(
                "SELECT reference, part_name, metadata_json FROM report_metadata WHERE report_id = ?", (report,),
            ).fetchone()
            assert (value, part_name) == (proposed, "KEEP-PART")
            provenance = json.loads(metadata_json)
            assert list(provenance["manual_overrides"]) == ["part_name"]
            assert provenance["field_sources"]["reference"] == "header_exact"
            assert provenance["metadata_review"]["accepted_ocr_fields"] == ["reference"]
            assert connection.execute("SELECT reference_source FROM report_parse_state WHERE report_id = ?",
                                      (report,)).fetchone() == ("header_exact",)
        after = _dump(path)
        selected = [row for row in after["report_metadata_candidates"] if row[1:3] == (report, "reference")]
        assert {row[0] for row in selected} == {row[0] for row in before["report_metadata_candidates"]
                                                 if row[1:3] == (report, "reference")}
        chosen = next(row for row in selected if row[12])
        assert chosen[0] == approval.candidate_id and chosen[:12] + chosen[13:] == old_evidence[:12] + old_evidence[13:]
        assert before["report_measurements"] == after["report_measurements"]
        assert [row for row in before["parsed_reports"] if row[0] == other] == [
            row for row in after["parsed_reports"] if row[0] == other
        ]
    finally:
        dialog._discard_confirmed = True
        dialog.close()


def test_external_record_update_keeps_pending_modify_db_draft(tmp_path, qapplication_session, monkeypatch):
    from metroliza.ui import modify_db
    path, _repository, report, _other, _measurements = _database(tmp_path)
    dialog = ModifyDB(db_file=path, modal=False)
    messages = []
    monkeypatch.setattr(modify_db.QMessageBox, "critical", lambda *args: messages.append(args[1:]))
    monkeypatch.setattr(modify_db.QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(modify_db, "CustomLogger", lambda *args, **kwargs: None)
    try:
        dialog.ensure_record_tables_loaded()
        model = dialog.report_records_table.model()
        column = dialog._column_index_for_field(model.specs, "reference")
        cell = model.index(0, column)
        assert model.index(0, 0).data(Qt.ItemDataRole.UserRole) == report
        assert model.setData(cell, "EDITOR DRAFT")
        dialog.part_number_table.item(0, 1).setText("NEW SAMPLE")
        ReportEditService(path).apply_changes(
            storage_flavor="current", normalization_changes={}, report_updates=[(report, {"reference": "EXTERNAL"})],
        )
        external_state = _dump(path)
        dialog.apply_changes()
        _wait_edit(dialog)
        assert len(messages) == 1 and messages[0][0] == "Nothing was saved"
        assert "database changed" in messages[0][1] and "Pending edits were kept" in messages[0][1]
        assert not dialog._changes_committed and dialog.has_pending_changes()
        assert cell.data() == "EDITOR DRAFT" and dialog.part_number_table.item(0, 1).text() == "NEW SAMPLE"
        assert _dump(path) == external_state
    finally:
        dialog._discard_confirmed = True
        dialog.close()


def test_f02_gui_remains_responsive_and_sqlite_owned_by_worker(tmp_path, qapplication_session, monkeypatch):
    from metroliza.ui import modify_db
    from metroliza.reports import db
    path, _repo, _report, _other, _ids = _database(tmp_path)
    dialog = ModifyDB(db_file=path, modal=False)
    dialog.reference_table.item(0, 1).setText('WORKER')
    gui = threading.get_ident()
    write_started, gate = threading.Event(), threading.Event()
    owners, write_owners, beats, released = [], [], [], []
    connect = db.connect_sqlite

    def hold_normalization_write(statement):
        if statement.startswith('UPDATE report_metadata SET reference = '):
            write_owners.append(threading.get_ident())
            if not write_started.is_set():
                write_started.set()
                released.append(gate.wait(5))

    def tracked_connect(*args, **kwargs):
        owners.append(threading.get_ident())
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(hold_normalization_write)
        return connection

    timer = QTimer()

    def finish_gui_beat():
        if write_started.is_set():
            beats.append(threading.get_ident())
            gate.set()
            timer.stop()

    monkeypatch.setattr(db, 'connect_sqlite', tracked_connect)
    monkeypatch.setattr(modify_db.QMessageBox, 'information', lambda *args: None)
    timer.timeout.connect(finish_gui_beat)
    timer.start(10)
    try:
        dialog.apply_changes()
        _wait_edit(dialog)
        assert beats == [gui] and owners and gui not in owners
        assert len(write_owners) == 2 and all(owner in owners for owner in write_owners)
        assert released == [True]
        assert dialog._changes_committed
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute(
                'SELECT reference FROM report_metadata ORDER BY report_id',
            ).fetchall() == [('WORKER',), ('WORKER',)]
    finally:
        timer.stop()
        gate.set()
        dialog._discard_confirmed = True
        dialog.close()


def _alias_csv(tmp_path):
    path = str(tmp_path / 'aliases.db')
    aliases.ensure_characteristic_alias_schema(path)
    aliases.upsert_characteristic_alias(path, 'OLD', 'Old name', 'global')
    aliases.upsert_characteristic_alias(path, 'SAME', 'Same name', 'reference', 'REF')
    csv = tmp_path / 'aliases.csv'
    csv.write_text('alias_name,canonical_name,scope_type,scope_value\n'
                   'OLD,New name,global,\nNEW,Added name,global,\nSAME,Same name,reference,REF\n')
    return path, str(csv)


def test_f03_preview_classifies_and_only_new_keeps_existing(tmp_path):
    path, csv = _alias_csv(tmp_path)
    before = _dump(path)
    assert hasattr(aliases, 'preview_characteristic_aliases_csv'), 'CSV import needs a read-only preview'
    plan = aliases.preview_characteristic_aliases_csv(path, csv)
    assert (plan.added, plan.replaced, plan.unchanged) == (1, 1, 1)
    assert 'Old name → New name' in plan.replacement_lines()[0]
    assert _dump(path) == before
    assert aliases.apply_characteristic_alias_import(path, plan) == 1
    names = {row['alias_name']: row['canonical_name'] for row in aliases.fetch_all_characteristic_aliases(path)}
    assert names == {'OLD': 'Old name', 'NEW': 'Added name', 'SAME': 'Same name'}


def test_f03_write_failure_after_first_real_alias_mutation_is_atomic(tmp_path):
    path, csv = _alias_csv(tmp_path)
    assert hasattr(aliases, 'preview_characteristic_aliases_csv'), 'CSV import needs a read-only preview'
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("""CREATE TRIGGER fail_second BEFORE INSERT ON CHARACTERISTIC_ALIASES
            WHEN NEW.alias_name='NEW' AND
            (SELECT canonical_name FROM CHARACTERISTIC_ALIASES WHERE alias_name='OLD')='New name'
            BEGIN SELECT RAISE(ABORT, 'after first alias mutation'); END""")
    plan = aliases.preview_characteristic_aliases_csv(path, csv)
    before = _dump(path)
    with pytest.raises(sqlite3.IntegrityError, match='after first alias mutation'):
        aliases.apply_characteristic_alias_import(path, plan, replace=True)
    assert _dump(path) == before


def test_f03_real_review_defaults_to_only_new_and_bounds_replacements(tmp_path, qapplication_session, monkeypatch):
    from metroliza.ui import characteristic_mapping_dialog as ui
    path, csv = _alias_csv(tmp_path)
    assert hasattr(aliases, 'preview_characteristic_aliases_csv'), 'CSV import needs a read-only preview'
    plan = aliases.preview_characteristic_aliases_csv(path, csv)
    dialog = ui.CharacteristicMappingDialog(db_file=path)

    def inspect_box(box):
        assert box.defaultButton().text() == 'Import only new'
        assert 'Added: 1 / Replaced: 1 / Unchanged: 1' in box.text()
        assert 'Old name → New name' in box.text()
        return ui.QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(ui.QMessageBox, 'exec', inspect_box)
    assert dialog._confirm_alias_import(plan) is None
    long_plan = aliases.AliasImportPlan(plan.rows * 100, plan.snapshot * 100, 100, 100, 100)
    assert len(long_plan.replacement_lines()) == 21
    assert long_plan.replacement_lines()[-1] == '… 80 more replacement(s)'
    dialog.close()


@pytest.mark.parametrize('change', ['replace', 'add', 'delete'])
def test_f03_stale_preview_aborts_atomically(tmp_path, change):
    path, csv = _alias_csv(tmp_path)
    assert hasattr(aliases, 'preview_characteristic_aliases_csv'), 'CSV import needs a read-only preview'
    plan = aliases.preview_characteristic_aliases_csv(path, csv)
    if change == 'delete':
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("DELETE FROM CHARACTERISTIC_ALIASES WHERE alias_name='OLD'")
    else:
        aliases.upsert_characteristic_alias(path, 'OLD' if change == 'replace' else 'NEW', 'Concurrent', 'global')
    before = _dump(path)
    with pytest.raises(ValueError, match='changed after preview'):
        aliases.apply_characteristic_alias_import(path, plan, replace=True)
    assert _dump(path) == before


@pytest.mark.parametrize('choice', [None, False, True])
def test_f03_native_gui_review_cancel_only_new_and_replace(tmp_path, qapplication_session, monkeypatch, choice):
    from metroliza.ui import characteristic_mapping_dialog as ui
    path, csv = _alias_csv(tmp_path)
    before = _dump(path)
    dialog = ui.CharacteristicMappingDialog(db_file=path)
    plans = []
    monkeypatch.setattr(ui.QFileDialog, 'getOpenFileName', lambda *args: (csv, ''))
    monkeypatch.setattr(ui.CharacteristicMappingDialog, '_confirm_alias_import',
                        lambda self, plan: (plans.append(plan), choice)[1], raising=False)
    monkeypatch.setattr(ui.QMessageBox, 'information', lambda *args: None)
    monkeypatch.setattr(ui.QMessageBox, 'critical', lambda *args: pytest.fail(str(args)))
    dialog.import_mappings()
    from PyQt6.QtTest import QTest
    for _ in range(500):
        qapplication_session.processEvents()
        if dialog._alias_csv_thread is None:
            break
        QTest.qWait(10)
    assert dialog._alias_csv_thread is None
    if choice is None:
        assert _dump(path) == before
    else:
        names = {row['alias_name']: row['canonical_name'] for row in aliases.fetch_all_characteristic_aliases(path)}
        assert names['OLD'] == ('New name' if choice else 'Old name')
        assert names['NEW'] == 'Added name'
    assert plans, 'Import must show a preview before any upsert'
    dialog.close()


@pytest.mark.parametrize("text", ["1e999999999", "3e0", "1E2"])
def test_c2_integer_fields_reject_exponent_notation(text):
    from metroliza.reports.report_repository import validate_manual_number

    with pytest.raises(ValueError):
        validate_manual_number(text, integer=True)


@pytest.mark.parametrize("text", ["1,234e0", "1e9999", "1.5e1000"])
def test_c2_float_rejects_ambiguous_mantissa_and_unbounded_exponent(text):
    from metroliza.reports.report_repository import validate_manual_number

    with pytest.raises(ValueError):
        validate_manual_number(text)


def test_c2_float_keeps_bounded_exponent():
    from metroliza.reports.report_repository import validate_manual_number

    assert validate_manual_number("1,5e2") == 150.0


@pytest.mark.parametrize("text", ["٣", "١,٢٣٤", "１０,５"])
def test_c2_manual_numbers_require_ascii_digits(text):
    from metroliza.reports.report_repository import validate_manual_number

    with pytest.raises(ValueError):
        validate_manual_number(text)
