from pathlib import Path

import pytest

from metroliza.parsing.declarative_parser_profiles import (
    APPROVAL_FILE_NAME,
    PROFILE_FILE_NAME,
    approved_profiles_dir,
    disable_profile,
    enable_profile,
    expected_sample_paths,
    install_profile,
    list_profiles,
    load_approved_profile_parsers,
    load_profile_payload,
    render_profile_template,
    rollback_profile,
    validate_profile_file,
)
from metroliza.parsing.parser_plugin_contracts import ProbeContext


def _sample_text() -> str:
    return "\n".join(
        (
            "SYNTHETIC SUPPLIER ALPHA",
            "Reference: REF123",
            "Date: 2026-01-05",
            "Sample: 0001",
            "DIM X 10.0 0.1 -0.1 - 10.02 0.02 0",
            "",
        )
    )


def _profile_text() -> str:
    return r"""
schema_version: 1
plugin:
  plugin_id: supplier_alpha
  display_name: Supplier Alpha
  version: 0.1.0
  source_format: pdf
  supported_locales: ["*"]
  template_ids: ["synthetic_fixture"]
  priority: 900
probe:
  required_markers:
    - "SYNTHETIC SUPPLIER ALPHA"
  reject_markers: []
  confidence: 92
extraction:
  report_fields:
    reference: 'Reference:\s*(?P<value>\S+)'
    report_date: 'Date:\s*(?P<value>\d{4}-\d{2}-\d{2})'
    sample_number: 'Sample:\s*(?P<value>\S+)'
  blocks:
    - header: "MAIN FEATURE"
      pattern: '^DIM\s+(?P<axis_code>\w+)\s+(?P<nominal>[-0-9.,]+)\s+(?P<tol_plus>[-0-9.,]+)\s+(?P<tol_minus>[-0-9.,]+)\s+(?P<bonus>[-0-9.,]+|-)\s+(?P<measured>[-0-9.,]+)\s+(?P<deviation>[-0-9.,]+)\s+(?P<out_of_tolerance>[-0-9.,]+)$'
normalization:
  decimal_separator: "."
  date_formats: ["%Y-%m-%d"]
  missing_value_tokens: ["", "-", "NA", "N/A"]
"""


def _expected_results() -> str:
    return (
        "sample_file,reference,report_date,sample_number,block_index,header_normalized,"
        "axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
        "sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0\n"
    )


def _write_fixture(tmp_path: Path):
    profile_path = tmp_path / "profile.yaml"
    sample_path = tmp_path / "sample_report_01.pdf"
    expected_path = tmp_path / "expected_results_template.csv"
    profile_path.write_text(_profile_text(), encoding="utf-8")
    sample_path.write_text(_sample_text(), encoding="utf-8")
    expected_path.write_text(_expected_results(), encoding="utf-8")
    return profile_path, sample_path, expected_path


def test_declarative_profile_validates_and_parses_expected_results(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)

    report = validate_profile_file(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
    )

    assert report.passed is True
    assert report.plugin_id == "supplier_alpha"
    assert any(check.name == "probe_required_markers_present" and check.passed for check in report.checks)
    assert report.contract_reports[0].passed is True


