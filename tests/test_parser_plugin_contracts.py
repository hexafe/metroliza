import importlib
import importlib.machinery
import json
import sys
import types


custom_logger_stub = types.ModuleType("modules.custom_logger")


class _DummyCustomLogger:
    def __init__(self, *_args, **_kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyCustomLogger
sys.modules.setdefault("modules.custom_logger", custom_logger_stub)

fitz_stub = types.ModuleType("fitz")
fitz_stub.__spec__ = importlib.machinery.ModuleSpec("fitz", loader=None)
fitz_stub.open = lambda *_args, **_kwargs: None
sys.modules.setdefault("fitz", fitz_stub)

CMMReportParser = importlib.import_module("modules.cmm_report_parser").CMMReportParser
llm_plugin_factory = importlib.import_module("modules.llm_plugin_factory")
build_plugin_scaffold = llm_plugin_factory.build_plugin_scaffold
build_plugin_workspace_bundle = llm_plugin_factory.build_plugin_workspace_bundle
write_plugin_workspace = llm_plugin_factory.write_plugin_workspace
parser_profile_handoff = importlib.import_module("metroliza.parsing.parser_profile_handoff")
default_external_plugin_dir_display = importlib.import_module(
    "modules.parser_plugin_paths"
).default_external_plugin_dir_display


PYTHON_MICROTASK_PROMPT_ORDER = [
    "prompts/microtasks/01_template_analysis.md",
    "prompts/microtasks/02_manifest_probe.md",
    "prompts/microtasks/03_parser_implementation.md",
    "prompts/microtasks/04_parse_result_v2_mapping.md",
    "prompts/microtasks/05_tests_expected_results.md",
    "prompts/microtasks/06_repair_failed_checks.md",
]
DECLARATIVE_MICROTASK_PROMPT_ORDER = [
    "prompts/01_identify_template_markers.md",
    "prompts/02_extract_report_identity.md",
    "prompts/03_extract_measurement_rows.md",
    "prompts/04_define_normalization.md",
    "prompts/05_complete_profile_yaml.md",
    "prompts/06_fix_validation_failures.md",
]


def _load_handoff_manifest(workspace):
    return json.loads((workspace.root / "handoff_manifest.json").read_text(encoding="utf-8"))


def _write_handoff_manifest(workspace, manifest):
    (workspace.root / "handoff_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _integrity_check(report, name):
    return next(check for check in report.checks if check.name == name)


def test_cmm_parse_to_v2_and_back_to_legacy_roundtrip_shape():
    parser = CMMReportParser("REF01_2024-01-02_123.pdf", database=":memory:")
    parser.raw_text = ["dummy"]
    parser.blocks_text = [[["Header A"], [["X", 1.0, 0.1, -0.1, 0.0, 1.02, 0.02, 0.0]]]]

    parse_result = parser.parse_to_v2()

    assert parse_result.meta.plugin_id == "cmm"
    assert parse_result.report.reference == (parser.reference or "")
    assert len(parse_result.blocks) == 1
    assert parse_result.blocks[0].dimensions[0].axis_code == "X"

    legacy_blocks = parser.to_legacy_blocks(parse_result)
    assert legacy_blocks[0][1][0][0] == "X"


def test_llm_plugin_factory_scaffold_contains_required_entrypoints():
    scaffold = build_plugin_scaffold()

    assert "ParseResultV2" in scaffold.analysis_prompt_template
    assert "inside the existing parser-plugin contract" in scaffold.analysis_prompt_template
    assert "Runtime selection notes" in scaffold.analysis_prompt_template
    assert "Expected-results validation notes" in scaffold.analysis_prompt_template
    assert "open_report" in scaffold.plugin_template
    assert "split_text_to_blocks" in scaffold.plugin_template
    assert "parse_to_v2" in scaffold.plugin_template
    assert "to_legacy_blocks" in scaffold.plugin_template
    assert "supported_locales" in scaffold.plugin_template
    assert "priority" in scaffold.plugin_template
    assert "probe_result = {{CLASS_NAME}}.probe" in scaffold.test_template
    assert "legacy_blocks = parser.to_legacy_blocks(parse_result)" in scaffold.test_template
    assert "template_markers_not_configured" in scaffold.plugin_template
    assert "missing_template_markers" in scaffold.plugin_template


def test_llm_plugin_workspace_bundle_contains_install_and_validation_guidance():
    bundle = build_plugin_workspace_bundle(plugin_id="supplier_alpha", source_format="pdf")
    manifest = json.loads(bundle["handoff_manifest.json"])

    assert "python scripts/validate_parser_plugins.py" in bundle["README.md"]
    assert default_external_plugin_dir_display() in bundle["README.md"]
    assert "sample_report_01.pdf" in bundle["expected_results_template.csv"]
    assert "generated_plugin.py" in bundle["README.md"]
    assert "artifacts/README.md" in bundle
    assert "NON_TECHNICAL_STEPS.md" in bundle
    assert "contracts/00_read_this_first.md" in bundle
    assert "contracts/01_parser_api_contract.md" in bundle
    assert "contracts/03_sqlite_persistence_contract.md" in bundle
    assert "contracts/07_privacy_redaction_checklist.md" in bundle
    assert "reference/contract_snippets.md" in bundle
    assert "prompts/microtasks/01_template_analysis.md" in bundle
    assert "prompts/microtasks/06_repair_failed_checks.md" in bundle
    assert manifest["plugin_id"] == "supplier_alpha"
    assert manifest["source_format"] == "pdf"
    assert manifest["full_prompt_order"] == [
        "prompts/01_analysis_prompt.md",
        "prompts/02_implementation_prompt.md",
    ]
    assert manifest["microtask_prompt_order"] == PYTHON_MICROTASK_PROMPT_ORDER
    assert manifest["prompt_files"] == [
        "prompts/01_analysis_prompt.md",
        "prompts/02_implementation_prompt.md",
        *PYTHON_MICROTASK_PROMPT_ORDER,
    ]
    assert "contracts/07_privacy_redaction_checklist.md" in manifest["contract_files"]
    assert manifest["runtime_contract"]["plugin_must_write_sqlite"] is False
    assert manifest["runtime_contract"]["strict_selection_min_confidence"] == 80
    assert "PluginManifest" in bundle["reference/contract_snippets.md"]
    assert "ProbeResult" in bundle["reference/contract_snippets.md"]
    assert "ParseResultV2" in bundle["reference/contract_snippets.md"]
    assert "sample_file,reference,report_date" in bundle["reference/contract_snippets.md"]
    assert "Metroliza owns database writes" in bundle["contracts/00_read_this_first.md"]
    assert "Strict matching requires confidence >= 80" in bundle["contracts/02_runtime_selection_contract.md"]
    assert "every parsed measurement row" in bundle["contracts/04_expected_results_contract.md"]


def test_declarative_handoff_manifest_is_self_contained(tmp_path):
    workspace = parser_profile_handoff.create_profile_handoff_workspace(
        plugin_id="supplier_alpha",
        display_name="Supplier Alpha",
        source_format="csv",
        output_dir=tmp_path / "handoff",
    )

    manifest = _load_handoff_manifest(workspace)
    report = parser_profile_handoff.validate_handoff_workspace(workspace.root)

    assert report.passed
    assert manifest["package_type"] == "declarative_profile"
    assert manifest["allowed_outputs"] == ["profile.yaml"]
    assert manifest["installation_path"].endswith("/profiles/approved/supplier_alpha/profile.yaml")
    assert manifest["full_prompt_order"] == []
    assert manifest["prompt_files"] == DECLARATIVE_MICROTASK_PROMPT_ORDER
    assert manifest["microtask_prompt_order"] == DECLARATIVE_MICROTASK_PROMPT_ORDER
    assert (workspace.root / "contracts" / "07_privacy_redaction_checklist.md").exists()


def test_handoff_integrity_rejects_stale_or_missing_microtask_prompt_entries(tmp_path):
    workspace = parser_profile_handoff.create_profile_handoff_workspace(
        plugin_id="supplier_alpha",
        display_name="Supplier Alpha",
        source_format="csv",
        output_dir=tmp_path / "handoff",
    )
    manifest = _load_handoff_manifest(workspace)
    manifest["microtask_prompt_order"] = [
        "prompts/01_identify_template_markers.md",
        "prompts/02_map_report_fields.md",
    ]
    _write_handoff_manifest(workspace, manifest)

    report = parser_profile_handoff.validate_handoff_workspace(workspace.root)
    check = _integrity_check(report, "manifest_microtask_prompt_order")

    assert not report.passed
    assert not check.passed
    assert "prompts/02_extract_report_identity.md" in check.detail
    assert "prompts/02_map_report_fields.md" in check.detail


def test_handoff_integrity_rejects_prompt_files_that_omit_generated_prompt(tmp_path):
    workspace = parser_profile_handoff.create_profile_handoff_workspace(
        plugin_id="supplier_alpha",
        display_name="Supplier Alpha",
        source_format="csv",
        output_dir=tmp_path / "handoff",
    )
    manifest = _load_handoff_manifest(workspace)
    manifest["prompt_files"] = [
        path
        for path in manifest["prompt_files"]
        if path != "prompts/03_extract_measurement_rows.md"
    ]
    _write_handoff_manifest(workspace, manifest)

    report = parser_profile_handoff.validate_handoff_workspace(workspace.root)
    check = _integrity_check(report, "manifest_prompt_files_match_workspace")

    assert not report.passed
    assert not check.passed
    assert "prompts/03_extract_measurement_rows.md" in check.detail


def test_handoff_integrity_rejects_bad_manifest_json(tmp_path):
    workspace = parser_profile_handoff.create_profile_handoff_workspace(
        plugin_id="supplier_alpha",
        display_name="Supplier Alpha",
        source_format="csv",
        output_dir=tmp_path / "handoff",
    )
    (workspace.root / "handoff_manifest.json").write_text("{bad json\n", encoding="utf-8")

    report = parser_profile_handoff.validate_handoff_workspace(workspace.root)
    check = _integrity_check(report, "manifest_json_readable")

    assert not report.passed
    assert not check.passed


def test_handoff_integrity_rejects_missing_manifest_referenced_file(tmp_path):
    workspace = parser_profile_handoff.create_profile_handoff_workspace(
        plugin_id="supplier_alpha",
        display_name="Supplier Alpha",
        source_format="csv",
        output_dir=tmp_path / "handoff",
    )
    missing_prompt = workspace.root / "prompts" / "04_define_normalization.md"
    missing_prompt.unlink()

    report = parser_profile_handoff.validate_handoff_workspace(workspace.root)
    check = _integrity_check(report, "manifest_referenced_files_exist")

    assert not report.passed
    assert not check.passed
    assert "prompts/04_define_normalization.md" in check.detail


def test_write_plugin_workspace_writes_bundle_files(tmp_path):
    output_dir = tmp_path / "workspace"

    result = write_plugin_workspace(output_dir, plugin_id="supplier_alpha", source_format="csv")

    assert result.output_dir == output_dir
    assert (output_dir / "README.md").exists()
    assert (output_dir / "prompts" / "01_analysis_prompt.md").exists()
    assert (output_dir / "prompts" / "microtasks" / "01_template_analysis.md").exists()
    assert (output_dir / "contracts" / "01_parser_api_contract.md").exists()
    assert (output_dir / "reference" / "contract_snippets.md").exists()
    assert (output_dir / "handoff_manifest.json").exists()
    assert (output_dir / "tests" / "test_generated_plugin.py").exists()
    assert (output_dir / "artifacts" / "README.md").read_text(encoding="utf-8").strip()


def test_write_plugin_workspace_rejects_non_empty_directory_without_overwrite(tmp_path):
    output_dir = tmp_path / "workspace"
    output_dir.mkdir()
    (output_dir / "placeholder.txt").write_text("existing\n", encoding="utf-8")

    try:
        write_plugin_workspace(output_dir, plugin_id="supplier_alpha")
    except FileExistsError as exc:
        assert str(output_dir) in str(exc)
    else:  # pragma: no cover - defensive assertion branch
        raise AssertionError("Expected FileExistsError for non-empty workspace output directory")
