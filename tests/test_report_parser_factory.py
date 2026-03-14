import importlib
import importlib.machinery
import sys
import types


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
contracts_module = importlib.import_module("modules.parser_plugin_contracts")

CMMReportParser = importlib.import_module("modules.CMMReportParser").CMMReportParser
BaseReportParser = base_module.BaseReportParser
BaseReportParserPlugin = contracts_module.BaseReportParserPlugin
PluginManifest = contracts_module.PluginManifest
ProbeContext = contracts_module.ProbeContext
ProbeResult = contracts_module.ProbeResult
PARSER_MANIFESTS = factory_module.PARSER_MANIFESTS
PARSER_MAP = factory_module.PARSER_MAP
PARSER_DETECTORS = factory_module.PARSER_DETECTORS
detect_format = factory_module.detect_format
get_parser = factory_module.get_parser
register_parser = factory_module.register_parser
resolve_parser_with_diagnostics = factory_module.resolve_parser_with_diagnostics


def test_detect_format_accepts_pathlike(tmp_path):
    report_path = tmp_path / "A1234_2024-01-01_001.PDF"
    assert detect_format(report_path) == "cmm"


def test_get_parser_returns_cmm_parser_for_pdf(tmp_path):
    report_path = tmp_path / "A1234_2024-01-01_001.pdf"
    parser = get_parser(report_path, database=":memory:")
    assert isinstance(parser, CMMReportParser)


def test_register_parser_allows_runtime_extension(tmp_path):
    class DummyParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="dummy",
            display_name="Dummy",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        @classmethod
        def probe(cls, _path, _context: ProbeContext) -> ProbeResult:
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse=True,
                confidence=50,
            )

        def open_report(self):
            self.raw_text = ["ok"]

        def split_text_to_blocks(self):
            self.blocks_text = []

        def parse_to_v2(self):
            raise NotImplementedError

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            return []

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    try:
        register_parser(DummyParser)
        parser = get_parser(tmp_path / "file.pdf", database=":memory:")
        assert "dummy" in PARSER_MAP
        assert isinstance(parser, BaseReportParser)
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)



def test_register_parser_supports_legacy_signature_with_detector(tmp_path):
    class LegacyDummyParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="legacy_dummy",
            display_name="Legacy Dummy",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        @classmethod
        def probe(cls, _path, _context: ProbeContext) -> ProbeResult:
            return ProbeResult(plugin_id=cls.manifest.plugin_id, can_parse=False, confidence=0)

        def open_report(self):
            self.raw_text = ["ok"]

        def split_text_to_blocks(self):
            self.blocks_text = []

        def parse_to_v2(self):
            raise NotImplementedError

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            return []

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    try:
        register_parser(
            "legacy_dummy",
            LegacyDummyParser,
            detector=lambda _path: ProbeResult(
                plugin_id="legacy_dummy",
                can_parse=True,
                confidence=101,
                reasons=("legacy_detector",),
            ),
        )

        parser = get_parser(tmp_path / "legacy_file.pdf", database=":memory:")
        assert isinstance(parser, LegacyDummyParser)
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)

def test_resolver_reports_no_plugin_for_unknown_format(tmp_path):
    diagnostics = resolve_parser_with_diagnostics(tmp_path / "file.txt")
    assert diagnostics.selected is None
    assert diagnostics.rejected_reason == "no_plugin_can_parse"


def test_pdf_alias_assignment_updates_canonical_blocks_text():
    parser = CMMReportParser("REF01_2024-01-02_123.pdf", database=":memory:")
    parser.pdf_blocks_text = [[["Header"], [["X", 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]]]]

    assert parser.blocks_text == parser.pdf_blocks_text
