"""Synthetic persisted RC1 structure, source identity and read-only guarantees."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import tarfile
import zipfile

import pytest

from metroliza.parsing.cmm_report_parser import CMMReportParser
from metroliza.parsing.pdf_backend import require_pdf_backend
from scripts import detect_cmm_page_breaks as detector


def _pdf(path: Path, per_page: int = 9):
    rnd = random.Random(5)
    lines = ["SYNTHETIC CMM MEASUREMENT REPORT", "CMM REPORT", "REFERENCE: ABC01107",
             "DATE: 2024-02-03", "SAMPLE: 0001"]
    for feature in range(6):
        lines += [f"#FEATURE_{feature:02d}", "DIM"]
        for axis in "XYZD":
            nominal, tolerance = rnd.uniform(5, 200), 0.2
            measured = nominal + rnd.gauss(0, 0.1)
            lines.append(f"{axis} {nominal:.4f} {tolerance:.4f} {-tolerance:.4f} "
                         f"{measured:.4f} {measured-nominal:.4f} "
                         f"{max(0.0, abs(measured-nominal)-tolerance):.4f}")
    lines.append("#END")
    with require_pdf_backend().open() as doc:
        for offset in range(0, len(lines), per_page):
            doc.new_page().insert_text((40, 40), "\n".join(lines[offset:offset+per_page]), fontsize=8)
        doc.save(str(path))


def _persist(pdf: Path, database: Path, *, rc1=False):
    parser = CMMReportParser(str(pdf), str(database), metadata_parsing_mode="light")
    if rc1:
        with require_pdf_backend().open(str(pdf)) as doc:
            joined = "\n".join(page.get_text() for page in doc)
        # Recreate the historical page-join lines; use the real parser and
        # persistence code, rather than fabricating a block count in SQL.
        parser._cached_embedded_lines_for_open_report = lambda: joined.splitlines()
    parser.import_report_if_absent()
    return len(parser.blocks_text)


@pytest.fixture
def stored(tmp_path, qapplication_session):
    source = tmp_path / "sources"
    source.mkdir()
    pdf = source / "synthetic.pdf"
    _pdf(pdf)
    return source, pdf, tmp_path / "reports.db"


@pytest.mark.parametrize("rc1,expected,blocks", [(True, "EXTRA_BLOCKS_SUSPECTED", 8),
                                               (False, "MATCH", 6)])
def test_detect_cmm_page_breaks_persisted_structure_and_unchanged_database(stored, rc1, expected, blocks):
    source, pdf, database = stored
    assert _persist(pdf, database, rc1=rc1) == blocks
    before = database.read_bytes(), database.stat().st_mtime_ns, set(database.parent.iterdir())
    result, = detector.compare_database(database, [source], temp_dir=database.parent)
    assert (result.verdict, result.stored_blocks, result.reparsed_blocks) == (expected, blocks, 6)
    assert (result.stored_measurements, result.reparsed_measurements) == (24, 24)
    assert result.identity == "sha256"
    with detector.open_readonly(database) as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("CREATE TABLE forbidden (id INTEGER)")
    assert (database.read_bytes(), database.stat().st_mtime_ns,
            set(database.parent.iterdir())) == before


def test_missing_and_changed_same_name_sources(stored):
    source, pdf, database = stored
    _persist(pdf, database)
    pdf.write_bytes(pdf.read_bytes() + b"\n% changed synthetic content\n")
    result, = detector.compare_database(database, [source])
    assert result.verdict == "SOURCE_NOT_FOUND"
    pdf.unlink()
    assert detector.compare_database(database, [source])[0].verdict == "SOURCE_NOT_FOUND"


@pytest.mark.parametrize("kind", ["zip", "tar"])
def test_archive_sources_renamed_and_duplicate_exact_content(stored, kind):
    source, pdf, database = stored
    _persist(pdf, database)
    archive = database.parent / f"reports.{kind}"
    if kind == "zip":
        with zipfile.ZipFile(archive, "w") as stream:
            stream.write(pdf, "nested/renamed.pdf")
            stream.write(pdf, "duplicate.pdf")
    else:
        with tarfile.open(archive, "w") as stream:
            stream.add(pdf, "nested/renamed.pdf")
            stream.add(pdf, "duplicate.pdf")
    pdf.unlink()
    before = set(database.parent.iterdir())
    result, = detector.compare_database(database, [archive], temp_dir=database.parent)
    assert result.verdict == "MATCH"
    assert set(database.parent.iterdir()) == before


@pytest.mark.parametrize("change,verdict", [
    ("UPDATE source_files SET sha256=''", "AMBIGUOUS"),
    ("UPDATE parsed_reports SET raw_report_json='{}'", "AMBIGUOUS"),
    ("UPDATE parsed_reports SET raw_report_json='[]'", "AMBIGUOUS"),
    ("UPDATE parsed_reports SET raw_report_json='invalid'", "AMBIGUOUS"),
    ("DELETE FROM report_measurements WHERE row_order=1", "OTHER_DIFF"),
    ("UPDATE parsed_reports SET parser_id='other'", "OTHER_DIFF"),
])
def test_incomplete_provenance_and_other_differences(stored, change, verdict):
    source, pdf, database = stored
    _persist(pdf, database)
    with closing(sqlite3.connect(database)) as db:
        db.execute(change)
        db.commit()
    assert detector.compare_database(database, [source])[0].verdict == verdict


def test_filename_fallback_is_ambiguous_with_multiple_candidates(stored):
    source, pdf, database = stored
    _persist(pdf, database)
    with closing(sqlite3.connect(database)) as db:
        db.execute("UPDATE source_files SET sha256=''")
        db.commit()
    nested = source / "nested"
    nested.mkdir()
    (nested / pdf.name).write_bytes(pdf.read_bytes())
    result, = detector.compare_database(database, [source])
    assert (result.verdict, result.reason) == ("AMBIGUOUS", "MULTIPLE_FILENAME_CANDIDATES")


@pytest.mark.parametrize("extension", ["json", "csv"])
def test_cli_local_output_and_stdout_privacy(stored, extension, capsys):
    source, pdf, database = stored
    _persist(pdf, database)
    capsys.readouterr()
    output = database.parent / f"comparison.{extension}"
    assert detector.main([str(database), str(source), "--output", str(output)]) == 0
    stdout = capsys.readouterr().out
    assert json.loads(stdout) == {"reports": 1, "verdicts": {"MATCH": 1}}
    content = output.read_text()
    assert "MATCH" in content and pdf.name in content
    assert "ABC01107" not in content and str(source) not in content
    assert detector.main([str(database), str(source), "--output", str(output)]) == 2


def test_cli_cannot_overwrite_database_or_alias(stored):
    source, pdf, database = stored
    _persist(pdf, database)
    before = database.read_bytes(), database.stat().st_mtime_ns
    for alias in (database, database.parent / "alias.json"):
        if alias != database:
            alias.symlink_to(database)
        assert detector.main([str(database), str(source), "--output", str(alias)]) == 2
    assert (database.read_bytes(), database.stat().st_mtime_ns) == before


def test_sidecars_and_unknown_schema_are_refused(stored):
    source, pdf, database = stored
    _persist(pdf, database)
    wal = Path(str(database) + "-wal")
    wal.write_bytes(b"synthetic sidecar sentinel")
    with pytest.raises(ValueError, match="SIDECARS"):
        detector.compare_database(database, [source])
    assert wal.read_bytes() == b"synthetic sidecar sentinel"
    unknown = database.parent / "unknown.db"
    with closing(sqlite3.connect(unknown)):
        pass
    before = unknown.read_bytes(), unknown.stat().st_mtime_ns
    assert detector.main([str(unknown), str(source), "--output", str(unknown.with_suffix(".json"))]) == 2
    assert (unknown.read_bytes(), unknown.stat().st_mtime_ns) == before


def test_parser_failure_discloses_no_content(stored, monkeypatch, capsys):
    source, pdf, database = stored
    _persist(pdf, database)
    capsys.readouterr()

    def fail(*args):
        raise ValueError("sensitive synthetic report text")

    monkeypatch.setattr(detector, "reparse_counts", fail)
    result, = detector.compare_database(database, [source])
    assert (result.verdict, result.reason) == ("OTHER_DIFF", "PARSE_FAILED")
    assert "sensitive" not in repr(result) + capsys.readouterr().out


def test_unsafe_archive_is_rejected_without_residue(stored, capsys):
    source, pdf, database = stored
    _persist(pdf, database)
    archive = database.parent / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("../escaped.pdf", pdf.read_bytes())
    before = set(database.parent.iterdir())
    assert detector.main([str(database), str(archive), "--temp-dir", str(database.parent),
                          "--output", str(database.parent / "result.json")]) == 2
    assert set(database.parent.iterdir()) == before
    assert "escaped.pdf" not in capsys.readouterr().out


def test_malformed_pdf_cli_is_headless_and_reports_failure(stored):
    source, pdf, database = stored
    _persist(pdf, database)
    pdf.write_bytes(b"synthetic malformed PDF with private marker")
    with closing(sqlite3.connect(database)) as db:
        db.execute("UPDATE source_files SET sha256=?", (hashlib.sha256(pdf.read_bytes()).hexdigest(),))
        db.commit()
    output = database.parent / "malformed.json"
    before = database.read_bytes(), database.stat().st_mtime_ns
    # A separate CLI process has no QApplication: an inherited GUI error
    # handler would abort rather than return a verdict.
    result = subprocess.run(
        [sys.executable, "scripts/detect_cmm_page_breaks.py", str(database), str(source),
         "--output", str(output)], capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    row, = json.loads(output.read_text())
    assert (row["verdict"], row["reason"]) == ("OTHER_DIFF", "PARSE_FAILED")
    assert "private marker" not in result.stdout + result.stderr + output.read_text()
    assert (database.read_bytes(), database.stat().st_mtime_ns) == before
