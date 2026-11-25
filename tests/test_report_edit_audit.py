"""Exercise the local receipt through the transactional edit and dialog paths."""

from contextlib import closing, nullcontext
from dataclasses import FrozenInstanceError
import json
import sqlite3
import time

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox

from metroliza.reports import report_edit_audit
from metroliza.reports.report_edit_audit import AUDIT_SAMPLE_LIMIT, OmittedEditValue
from metroliza.reports.report_edit_service import ReportEditService
from metroliza.reports.report_identity import build_report_identity_hash
from metroliza.reports.report_metadata_models import CanonicalReportMetadata
from metroliza.reports.report_query_service import build_measurement_filter_query
from metroliza.reports.report_repository import ReportRepository, SEMANTIC_DUPLICATE_WARNING_CODE
from metroliza.reports.report_schema import ensure_report_schema
from metroliza.ui.modify_db import ModifyDB


_CANARY = "SYNTHETIC PRIVATE EDIT"


def _make_current_database(database):
    ensure_report_schema(str(database))
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript("""
            INSERT INTO source_files (id, sha256, source_format, discovered_at)
                VALUES (1, 'synthetic-content-id', 'pdf', '2026-01-05');
            INSERT INTO parsed_reports (
                id, source_file_id, parser_id, template_family, parse_status, created_at, updated_at
            ) VALUES (2, 1, 'cmm', 'synthetic', 'parsed', '2026-01-05', '2026-01-05');
            INSERT INTO report_metadata (report_id, reference, metadata_version)
                VALUES (2, 'ORIGINAL', '1');
            INSERT INTO report_measurements (id, report_id, row_order, meas, status_code)
                VALUES (3, 2, 0, NULL, 'ok');
        """)


def _edit_report_comment(dialog, text):
    dialog.ensure_record_tables_loaded()
    model = dialog.report_records_table.model()
    column = next(index for index, spec in enumerate(model.specs) if spec["field"] == "comment")
    assert model.setData(model.index(0, column), text)


def test_canonical_receipt_reads_initial_and_committed_typed_values(tmp_path):
    database = tmp_path / "reports.sqlite"
    _make_current_database(database)

    receipt = ReportEditService(str(database)).apply_changes_with_receipt(
        storage_flavor="current",
        normalization_changes={"reference": (("INTERMEDIATE", "ORIGINAL"),)},
        report_updates=((2, {"reference": _CANARY}),),
        measurement_updates=((3, {"meas": "0"}),),
    )

    assert receipt.normalization_operation_count == 1
    bulk, = receipt.normalization_samples
    assert (bulk.field_name, bulk.matched_rows, bulk.requested_old, bulk.requested_new) == (
        "reference", 1, "ORIGINAL", "INTERMEDIATE",
    )
    report, measurement = receipt.record_samples
    assert (report.entity, report.record_id, report.field_name, report.before, report.after) == (
        "report", 2, "reference", "ORIGINAL", _CANARY,
    )
    assert (measurement.entity, measurement.record_id, measurement.field_name) == (
        "measurement", 3, "meas",
    )
    assert measurement.before is None
    assert type(measurement.after) is float
    assert measurement.after == 0.0
    assert receipt.unavailable_record_sample_count == 0
    assert not receipt.samples_truncated
    assert all(_CANARY not in repr(value) for value in (receipt, report, receipt.record_samples))
    with pytest.raises(FrozenInstanceError):
        report.after = "not immutable"
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT reference FROM report_metadata").fetchone() == (_CANARY,)
        assert connection.execute("SELECT meas FROM report_measurements").fetchone() == (0.0,)


