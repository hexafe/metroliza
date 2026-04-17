import sqlite3

import modules.report_metadata_persistence as report_metadata_persistence


def test_report_metadata_persistence_wrapper_delegates_to_repository(monkeypatch):
    calls = []

    class FakeRepository:
        def __init__(self, database, *, connection=None):
            calls.append(("init", database, connection))

        def ensure_schema(self):
            calls.append(("ensure_schema",))

        def persist_parsed_report(self, **kwargs):
            calls.append(("persist_parsed_report", kwargs))
            return 123

    monkeypatch.setattr(report_metadata_persistence, "ReportRepository", FakeRepository)

    marker = object()
    persistence = report_metadata_persistence.ReportMetadataPersistence("reports.db", connection=marker)
    result = persistence.persist_parsed_report(source_path="example.pdf")
    persistence.ensure_schema()

    assert result == 123
    assert calls == [
        ("init", "reports.db", marker),
        ("persist_parsed_report", {"source_path": "example.pdf"}),
        ("ensure_schema",),
    ]


def test_persist_parsed_report_wrapper_persists_through_repository(tmp_path):
    db_path = str(tmp_path / "reports.db")
    source_path = tmp_path / "report.pdf"
    source_path.write_bytes(b"report-content")

    report_id = report_metadata_persistence.persist_parsed_report(
        db_path,
        source_path=source_path,
        parser_id="cmm",
        template_family="cmm_pdf_header_box",
        parse_status="parsed",
        metadata={
            "reference": "R-001",
            "reference_raw": "R-001",
            "report_date": "2024-01-02",
            "report_time": "08:09",
            "part_name": "Widget",
            "revision": "A",
            "sample_number": "3",
            "sample_number_kind": "stats_count",
            "stats_count_raw": "3",
            "stats_count_int": 3,
            "operator_name": "Operator",
            "comment": None,
        },
        candidates=[],
        warnings=[],
        measurements=[],
        metadata_version="report_metadata_v1",
    )

    with sqlite3.connect(db_path) as conn:
        parsed_report_count = conn.execute("SELECT COUNT(*) FROM parsed_reports").fetchone()[0]
        report_metadata_count = conn.execute("SELECT COUNT(*) FROM report_metadata").fetchone()[0]
        source_file_count = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]

    assert report_id > 0
    assert parsed_report_count == 1
    assert report_metadata_count == 1
    assert source_file_count == 1
