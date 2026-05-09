from scripts.check_release_hygiene import _is_blocked


def test_release_hygiene_blocks_generated_release_artifacts_and_local_data():
    assert _is_blocked("logs/release_checks/google_conversion.log")
    assert _is_blocked("artifacts/parser_plugin_workspace_ci/generated_plugin.py")
    assert _is_blocked("smoke-artifacts/packaging-smoke-stdout.log")
    assert _is_blocked("nuitka-build-report.xml")
    assert _is_blocked("local_measurements.sqlite")
    assert _is_blocked("customer_report.pdf")
    assert _is_blocked("measurement_export.csv")
    assert _is_blocked("customer_export.xlsx")


def test_release_hygiene_allows_checked_in_synthetic_fixtures():
    assert _is_blocked("tests/fixtures/pdf/cmm_smoke_fixture.pdf") is None
    assert _is_blocked("docs/user_manual/group_analysis/user_manual.pdf") is None
    assert _is_blocked("config/google/credentials.example.json") is None