def _make_bulk_database(database, matching_count):
    ensure_report_schema(str(database))
    initial_values = [(number, "A", "1", f"Part-{number}") for number in range(1, matching_count + 1)]
    initial_values.extend(((matching_count + 1, "B", "2", "Other"), (matching_count + 2, "C", "3", "Part-1")))
    with closing(sqlite3.connect(database)) as connection, connection:
        for report_id, reference, sample, part in initial_values:
            identity = build_report_identity_hash(CanonicalReportMetadata(
                parser_id="cmm", template_family="synthetic", template_variant=None, metadata_confidence=0.0,
                reference=reference, reference_raw=None, report_date=None, report_time=None, part_name=part,
                revision=None, sample_number=sample, sample_number_kind=None, stats_count_raw=None,
                stats_count_int=None, operator_name=None, comment=None, page_count=None, metadata_json={}, warnings=(),
            ))
            connection.execute(
                "INSERT INTO source_files (id, sha256, source_format, discovered_at) VALUES (?, ?, 'pdf', '2026-01-05')",
                (report_id, f"report-{report_id}"),
            )
            connection.execute(
                "INSERT INTO parsed_reports (id, source_file_id, parser_id, template_family, parse_status, "
                "identity_hash, created_at, updated_at) VALUES (?, ?, 'cmm', 'synthetic', 'parsed', ?, '2026-01-05', '2026-01-05')",
                (report_id, report_id, identity),
            )
            connection.execute(
                "INSERT INTO report_metadata (report_id, reference, sample_number, part_name, metadata_version) "
                "VALUES (?, ?, ?, ?, '1')",
                (report_id, reference, sample, part),
            )
        connection.executemany(
            "INSERT INTO report_metadata_candidates (report_id, field_name, raw_value, normalized_value, "
            "source_type, rule_id, confidence, is_selected, evidence_text, created_at) "
            "VALUES (1, ?, ?, ?, 'header_exact', 'test_ocr', 1, 1, ?, '2026-01-05')",
            (("reference", "A", "A", "DRAWING No A"), ("sample_number", "1", "1", "SAMPLE NO 1")),
        )
        connection.execute(
            "INSERT INTO report_measurements (report_id, row_order, header, status_code) VALUES (1, 0, 'OLD', 'ok')"
        )


def _dump_database(database):
    with closing(sqlite3.connect(database)) as connection:
        return list(connection.iterdump())


def test_current_bulk_normalization_reconciles_evidence_across_pages_and_keeps_matched_counts(tmp_path):
    database = tmp_path / "bulk.sqlite"
    _make_bulk_database(database, matching_count=130)
    service = ReportEditService(str(database))

    receipt = service.apply_changes_with_receipt(
        storage_flavor="current",
        normalization_changes={
            "sample_number": (("2", "1"), ("3", "2")),
            "header": (("NEW", "OLD"),),
            "reference": (("B", "A"), ("C", "B")),
        },
    )

    assert receipt.normalization_operation_count == 5
    assert [(row.field_name, row.matched_rows) for row in receipt.normalization_samples] == [
        ("reference", 130), ("reference", 131), ("sample_number", 130), ("sample_number", 131), ("header", 1),
    ]
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT reference, sample_number, count(*) FROM report_metadata").fetchone() == (
            "C", "3", 132,
        )
        assert connection.execute("SELECT header FROM report_measurements").fetchone() == ("NEW",)
        for (metadata_json,) in connection.execute("SELECT metadata_json FROM report_metadata ORDER BY report_id LIMIT 131"):
            provenance = json.loads(metadata_json)
            assert provenance["field_sources"] == {"reference": "manual", "sample_number": "manual"}
            assert {field: (edit["value"], edit["reason"]) for field, edit in provenance["manual_overrides"].items()} == {
                "reference": ("C", "bulk_normalization"), "sample_number": ("3", "bulk_normalization"),
            }
        assert connection.execute("SELECT metadata_json FROM report_metadata WHERE report_id = 132").fetchone() == (None,)
        assert connection.execute(
            "SELECT field_name, raw_value, source_type, is_selected, evidence_text FROM report_metadata_candidates "
            "WHERE report_id = 1 ORDER BY field_name, id",
        ).fetchall() == [
            ("reference", "A", "header_exact", 0, "DRAWING No A"),
            ("reference", "B", "user_manual", 0, None),
            ("reference", "C", "user_manual", 1, None),
            ("sample_number", "1", "header_exact", 0, "SAMPLE NO 1"),
            ("sample_number", "2", "user_manual", 0, None),
            ("sample_number", "3", "user_manual", 1, None),
        ]
        assert connection.execute(
            "SELECT reference_source FROM report_parse_state WHERE report_id = 1",
        ).fetchone() == ("manual",)
        hashes = connection.execute("SELECT identity_hash FROM parsed_reports WHERE id IN (1, 132) ORDER BY id").fetchall()
        assert hashes[0] == hashes[1]
        warning, = connection.execute(
            "SELECT details_json FROM report_metadata_warnings WHERE report_id = 1 AND code = ?",
            (SEMANTIC_DUPLICATE_WARNING_CODE,),
        ).fetchone()
        assert json.loads(warning)["duplicate_report_ids"] == [132]


