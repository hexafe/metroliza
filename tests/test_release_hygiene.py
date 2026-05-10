from scripts.check_release_hygiene import _is_blocked


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
    assert _is_blocked("docs/user_manual/group_analysis/user_manual.pdf") is None
    assert _is_blocked("config/google/credentials.example.json") is None
