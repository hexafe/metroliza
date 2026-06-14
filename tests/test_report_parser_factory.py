import importlib
import importlib.machinery
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import types

import pytest


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

# Some integration tests install a lightweight `modules.cmm_report_parser` stub in
# `sys.modules` before importing thread modules. This test module needs the real
# parser implementation, so force a clean import of both the parser and factory.
sys.modules.pop("modules.report_parser_factory", None)
sys.modules.pop("metroliza.reports.report_parser_factory", None)
sys.modules.pop("modules.cmm_report_parser", None)
sys.modules.pop("metroliza.parsing.cmm_report_parser", None)

factory_module = importlib.import_module("modules.report_parser_factory")
base_module = importlib.import_module("modules.base_report_parser")
contracts_module = importlib.import_module("modules.parser_plugin_contracts")
parser_plugin_paths_module = importlib.import_module("modules.parser_plugin_paths")


CMMReportParser = importlib.import_module("modules.cmm_report_parser").CMMReportParser
BaseReportParser = base_module.BaseReportParser
BaseReportParserPlugin = contracts_module.BaseReportParserPlugin
MeasurementBlockV2 = contracts_module.MeasurementBlockV2
MeasurementV2 = contracts_module.MeasurementV2
ParseMetaV2 = contracts_module.ParseMetaV2
ParseResultV2 = contracts_module.ParseResultV2
ParseWarning = contracts_module.ParseWarning
PluginManifest = contracts_module.PluginManifest
ProbeContext = contracts_module.ProbeContext
ProbeResult = contracts_module.ProbeResult
ReportInfoV2 = contracts_module.ReportInfoV2
infer_source_format = contracts_module.infer_source_format
PARSER_MANIFESTS = factory_module.PARSER_MANIFESTS
PARSER_MAP = factory_module.PARSER_MAP
PARSER_DETECTORS = factory_module.PARSER_DETECTORS
PROBE_RESULT_CACHE = factory_module.PROBE_RESULT_CACHE
detect_format = factory_module.detect_format
get_parser = factory_module.get_parser
register_parser = factory_module.register_parser
reset_probe_cache = factory_module.reset_probe_cache
reset_external_plugin_loader_state = factory_module.reset_external_plugin_loader_state
resolve_parser_with_diagnostics = factory_module.resolve_parser_with_diagnostics


def _restore_real_cmm_registration():
    PARSER_MAP["cmm"] = CMMReportParser
    PARSER_MANIFESTS["cmm"] = PluginManifest(
        plugin_id="cmm",
        display_name="CMM PDF Parser",
        version=CMMReportParser.manifest.version,
        supported_formats=("pdf",),
        priority=100,
    )
    PARSER_DETECTORS["cmm"] = CMMReportParser.probe_pdf_candidate


def _write_cmm_probe_fixture(path: Path) -> Path:
    path.write_bytes(
        b"%PDF-1.4\n"
        b"CMM REPORT\n"
        b"REFERENCE: REF01\n"
        b"DATE: 2024-01-02\n"
        b"PART NAME: BRACKET\n"
        b"MEASUREMENT MADE BY: CMM OPERATOR A\n"
        b"NOMINAL TOL MEASURED DEVIATION OUTTOL\n"
    )
    return path


def test_detect_format_accepts_pathlike(tmp_path):
    report_path = tmp_path / "A1234_2024-01-01_001.PDF"
    _write_cmm_probe_fixture(report_path)
    assert detect_format(report_path) == "cmm"


def test_factory_uses_statically_imported_builtin_cmm_parser():
    assert factory_module.CMMReportParser is CMMReportParser


def test_get_parser_returns_cmm_parser_for_pdf(tmp_path):
    report_path = tmp_path / "A1234_2024-01-01_001.pdf"
    _write_cmm_probe_fixture(report_path)

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    try:
        _restore_real_cmm_registration()
        parser = get_parser(report_path, database=":memory:")
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)

    assert parser.__class__.__name__ == "CMMReportParser"