def test_current_bulk_noop_counts_matches_without_rewriting_manual_history(tmp_path):
    database = tmp_path / "bulk-noop.sqlite"
    _make_bulk_database(database, matching_count=2)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "CREATE TRIGGER reject_noop BEFORE UPDATE OF reference ON report_metadata "
            "BEGIN SELECT RAISE(ABORT, 'unexpected update for same value'); END"
        )
    before = _dump_database(database)

    receipt = ReportEditService(str(database)).apply_changes_with_receipt(
        storage_flavor="current", normalization_changes={"reference": (("A", "A"), ("ANY", "MISSING"))},
    )

    assert [sample.matched_rows for sample in receipt.normalization_samples] == [2, 0]
    assert _dump_database(database) == before


def test_current_bulk_late_header_failure_rolls_back_domain_and_header_mutations(tmp_path):
    database = tmp_path / "bulk-rollback.sqlite"
    _make_bulk_database(database, matching_count=2)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "CREATE TRIGGER reject_header AFTER UPDATE OF header ON report_measurements WHEN ("
            "SELECT count(*) FROM report_metadata_candidates WHERE source_type = 'user_manual' AND is_selected = 1"
            ") = 4 BEGIN SELECT RAISE(ABORT, 'late normalization rollback'); END"
        )
    before = _dump_database(database)

    with pytest.raises(sqlite3.IntegrityError, match="late normalization rollback"):
        ReportEditService(str(database)).apply_changes(
            storage_flavor="current",
            normalization_changes={"reference": (("EDITED", "A"),), "sample_number": (("4", "1"),),
                                   "header": (("NEW", "OLD"),)},
        )

    assert _dump_database(database) == before


@pytest.mark.parametrize(("entrypoint", "old_kind"), [("bulk", "filename_tail"), ("record", "stats_count")])
def test_manual_sample_number_uses_unknown_kind_and_preserves_original_evidence(tmp_path, entrypoint, old_kind):
    database = tmp_path / "sample-kind.sqlite"
    _make_bulk_database(database, matching_count=1)
    old_source = "filename_candidate" if old_kind == "filename_tail" else "projected_from_stats_count"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "UPDATE report_metadata SET sample_number_kind = ?, metadata_json = ? WHERE report_id = 1",
            (old_kind, json.dumps({"field_sources": {"sample_number": old_source, "part_name": "filename_candidate"},
                                   "sample_number_provenance": old_source})),
        )
        connection.execute(
            "UPDATE report_metadata_candidates SET source_type = ? WHERE report_id = 1 AND field_name = 'sample_number'",
            (old_source,),
        )
        connection.executemany(
            "INSERT INTO report_metadata_warnings (report_id, code, field_name, severity, message, created_at) "
            "VALUES (1, ?, ?, 'info', 'Synthetic warning', '2026-01-05')",
            (("sample_number_projected_from_stats_count", "sample_number"), ("unrelated", "reference")),
        )
    service = ReportEditService(str(database))

    def edit(new):
        if entrypoint == "bulk":
            service.apply_changes(storage_flavor="current", normalization_changes={"sample_number": ((new, "1"),)})
        else:
            service.apply_changes(storage_flavor="current", normalization_changes={},
                                  report_updates=((1, {"sample_number": new}),))

    with closing(sqlite3.connect(database)) as connection:
        assert len(connection.execute(build_measurement_filter_query(sample_number_kind_values=(old_kind,))).fetchall()) == 1
    before = _dump_database(database)
    edit("1")
    assert _dump_database(database) == before
    edit("MANUAL-5")

    def assert_sample(expected):
        with closing(sqlite3.connect(database)) as connection:
            sample, kind, raw_json = connection.execute(
                "SELECT sample_number, sample_number_kind, metadata_json FROM report_metadata WHERE report_id = 1",
            ).fetchone()
            assert (sample, kind) == (expected, "unknown")
            metadata_json = json.loads(raw_json)
            assert metadata_json["field_sources"] == {"sample_number": "manual", "part_name": "filename_candidate"}
            assert metadata_json["sample_number_provenance"] == "manual"
            assert metadata_json["manual_overrides"]["sample_number"]["value"] == expected
            old_rows = connection.execute(build_measurement_filter_query(sample_number_kind_values=(old_kind,))).fetchall()
            new_rows = connection.execute(build_measurement_filter_query(sample_number_kind_values=("unknown",))).fetchall()
            assert old_rows == [] and len(new_rows) == 1
            assert connection.execute(
                "SELECT code, field_name FROM report_metadata_warnings WHERE report_id = 1 ORDER BY id",
            ).fetchall() == [("unrelated", "reference")]
            assert connection.execute(
                "SELECT raw_value, source_type, is_selected, evidence_text FROM report_metadata_candidates "
                "WHERE report_id = 1 AND field_name = 'sample_number' ORDER BY id",
            ).fetchall() == [
                ("1", old_source, 0, "SAMPLE NO 1"), ("MANUAL-5", "user_manual", int(expected is not None), None),
            ]

    assert_sample("MANUAL-5")
    ReportRepository(str(database)).update_report_metadata_fields(1, {"sample_number": None})
    assert_sample(None)


