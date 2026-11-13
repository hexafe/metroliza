"""W04 acceptance through real MainWindow, review and import workers."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from metroliza.app.windows_candidate_import_guards import FACETS, run_import_guard_checks


@pytest.fixture(scope="session", autouse=True)
def application():
    # Keep the shared application alive across this and subsequent Qt cohorts.
    from metroliza.app.bootstrap import get_or_create_qapplication

    return get_or_create_qapplication()


@pytest.mark.parametrize("directory", ("plain", "owned # próba"))
def test_real_import_guard_slice_preserves_committed_database_and_sources(tmp_path, directory):
    scratch = tmp_path / directory
    scratch.mkdir()
    fixtures = Path(__file__).parent / "fixtures" / "windows_candidate" / "reports"

    outcome = run_import_guard_checks(scratch, fixtures)

    assert outcome["status"] == "passed", outcome
    assert outcome["facets"] == dict.fromkeys(FACETS, "passed")
    assert outcome["error_codes"] == []
    evidence = outcome["evidence"]
    assert evidence["initial_imported"] == 2
    assert evidence["duplicate_count"] == 2
    assert evidence["drift_rejected"] == 1
    assert evidence["cancelled_files"] >= 1
    assert len(evidence["committed_database_sha256"]) == 64
    assert len(evidence["committed_logical_sha256"]) == 64
    assert evidence["cancel_barrier_stage"] == "real_parse_batch_entry"
    assert len(evidence["database_sha256_after_close"]) == 64
    assert set(evidence["sidecars_after_window_close"]) <= {"-wal", "-shm"}
    assert len(evidence["source_hashes"]) == 5
    assert (scratch / evidence["relative_artifact_dir"] / "reports.sqlite").is_file()


def test_invalid_fixture_directory_returns_closed_failure(tmp_path):
    outcome = run_import_guard_checks(tmp_path, tmp_path / "missing")

    assert outcome["status"] == "failed"
    assert outcome["facets"] == dict.fromkeys(FACETS, "not_run")
    assert outcome["error_codes"] == ["fixtures_invalid"]
    assert outcome["evidence"]["relative_artifact_dir"] is None


def test_changed_public_fixture_does_not_start_a_window(tmp_path):
    public = Path(__file__).parent / "fixtures" / "windows_candidate" / "reports"
    fixtures = tmp_path / "copies"
    fixtures.mkdir()
    for source in public.glob("*.pdf"):
        shutil.copyfile(source, fixtures / source.name)
    (fixtures / "report-0.pdf").write_bytes(b"changed public fixture")

    outcome = run_import_guard_checks(tmp_path, fixtures)

    assert outcome["status"] == "failed"
    assert outcome["facets"] == dict.fromkeys(FACETS, "not_run")
    assert outcome["error_codes"] == ["fixture_staging_failed"]