def test_get_parser_passes_metadata_mode_to_constructor_when_supported(tmp_path):
    class ConstructorModeParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="constructor_mode",
            display_name="Constructor Mode",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        def __init__(self, file_path, database, connection=None, metadata_parsing_mode=None):
            super().__init__(file_path=file_path, database=database, connection=connection)
            self.constructor_mode = metadata_parsing_mode
            self.metadata_parsing_mode = None

        @classmethod
        def probe(cls, _path, _context: ProbeContext) -> ProbeResult:
            return ProbeResult(plugin_id=cls.manifest.plugin_id, can_parse=True, confidence=100)

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
        register_parser(ConstructorModeParser)
        parser = get_parser(
            tmp_path / "constructor_mode.pdf",
            database=":memory:",
            metadata_parsing_mode="light",
        )
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)

    assert isinstance(parser, ConstructorModeParser)
    assert parser.constructor_mode == "light"
    assert parser.metadata_parsing_mode == "light"


def test_get_parser_falls_back_for_constructor_without_metadata_mode(tmp_path):
    class LegacyConstructorParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="legacy_ctor",
            display_name="Legacy Constructor",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        def __init__(self, file_path, database, connection=None):
            super().__init__(file_path=file_path, database=database, connection=connection)

        @classmethod
        def probe(cls, _path, _context: ProbeContext) -> ProbeResult:
            return ProbeResult(plugin_id=cls.manifest.plugin_id, can_parse=True, confidence=100)

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
        register_parser(LegacyConstructorParser)
        parser = get_parser(
            tmp_path / "legacy_ctor.pdf",
            database=":memory:",
            metadata_parsing_mode="light",
        )
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)

    assert isinstance(parser, LegacyConstructorParser)


def test_get_parser_sets_metadata_mode_attribute_post_construction(tmp_path):
    class AttributeModeParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="attribute_mode",
            display_name="Attribute Mode",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        def __init__(self, file_path, database, connection=None):
            super().__init__(file_path=file_path, database=database, connection=connection)
            self.metadata_parsing_mode = "complete"

        @classmethod
        def probe(cls, _path, _context: ProbeContext) -> ProbeResult:
            return ProbeResult(plugin_id=cls.manifest.plugin_id, can_parse=True, confidence=100)

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
        register_parser(AttributeModeParser)
        parser = get_parser(
            tmp_path / "attribute_mode.pdf",
            database=":memory:",
            metadata_parsing_mode="light",
        )
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)

    assert isinstance(parser, AttributeModeParser)
    assert parser.metadata_parsing_mode == "light"


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
                confidence=90,
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
    original_detectors = dict(PARSER_DETECTORS)
    try:
        _restore_real_cmm_registration()
        register_parser(DummyParser)
        parser = get_parser(tmp_path / "file.pdf", database=":memory:")
        assert "dummy" in PARSER_MAP
        assert isinstance(parser, BaseReportParser)
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)