def test_legacy_chained_normalizations_count_matches_and_bound_the_combined_samples(tmp_path):
    database = tmp_path / "legacy.sqlite"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript("""
            CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT);
            CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY, MEAS REAL);
            INSERT INTO REPORTS VALUES (1, 'FIRST'), (2, 'FIRST'), (3, 'SECOND');
        """)
        connection.executemany("INSERT INTO MEASUREMENTS VALUES (?, NULL)", ((n,) for n in range(20)))
    service = ReportEditService(str(database))

    receipt = service.apply_changes_with_receipt(
        storage_flavor="legacy",
        normalization_changes={"reference": (("SECOND", "FIRST"), ("THIRD", "SECOND"))},
        report_updates=((1, {"unavailable_legacy_field": "ignored"}),),
        measurement_updates=tuple((n, {"meas": "0"}) for n in range(20)),
    )

    assert [sample.matched_rows for sample in receipt.normalization_samples] == [2, 3]
    assert receipt.normalization_operation_count == 2
    assert len(receipt.record_samples) + len(receipt.normalization_samples) == AUDIT_SAMPLE_LIMIT
    assert receipt.samples_truncated
    assert all(sample.entity == "measurement" and sample.before is None for sample in receipt.record_samples)
    assert all(type(sample.after) is float and sample.after == 0.0 for sample in receipt.record_samples)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT DISTINCT REFERENCE FROM REPORTS").fetchall() == [("THIRD",)]
        assert connection.execute("SELECT count(*) FROM MEASUREMENTS WHERE MEAS = 0").fetchone() == (20,)


def test_large_sample_values_are_explicitly_omitted(tmp_path):
    database = tmp_path / "reports.sqlite"
    _make_current_database(database)
    oversized = _CANARY + "ą" * 300
    receipt = ReportEditService(str(database)).apply_changes_with_receipt(
        storage_flavor="current",
        normalization_changes={},
        report_updates=((2, {"comment": oversized}),),
    )
    sample, = receipt.record_samples
    assert sample.before is None
    assert sample.after is OmittedEditValue.PREVIEW_LIMIT
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT comment FROM report_metadata").fetchone() == (oversized,)


def test_custom_adapter_result_is_unobservable_and_existing_apply_returns_none(tmp_path):
    database = tmp_path / "reports.sqlite"
    _make_current_database(database)
    payload = {
        "storage_flavor": "current", "normalization_changes": {},
        "report_updates": ((2, {"comment": _CANARY}),),
    }

    class Adapter:
        def update_report_metadata_fields(self, _id, _fields):
            self.called = True

    adapter = Adapter()
    assert ReportEditService(str(database), repository_factory=lambda _path: adapter).apply_changes_with_receipt(
        **payload
    ) is None
    assert adapter.called
    assert ReportEditService(str(database)).apply_changes(**payload) is None


def test_custom_factory_returning_exact_repository_commits_without_native_receipt(tmp_path):
    database = tmp_path / "reports.sqlite"
    _make_current_database(database)
    repository = ReportRepository(str(database))
    service = ReportEditService(str(database), repository_factory=lambda _path: repository)

    assert service.apply_changes_with_receipt(
        storage_flavor="current", normalization_changes={}, report_updates=((2, {"comment": _CANARY}),),
    ) is None
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT comment FROM report_metadata").fetchone() == (_CANARY,)


@pytest.mark.parametrize("override_at", ["instance", "class"])
def test_changed_repository_method_remains_dispatched_without_native_receipt(tmp_path, monkeypatch, override_at):
    database = tmp_path / "reports.sqlite"
    _make_current_database(database)
    calls = []

    def custom_update(_repository, report_id, _fields):
        calls.append(report_id)

    if override_at == "instance":
        original_init = ReportRepository.__init__

        def init(repository, *args, **kwargs):
            original_init(repository, *args, **kwargs)
            repository.update_report_metadata_fields = custom_update.__get__(repository, ReportRepository)

        monkeypatch.setattr(ReportRepository, "__init__", init)
    else:
        monkeypatch.setattr(ReportRepository, "update_report_metadata_fields", custom_update)

    assert ReportEditService(str(database)).apply_changes_with_receipt(
        storage_flavor="current", normalization_changes={}, report_updates=((2, {"comment": _CANARY}),),
    ) is None
    assert calls == [2]


