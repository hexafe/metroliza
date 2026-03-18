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
build_plugin_scaffold = importlib.import_module("modules.llm_plugin_factory").build_plugin_scaffold


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
    assert "parse_to_v2" in scaffold.plugin_template
    assert "to_legacy_blocks" in scaffold.plugin_template
    assert "contract_conformance" in scaffold.test_template