def test_generated_v2_parser_persists_through_base_repository_bridge(tmp_path):
    class GeneratedCsvParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="generated_csv",
            display_name="Generated CSV",
            version="0.1.0",
            supported_formats=("csv",),
            template_ids=("generated_fixture",),
        )

        @classmethod
        def probe(cls, _path, _context: ProbeContext) -> ProbeResult:
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse=True,
                confidence=95,
                matched_template_id="generated_fixture",
            )

        def open_report(self):
            self.raw_text = ["generated fixture"]

        def split_text_to_blocks(self):
            self.blocks_text = [[["MAIN FEATURE"], [["X", 10.0, 0.1, -0.1, None, 10.2, 0.2, 0.2]]]]

        def parse_to_v2(self):
            if not self.raw_text:
                self.open_report()
            return ParseResultV2(
                meta=ParseMetaV2(
                    source_file=self.source_path,
                    source_format="csv",
                    plugin_id=self.manifest.plugin_id,
                    plugin_version=self.manifest.version,
                    template_id="generated_fixture",
                    parse_timestamp="2026-01-01T00:00:00Z",
                    locale_detected="en-US",
                    confidence=95,
                ),
                report=ReportInfoV2(
                    reference="REF-GEN",
                    report_date="2026-01-05",
                    sample_number="0001",
                    file_name=self.file_name,
                    file_path=self.file_path,
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
                                measured=10.2,
                                deviation=0.2,
                                out_of_tolerance=0.2,
                                raw_tokens=("X", "10.2"),
                                raw_line_refs=(4,),
                                extensions={
                                    "characteristic_name": "Position X",
                                    "characteristic_family": "position",
                                },
                            ),
                        ),
                        block_index=0,
                    ),
                ),
                warnings=(ParseWarning(code="rounded_value", message="Rounded value in source", field="X"),),
            )

        @staticmethod
        def to_legacy_blocks(parse_result_v2):
            return [
                [
                    [list(block.header_raw)],
                    [
                        [
                            row.axis_code,
                            row.nominal,
                            row.tol_plus,
                            row.tol_minus,
                            row.bonus,
                            row.measured,
                            row.deviation,
                            row.out_of_tolerance,
                        ]
                        for row in block.dimensions
                    ],
                ]
                for block in parse_result_v2.blocks
            ]

    sample_path = tmp_path / "generated.csv"
    sample_path.write_text("generated fixture\n", encoding="utf-8")
    database_path = tmp_path / "reports.db"
    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    try:
        register_parser(GeneratedCsvParser)
        parser = get_parser(sample_path, database=str(database_path))
        report_id = parser.open_database_and_check_filename()
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)

    assert report_id > 0
    assert parser.canonical_metadata.reference == "REF-GEN"

    with sqlite3.connect(database_path) as connection:
        parsed_row = connection.execute(
            """
            SELECT parser_id, parse_status, measurement_count, has_nok, nok_count
            FROM parsed_reports
            WHERE id = ?
            """,
            (report_id,),
        ).fetchone()
        metadata_row = connection.execute(
            "SELECT reference, report_date, sample_number FROM report_metadata WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        warning_row = connection.execute(
            "SELECT code, field_name, message FROM report_metadata_warnings WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        measurement_row = connection.execute(
            """
            SELECT header, ax, meas, outtol, status_code, raw_measurement_json
            FROM report_measurements
            WHERE report_id = ?
            """,
            (report_id,),
        ).fetchone()

    assert parsed_row == ("generated_csv", "parsed_with_warnings", 1, 1, 1)
    assert metadata_row == ("REF-GEN", "2026-01-05", "0001")
    assert warning_row == ("rounded_value", "X", "Rounded value in source")
    assert measurement_row[:5] == ("MAIN FEATURE", "X", 10.2, 0.2, "nok")
    raw_measurement = json.loads(measurement_row[5])
    assert raw_measurement["extensions"]["characteristic_name"] == "Position X"
    assert raw_measurement["raw_tokens"] == ["X", "10.2"]


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


def test_resolver_uses_probe_cache_for_same_plugin_and_path(tmp_path):
    class CachedProbeParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="cached_probe",
            display_name="Cached Probe",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        probe_calls = 0

        @classmethod
        def probe(cls, _path, _context: ProbeContext) -> ProbeResult:
            cls.probe_calls += 1
            return ProbeResult(plugin_id=cls.manifest.plugin_id, can_parse=True, confidence=90)

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
    original_cache = dict(PROBE_RESULT_CACHE)
    try:
        reset_probe_cache()
        _restore_real_cmm_registration()
        register_parser(CachedProbeParser)

        report_path = tmp_path / "cached_file.pdf"
        resolve_parser_with_diagnostics(report_path)
        resolve_parser_with_diagnostics(report_path)

        assert CachedProbeParser.probe_calls == 1
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)


