from contextlib import closing
from io import BytesIO
from pathlib import Path
import shutil
import sqlite3
import tarfile
from types import SimpleNamespace
import zipfile

import pytest

from metroliza.parsing import report_parser_factory
import metroliza.parsing.preflight as preflight_module
from metroliza.parsing.parse_reports_thread import ParseReportsThread
from metroliza.parsing.preflight import (
    ParsePreflightService,
    ParsePreflightStatus,
    UnsafeReportArchiveError,
    is_supported_report_archive,
    safe_unpack_report_archive,
)
from metroliza.shared.parse_contracts import ParseRequest


FIXTURE = Path(__file__).parent / "fixtures" / "pdf" / "cmm_smoke_fixture.pdf"


def test_preflight_is_non_mutating_and_parser_resolution_is_rename_invariant(tmp_path):
    source = tmp_path / "reports"
    source.mkdir()
    first = source / "default-report.pdf"
    second = source / "totally-unrelated-name.pdf"
    shutil.copyfile(FIXTURE, first)
    shutil.copyfile(FIXTURE, second)
    database = tmp_path / "not-created-by-scan.db"

    result = ParsePreflightService().scan_source(
        source_path=source,
        database_path=database,
        metadata_parsing_mode="light",
    )

    assert not database.exists()
    assert [item.display_name for item in result.files] == [first.name, second.name]
    assert [item.status for item in result.files] == [
        ParsePreflightStatus.READY,
        ParsePreflightStatus.DUPLICATE,
    ]
    assert result.files[1].reason_codes[-1] == "duplicate_in_selected_source"
    assert len({item.fingerprint for item in result.files}) == 1
    assert len({item.parser_id for item in result.files}) == 1
    assert len({item.confidence for item in result.files}) == 1
    assert all(item.parser_id == "cmm" for item in result.files)


def test_preflight_classifies_existing_content_as_duplicate_without_writing(tmp_path):
    report = tmp_path / "report.pdf"
    shutil.copyfile(FIXTURE, report)
    initial = ParsePreflightService().scan_source(
        source_path=report,
        database_path=tmp_path / "missing.db",
        metadata_parsing_mode="light",
    )
    digest = initial.files[0].fingerprint.removeprefix("sha256:")

    database = tmp_path / "existing.db"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE source_files (id INTEGER PRIMARY KEY, sha256 TEXT, is_active INTEGER);
            CREATE TABLE parsed_reports (
                id INTEGER PRIMARY KEY,
                source_file_id INTEGER,
                parser_id TEXT,
                parser_version TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO source_files (id, sha256, is_active) VALUES (1, ?, 1)",
            (digest,),
        )
        connection.execute(
            """
            INSERT INTO parsed_reports (id, source_file_id, parser_id, parser_version)
            VALUES (1, 1, 'legacy_parser', '0')
            """
        )
    database_bytes_before = database.read_bytes()

    result = ParsePreflightService().scan_source(
        source_path=report,
        database_path=database,
        metadata_parsing_mode="light",
    )

    assert result.files[0].status is ParsePreflightStatus.DUPLICATE
    assert database.read_bytes() == database_bytes_before


def test_preflight_returns_unreadable_evidence_for_missing_source(tmp_path):
    missing = tmp_path / "missing-reports"

    result = ParsePreflightService().scan_source(
        source_path=missing,
        database_path=tmp_path / "unused.db",
        metadata_parsing_mode="light",
    )

    assert len(result.files) == 1
    assert result.files[0].status is ParsePreflightStatus.UNREADABLE
    assert result.files[0].reason_codes == ("source_unreadable",)
    assert not (tmp_path / "unused.db").exists()


def test_import_filter_rejects_content_changed_after_operator_scan(tmp_path):
    report = tmp_path / "report.pdf"
    shutil.copyfile(FIXTURE, report)
    database = tmp_path / "output.db"
    preflight = ParsePreflightService().scan_source(
        source_path=report,
        database_path=database,
        metadata_parsing_mode="light",
    )
    thread = ParseReportsThread(
        ParseRequest(
            source_directory=str(report),
            db_file=str(database),
            metadata_parsing_mode="light",
        )
    )
    thread.preflight_result = preflight
    report.write_bytes(b"changed after scan")

    approved, changed_count = thread._filter_reports_for_preflight([report])

    assert approved == []
    assert changed_count == 1
    assert not database.exists()


