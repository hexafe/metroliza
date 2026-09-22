from pathlib import Path
import shutil

from scripts.check_release_hygiene import PINNED_SYNTHETIC_FIXTURES, _collect_violations, _is_blocked


def test_release_hygiene_blocks_generated_release_artifacts_and_local_data():
    assert _is_blocked("logs/release_checks/google_conversion.log")
    assert _is_blocked("artifacts/parser_plugin_workspace_ci/generated_plugin.py")
    assert _is_blocked("artifacts/industrial/source_profile_dump.json")
    assert _is_blocked("industrial_exports/assembly_context.xlsx")
    assert _is_blocked("industrial_artifacts/sync.log")
    assert _is_blocked("smoke-artifacts/packaging-smoke-stdout.log")
    assert _is_blocked(".env")
    assert _is_blocked("connection_dump.json")
    assert _is_blocked("industrial_sources.yaml")
    assert _is_blocked("config/databases.yml")
    assert _is_blocked("odbc.ini")
    assert _is_blocked(".coverage")
    assert _is_blocked("coverage.xml")
    assert _is_blocked("htmlcov/index.html")
    assert _is_blocked("nuitka-build-report.xml")
    assert _is_blocked("local_measurements.sqlite")
    assert _is_blocked("customer_report.pdf")
    assert _is_blocked("measurement_export.csv")
    assert _is_blocked("customer_export.xlsx")
    assert _is_blocked("ARTIFACTS/industrial/source_profile_dump.json")
    assert _is_blocked("Industrial_Exports/assembly_context.XLSX")
    assert _is_blocked(r"logs\release_checks\google_conversion.LOG")
    assert _is_blocked("TOKEN.JSON")


def test_release_hygiene_allows_checked_in_synthetic_fixtures():
    assert _is_blocked("tests/fixtures/pdf/cmm_smoke_fixture.pdf") is None
    assert _is_blocked("tests/fixtures/industrial_realtime/stable_normal_process.csv") is None
    assert _is_blocked("docs/user_manual/group_analysis/user_manual.pdf") is None
    assert _is_blocked("config/google/credentials.example.json") is None
    assert _is_blocked("tests/fixtures/industrial_realtime/customer_export.csv")


def test_candidate_fixtures_require_exact_reviewed_bytes_and_no_neighbor_exception(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    paths = list(PINNED_SYNTHETIC_FIXTURES)
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / name, target)
    monkeypatch.chdir(tmp_path)
    assert _collect_violations(paths, label="test") == []

    for name in paths:
        target = Path(name)
        original = target.read_bytes()
        target.write_bytes(original + b"unreviewed modification")
        assert len(_collect_violations([name], label="test")) == 1
        target.write_bytes(original)

    neighbor = Path(paths[0]).with_name("unreviewed.csv")
    shutil.copyfile(paths[0], neighbor)
    assert len(_collect_violations([neighbor.as_posix()], label="test")) == 1


def test_candidate_fixture_path_cannot_admit_linked_content(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    name = next(iter(PINNED_SYNTHETIC_FIXTURES))
    target = tmp_path / name
    target.parent.mkdir(parents=True)
    source = tmp_path / "public_source.csv"
    shutil.copyfile(repo / name, source)
    target.symlink_to(source)
    monkeypatch.chdir(tmp_path)
    assert len(_collect_violations([name], label="test")) == 1
    target.unlink()
    target.hardlink_to(source)
    assert len(_collect_violations([name], label="test")) == 1
    target.unlink()
    target.symlink_to(tmp_path / "missing.csv")
    assert len(_collect_violations([name], label="test")) == 1
    target.unlink()
    assert len(_collect_violations([name], label="test")) == 1


def test_candidate_fixture_path_cannot_admit_symlinked_parent(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    name = next(iter(PINNED_SYNTHETIC_FIXTURES))
    target = tmp_path / name
    actual_parent = tmp_path / "public_inputs"
    actual_parent.mkdir()
    shutil.copyfile(repo / name, actual_parent / target.name)
    target.parent.parent.mkdir(parents=True)
    target.parent.symlink_to(actual_parent, target_is_directory=True)
    monkeypatch.chdir(tmp_path)
    assert len(_collect_violations([name], label="test")) == 1