def test_resolver_does_not_rescan_entry_points_after_initial_load(monkeypatch, tmp_path):
    calls = {"count": 0}

    def _fake_entry_points():
        calls["count"] += 1
        return ()

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    original_cache = dict(PROBE_RESULT_CACHE)
    original_loaded = factory_module._EXTERNAL_PLUGINS_LOADED
    original_signature = factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE
    original_entry_points = factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS
    original_env = os.environ.get("PARSER_EXTERNAL_PLUGIN_PATHS")
    try:
        monkeypatch.setattr(factory_module, "_iter_external_plugin_entry_points", _fake_entry_points)
        monkeypatch.delenv("PARSER_EXTERNAL_PLUGIN_PATHS", raising=False)
        reset_external_plugin_loader_state()
        _restore_real_cmm_registration()

        resolve_parser_with_diagnostics(tmp_path / "first.pdf")
        resolve_parser_with_diagnostics(tmp_path / "second.pdf")

        assert calls["count"] == 1
    finally:
        if original_env is None:
            os.environ.pop("PARSER_EXTERNAL_PLUGIN_PATHS", None)
        else:
            os.environ["PARSER_EXTERNAL_PLUGIN_PATHS"] = original_env
        factory_module._EXTERNAL_PLUGINS_LOADED = original_loaded
        factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE = original_signature
        factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS = original_entry_points
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)


def test_reregistering_parser_without_detector_clears_stale_detector(tmp_path):
    class LegacyDetectorParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="detector_swap",
            display_name="Legacy Detector",
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

    class ReregisteredProbeParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="detector_swap",
            display_name="Reregistered Probe",
            version="1.1.0",
            supported_formats=("pdf",),
        )

        probe_calls = 0

        @classmethod
        def probe(cls, _path, _context: ProbeContext) -> ProbeResult:
            cls.probe_calls += 1
            return ProbeResult(plugin_id=cls.manifest.plugin_id, can_parse=True, confidence=83)

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
    original_cache = dict(PROBE_RESULT_CACHE)
    try:
        register_parser(
            "detector_swap",
            LegacyDetectorParser,
            detector=lambda _path: ProbeResult(
                plugin_id="detector_swap",
                can_parse=True,
                confidence=100,
                reasons=("stale_detector",),
            ),
        )

        register_parser(ReregisteredProbeParser)
        PARSER_MAP.pop("cmm", None)
        PARSER_MANIFESTS.pop("cmm", None)
        PARSER_DETECTORS.pop("cmm", None)
        reset_probe_cache()

        diagnostics = resolve_parser_with_diagnostics(tmp_path / "detector_swap.pdf")

        assert diagnostics.selected is not None
        assert diagnostics.selected.confidence == 83
        assert diagnostics.selected.reasons == ()
        assert ReregisteredProbeParser.probe_calls == 1
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)


def test_strict_matching_rejects_low_confidence_candidate(tmp_path):
    class LowConfidenceParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="low_confidence",
            display_name="Low Confidence",
            version="1.0.0",
            supported_formats=("pdf",),
            priority=1000,
        )

        @classmethod
        def probe(cls, _path, _context: ProbeContext) -> ProbeResult:
            return ProbeResult(plugin_id=cls.manifest.plugin_id, can_parse=True, confidence=40)

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
    original_cache = dict(PROBE_RESULT_CACHE)
    original_env = os.environ.get("PARSER_STRICT_MATCHING")
    try:
        os.environ["PARSER_STRICT_MATCHING"] = "false"

        _restore_real_cmm_registration()
        register_parser(LowConfidenceParser)
        PARSER_MAP.pop("cmm", None)
        PARSER_MANIFESTS.pop("cmm", None)
        PARSER_DETECTORS.pop("cmm", None)
        reset_probe_cache()

        report_path = tmp_path / "strict_mode.pdf"

        non_strict = resolve_parser_with_diagnostics(report_path)
        assert non_strict.selected is not None
        assert non_strict.selected.plugin_id == "low_confidence"

        os.environ["PARSER_STRICT_MATCHING"] = "true"
        reset_probe_cache()
        strict = resolve_parser_with_diagnostics(report_path)
        assert strict.selected is None
        assert strict.rejected_reason == "no_plugin_above_confidence_threshold"
    finally:
        if original_env is None:
            os.environ.pop("PARSER_STRICT_MATCHING", None)
        else:
            os.environ["PARSER_STRICT_MATCHING"] = original_env
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)