def test_declarative_profile_rejects_header_only_expected_results(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    expected_path.write_text(
        "sample_file,reference,report_date,sample_number,block_index,header_normalized,"
        "axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n",
        encoding="utf-8",
    )

    report = validate_profile_file(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
    )

    assert report.passed is False
    assert any(
        check.name == "expected_results_rows_present" and not check.passed
        for check in report.contract_reports[0].checks
    )


def test_declarative_profile_rejects_unexpected_extra_rows(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    sample_path.write_text(
        _sample_text().replace(
            "DIM X 10.0 0.1 -0.1 - 10.02 0.02 0",
            "DIM X 10.0 0.1 -0.1 - 10.02 0.02 0\nDIM Y 11.0 0.1 -0.1 - 11.01 0.01 0",
        ),
        encoding="utf-8",
    )

    report = validate_profile_file(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
    )

    assert report.passed is False
    assert any(
        check.name == "expected_results_actual_row_count_matches" and not check.passed
        for check in report.contract_reports[0].checks
    )


def test_declarative_profile_matches_duplicate_axis_rows_by_occurrence(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    sample_path.write_text(
        _sample_text().replace(
            "DIM X 10.0 0.1 -0.1 - 10.02 0.02 0",
            "DIM X 10.0 0.1 -0.1 - 10.02 0.02 0\nDIM X 10.0 0.1 -0.1 - 10.03 0.03 0",
        ),
        encoding="utf-8",
    )
    expected_path.write_text(
        "sample_file,reference,report_date,sample_number,block_index,header_normalized,"
        "axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
        "sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0\n"
        "sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.03,0.03,0\n",
        encoding="utf-8",
    )

    report = validate_profile_file(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
    )

    assert report.passed is True


def test_declarative_profile_reads_excel_reports(tmp_path):
    pd = pytest.importorskip("pandas")

    profile_path, _sample_path, expected_path = _write_fixture(tmp_path)
    text = profile_path.read_text(encoding="utf-8").replace("source_format: pdf", "source_format: excel")
    profile_path.write_text(text, encoding="utf-8")
    sample_path = tmp_path / "sample_report_01.xlsx"
    pd.DataFrame(
        [
            ["SYNTHETIC SUPPLIER ALPHA"],
            ["Reference:", "REF123"],
            ["Date:", "2026-01-05"],
            ["Sample:", "0001"],
            ["DIM", "X", "10.0", "0.1", "-0.1", "-", "10.02", "0.02", "0"],
        ]
    ).to_excel(sample_path, index=False, header=False)
    expected_path.write_text(_expected_results().replace(".pdf", ".xlsx"), encoding="utf-8")

    report = validate_profile_file(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
    )

    assert report.passed is True


def test_declarative_profile_applies_date_and_missing_value_normalization(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    profile_text = profile_path.read_text(encoding="utf-8")
    profile_text = profile_text.replace(
        r"report_date: 'Date:\s*(?P<value>\d{4}-\d{2}-\d{2})'",
        r"report_date: 'Date:\s*(?P<value>\d{2}/\d{2}/\d{4})'",
    ).replace('date_formats: ["%Y-%m-%d"]', 'date_formats: ["%d/%m/%Y"]')
    profile_text = profile_text.replace(r"(?P<bonus>[-0-9.,]+|-)", r"(?P<bonus>[-0-9.,]+|-|MISSING)")
    profile_text = profile_text.replace(
        'missing_value_tokens: ["", "-", "NA", "N/A"]',
        'missing_value_tokens: ["MISSING"]',
    )
    profile_path.write_text(profile_text, encoding="utf-8")
    sample_path.write_text(
        _sample_text()
        .replace("Date: 2026-01-05", "Date: 05/01/2026")
        .replace("DIM X 10.0 0.1 -0.1 - 10.02 0.02 0", "DIM X 10.0 0.1 -0.1 MISSING 10.02 0.02 0"),
        encoding="utf-8",
    )

    report = validate_profile_file(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
    )

    assert report.passed is True


def test_declarative_profile_install_writes_approval_and_loads_parser(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)

    result = install_profile(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
        approved_by="qa",
        home=tmp_path,
    )
    parsers, errors = load_approved_profile_parsers(home=tmp_path)

    assert result.plugin_id == "supplier_alpha"
    assert (approved_profiles_dir(home=tmp_path) / "supplier_alpha" / PROFILE_FILE_NAME).exists()
    assert (approved_profiles_dir(home=tmp_path) / "supplier_alpha" / APPROVAL_FILE_NAME).exists()
    assert errors == ()
    assert len(parsers) == 1
    plugin_id, parser_cls = parsers[0]
    assert plugin_id == "supplier_alpha"
    probe = parser_cls.probe(sample_path, ProbeContext(source_path=str(sample_path), source_format="pdf"))
    assert probe.can_parse is True
    parser = parser_cls(str(sample_path), database=":memory:")
    parsed = parser.parse_to_v2()
    assert parsed.report.reference == "REF123"
    assert parsed.blocks[0].dimensions[0].measured == 10.02


def test_declarative_profile_checksum_mismatch_is_not_loaded(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    install_profile(profile_path, sample_paths=(sample_path,), expected_results_ref=expected_path, home=tmp_path)
    approved_profile = approved_profiles_dir(home=tmp_path) / "supplier_alpha" / PROFILE_FILE_NAME
    approved_profile.write_text(approved_profile.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    parsers, errors = load_approved_profile_parsers(home=tmp_path)

    assert parsers == ()
    assert any("checksum mismatch" in error for error in errors)


def test_declarative_profile_install_requires_fixture_validation(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)

    with pytest.raises(ValueError, match="expected-results CSV"):
        install_profile(profile_path, sample_paths=(sample_path,), home=tmp_path)
    with pytest.raises(ValueError, match="at least one sample report"):
        install_profile(profile_path, expected_results_ref=expected_path, home=tmp_path)


def test_declarative_profile_disable_enable_moves_between_store_states(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    install_profile(profile_path, sample_paths=(sample_path,), expected_results_ref=expected_path, home=tmp_path)

    disabled_dir = disable_profile("supplier_alpha", home=tmp_path)
    assert disabled_dir.exists()
    installed_after_disable = list_profiles(home=tmp_path)
    enabled_dir = enable_profile("supplier_alpha", home=tmp_path)

    assert any(profile.plugin_id == "supplier_alpha" and not profile.enabled for profile in installed_after_disable)
    assert enabled_dir.exists()
    assert list_profiles(home=tmp_path)[0].enabled is True


def test_declarative_profile_disabled_listing_validates_approval_checksum(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    install_profile(profile_path, sample_paths=(sample_path,), expected_results_ref=expected_path, home=tmp_path)
    disabled_dir = disable_profile("supplier_alpha", home=tmp_path)
    disabled_profile = disabled_dir / PROFILE_FILE_NAME
    disabled_profile.write_text(disabled_profile.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    profiles = list_profiles(home=tmp_path)

    assert profiles[0].plugin_id == "supplier_alpha"
    assert profiles[0].enabled is False
    assert profiles[0].approved is False
    assert "checksum mismatch" in profiles[0].detail


def test_declarative_profile_store_actions_reject_path_like_plugin_ids(tmp_path):
    for action in (disable_profile, enable_profile, rollback_profile):
        with pytest.raises(ValueError):
            action("../supplier_alpha", home=tmp_path)


def test_expected_sample_paths_rejects_entries_outside_samples(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    expected_path = workspace / "expected_results.csv"
    expected_path.write_text("sample_file,reference\n../secret.pdf,REF123\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sample_file entries"):
        expected_sample_paths(workspace, expected_path)


def test_declarative_profile_template_is_data_only_yaml():
    template = render_profile_template(
        plugin_id="Supplier Alpha",
        display_name="Supplier Alpha",
        source_format="pdf",
    )

    assert "schema_version: 1" in template
    assert "plugin_id: supplier_alpha" in template
    assert "import " not in template
    assert "eval(" not in template


def test_declarative_profile_template_quotes_user_display_name(tmp_path):
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        render_profile_template(
            plugin_id="a",
            display_name="Supplier: Alpha #1",
            source_format="pdf",
        ),
        encoding="utf-8",
    )

    payload = load_profile_payload(profile_path)

    assert payload["plugin"]["plugin_id"] == "a_profile"
    assert payload["plugin"]["display_name"] == "Supplier: Alpha #1"


def test_declarative_profile_policy_rejects_generic_probe_without_markers(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    text = profile_path.read_text(encoding="utf-8")
    text = text.replace('  required_markers:\n    - "SYNTHETIC SUPPLIER ALPHA"\n', "  required_markers: []\n")
    profile_path.write_text(text, encoding="utf-8")

    report = validate_profile_file(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
    )

    assert report.passed is False
    assert any(check.name == "probe_required_markers_present" and not check.passed for check in report.checks)


def test_declarative_profile_policy_rejects_dangerous_regex(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    text = profile_path.read_text(encoding="utf-8")
    text = text.replace(r"(?P<axis_code>\w+)", r"(?P<axis_code>(?:\w+)+)")
    profile_path.write_text(text, encoding="utf-8")

    report = validate_profile_file(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
    )

    assert report.passed is False
    assert any(check.name == "row_pattern_0_regex_safe" and not check.passed for check in report.checks)


def test_declarative_profile_install_refuses_failed_validation(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    sample_path.write_text("wrong supplier\n", encoding="utf-8")

    with pytest.raises(ValueError):
        install_profile(
            profile_path,
            sample_paths=(sample_path,),
            expected_results_ref=expected_path,
            home=tmp_path,
        )


def test_report_factory_registers_approved_declarative_profiles(monkeypatch, tmp_path):
    from metroliza.parsing import declarative_parser_profiles as profiles
    from metroliza.reports import report_parser_factory

    profile_path, _sample_path, _expected_path = _write_fixture(tmp_path)
    payload = profiles.load_profile_payload(profile_path)
    parser_cls = profiles.build_parser_class_from_profile(payload, origin_path=profile_path)
    original_map = dict(report_parser_factory.PARSER_MAP)
    original_manifests = dict(report_parser_factory.PARSER_MANIFESTS)
    original_detectors = dict(report_parser_factory.PARSER_DETECTORS)
    original_cache = dict(report_parser_factory.PROBE_RESULT_CACHE)
    original_loaded = report_parser_factory._EXTERNAL_PLUGINS_LOADED
    original_signature = report_parser_factory._EXTERNAL_PLUGIN_CONFIG_SIGNATURE
    original_entry_points = report_parser_factory._EXTERNAL_PLUGIN_ENTRY_POINTS

    monkeypatch.setattr(
        profiles,
        "load_approved_profile_parsers",
        lambda: ((("supplier_alpha", parser_cls),), ()),
    )
    monkeypatch.setattr(report_parser_factory, "_discover_external_plugin_entry_points", lambda force_refresh=False: ())
    monkeypatch.setattr(
        report_parser_factory.parser_plugin_paths,
        "configured_external_plugin_path_entries",
        lambda raw_paths=None, include_default_dir=True, home=None: (),
    )
    try:
        report_parser_factory.reset_external_plugin_loader_state()
        report_parser_factory._ensure_external_plugins_loaded_once()

        assert "supplier_alpha" in report_parser_factory.PARSER_MAP
        assert report_parser_factory.PARSER_MANIFESTS["supplier_alpha"].capabilities["declarative_profile"] is True
    finally:
        report_parser_factory.PARSER_MAP.clear()
        report_parser_factory.PARSER_MAP.update(original_map)
        report_parser_factory.PARSER_MANIFESTS.clear()
        report_parser_factory.PARSER_MANIFESTS.update(original_manifests)
        report_parser_factory.PARSER_DETECTORS.clear()
        report_parser_factory.PARSER_DETECTORS.update(original_detectors)
        report_parser_factory.PROBE_RESULT_CACHE.clear()
        report_parser_factory.PROBE_RESULT_CACHE.update(original_cache)
        report_parser_factory._EXTERNAL_PLUGINS_LOADED = original_loaded
        report_parser_factory._EXTERNAL_PLUGIN_CONFIG_SIGNATURE = original_signature
        report_parser_factory._EXTERNAL_PLUGIN_ENTRY_POINTS = original_entry_points


def test_report_factory_reload_removes_disabled_declarative_profiles(monkeypatch, tmp_path):
    from metroliza.parsing import declarative_parser_profiles as profiles
    from metroliza.reports import report_parser_factory

    profile_path, _sample_path, _expected_path = _write_fixture(tmp_path)
    payload = profiles.load_profile_payload(profile_path)
    parser_cls = profiles.build_parser_class_from_profile(payload, origin_path=profile_path)
    state = {
        "signature": (("supplier_alpha", "profile-hash-1", "approval-hash-1"),),
        "profiles": (("supplier_alpha", parser_cls),),
    }
    original_map = dict(report_parser_factory.PARSER_MAP)
    original_manifests = dict(report_parser_factory.PARSER_MANIFESTS)
    original_detectors = dict(report_parser_factory.PARSER_DETECTORS)
    original_cache = dict(report_parser_factory.PROBE_RESULT_CACHE)
    original_loaded = report_parser_factory._EXTERNAL_PLUGINS_LOADED
    original_signature = report_parser_factory._EXTERNAL_PLUGIN_CONFIG_SIGNATURE
    original_entry_points = report_parser_factory._EXTERNAL_PLUGIN_ENTRY_POINTS

    monkeypatch.setattr(
        profiles,
        "load_approved_profile_parsers",
        lambda: (state["profiles"], ()),
    )
    monkeypatch.setattr(profiles, "profile_store_signature", lambda: state["signature"])
    monkeypatch.setattr(report_parser_factory, "_discover_external_plugin_entry_points", lambda force_refresh=False: ())
    monkeypatch.setattr(
        report_parser_factory.parser_plugin_paths,
        "configured_external_plugin_path_entries",
        lambda raw_paths=None, include_default_dir=True, home=None: (),
    )
    try:
        report_parser_factory.reset_external_plugin_loader_state()
        report_parser_factory._ensure_external_plugins_loaded_once()
        assert "supplier_alpha" in report_parser_factory.PARSER_MAP

        state["signature"] = ()
        state["profiles"] = ()
        report_parser_factory._ensure_external_plugins_loaded_once()

        assert "supplier_alpha" not in report_parser_factory.PARSER_MAP
    finally:
        report_parser_factory.PARSER_MAP.clear()
        report_parser_factory.PARSER_MAP.update(original_map)
        report_parser_factory.PARSER_MANIFESTS.clear()
        report_parser_factory.PARSER_MANIFESTS.update(original_manifests)
        report_parser_factory.PARSER_DETECTORS.clear()
        report_parser_factory.PARSER_DETECTORS.update(original_detectors)
        report_parser_factory.PROBE_RESULT_CACHE.clear()
        report_parser_factory.PROBE_RESULT_CACHE.update(original_cache)
        report_parser_factory._EXTERNAL_PLUGINS_LOADED = original_loaded
        report_parser_factory._EXTERNAL_PLUGIN_CONFIG_SIGNATURE = original_signature
        report_parser_factory._EXTERNAL_PLUGIN_ENTRY_POINTS = original_entry_points