def test_legacy_duplicate_and_missing_keys_have_explicit_unavailable_samples(tmp_path, monkeypatch):
    database = tmp_path / "legacy.sqlite"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript("""
            CREATE TABLE REPORTS (ID INTEGER, REFERENCE TEXT);
            CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY, MEAS REAL);
            INSERT INTO REPORTS VALUES (4, 'FIRST'), (4, 'SECOND');
            INSERT INTO MEASUREMENTS VALUES (1, NULL);
        """)

    original_read = report_edit_audit._read_record_value
    looked_up = []

    def checked_read(cursor, target):
        looked_up.append((target.table, target.record_id))
        return original_read(cursor, target)

    monkeypatch.setattr(report_edit_audit, "_read_record_value", checked_read)
    receipt = ReportEditService(str(database)).apply_changes_with_receipt(
        storage_flavor="legacy", normalization_changes={},
        report_updates=((4, {"reference": _CANARY}),),
        measurement_updates=((2, {"meas": "0"}), (1, {"meas": "0"})),
    )

    assert looked_up == [("MEASUREMENTS", 2), ("MEASUREMENTS", 1)] * 2
    assert receipt.unavailable_record_sample_count == 2
    assert not receipt.samples_truncated
    ambiguous, missing, observed = receipt.record_samples
    assert (ambiguous.record_id, missing.record_id, observed.record_id) == (4, 2, 1)
    for sample in (ambiguous, missing):
        assert sample.before is sample.after is OmittedEditValue.UNAVAILABLE
    assert observed.before is None and observed.after == 0.0
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT REFERENCE FROM REPORTS ORDER BY rowid").fetchall() == [(_CANARY,)] * 2
        assert connection.execute("SELECT * FROM MEASUREMENTS").fetchall() == [(1, 0.0)]


def test_dialog_preserves_instance_apply_override_without_a_receipt(
    tmp_path, monkeypatch, qapplication_session,
):
    database = tmp_path / "reports.sqlite"
    _make_current_database(database)
    service = ReportEditService(str(database))
    apply_calls, edited_paths, receipts = [], [], []
    monkeypatch.setattr(service, "apply_changes", lambda **payload: apply_calls.append(payload))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    dialog = ModifyDB(db_file=str(database), modal=False)
    monkeypatch.setattr(dialog, "collect_report_record_updates", lambda: [(2, {"comment": _CANARY})])
    monkeypatch.setattr(dialog, "_create_report_edit_service", lambda: service)
    dialog.database_edited.connect(edited_paths.append)
    dialog.database_edit_receipt.connect(receipts.append)
    try:
        dialog.apply_changes()
        assert len(apply_calls) == 1
        assert edited_paths == [str(database)]
        assert receipts == []
    finally:
        dialog._discard_confirmed = True
        dialog.close()


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("fail_commit", [False, True])
def test_apply_emits_receipt_once_only_after_commit(
    tmp_path, monkeypatch, qapplication_session, native, fail_commit,
):
    database = tmp_path / "reports.sqlite"
    _make_current_database(database)
    if fail_commit:
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.executescript("""
                CREATE TABLE parent (id INTEGER PRIMARY KEY);
                CREATE TABLE child (
                    parent_id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED
                );
                CREATE TRIGGER populate_child AFTER UPDATE OF comment ON report_metadata
                BEGIN
                    INSERT INTO child VALUES (999);
                END;
            """)

    dialog = ModifyDB(db_file=str(database) if native else database, modal=False)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    errors, edited_paths, receipts = [], [], []
    monkeypatch.setattr(dialog, "_report_save_error", errors.append)
    dialog.database_edited.connect(edited_paths.append)

    def receive(receipt):
        with closing(sqlite3.connect(database)) as connection:
            value = connection.execute("SELECT comment FROM report_metadata").fetchone()[0]
        receipts.append((receipt, value))

    dialog.database_edit_receipt.connect(receive)
    try:
        _edit_report_comment(dialog, _CANARY)
        dialog.apply_changes()
        assert (getattr(dialog, "_edit_thread", None) is not None) is native
        deadline = time.monotonic() + 5
        while getattr(dialog, "_edit_thread", None) is not None and time.monotonic() < deadline:
            qapplication_session.processEvents()
            QTest.qWait(5)
        assert getattr(dialog, "_edit_thread", None) is None
        if fail_commit:
            assert len(errors) == 1 and isinstance(errors[0], sqlite3.IntegrityError)
            assert not receipts and not edited_paths
            with closing(sqlite3.connect(database)) as connection:
                assert connection.execute("SELECT comment FROM report_metadata").fetchone() == (None,)
                assert connection.execute("PRAGMA table_info(metroliza_report_edit_receipts)").fetchall() == []
        else:
            assert not errors and edited_paths == [str(database)]
            (receipt, committed_value), = receipts
            assert committed_value == _CANARY
            sample, = receipt.record_samples
            assert sample.after == _CANARY
            if native:
                with closing(sqlite3.connect(database)) as connection:
                    assert connection.execute("SELECT count(*) FROM metroliza_report_edit_receipts").fetchone() == (1,)
    finally:
        dialog._discard_confirmed = True
        dialog.close()