def test_strict_matching_is_default_when_env_is_unset(tmp_path, monkeypatch):
    class DefaultStrictLowConfidenceParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="default_strict_low_confidence",
            display_name="Default Strict Low Confidence",
            version="1.0.0",
            supported_formats=("pdf",),
            priority=1000,
        )

        @classmethod
        def probe(cls, _path, _context: ProbeContext) -> ProbeResult:
            return ProbeResult(plugin_id=cls.manifest.plugin_id, can_parse=True, confidence=40)

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
    original_cache = dict(PROBE_RESULT_CACHE)
    try:
        monkeypatch.delenv("PARSER_STRICT_MATCHING", raising=False)

        _restore_real_cmm_registration()
        register_parser(DefaultStrictLowConfidenceParser)
        PARSER_MAP.pop("cmm", None)
        PARSER_MANIFESTS.pop("cmm", None)
        PARSER_DETECTORS.pop("cmm", None)
        reset_probe_cache()

        report_path = tmp_path / "strict_default_mode.pdf"
        diagnostics = resolve_parser_with_diagnostics(report_path)

        assert diagnostics.selected is None
        assert diagnostics.rejected_reason == "no_plugin_above_confidence_threshold"
        with pytest.raises(ValueError, match="Unsupported report format"):
            get_parser(report_path, database=":memory:")
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)


def test_pdf_alias_assignment_updates_canonical_blocks_text():
    parser = CMMReportParser("REF01_2024-01-02_123.pdf", database=":memory:")
    parser.pdf_blocks_text = [[["Header"], [["X", 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]]]]

    assert parser.blocks_text == parser.pdf_blocks_text


def test_load_external_plugins_registers_plugin_from_file(tmp_path):
    plugin_file = tmp_path / "demo_external_plugin.py"
    plugin_file.write_text(
        """
from modules.base_report_parser import BaseReportParser
from modules.parser_plugin_contracts import BaseReportParserPlugin, PluginManifest, ProbeResult

class DemoExternalParser(BaseReportParser, BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id=\"demo_external\",
        display_name=\"Demo External\",
        version=\"1.0.0\",
        supported_formats=(\"pdf\",),
    )

    @classmethod
    def probe(cls, _input_ref, _context):
        return ProbeResult(plugin_id=\"demo_external\", can_parse=True, confidence=87)

    def open_report(self):
        self.raw_text = [\"ok\"]

    def split_text_to_blocks(self):
        self.blocks_text = []

    def parse_to_v2(self):
        raise NotImplementedError

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        return []
"""
    )

    load_external_plugins = factory_module.load_external_plugins

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    original_cache = dict(PROBE_RESULT_CACHE)
    try:
        result = load_external_plugins(str(plugin_file))
        assert "demo_external" in PARSER_MAP
        assert "demo_external" in result.loaded_plugin_ids
        diagnostics = resolve_parser_with_diagnostics(tmp_path / "external.pdf")
        assert diagnostics.selected is not None
        assert diagnostics.selected.plugin_id == "demo_external"
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)


def test_load_external_plugins_supports_dataclass_future_annotations(tmp_path):
    plugin_file = tmp_path / "dataclass_external_plugin.py"
    plugin_file.write_text(
        """
from __future__ import annotations

from dataclasses import dataclass

from modules.base_report_parser import BaseReportParser
from modules.parser_plugin_contracts import BaseReportParserPlugin, PluginManifest, ProbeResult

@dataclass(frozen=True)
class ExternalConfig:
    label: str

class DataclassExternalParser(BaseReportParser, BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id="dataclass_external",
        display_name="Dataclass External",
        version="1.0.0",
        supported_formats=("pdf",),
    )
    config = ExternalConfig(label="ok")

    @classmethod
    def probe(cls, _input_ref, _context):
        return ProbeResult(plugin_id="dataclass_external", can_parse=True, confidence=88)

    def open_report(self):
        self.raw_text = ["ok"]

    def split_text_to_blocks(self):
        self.blocks_text = []

    def parse_to_v2(self):
        raise NotImplementedError

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        return []
""",
        encoding="utf-8",
    )

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    original_cache = dict(PROBE_RESULT_CACHE)
    try:
        result = factory_module.load_external_plugins(str(plugin_file))

        assert result.errors == ()
        assert "dataclass_external" in result.loaded_plugin_ids
        assert result.loaded_modules[0] in sys.modules
    finally:
        for module_name in result.loaded_modules if "result" in locals() else ():
            sys.modules.pop(module_name, None)
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)