def test_import_filter_rejects_same_parser_id_from_new_registry_generation(
    tmp_path,
    monkeypatch,
):
    report = tmp_path / "report.pdf"
    shutil.copyfile(FIXTURE, report)
    database = tmp_path / "output.db"
    preflight = ParsePreflightService().scan_source(
        source_path=report,
        database_path=database,
        metadata_parsing_mode="light",
    )
    approved_item = preflight.ready_files[0]
    assert approved_item.registry_generation_id is not None
    thread = ParseReportsThread(
        ParseRequest(
            source_directory=str(report),
            db_file=str(database),
            metadata_parsing_mode="light",
        )
    )
    thread.preflight_result = preflight
    monkeypatch.setattr(
        report_parser_factory,
        "resolve_parser_with_diagnostics",
        lambda *_args, **_kwargs: SimpleNamespace(
            selected=SimpleNamespace(plugin_id=approved_item.parser_id),
            registry_generation_id=approved_item.registry_generation_id + 1,
        ),
    )

    approved, changed_count = thread._filter_reports_for_preflight([report])

    assert approved == []
    assert changed_count == 1
    assert not database.exists()


def test_duplicate_content_is_imported_once_and_reported_truthfully(tmp_path):
    source = tmp_path / "reports"
    source.mkdir()
    first = source / "01-report.pdf"
    second = source / "02-copy.pdf"
    shutil.copyfile(FIXTURE, first)
    shutil.copyfile(FIXTURE, second)
    database = tmp_path / "output.db"
    preflight = ParsePreflightService().scan_source(
        source_path=source,
        database_path=database,
        metadata_parsing_mode="light",
    )
    thread = ParseReportsThread(
        ParseRequest(
            source_directory=str(source),
            db_file=str(database),
            metadata_parsing_mode="light",
        )
    )
    thread.preflight_result = preflight

    thread.run()

    assert thread.last_parse_result.total_files == 2
    assert thread.last_parse_result.parsed_files == 1
    assert thread.last_parse_result.preflight_duplicate_files == 1
    assert thread.last_parse_result.preflight_changed_files == 0
    with closing(sqlite3.connect(database)) as connection, connection:
        stored_count = connection.execute("SELECT COUNT(*) FROM parsed_reports").fetchone()[0]
    assert stored_count == 1


def test_deleted_ready_file_after_scan_is_reported_as_changed(tmp_path):
    source = tmp_path / "reports"
    source.mkdir()
    report = source / "report.pdf"
    shutil.copyfile(FIXTURE, report)
    database = tmp_path / "output.db"
    preflight = ParsePreflightService().scan_source(
        source_path=source,
        database_path=database,
        metadata_parsing_mode="light",
    )
    report.unlink()
    thread = ParseReportsThread(
        ParseRequest(
            source_directory=str(source),
            db_file=str(database),
            metadata_parsing_mode="light",
        )
    )
    thread.preflight_result = preflight

    thread.run()

    assert thread.last_parse_result.total_files == 1
    assert thread.last_parse_result.parsed_files == 0
    assert thread.last_parse_result.preflight_changed_files == 1


def test_archive_traversal_is_rejected_before_preflight_or_import(tmp_path):
    archive = tmp_path / "reports.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escaped.pdf", FIXTURE.read_bytes())
    extraction_root = tmp_path / "extract"

    with pytest.raises(UnsafeReportArchiveError):
        safe_unpack_report_archive(archive, extraction_root)

    assert not (tmp_path / "escaped.pdf").exists()
    result = ParsePreflightService().scan_source(
        source_path=archive,
        database_path=tmp_path / "output.db",
        metadata_parsing_mode="light",
    )
    assert result.files[0].status is ParsePreflightStatus.UNREADABLE

    thread = ParseReportsThread(
        ParseRequest(
            source_directory=str(archive),
            db_file=str(tmp_path / "import.db"),
            metadata_parsing_mode="light",
        )
    )
    try:
        with pytest.raises(UnsafeReportArchiveError):
            thread._resolve_report_root()
    finally:
        if thread._extracted_archive_dir is not None:
            thread._extracted_archive_dir.cleanup()
            thread._extracted_archive_dir = None


def test_archive_extraction_rejects_uncompressed_size_budget(tmp_path, monkeypatch):
    archive = tmp_path / "oversized.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("first.pdf", b"12")
        bundle.writestr("second.pdf", b"34")
    monkeypatch.setattr(preflight_module, "_MAX_ARCHIVE_UNCOMPRESSED_BYTES", 3)

    with pytest.raises(UnsafeReportArchiveError, match="safe extraction limits"):
        safe_unpack_report_archive(archive, tmp_path / "extract")

    assert not (tmp_path / "extract" / "first.pdf").exists()