@pytest.mark.parametrize("hold_wal_open", [False, True])
def test_committed_edit_refreshes_open_history_without_replacing_its_selection(
    tmp_path, monkeypatch, qapplication_session, hold_wal_open,
):
    from PyQt6.QtCore import QSettings

    from metroliza.app import analysis_history as history
    from metroliza.ui.main_window import MainWindow
    from metroliza.ui.ui_preferences import UiPreferences

    database = tmp_path / "reports.sqlite"
    _make_current_database(database)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript("""
            CREATE TABLE parent (id INTEGER PRIMARY KEY);
            CREATE TABLE child (
                parent_id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER reject_comment AFTER UPDATE OF comment ON report_metadata
            WHEN NEW.comment = 'reject this synthetic edit'
            BEGIN
                INSERT INTO child VALUES (999);
            END;
        """)
    connection_owner = closing(sqlite3.connect(database)) if hold_wal_open else nullcontext()
    with connection_owner as keeper:
        if keeper is not None:
            assert keeper.execute("PRAGMA journal_mode").fetchone() == ("wal",)
            assert keeper.execute("SELECT count(*) FROM report_metadata").fetchone() == (1,)

        monkeypatch.setattr(history, "_history_directory", lambda: tmp_path / "history")
        monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
        preferences = UiPreferences(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
        window = MainWindow("test", None, ui_preferences=preferences)
        editor = window._create_modify_database_dialog(ModifyDB, str(database))
        errors, edited_paths = [], []
        monkeypatch.setattr(editor, "_report_save_error", errors.append)
        editor.database_edited.connect(edited_paths.append)

        def wait_until(predicate):
            deadline = time.monotonic() + 5
            while not predicate() and time.monotonic() < deadline:
                qapplication_session.processEvents()
                QTest.qWait(5)
            assert predicate()

        def apply():
            editor.apply_changes()
            wait_until(lambda: getattr(editor, "_edit_thread", None) is None)

        try:
            output = tmp_path / "analysis.xlsx"
            output.touch()
            saved = history.record_analysis({"kind": "reports", "artifacts": [output], "source": database})
            window._open_analysis_history()
            dialog = window.window_coordinator.get("analysis_history")
            wait_until(lambda: dialog.runs.currentItem() is not None)
            selected = dialog.runs.currentItem()
            assert selected is not None
            assert "Published" in dialog.result.summary.text()

            apply()
            assert not edited_paths and not errors
            assert history.analysis_is_stale(saved) is False
            assert "Published" in dialog.result.summary.text()

            _edit_report_comment(editor, "reject this synthetic edit")
            apply()
            assert len(errors) == 1 and isinstance(errors[0], sqlite3.IntegrityError)
            assert not edited_paths
            assert history.analysis_is_stale(saved) is False
            assert "Published" in dialog.result.summary.text()

            _edit_report_comment(editor, _CANARY)
            main_bytes = database.read_bytes()
            apply()
            assert edited_paths == [str(database)]
            if hold_wal_open:
                assert database.read_bytes() == main_bytes
                assert database.with_name(database.name + "-wal").stat().st_size > 0
            else:
                assert database.read_bytes() != main_bytes
            assert history.analysis_is_stale(saved) is True
            assert "Source changed" in dialog.result.summary.text()
            assert dialog.runs.currentItem() is selected
        finally:
            editor._discard_confirmed = True
            editor.close()
            window.close()