def test_external_plugin_load_errors_are_logged_by_auto_loader(monkeypatch, tmp_path, caplog):
    plugin_file = tmp_path / "broken_external_plugin.py"
    plugin_file.write_text('raise RuntimeError("plugin failed during import")\n', encoding="utf-8")

    monkeypatch.setattr(
        parser_plugin_paths_module,
        "configured_external_plugin_path_entries",
        lambda raw_paths=None, include_default_dir=True, home=None: (str(plugin_file),),
    )
    monkeypatch.setattr(factory_module, "_discover_external_plugin_entry_points", lambda force_refresh=False: ())
    reset_external_plugin_loader_state()
    try:
        with caplog.at_level(logging.WARNING, logger=factory_module.logger.name):
            factory_module._ensure_external_plugins_loaded_once()

        assert "External parser plugin load issue" in caplog.text
        assert "plugin failed during import" in caplog.text
    finally:
        reset_external_plugin_loader_state()


def test_resolver_handles_probe_exceptions_without_crashing(tmp_path):
    plugin_file = tmp_path / "broken_probe_plugin.py"
    plugin_file.write_text(
        """
from modules.base_report_parser import BaseReportParser
from modules.parser_plugin_contracts import BaseReportParserPlugin, PluginManifest

class BrokenProbeParser(BaseReportParser, BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id="broken_probe",
        display_name="Broken Probe",
        version="1.0.0",
        supported_formats=("pdf",),
        priority=900,
    )

    @classmethod
    def probe(cls, _input_ref, _context):
        raise RuntimeError("probe exploded")

    def open_report(self):
        self.raw_text = ["ok"]

    def split_text_to_blocks(self):
        self.blocks_text = []

    def parse_to_v2(self):
        raise NotImplementedError

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        return []
""",
        encoding="utf-8",
    )

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    original_cache = dict(PROBE_RESULT_CACHE)
    try:
        _restore_real_cmm_registration()
        load_external_plugins = factory_module.load_external_plugins
        load_result = load_external_plugins(str(plugin_file))
        assert "broken_probe" in load_result.loaded_plugin_ids

        diagnostics = resolve_parser_with_diagnostics(tmp_path / "broken_probe_report.pdf")
        broken_candidate = next(
            candidate
            for candidate in diagnostics.candidates_considered
            if candidate.plugin_id == "broken_probe"
        )

        assert diagnostics.selected is None
        assert diagnostics.rejected_reason == "no_plugin_can_parse"
        assert broken_candidate.can_parse is False
        assert broken_candidate.confidence == 0
        assert "probe_exception" in broken_candidate.reasons
        assert any("probe exploded" in warning for warning in broken_candidate.warnings)
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)


def test_load_external_plugins_reports_skipped_paths_for_missing_input(tmp_path):
    load_external_plugins = factory_module.load_external_plugins
    missing_path = str(tmp_path / "missing_dir")

    result = load_external_plugins(missing_path)
    assert missing_path in result.skipped_paths


