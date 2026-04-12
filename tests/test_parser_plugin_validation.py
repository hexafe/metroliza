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

contracts = importlib.import_module("modules.parser_plugin_contracts")
base_module = importlib.import_module("modules.base_report_parser")
validation = importlib.import_module("modules.parser_plugin_validation")

BaseReportParser = base_module.BaseReportParser
BaseReportParserPlugin = contracts.BaseReportParserPlugin
MeasurementBlockV2 = contracts.MeasurementBlockV2
MeasurementV2 = contracts.MeasurementV2
ParseMetaV2 = contracts.ParseMetaV2
ParseResultV2 = contracts.ParseResultV2
PluginManifest = contracts.PluginManifest
ProbeResult = contracts.ProbeResult
ReportInfoV2 = contracts.ReportInfoV2


def test_validate_plugin_contract_passes_for_well_formed_plugin():
    class DemoParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="demo_plugin",
            display_name="Demo Plugin",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        @classmethod
        def probe(cls, _input_ref, _context):
            return ProbeResult(plugin_id="demo_plugin", can_parse=True, confidence=90)

        def open_report(self):
            self.raw_text = ["ok"]

        def split_text_to_blocks(self):
            self.blocks_text = []

        def parse_to_v2(self):
            return ParseResultV2(
                meta=ParseMetaV2(
                    source_file="sample.pdf",
                    source_format="pdf",
                    plugin_id="demo_plugin",
                    plugin_version="1.0.0",
                    template_id=None,
                    parse_timestamp="2026-01-01T00:00:00Z",
                    locale_detected=None,
                    confidence=90,
                ),
                report=ReportInfoV2(
                    reference="REF",
                    report_date="2026-01-01",
                    sample_number="001",
                    file_name="sample.pdf",
                    file_path=".",
                ),
                blocks=(),
            )

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            return []

    report = validation.validate_plugin_contract(DemoParser, parse_invoker=lambda parser: parser.parse_to_v2())

    assert report.passed is True
    assert report.plugin_id == "demo_plugin"


def test_validate_plugin_contract_fails_on_invalid_probe_response():
    class BadProbeParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="bad_probe",
            display_name="Bad Probe",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        @classmethod
        def probe(cls, _input_ref, _context):
            return "not-probe-result"

        def open_report(self):
            self.raw_text = []

        def split_text_to_blocks(self):
            self.blocks_text = []

        def parse_to_v2(self):
            raise NotImplementedError

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            return []

    report = validation.validate_plugin_contract(BadProbeParser)

    assert report.passed is False
    assert any(check.name == "probe_returns_probe_result" and not check.passed for check in report.checks)


def test_validate_plugin_contract_compares_against_expected_results_csv(tmp_path):
    class DemoSemanticParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="demo_semantic",
            display_name="Demo Semantic",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        @classmethod
        def probe(cls, _input_ref, _context):
            return ProbeResult(plugin_id="demo_semantic", can_parse=True, confidence=90)

        def open_report(self):
            self.raw_text = ["ok"]

        def split_text_to_blocks(self):
            self.blocks_text = []

        def parse_to_v2(self):
            return ParseResultV2(
                meta=ParseMetaV2(
                    source_file="sample_report_01.pdf",
                    source_format="pdf",
                    plugin_id="demo_semantic",
                    plugin_version="1.0.0",
                    template_id="default",
                    parse_timestamp="2026-01-01T00:00:00Z",
                    locale_detected=None,
                    confidence=90,
                ),
                report=ReportInfoV2(
                    reference="REF123",
                    report_date="2026-01-05",
                    sample_number="0001",
                    file_name="sample_report_01.pdf",
                    file_path=".",
                ),
                blocks=(
                    MeasurementBlockV2(
                        header_raw=("MAIN FEATURE",),
                        header_normalized="MAIN FEATURE",
                        dimensions=(
                            MeasurementV2(
                                axis_code="X",
                                nominal=10.0,
                                tol_plus=0.1,
                                tol_minus=-0.1,
                                bonus=None,
                                measured=10.02,
                                deviation=0.02,
                                out_of_tolerance=0.0,
                            ),
                        ),
                        block_index=0,
                    ),
                ),
            )

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            return []

    sample_file = tmp_path / "sample_report_01.pdf"
    sample_file.write_text("placeholder\n", encoding="utf-8")
    expected_results = tmp_path / "expected_results_template.csv"
    expected_results.write_text(
        "sample_file,reference,report_date,sample_number,block_index,header_normalized,axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
        "sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0\n",
        encoding="utf-8",
    )

    report = validation.validate_plugin_contract(
        DemoSemanticParser,
        sample_input_ref=sample_file,
        parse_invoker=lambda parser: parser.parse_to_v2(),
        expected_results_ref=expected_results,
    )

    assert report.passed is True
    assert any(check.name == "expected_results_sample_rows_found" and check.passed for check in report.checks)


def test_validate_plugin_contract_reports_expected_results_mismatch(tmp_path):
    class DemoMismatchParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="demo_mismatch",
            display_name="Demo Mismatch",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        @classmethod
        def probe(cls, _input_ref, _context):
            return ProbeResult(plugin_id="demo_mismatch", can_parse=True, confidence=90)

        def open_report(self):
            self.raw_text = ["ok"]

        def split_text_to_blocks(self):
            self.blocks_text = []

        def parse_to_v2(self):
            return ParseResultV2(
                meta=ParseMetaV2(
                    source_file="sample_report_01.pdf",
                    source_format="pdf",
                    plugin_id="demo_mismatch",
                    plugin_version="1.0.0",
                    template_id="default",
                    parse_timestamp="2026-01-01T00:00:00Z",
                    locale_detected=None,
                    confidence=90,
                ),
                report=ReportInfoV2(
                    reference="REF123",
                    report_date="2026-01-05",
                    sample_number="0001",
                    file_name="sample_report_01.pdf",
                    file_path=".",
                ),
                blocks=(
                    MeasurementBlockV2(
                        header_raw=("MAIN FEATURE",),
                        header_normalized="MAIN FEATURE",
                        dimensions=(
                            MeasurementV2(
                                axis_code="X",
                                nominal=10.0,
                                tol_plus=0.1,
                                tol_minus=-0.1,
                                bonus=None,
                                measured=10.5,
                                deviation=0.5,
                                out_of_tolerance=1.0,
                            ),
                        ),
                        block_index=0,
                    ),
                ),
            )

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            return []

    sample_file = tmp_path / "sample_report_01.pdf"
    sample_file.write_text("placeholder\n", encoding="utf-8")
    expected_results = tmp_path / "expected_results_template.csv"
    expected_results.write_text(
        "sample_file,reference,report_date,sample_number,block_index,header_normalized,axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
        "sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0\n",
        encoding="utf-8",
    )

    report = validation.validate_plugin_contract(
        DemoMismatchParser,
        sample_input_ref=sample_file,
        parse_invoker=lambda parser: parser.parse_to_v2(),
        expected_results_ref=expected_results,
    )

    assert report.passed is False
    assert any(check.name.endswith("_measured_matches") and not check.passed for check in report.checks)
