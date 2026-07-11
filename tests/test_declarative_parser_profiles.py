from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
from threading import Event

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


def test_declarative_profile_preserves_multiline_report_field_patterns(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8").replace(
            r"reference: 'Reference:\s*(?P<value>\S+)'",
            r"reference: 'Reference:\s*\n\s*(?P<value>\S+)'",
        ),
        encoding="utf-8",
    )
    sample_path.write_text(
        _sample_text().replace("Reference: REF123", "Reference:\n  REF123"),
        encoding="utf-8",
    )

    report = validate_profile_file(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
    )

    assert report.passed is True
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
    openpyxl = pytest.importorskip("openpyxl")

    profile_path, _sample_path, expected_path = _write_fixture(tmp_path)
    text = profile_path.read_text(encoding="utf-8").replace("source_format: pdf", "source_format: excel")
    profile_path.write_text(text, encoding="utf-8")
    sample_path = tmp_path / "sample_report_01.xlsx"
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    for row in (
        ["SYNTHETIC SUPPLIER ALPHA"],
        ["Reference:", "REF123"],
        ["Date:", "2026-01-05"],
        ["Sample:", "0001"],
        ["DIM", "X", "10.0", "0.1", "-0.1", "-", "10.02", "0.02", "0"],
    ):
        worksheet.append(row)
    workbook.save(sample_path)
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


def test_declarative_profile_policy_rejects_quantified_alternation(tmp_path):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    text = profile_path.read_text(encoding="utf-8")
    text = text.replace(r"(?P<axis_code>\w+)", r"(?P<axis_code>(a|aa)+)")
    profile_path.write_text(text, encoding="utf-8")

    report = validate_profile_file(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
    )

    assert report.passed is False
    assert any(check.name == "row_pattern_0_regex_safe" and not check.passed for check in report.checks)


def test_declarative_profile_reuses_bounded_source_extraction(monkeypatch, tmp_path):
    from metroliza.parsing import declarative_parser_profiles as profiles
    from metroliza.parsing.source_inspection import SourceInspectionContext

    profile_path, sample_path, _expected_path = _write_fixture(tmp_path)
    payload = load_profile_payload(profile_path)
    inspection = SourceInspectionContext.from_path(sample_path, source_format="pdf")
    original_reader = profiles._read_source_text
    reads = 0

    def _counted_reader(path, max_chars):
        nonlocal reads
        reads += 1
        return original_reader(path, max_chars)

    monkeypatch.setattr(profiles, "_read_source_text", _counted_reader)
    context = ProbeContext(
        source_path=str(sample_path),
        source_format="pdf",
        source_inspection=inspection,
    )

    assert profiles.profile_probe(payload, sample_path, context).can_parse is True
    result = profiles.parse_profile_result(
        payload,
        sample_path,
        source_inspection=inspection,
    )

    assert result.report.reference == "REF123"
    assert reads == 1


def test_declarative_profile_caps_regex_input_line_length(monkeypatch, tmp_path):
    from metroliza.parsing import declarative_parser_profiles as profiles

    profile_path, sample_path, _expected_path = _write_fixture(tmp_path)
    payload = load_profile_payload(profile_path)
    monkeypatch.setattr(profiles, "MAX_PROFILE_LINE_CHARS", 32)

    with pytest.raises(ValueError, match="input line 5 exceeds 32 characters"):
        profiles.parse_profile_result(payload, sample_path)


def test_declarative_profile_caps_row_pattern_count_in_validation_and_runtime(tmp_path):
    from metroliza.parsing import declarative_parser_profiles as profiles

    profile_path, sample_path, _expected_path = _write_fixture(tmp_path)
    payload = load_profile_payload(profile_path)
    payload["extraction"]["blocks"] *= profiles.MAX_PROFILE_ROW_SPECS + 1

    checks = profiles._profile_policy_checks(payload)

    assert any(
        check.name == "row_pattern_count_within_limit" and not check.passed
        for check in checks
    )
    with pytest.raises(ValueError, match="exceeds 32 row patterns"):
        profiles.parse_profile_result(payload, sample_path)