def test_resolver_loads_plugins_from_default_drop_in_directory(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "parser_plugins"
    plugin_dir.mkdir()
    plugin_file = plugin_dir / "dropin_supplier.py"
    plugin_file.write_text(
        """
from modules.base_report_parser import BaseReportParser
from modules.parser_plugin_contracts import BaseReportParserPlugin, PluginManifest, ProbeResult

class DropInSupplierParser(BaseReportParser, BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id="dropin_supplier",
        display_name="Drop-In Supplier",
        version="1.0.0",
        supported_formats=("pdf",),
        priority=1000,
    )

    @classmethod
    def probe(cls, _input_ref, _context):
        return ProbeResult(plugin_id="dropin_supplier", can_parse=True, confidence=101)

    def open_report(self):
        self.raw_text = ["ok"]

    def split_text_to_blocks(self):
        self.blocks_text = []

    def parse_to_v2(self):
        raise NotImplementedError

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        return []
"""
    )

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    original_cache = dict(PROBE_RESULT_CACHE)
    original_loaded = factory_module._EXTERNAL_PLUGINS_LOADED
    original_signature = factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE
    original_entry_points = factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS
    original_env = os.environ.get("PARSER_EXTERNAL_PLUGIN_PATHS")
    try:
        monkeypatch.setattr(
            parser_plugin_paths_module,
            "configured_external_plugin_path_entries",
            lambda raw_paths=None, include_default_dir=True, home=None: (str(plugin_dir),),
        )
        os.environ.pop("PARSER_EXTERNAL_PLUGIN_PATHS", None)
        factory_module._EXTERNAL_PLUGINS_LOADED = False
        factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE = None
        factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS = None
        reset_probe_cache()
        _restore_real_cmm_registration()

        diagnostics = resolve_parser_with_diagnostics(tmp_path / "dropin_report.pdf")

        assert diagnostics.selected is not None
        assert diagnostics.selected.plugin_id == "dropin_supplier"
        assert "dropin_supplier" in PARSER_MAP
    finally:
        if original_env is None:
            os.environ.pop("PARSER_EXTERNAL_PLUGIN_PATHS", None)
        else:
            os.environ["PARSER_EXTERNAL_PLUGIN_PATHS"] = original_env
        factory_module._EXTERNAL_PLUGINS_LOADED = original_loaded
        factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE = original_signature
        factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS = original_entry_points
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)


def test_resolver_reloads_external_plugins_when_path_config_changes(tmp_path):
    plugin_file = tmp_path / "late_external_plugin.py"
    plugin_file.write_text(
        """
from modules.base_report_parser import BaseReportParser
from modules.parser_plugin_contracts import BaseReportParserPlugin, PluginManifest, ProbeResult

class LateExternalParser(BaseReportParser, BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id=\"late_external\",
        display_name=\"Late External\",
        version=\"1.0.0\",
        supported_formats=(\"pdf\",),
        priority=1000,
    )

    @classmethod
    def probe(cls, _input_ref, _context):
        return ProbeResult(plugin_id=\"late_external\", can_parse=True, confidence=101)

    def open_report(self):
        self.raw_text = [\"ok\"]

    def split_text_to_blocks(self):
        self.blocks_text = []

    def parse_to_v2(self):
        raise NotImplementedError

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        return []
"""
    )

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    original_cache = dict(PROBE_RESULT_CACHE)
    original_loaded = factory_module._EXTERNAL_PLUGINS_LOADED
    original_signature = factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE
    original_entry_points = factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS
    original_env = os.environ.get("PARSER_EXTERNAL_PLUGIN_PATHS")
    try:
        os.environ.pop("PARSER_EXTERNAL_PLUGIN_PATHS", None)
        factory_module._EXTERNAL_PLUGINS_LOADED = False
        factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE = None
        factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS = None
        reset_probe_cache()
        _restore_real_cmm_registration()

        initial_report = tmp_path / "REF01_2024-01-02_001.pdf"
        initial_report.write_bytes(
            b"%PDF-1.4\n"
            b"REFERENCE: REF01\n"
            b"DATE: 2024-01-02\n"
            b"PART NAME: BRACKET\n"
            b"NOMINAL TOL MEASURED\n"
        )

        initial = resolve_parser_with_diagnostics(initial_report)
        assert initial.selected is not None
        assert initial.selected.plugin_id == "cmm"

        os.environ["PARSER_EXTERNAL_PLUGIN_PATHS"] = str(plugin_file)
        updated = resolve_parser_with_diagnostics(tmp_path / "after_config.pdf")

        assert updated.selected is not None
        assert updated.selected.plugin_id == "late_external"
        assert "late_external" in PARSER_MAP
    finally:
        if original_env is None:
            os.environ.pop("PARSER_EXTERNAL_PLUGIN_PATHS", None)
        else:
            os.environ["PARSER_EXTERNAL_PLUGIN_PATHS"] = original_env
        factory_module._EXTERNAL_PLUGINS_LOADED = original_loaded
        factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE = original_signature
        factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS = original_entry_points
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)