def test_archive_extraction_streams_validated_members_without_extractall(tmp_path, monkeypatch):
    zip_archive = tmp_path / "reports.zip"
    with zipfile.ZipFile(zip_archive, "w") as bundle:
        bundle.writestr("nested/report.pdf", b"zip-report")
    tar_archive = tmp_path / "reports.tar"
    payload = b"tar-report"
    with tarfile.open(tar_archive, "w") as bundle:
        member = tarfile.TarInfo("nested/report.pdf")
        member.size = len(payload)
        bundle.addfile(member, BytesIO(payload))

    monkeypatch.setattr(
        zipfile.ZipFile,
        "extractall",
        lambda *_args, **_kwargs: pytest.fail("ZipFile.extractall must not be used"),
    )
    monkeypatch.setattr(
        tarfile.TarFile,
        "extractall",
        lambda *_args, **_kwargs: pytest.fail("TarFile.extractall must not be used"),
    )

    zip_target = tmp_path / "zip-extract"
    tar_target = tmp_path / "tar-extract"
    safe_unpack_report_archive(zip_archive, zip_target)
    safe_unpack_report_archive(tar_archive, tar_target)

    assert (zip_target / "nested" / "report.pdf").read_bytes() == b"zip-report"
    assert (tar_target / "nested" / "report.pdf").read_bytes() == b"tar-report"


def test_archive_extraction_rejects_case_colliding_member_paths(tmp_path):
    archive = tmp_path / "colliding.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("Report.pdf", b"first")
        bundle.writestr("report.PDF", b"second")

    extraction_root = tmp_path / "extract"
    with pytest.raises(UnsafeReportArchiveError, match="unsafe entry"):
        safe_unpack_report_archive(archive, extraction_root)

    assert not extraction_root.exists()


def test_archive_extraction_preserves_nonempty_destination(tmp_path):
    archive = tmp_path / "reports.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("report.pdf", b"replacement")
    extraction_root = tmp_path / "extract"
    extraction_root.mkdir()
    existing = extraction_root / "report.pdf"
    existing.write_bytes(b"operator-data")

    with pytest.raises(UnsafeReportArchiveError, match="empty directory"):
        safe_unpack_report_archive(archive, extraction_root)

    assert existing.read_bytes() == b"operator-data"


@pytest.mark.parametrize(
    "member_name",
    (
        "CON",
        "nested/NUL.txt",
        "nested/report.pdf:stream",
        "nested/report.pdf.",
        "nested/report.pdf ",
    ),
)
def test_archive_extraction_rejects_windows_unsafe_member_names(tmp_path, member_name):
    archive = tmp_path / "unsafe-windows-name.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(member_name, b"report")

    with pytest.raises(UnsafeReportArchiveError, match="unsafe entry"):
        safe_unpack_report_archive(archive, tmp_path / "extract")


@pytest.mark.parametrize(
    "filename",
    (
        "reports.tar.gz",
        "REPORTS.TAR.BZ2",
        "reports.tar.xz",
    ),
)
def test_archive_recognition_uses_complete_case_insensitive_filename(filename):
    assert is_supported_report_archive(filename)


def test_zstd_archive_recognition_matches_active_tarfile_decoder():
    try:
        with tarfile.open(fileobj=BytesIO(), mode="r:zst"):
            pass
    except tarfile.CompressionError:
        runtime_supports_zstd = False
    except tarfile.TarError:
        runtime_supports_zstd = True
    else:
        runtime_supports_zstd = True

    assert is_supported_report_archive("reports.tar.zst") is runtime_supports_zstd
    assert is_supported_report_archive("REPORTS.TZST") is runtime_supports_zstd


def test_tar_gz_archive_scan_and_import_share_container_recognition(tmp_path):
    source_report = tmp_path / "content-does-not-match-name.pdf"
    shutil.copyfile(FIXTURE, source_report)
    archive = tmp_path / "REPORTS.TAR.GZ"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source_report, arcname="renamed-inside-archive.pdf")
    database = tmp_path / "archive-output.db"

    preflight = ParsePreflightService().scan_source(
        source_path=archive,
        database_path=database,
        metadata_parsing_mode="light",
    )
    assert len(preflight.ready_files) == 1
    assert preflight.ready_files[0].parser_id == "cmm"

    thread = ParseReportsThread(
        ParseRequest(
            source_directory=str(archive),
            db_file=str(database),
            metadata_parsing_mode="light",
        )
    )
    thread.preflight_result = preflight
    thread.run()

    assert thread.last_parse_result.total_files == 1
    assert thread.last_parse_result.parsed_files == 1
    assert thread.last_parse_result.preflight_changed_files == 0
    with closing(sqlite3.connect(database)) as connection:
        stored_count = connection.execute("SELECT COUNT(*) FROM parsed_reports").fetchone()[0]
    assert stored_count == 1