def test_declarative_profile_caps_total_row_matches(monkeypatch, tmp_path):
    from metroliza.parsing import declarative_parser_profiles as profiles

    profile_path, sample_path, _expected_path = _write_fixture(tmp_path)
    payload = load_profile_payload(profile_path)
    sample_path.write_text(
        _sample_text().replace(
            "DIM X 10.0 0.1 -0.1 - 10.02 0.02 0",
            "DIM X 10.0 0.1 -0.1 - 10.02 0.02 0\n"
            "DIM Y 11.0 0.1 -0.1 - 11.02 0.02 0",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(profiles, "MAX_PROFILE_TOTAL_ROW_MATCHES", 1)

    with pytest.raises(ValueError, match="exceeded 1 total row matches"):
        profiles.parse_profile_result(payload, sample_path)


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


def test_profile_update_replace_failure_restores_existing_approved_generation(
    monkeypatch,
    tmp_path,
):
    from metroliza.parsing import declarative_parser_profiles as profiles

    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    install_profile(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
        home=tmp_path,
    )
    target_dir = approved_profiles_dir(home=tmp_path) / "supplier_alpha"
    old_profile = (target_dir / PROFILE_FILE_NAME).read_bytes()
    old_approval = (target_dir / APPROVAL_FILE_NAME).read_bytes()
    profile_path.write_text(
        _profile_text().replace("version: 0.1.0", "version: 0.2.0"),
        encoding="utf-8",
    )
    original_replace = Path.replace

    def _fail_staged_promotion(path, target):
        if path.parent.name == ".staging":
            raise OSError("injected staged generation replace failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", _fail_staged_promotion)

    with pytest.raises(OSError, match="injected staged generation replace failure"):
        install_profile(
            profile_path,
            sample_paths=(sample_path,),
            expected_results_ref=expected_path,
            home=tmp_path,
        )

    parsers, errors = load_approved_profile_parsers(home=tmp_path)
    assert (target_dir / PROFILE_FILE_NAME).read_bytes() == old_profile
    assert (target_dir / APPROVAL_FILE_NAME).read_bytes() == old_approval
    assert errors == ()
    assert parsers[0][1].manifest.version == "0.1.0"
    assert not any((target_dir.parent / ".staging").iterdir())
    assert profiles.profile_store_signature(home=tmp_path)


def test_profile_update_sidecar_write_failure_leaves_existing_generation_intact(
    monkeypatch,
    tmp_path,
):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    install_profile(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
        home=tmp_path,
    )
    target_dir = approved_profiles_dir(home=tmp_path) / "supplier_alpha"
    old_profile = (target_dir / PROFILE_FILE_NAME).read_bytes()
    old_approval = (target_dir / APPROVAL_FILE_NAME).read_bytes()
    profile_path.write_text(
        _profile_text().replace("version: 0.1.0", "version: 0.2.0"),
        encoding="utf-8",
    )
    original_write_text = Path.write_text

    def _fail_staged_approval(path, *args, **kwargs):
        if path.name == APPROVAL_FILE_NAME and ".staging" in path.parts:
            raise OSError("injected approval sidecar write failure")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _fail_staged_approval)

    with pytest.raises(OSError, match="injected approval sidecar write failure"):
        install_profile(
            profile_path,
            sample_paths=(sample_path,),
            expected_results_ref=expected_path,
            home=tmp_path,
        )

    assert (target_dir / PROFILE_FILE_NAME).read_bytes() == old_profile
    assert (target_dir / APPROVAL_FILE_NAME).read_bytes() == old_approval
    assert load_approved_profile_parsers(home=tmp_path)[1] == ()


def test_profile_promotion_blocks_reader_until_complete_generation_is_visible(
    monkeypatch,
    tmp_path,
):
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    install_profile(
        profile_path,
        sample_paths=(sample_path,),
        expected_results_ref=expected_path,
        home=tmp_path,
    )
    old_parsers, old_errors = load_approved_profile_parsers(home=tmp_path)
    assert old_errors == ()
    assert old_parsers[0][1].manifest.version == "0.1.0"

    profile_path.write_text(
        _profile_text().replace("version: 0.1.0", "version: 0.2.0"),
        encoding="utf-8",
    )
    target_dir = approved_profiles_dir(home=tmp_path) / "supplier_alpha"
    generation_gap_open = Event()
    release_promotion = Event()
    reader_started = Event()
    original_replace = Path.replace

    def _pause_after_old_generation_moves(path, target):
        result = original_replace(path, target)
        if path == target_dir:
            generation_gap_open.set()
            assert release_promotion.wait(timeout=5)
        return result

    def _read_profiles():
        reader_started.set()
        return load_approved_profile_parsers(home=tmp_path)

    monkeypatch.setattr(Path, "replace", _pause_after_old_generation_moves)
    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(
            install_profile,
            profile_path,
            sample_paths=(sample_path,),
            expected_results_ref=expected_path,
            home=tmp_path,
        )
        assert generation_gap_open.wait(timeout=5)
        reader = executor.submit(_read_profiles)
        assert reader_started.wait(timeout=5)
        try:
            assert reader.done() is False
        finally:
            release_promotion.set()
        writer.result(timeout=5)
        new_parsers, new_errors = reader.result(timeout=5)

    assert new_errors == ()
    assert new_parsers[0][1].manifest.version == "0.2.0"


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


def test_report_factory_invalidates_changed_sidecar_and_removed_profile_generations(
    monkeypatch,
    tmp_path,
):
    from metroliza.reports import report_parser_factory

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    profile_path, sample_path, expected_path = _write_fixture(tmp_path)
    old_report = tmp_path / "old_supplier_report.pdf"
    old_report.write_text(_sample_text(), encoding="utf-8")
    original_map = dict(report_parser_factory.PARSER_MAP)
    original_manifests = dict(report_parser_factory.PARSER_MANIFESTS)
    original_detectors = dict(report_parser_factory.PARSER_DETECTORS)
    original_cache = dict(report_parser_factory.PROBE_RESULT_CACHE)
    original_loaded = report_parser_factory._EXTERNAL_PLUGINS_LOADED
    original_signature = report_parser_factory._EXTERNAL_PLUGIN_CONFIG_SIGNATURE
    original_entry_points = report_parser_factory._EXTERNAL_PLUGIN_ENTRY_POINTS

    monkeypatch.setattr(
        report_parser_factory,
        "_discover_external_plugin_entry_points",
        lambda force_refresh=False: (),
    )
    monkeypatch.setattr(
        report_parser_factory.parser_plugin_paths,
        "configured_external_plugin_path_entries",
        lambda raw_paths=None, include_default_dir=True, home=None: (),
    )
    try:
        install_profile(
            profile_path,
            sample_paths=(sample_path,),
            expected_results_ref=expected_path,
            home=tmp_path,
        )
        report_parser_factory.reset_external_plugin_loader_state()
        old_diagnostics = report_parser_factory.resolve_parser_with_diagnostics(old_report)
        old_parser_class = report_parser_factory.PARSER_MAP["supplier_alpha"]
        assert old_diagnostics.selected is not None
        assert old_diagnostics.selected.plugin_id == "supplier_alpha"
        assert report_parser_factory.PROBE_RESULT_CACHE

        profile_path.write_text(
            _profile_text()
            .replace("version: 0.1.0", "version: 0.2.0")
            .replace("SYNTHETIC SUPPLIER ALPHA", "SYNTHETIC SUPPLIER BETA"),
            encoding="utf-8",
        )
        sample_path.write_text(
            _sample_text().replace(
                "SYNTHETIC SUPPLIER ALPHA",
                "SYNTHETIC SUPPLIER BETA",
            ),
            encoding="utf-8",
        )
        install_profile(
            profile_path,
            sample_paths=(sample_path,),
            expected_results_ref=expected_path,
            home=tmp_path,
        )
        assert report_parser_factory._EXTERNAL_PLUGINS_LOADED is False
        assert not report_parser_factory.PROBE_RESULT_CACHE

        changed_diagnostics = report_parser_factory.resolve_parser_with_diagnostics(sample_path)
        changed_parser_class = report_parser_factory.PARSER_MAP["supplier_alpha"]
        assert changed_diagnostics.selected is not None
        assert changed_diagnostics.selected.plugin_id == "supplier_alpha"
        assert changed_parser_class is not old_parser_class
        stale_diagnostics = report_parser_factory.resolve_parser_with_diagnostics(old_report)
        assert stale_diagnostics.selected is None

        approved_dir = approved_profiles_dir(home=tmp_path) / "supplier_alpha"
        approval_path = approved_dir / APPROVAL_FILE_NAME
        approval_payload = json.loads(approval_path.read_text(encoding="utf-8"))
        approval_payload["approved_by"] = "changed-sidecar"
        approval_path.write_text(
            json.dumps(approval_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_parser_factory.resolve_parser_with_diagnostics(sample_path)
        sidecar_parser_class = report_parser_factory.PARSER_MAP["supplier_alpha"]
        assert sidecar_parser_class is not changed_parser_class

        approval_bytes = approval_path.read_bytes()
        approval_path.unlink()
        no_approval = report_parser_factory.resolve_parser_with_diagnostics(sample_path)
        assert "supplier_alpha" not in report_parser_factory.PARSER_MAP
        assert no_approval.selected is None

        approval_path.write_bytes(approval_bytes)
        restored = report_parser_factory.resolve_parser_with_diagnostics(sample_path)
        assert restored.selected is not None
        assert restored.selected.plugin_id == "supplier_alpha"

        shutil.rmtree(approved_dir)
        removed = report_parser_factory.resolve_parser_with_diagnostics(sample_path)
        assert "supplier_alpha" not in report_parser_factory.PARSER_MAP
        assert removed.selected is None
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