def test_load_external_plugins_registers_plugins_from_entry_points(monkeypatch):
    class DemoEntryPointParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="demo_ep",
            display_name="Demo EP",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        @classmethod
        def probe(cls, _input_ref, _context):
            return ProbeResult(plugin_id="demo_ep", can_parse=True, confidence=60)

        def open_report(self):
            self.raw_text = []

        def split_text_to_blocks(self):
            self.blocks_text = []

        def parse_to_v2(self):
            raise NotImplementedError

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            return []

    class _DummyEntryPoint:
        name = "demo_ep"

        @staticmethod
        def load():
            return DemoEntryPointParser

    load_external_plugins = factory_module.load_external_plugins

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    original_cache = dict(PROBE_RESULT_CACHE)
    try:
        monkeypatch.setattr(factory_module, "_iter_external_plugin_entry_points", lambda: (_DummyEntryPoint(),))
        result = load_external_plugins(paths=())
        assert "demo_ep" in PARSER_MAP
        assert "demo_ep" in result.loaded_plugin_ids
        assert "demo_ep" in result.loaded_entry_points
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)


def test_resolve_parser_auto_loads_entry_point_plugins_without_path_env(monkeypatch, tmp_path):
    class EntryPointOnlyParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="entry_point_only",
            display_name="Entry Point Only",
            version="1.0.0",
            supported_formats=("pdf",),
            priority=500,
        )

        @classmethod
        def probe(cls, _input_ref, _context):
            return ProbeResult(plugin_id="entry_point_only", can_parse=True, confidence=95)

        def open_report(self):
            self.raw_text = []

        def split_text_to_blocks(self):
            self.blocks_text = []

        def parse_to_v2(self):
            raise NotImplementedError

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            return []

    class _DummyEntryPoint:
        name = "entry_point_only"

        @staticmethod
        def load():
            return EntryPointOnlyParser

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    original_cache = dict(PROBE_RESULT_CACHE)
    original_loaded_flag = factory_module._EXTERNAL_PLUGINS_LOADED
    original_signature = factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE
    original_entry_points = factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS
    try:
        monkeypatch.delenv("PARSER_EXTERNAL_PLUGIN_PATHS", raising=False)
        monkeypatch.setattr(factory_module, "_iter_external_plugin_entry_points", lambda: (_DummyEntryPoint(),))
        factory_module._EXTERNAL_PLUGINS_LOADED = False
        factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE = None
        factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS = None
        PARSER_MAP.pop("cmm", None)
        PARSER_MANIFESTS.pop("cmm", None)
        PARSER_DETECTORS.pop("cmm", None)
        reset_probe_cache()

        diagnostics = resolve_parser_with_diagnostics(tmp_path / "entry_point.pdf")

        assert diagnostics.selected is not None
        assert diagnostics.selected.plugin_id == "entry_point_only"
        assert factory_module._EXTERNAL_PLUGINS_LOADED is True
    finally:
        factory_module._EXTERNAL_PLUGINS_LOADED = original_loaded_flag
        factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE = original_signature
        factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS = original_entry_points
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        PROBE_RESULT_CACHE.clear()
        PROBE_RESULT_CACHE.update(original_cache)
