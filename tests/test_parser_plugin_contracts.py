import importlib
import importlib.machinery
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
default_external_plugin_dir_display = importlib.import_module(
    "modules.parser_plugin_paths"
).default_external_plugin_dir_display


def test_cmm_parse_to_v2_and_back_to_legacy_roundtrip_shape():
    parser = CMMReportParser("REF01_2024-01-02_123.pdf", database=":memory:")
    parser.raw_text = ["dummy"]
    parser.blocks_text = [[["Header A"], [["X", 1.0, 0.1, -0.1, 0.0, 1.02, 0.02, 0.0]]]]

    parse_result = parser.parse_to_v2()

    assert parse_result.meta.plugin_id == "cmm"
    assert parse_result.report.reference == parser.reference
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


def test_llm_plugin_workspace_bundle_contains_install_and_validation_guidance():
    bundle = build_plugin_workspace_bundle(plugin_id="supplier_alpha", source_format="pdf")

    assert "python scripts/validate_parser_plugins.py" in bundle["README.md"]
    assert default_external_plugin_dir_display() in bundle["README.md"]
    assert "sample_report_01.pdf" in bundle["expected_results_template.csv"]
    assert "generated_plugin.py" in bundle["README.md"]
    assert "artifacts/README.md" in bundle


def test_write_plugin_workspace_writes_bundle_files(tmp_path):
    output_dir = tmp_path / "workspace"

    result = write_plugin_workspace(output_dir, plugin_id="supplier_alpha", source_format="csv")

    assert result.output_dir == output_dir
    assert (output_dir / "README.md").exists()
    assert (output_dir / "prompts" / "01_analysis_prompt.md").exists()
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
