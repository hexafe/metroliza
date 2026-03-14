import importlib
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path


custom_logger_stub = types.ModuleType("modules.CustomLogger")


class _DummyCustomLogger:
    def __init__(self, *_args, **_kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyCustomLogger
sys.modules.setdefault("modules.CustomLogger", custom_logger_stub)

fitz_stub = types.ModuleType("fitz")
fitz_stub.__spec__ = importlib.machinery.ModuleSpec("fitz", loader=None)
fitz_stub.open = lambda *_args, **_kwargs: None
sys.modules.setdefault("fitz", fitz_stub)

factory_module = importlib.import_module("modules.report_parser_factory")
base_module = importlib.import_module("modules.base_report_parser")


def _load_real_cmm_report_parser_class():
    module_path = Path("modules/CMMReportParser.py")
    spec = importlib.util.spec_from_file_location("_real_cmm_report_parser_for_factory_tests", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.CMMReportParser


CMMReportParser = _load_real_cmm_report_parser_class()
BaseReportParser = base_module.BaseReportParser
PARSER_DETECTORS = factory_module.PARSER_DETECTORS
PARSER_MAP = factory_module.PARSER_MAP
ProbeResult = factory_module.ProbeResult
detect_format = factory_module.detect_format
get_parser = factory_module.get_parser
register_parser = factory_module.register_parser


def test_detect_format_accepts_pathlike(tmp_path):
    report_path = tmp_path / "A1234_2024-01-01_001.PDF"
    assert detect_format(report_path) == "cmm"


def test_get_parser_returns_cmm_parser_for_pdf(tmp_path):
    report_path = tmp_path / "A1234_2024-01-01_001.pdf"

    original_cmm = PARSER_MAP.get("cmm")
    PARSER_MAP["cmm"] = CMMReportParser
    try:
        parser = get_parser(report_path, database=":memory:")
    finally:
        if original_cmm is None:
            del PARSER_MAP["cmm"]
        else:
            PARSER_MAP["cmm"] = original_cmm

    assert isinstance(parser, CMMReportParser)


def test_register_parser_allows_runtime_extension(tmp_path):
    class DummyParser(BaseReportParser):
        def open_report(self):
            self.raw_text = ["ok"]

        def split_text_to_blocks(self):
            self.blocks_text = []

    original_map = dict(PARSER_MAP)
    original_detectors = dict(PARSER_DETECTORS)
    try:
        register_parser(
            "dummy",
            DummyParser,
            detector=lambda _path: ProbeResult(
                format_id="dummy",
                can_parse=True,
                confidence=50,
            ),
        )

        parser = get_parser(tmp_path / "file.any", database=":memory:")
        assert "dummy" in PARSER_MAP
        assert isinstance(parser, DummyParser)
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)


def test_pdf_alias_assignment_updates_canonical_blocks_text():
    parser = CMMReportParser("REF01_2024-01-02_123.pdf", database=":memory:")
    parser.pdf_blocks_text = [[['Header'], [['X', 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]]]]

    assert parser.blocks_text == parser.pdf_blocks_text
