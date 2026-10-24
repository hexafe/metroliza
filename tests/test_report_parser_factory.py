import importlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
from threading import Barrier, Lock
import time

import pytest

from metroliza.parsing.pdf_backend import require_pdf_backend


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
    backend = require_pdf_backend()
    document = backend.open()
    try:
        page = document.new_page()
        page.insert_text(
            (72, 72),
            "CMM REPORT\n"
            "REFERENCE: REF01\n"
            "DATE: 2024-01-02\n"
            "PART NAME: BRACKET\n"
            "MEASUREMENT MADE BY: CMM OPERATOR A\n"
            "NOMINAL TOL MEASURED DEVIATION OUTTOL\n"
            "#FEATURE 1\n"
            "DIM\n"
            "X 10 0.2 -0.2 10.1 0.1 0\n",
        )
        document.save(str(path), garbage=4, deflate=True)
    finally:
        document.close()
    return path


def _write_non_cmm_pdf(path: Path) -> Path:
    backend = require_pdf_backend()
    document = backend.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "ALTERNATE SUMMARY REPORT\nNO MEASUREMENT TABLE\n")
        document.save(str(path), garbage=4, deflate=True)
    finally:
        document.close()
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

    with closing(sqlite3.connect(database_path)) as connection:
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


def test_probe_cache_is_bounded_lru(monkeypatch, tmp_path):
    from metroliza.parsing.source_inspection import SourceInspectionContext

    class _CachedParser:
        probe_calls = 0

        @classmethod
        def probe(cls, _path, _context):
            cls.probe_calls += 1
            return ProbeResult(plugin_id="bounded_cache", can_parse=True, confidence=90)

    assert factory_module.PROBE_RESULT_CACHE_MAX_ENTRIES == 2048
    monkeypatch.setattr(factory_module, "PROBE_RESULT_CACHE_MAX_ENTRIES", 2)
    reset_probe_cache()
    try:
        contexts = []
        for name in ("one.pdf", "two.pdf", "three.pdf"):
            source_path = tmp_path / name
            source_path.write_bytes(name.encode("utf-8"))
            contexts.append(
                SourceInspectionContext.from_path(source_path, source_format="pdf")
            )

        for context in contexts[:2]:
            factory_module._probe_with_cache(
                "bounded_cache",
                _CachedParser,
                context.source_path,
                ProbeContext(
                    source_path=context.source_path,
                    source_format="pdf",
                    source_inspection=context,
                ),
            )

        first_context = contexts[0]
        factory_module._probe_with_cache(
            "bounded_cache",
            _CachedParser,
            first_context.source_path,
            ProbeContext(
                source_path=first_context.source_path,
                source_format="pdf",
                source_inspection=first_context,
            ),
        )
        third_context = contexts[2]
        factory_module._probe_with_cache(
            "bounded_cache",
            _CachedParser,
            third_context.source_path,
            ProbeContext(
                source_path=third_context.source_path,
                source_format="pdf",
                source_inspection=third_context,
            ),
        )

        cached_paths = [cache_key[1] for cache_key in PROBE_RESULT_CACHE]
        assert cached_paths == [first_context.source_path, third_context.source_path]
        assert len(PROBE_RESULT_CACHE) == 2
        assert _CachedParser.probe_calls == 3
    finally:
        reset_probe_cache()


def test_probe_cache_single_flights_concurrent_same_key(tmp_path):
    from metroliza.parsing.source_inspection import SourceInspectionContext

    call_lock = Lock()

    class _ConcurrentParser:
        probe_calls = 0

        @classmethod
        def probe(cls, _path, _context):
            with call_lock:
                cls.probe_calls += 1
            time.sleep(0.05)
            return ProbeResult(plugin_id="concurrent_cache", can_parse=True, confidence=90)

    source_path = tmp_path / "shared.pdf"
    source_path.write_bytes(b"shared-cache-key")
    source_inspection = SourceInspectionContext.from_path(source_path, source_format="pdf")
    probe_context = ProbeContext(
        source_path=str(source_path),
        source_format="pdf",
        source_inspection=source_inspection,
    )

    reset_probe_cache()
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = tuple(
                executor.map(
                    lambda _index: factory_module._probe_with_cache(
                        "concurrent_cache",
                        _ConcurrentParser,
                        str(source_path),
                        probe_context,
                    ),
                    range(8),
                )
            )

        assert _ConcurrentParser.probe_calls == 1
        assert len(results) == 8
        assert all(result == results[0] for result in results)
    finally:
        reset_probe_cache()


def test_resolver_uses_immutable_registry_snapshot_during_registration(
    monkeypatch,
    tmp_path,
):
    probe_started = Barrier(2)
    allow_probe_to_finish = Barrier(2)

    class SnapshotParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="snapshot_parser",
            display_name="Snapshot parser",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        @classmethod
        def probe(cls, _path, _context):
            probe_started.wait(timeout=2)
            allow_probe_to_finish.wait(timeout=2)
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse=True,
                confidence=100,
            )

        def parse_to_v2(self):
            raise NotImplementedError

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            raise NotImplementedError

        def open_report(self):
            raise NotImplementedError

        def split_text_to_blocks(self):
            raise NotImplementedError

    class LateParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="late_parser",
            display_name="Late parser",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        @classmethod
        def probe(cls, _path, _context):
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse=True,
                confidence=100,
            )

        def parse_to_v2(self):
            raise NotImplementedError

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            raise NotImplementedError

        def open_report(self):
            raise NotImplementedError

        def split_text_to_blocks(self):
            raise NotImplementedError

    source_path = tmp_path / "snapshot.pdf"
    source_path.write_bytes(b"snapshot")
    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    monkeypatch.setattr(factory_module, "_ensure_external_plugins_loaded_once", lambda: None)
    try:
        PARSER_MAP.clear()
        PARSER_MANIFESTS.clear()
        PARSER_DETECTORS.clear()
        register_parser(SnapshotParser)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(resolve_parser_with_diagnostics, source_path)
            probe_started.wait(timeout=2)
            register_parser(LateParser)
            allow_probe_to_finish.wait(timeout=2)
            diagnostics = future.result(timeout=2)

        assert diagnostics.selected is not None
        assert diagnostics.selected.plugin_id == "snapshot_parser"
        assert tuple(
            candidate.plugin_id for candidate in diagnostics.candidates_considered
        ) == ("snapshot_parser",)
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        reset_probe_cache()


def test_get_parser_constructs_class_selected_from_same_registry_snapshot(
    monkeypatch,
    tmp_path,
):
    probe_started = Barrier(2)
    allow_probe_to_finish = Barrier(2)

    class SelectedParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="swappable_parser",
            display_name="Selected parser",
            version="1.0.0",
            supported_formats=("pdf",),
        )

        @classmethod
        def probe(cls, _path, _context):
            probe_started.wait(timeout=2)
            allow_probe_to_finish.wait(timeout=2)
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse=True,
                confidence=100,
            )

        def open_report(self):
            return None

        def split_text_to_blocks(self):
            return None

        def parse_to_v2(self):
            raise NotImplementedError

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            raise NotImplementedError

    class ReplacementParser(BaseReportParser, BaseReportParserPlugin):
        manifest = PluginManifest(
            plugin_id="swappable_parser",
            display_name="Replacement parser",
            version="2.0.0",
            supported_formats=("pdf",),
        )

        @classmethod
        def probe(cls, _path, _context):
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse=False,
                confidence=0,
            )

        def open_report(self):
            return None

        def split_text_to_blocks(self):
            return None

        def parse_to_v2(self):
            raise NotImplementedError

        @staticmethod
        def to_legacy_blocks(_parse_result_v2):
            raise NotImplementedError

    source_path = tmp_path / "swap.pdf"
    source_path.write_bytes(b"swap")
    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    monkeypatch.setattr(factory_module, "_ensure_external_plugins_loaded_once", lambda: None)
    try:
        PARSER_MAP.clear()
        PARSER_MANIFESTS.clear()
        PARSER_DETECTORS.clear()
        register_parser(SelectedParser)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                get_parser,
                source_path,
                database=str(tmp_path / "swap.sqlite3"),
            )
            probe_started.wait(timeout=2)
            register_parser(ReplacementParser, replace=True)
            allow_probe_to_finish.wait(timeout=2)
            parser = future.result(timeout=2)

        assert type(parser) is SelectedParser
        assert PARSER_MAP["swappable_parser"] is ReplacementParser
        replacement_diagnostics = resolve_parser_with_diagnostics(source_path)
        assert replacement_diagnostics.selected is None
        assert replacement_diagnostics.rejected_reason == "no_plugin_can_parse"
    finally:
        PARSER_MAP.clear()
        PARSER_MAP.update(original_map)
        PARSER_MANIFESTS.clear()
        PARSER_MANIFESTS.update(original_manifests)
        PARSER_DETECTORS.clear()
        PARSER_DETECTORS.update(original_detectors)
        reset_probe_cache()


def test_resolver_rehashes_before_persistence_and_shares_extraction(monkeypatch, tmp_path):
    from metroliza.parsing.source_inspection import SourceInspectionContext
    from metroliza.parsing.parse_reports_thread import parse_new_reports
    from metroliza.reports import report_repository

    source_reads = 0
    hash_reads = 0
    repository_hash_reads = 0
    original_context_hash = SourceInspectionContext._compute_sha256
    original_repository_hash = report_repository.compute_sha256

    def _load_source(path, max_chars):
        nonlocal source_reads
        source_reads += 1
        return path.read_text(encoding="utf-8")[:max_chars]

    def _count_context_hash(self):
        nonlocal hash_reads
        hash_reads += 1
        return original_context_hash(self)

    def _count_repository_hash(path):
        nonlocal repository_hash_reads
        repository_hash_reads += 1
        return original_repository_hash(path)

    class _InspectionParser(BaseReportParser, BaseReportParserPlugin):
        @classmethod
        def probe(cls, _path, context: ProbeContext) -> ProbeResult:
            assert context.source_inspection is not None
            text = context.source_inspection.get_extracted_text(
                cache_key="inspection-test",
                max_chars=1_000,
                loader=_load_source,
            )
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse="SHARED INSPECTION" in text,
                confidence=cls.manifest.priority,
            )

        def open_report(self):
            self.raw_text = []

        def split_text_to_blocks(self):
            self.blocks_text = []

        def parse_to_v2(self):
            return ParseResultV2(
                meta=ParseMetaV2(
                    source_file=self.file_name,
                    source_format="csv",
                    plugin_id=self.manifest.plugin_id,
                    plugin_version="1.0.0",
                    template_id=None,
                    parse_timestamp="2026-07-09T00:00:00Z",
                    locale_detected=None,
                    confidence=95,
                ),
                report=ReportInfoV2(
                    reference="REF-SHARED",
                    report_date="2026-07-09",
                    sample_number="1",
                    file_name=self.file_name,
                    file_path=self.file_path,
                ),
                blocks=(
                    MeasurementBlockV2(
                        header_raw=("SHARED INSPECTION",),
                        header_normalized="SHARED INSPECTION",
                        dimensions=(
                            MeasurementV2(
                                axis_code="X",
                                nominal=1.0,
                                tol_plus=0.1,
                                tol_minus=-0.1,
                                bonus=0.0,
                                measured=1.0,
                                deviation=0.0,
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

    class LowInspectionParser(_InspectionParser):
        manifest = PluginManifest(
            plugin_id="inspection_low",
            display_name="Inspection Low",
            version="1.0.0",
            supported_formats=("csv",),
            priority=90,
        )

    class HighInspectionParser(_InspectionParser):
        manifest = PluginManifest(
            plugin_id="inspection_high",
            display_name="Inspection High",
            version="1.0.0",
            supported_formats=("csv",),
            priority=95,
        )

    original_map = dict(PARSER_MAP)
    original_manifests = dict(PARSER_MANIFESTS)
    original_detectors = dict(PARSER_DETECTORS)
    original_cache = dict(PROBE_RESULT_CACHE)
    try:
        monkeypatch.setattr(SourceInspectionContext, "_compute_sha256", _count_context_hash)
        monkeypatch.setattr(report_repository, "compute_sha256", _count_repository_hash)
        reset_probe_cache()
        register_parser(LowInspectionParser)
        register_parser(HighInspectionParser)
        source_path = tmp_path / "shared.csv"
        source_path.write_text("SHARED INSPECTION\n", encoding="utf-8")

        parsed = []

        def _parser_factory(path, *, source_inspection=None):
            parser = get_parser(
                path,
                database=str(tmp_path / "shared.db"),
                source_inspection=source_inspection,
            )
            parsed.append(parser)
            return parser

        result = parse_new_reports(
            [source_path],
            set(),
            parser_factory=_parser_factory,
            persist_report=lambda parser: parser.open_database_and_check_filename(),
        )
        parser = parsed[0]

        assert isinstance(parser, HighInspectionParser)
        assert result.parsed_files == 1
        assert result.failed_files == 0
        assert hash_reads == 2
        assert source_reads == 1
        assert repository_hash_reads == 0

        changing_source_path = tmp_path / "changing.csv"
        changing_source_path.write_text("SHARED INSPECTION\n", encoding="utf-8")
        changing_parser = get_parser(
            changing_source_path,
            database=str(tmp_path / "changing.db"),
        )
        changing_source_path.write_text("CHANGED AFTER RESOLUTION\n", encoding="utf-8")

        with pytest.raises(ValueError, match="Source changed after parser resolution"):
            changing_parser.open_database_and_check_filename()
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

        register_parser(ReregisteredProbeParser, replace=True)
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

        report_path = _write_non_cmm_pdf(tmp_path / "strict_mode.pdf")

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

        report_path = _write_non_cmm_pdf(tmp_path / "strict_default_mode.pdf")
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
        assert diagnostics.rejected_reason == "parser_inspection_failed"
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
        _write_cmm_probe_fixture(initial_report)

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
    original_loaded_flag = factory_module._EXTERNAL_PLUGINS_LOADED
    original_signature = factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE
    original_entry_points = factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS
    try:
        monkeypatch.setattr(factory_module, "_iter_external_plugin_entry_points", lambda: (_DummyEntryPoint(),))
        result = load_external_plugins(paths=())
        assert "demo_ep" in PARSER_MAP
        assert "demo_ep" in result.loaded_plugin_ids
        assert "demo_ep" in result.loaded_entry_points
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


# Literal expectations are established on the unchanged STEP3 base before caching.
@pytest.mark.parametrize(
    ("definition", "keyword", "expected"),
    [
        ("def callback(value): pass", "value", True),
        ("def callback(value, /): pass", "value", False),
        ("def callback(*, value=None): pass", "value", True),
        ("def callback(*value): pass", "value", True),
        ("def callback(**value): pass", "missing", True),
        ("def callback(value, /, **kwargs): pass", "value", True),
        ("def callback(value=None): pass", "missing", False),
        ("async def callback(*, value): pass", "value", True),
    ],
)
def test_keyword_inspection_literal_parameter_kinds(definition, keyword, expected):
    namespace = {}
    exec(definition, namespace)
    callback = namespace["callback"]
    assert factory_module._callable_accepts_keyword(callback, keyword) is expected
    assert factory_module._callable_accepts_keyword(callback, keyword) is expected


def test_keyword_inspection_dynamic_callable_errors_and_raw_keyword():
    import inspect

    events = []

    class DynamicCallable:
        @property
        def __signature__(self):
            events.append("signature")
            return inspect.Signature(
                [inspect.Parameter("value", inspect.Parameter.KEYWORD_ONLY)]
            )

        def __call__(self, **kwargs):
            return kwargs

        def __hash__(self):
            raise AssertionError("callable hashing is not part of inspection")

    class Keyword(str):
        def __hash__(self):
            events.append("keyword_hash")
            return super().__hash__()

    callback = DynamicCallable()
    assert factory_module._callable_accepts_keyword(callback, Keyword("value")) is True
    assert factory_module._callable_accepts_keyword(callback, "other") is False
    assert events == ["signature", "keyword_hash", "signature"]

    for error, handled in [(TypeError, True), (ValueError, True), (RuntimeError, False)]:
        class RaisingCallable:
            @property
            def __signature__(self):
                raise error("signature failure")

            def __call__(self):
                pass

        if handled:
            assert factory_module._callable_accepts_keyword(RaisingCallable(), "x") is False
        else:
            with pytest.raises(RuntimeError, match="signature failure"):
                factory_module._callable_accepts_keyword(RaisingCallable(), "x")


def test_keyword_inspection_function_metadata_mutations():
    import inspect

    def callback(value=None):
        pass

    assert factory_module._callable_accepts_keyword(callback, "value") is True
    callback.__signature__ = inspect.Signature()
    assert factory_module._callable_accepts_keyword(callback, "value") is False
    del callback.__signature__

    def replacement(*, other=1):
        pass

    callback.__code__ = replacement.__code__
    callback.__defaults__ = None
    callback.__kwdefaults__ = {"other": 1}
    assert factory_module._callable_accepts_keyword(callback, "value") is False
    assert factory_module._callable_accepts_keyword(callback, "other") is True
    callback.__annotations__["other"] = "changed"
    callback.__kwdefaults__["other"] = 2
    assert factory_module._callable_accepts_keyword(callback, "other") is True
    callback.__wrapped__ = lambda wrapped: None
    assert factory_module._callable_accepts_keyword(callback, "wrapped") is True
    assert factory_module._callable_accepts_keyword(callback, "other") is False


def test_keyword_inspection_decorators_partials_and_methods():
    from functools import partial, wraps

    def original(value, *, option=None):
        pass

    @wraps(original)
    def decorated(*args, **kwargs):
        return original(*args, **kwargs)

    class Owner:
        def method(self, *, value):
            pass

    for callback, keyword, expected in [
        (decorated, "value", True),
        (decorated, "missing", False),
        (partial(original, 1), "value", False),
        (partial(original, 1), "option", True),
        (Owner().method, "value", True),
        (Owner().method, "self", False),
        (len, "value", False),
        (None, "value", False),
    ]:
        assert factory_module._callable_accepts_keyword(callback, keyword) is expected


def test_keyword_inspection_factory_forwards_full_arguments_and_callback_errors():
    from types import SimpleNamespace

    context = object()
    calls = []

    def callback(path, *args, **kwargs):
        calls.append((path, args, kwargs))
        return SimpleNamespace()

    for _ in range(2):
        parser = factory_module.invoke_parser_factory(
            callback, "report.pdf", "database", source_inspection=context,
            expected_plugin_id="plugin", expected_registry_generation_id=23, extra="kept",
        )
        assert parser.source_inspection_context is context
    assert calls == [
        ("report.pdf", ("database",), {
            "extra": "kept", "source_inspection": context,
            "expected_plugin_id": "plugin", "expected_registry_generation_id": 23,
        }),
    ] * 2

    def broken(path, **kwargs):
        raise TypeError("callback body failure")

    with pytest.raises(TypeError, match="callback body failure"):
        factory_module.invoke_parser_factory(broken, "report.pdf", source_inspection=context)


def test_keyword_inspection_parallel_plain_functions():
    def first(*, first=None):
        pass

    def second(*, second=None):
        pass

    def query(index):
        callback = first if index % 2 else second
        return factory_module._callable_accepts_keyword(callback, "first")

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(query, range(128))) == [bool(index % 2) for index in range(128)]


def test_keyword_cache_activation_invalidation_and_inspector_replacement(monkeypatch):
    import inspect

    factory_module._KEYWORD_SIGNATURE_CACHE.clear()
    original = inspect._signature_from_function
    inspected = []

    def observe(cls, callback, *args, **kwargs):
        inspected.append(callback.__name__)
        return original(cls, callback, *args, **kwargs)

    monkeypatch.setattr(inspect, "_signature_from_function", observe)

    def callback(value=None, *, option=1):
        pass

    assert factory_module._callable_accepts_keyword(callback, "value") is True
    assert factory_module._callable_accepts_keyword(callback, "missing") is False
    assert inspected == ["callback"]
    callback.__annotations__["value"] = "literal annotation"
    assert factory_module._callable_accepts_keyword(callback, "value") is True
    callback.__kwdefaults__["option"] = 2
    assert factory_module._callable_accepts_keyword(callback, "option") is True
    callback.__defaults__ = (3,)
    assert factory_module._callable_accepts_keyword(callback, "value") is True
    assert inspected == ["callback"] * 4
    callback.__signature__ = inspect.Signature()
    assert factory_module._callable_accepts_keyword(callback, "value") is False
    del callback.__signature__

    def replacement(*, other=None):
        pass

    callback.__code__ = replacement.__code__
    callback.__defaults__ = None
    callback.__kwdefaults__ = {"other": None}
    assert factory_module._callable_accepts_keyword(callback, "other") is True
    assert factory_module._callable_accepts_keyword(callback, "value") is False
    assert inspected == ["callback"] * 5

    def failing_inspector(_callback):
        raise RuntimeError("replaced inspector")

    monkeypatch.setattr(inspect, "signature", failing_inspector)
    with pytest.raises(RuntimeError, match="replaced inspector"):
        factory_module._callable_accepts_keyword(callback, "other")


def test_keyword_cache_unsafe_metadata_keeps_exact_inspection_callbacks(monkeypatch):
    import inspect

    events = []

    class Annotations(dict):
        def keys(self):
            events.append("keys")
            return super().keys()

    def callback(value):
        pass

    callback.__annotations__ = Annotations(value=object())
    original = inspect.signature
    for _ in range(2):
        events.clear()
        expected = original(callback)
        expected_events = list(events)
        events.clear()
        assert factory_module._callable_accepts_keyword(callback, "value") is True
        assert events == expected_events
        assert "value" in expected.parameters
    assert callback not in factory_module._KEYWORD_SIGNATURE_CACHE


def test_keyword_cache_reentrant_inspection_and_mutation_during_fill(monkeypatch):
    import inspect

    factory_module._KEYWORD_SIGNATURE_CACHE.clear()
    original = inspect._signature_from_function
    events = []

    def inner(*, inner=None):
        pass

    def outer(*, outer=None):
        pass

    def observe(cls, callback, *args, **kwargs):
        if callback is outer:
            assert factory_module._callable_accepts_keyword(inner, "inner") is True
            events.append("inner complete")
        signature = original(cls, callback, *args, **kwargs)
        if callback is outer:
            callback.__signature__ = inspect.Signature()
        return signature

    monkeypatch.setattr(inspect, "_signature_from_function", observe)
    assert factory_module._callable_accepts_keyword(outer, "outer") is True
    assert outer not in factory_module._KEYWORD_SIGNATURE_CACHE
    assert factory_module._callable_accepts_keyword(outer, "outer") is False
    assert events == ["inner complete"]


def test_keyword_cache_is_bounded_and_does_not_retain_plugin_closures():
    import weakref

    factory_module._KEYWORD_SIGNATURE_CACHE.clear()

    class Payload:
        pass

    def make_callback():
        payload = Payload()

        def callback(*, value=None):
            return payload

        return callback, weakref.ref(payload)

    callback, payload_ref = make_callback()
    callback_ref = weakref.ref(callback)
    assert factory_module._callable_accepts_keyword(callback, "value") is True
    assert callback in factory_module._KEYWORD_SIGNATURE_CACHE
    del callback
    # No forced GC: neither the function nor its closure forms a cycle.
    assert callback_ref() is None
    assert payload_ref() is None
    callbacks = [make_callback()[0] for _ in range(factory_module._KEYWORD_SIGNATURE_CACHE_LIMIT + 3)]
    for callback in callbacks:
        assert factory_module._callable_accepts_keyword(callback, "value") is True
    assert len(factory_module._KEYWORD_SIGNATURE_CACHE) == factory_module._KEYWORD_SIGNATURE_CACHE_LIMIT
    assert callbacks[0] not in factory_module._KEYWORD_SIGNATURE_CACHE
    assert factory_module._callable_accepts_keyword(callbacks[0], "value") is True


def test_keyword_cache_code_swap_during_inspection_does_not_persist(monkeypatch):
    import inspect

    cache = getattr(factory_module, "_KEYWORD_SIGNATURE_CACHE", None)
    if cache is not None:
        cache.clear()
    original = inspect._signature_from_function
    swap_pending = True

    def callback(*, value=None):
        pass

    def replacement(*, other=None):
        pass

    def observe(cls, inspected, *args, **kwargs):
        nonlocal swap_pending
        if inspected is callback and swap_pending:
            swap_pending = False
            code = callback.__code__
            callback.__code__ = replacement.__code__
            try:
                return original(cls, inspected, *args, **kwargs)
            finally:
                callback.__code__ = code
        return original(cls, inspected, *args, **kwargs)

    monkeypatch.setattr(inspect, "_signature_from_function", observe)
    assert factory_module._callable_accepts_keyword(callback, "other") is True
    assert factory_module._callable_accepts_keyword(callback, "other") is False
    assert factory_module._callable_accepts_keyword(callback, "value") is True


@pytest.mark.parametrize("location", ["annotation", "default", "kwdefault"])
def test_keyword_inspection_metadata_types_do_not_dispatch_equality(location):
    events = []

    class Meta(type):
        def __eq__(cls, _other):
            events.append("metaclass_eq")
            raise RuntimeError("metadata equality must not run")

    class Value(metaclass=Meta):
        pass

    def callback(value=None, *, option=None):
        pass

    if location == "annotation":
        callback.__annotations__["value"] = Value()
    elif location == "default":
        callback.__defaults__ = (Value(),)
    else:
        callback.__kwdefaults__["option"] = Value()
    assert factory_module._callable_accepts_keyword(callback, "value") is True
    assert factory_module._callable_accepts_keyword(callback, "value") is True
    assert events == []


def test_keyword_inspection_function_dictionary_subclass_keeps_fallback():
    events = []

    class State(dict):
        def __bool__(self):
            events.append("dict_bool")
            raise RuntimeError("function dictionary truth must not run")

    def callback(*, value=None):
        pass

    callback.__dict__ = State()
    assert factory_module._callable_accepts_keyword(callback, "value") is True
    assert factory_module._callable_accepts_keyword(callback, "missing") is False
    assert events == []


@pytest.mark.parametrize(
    ("mutation", "next_result"),
    [("signature", False), ("wrapped", False), ("annotation", True), ("dict", True)],
)
def test_keyword_inspection_thread_metadata_change_during_fill(monkeypatch, mutation, next_result):
    import inspect
    from threading import Event

    admitted, changed = Event(), Event()
    events = []

    class Meta(type):
        def __eq__(cls, _other):
            events.append("metaclass_eq")
            raise RuntimeError("metadata equality must not run")

    class Value(metaclass=Meta):
        pass

    class State(dict):
        def __bool__(self):
            events.append("dict_bool")
            raise RuntimeError("function dictionary truth must not run")

    def callback(*, value=None):
        pass

    original = inspect._signature_from_function

    def observe(cls, inspected, *args, **kwargs):
        signature = original(cls, inspected, *args, **kwargs)
        if inspected is callback and not admitted.is_set():
            admitted.set()
            assert changed.wait(5)
        return signature

    def change():
        assert admitted.wait(5)
        if mutation == "signature":
            callback.__signature__ = inspect.Signature()
        elif mutation == "wrapped":
            callback.__wrapped__ = lambda other: None
        elif mutation == "annotation":
            callback.__annotations__ = {"value": Value()}
        else:
            callback.__dict__ = State()
        changed.set()

    monkeypatch.setattr(inspect, "_signature_from_function", observe)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(change)
        assert factory_module._callable_accepts_keyword(callback, "value") is True
        pending.result(timeout=5)
    cache = getattr(factory_module, "_KEYWORD_SIGNATURE_CACHE", None)
    if cache is not None:
        assert callback not in cache
    assert factory_module._callable_accepts_keyword(callback, "value") is next_result
    assert factory_module._callable_accepts_keyword(callback, "value") is next_result
    assert events == []


def test_keyword_cache_capacity_allows_automatic_weak_retirement():
    import inspect
    from queue import SimpleQueue
    import sys
    from threading import Event, Thread
    import weakref

    cache = factory_module._KEYWORD_SIGNATURE_CACHE
    assert type(cache) is weakref.WeakKeyDictionary
    cache.clear()
    callbacks = [lambda *, value=None: None for _ in range(128)]
    for callback in callbacks:
        assert factory_module._callable_accepts_keyword(callback, "value") is True
    references = [weakref.ref(callback) for callback in callbacks]
    del callback
    handoff = SimpleQueue()
    handoff.put(callbacks)
    del callbacks
    ready, retire, gone = Event(), Event(), Event()
    errors, observations = [], []

    def own():
        owned = handoff.get()
        ready.set()
        try:
            assert retire.wait(5)
        except BaseException as error:
            errors.append(type(error).__name__)
        finally:
            owned.clear()
            gone.set()

    owner = Thread(target=own)
    function = factory_module._cached_keyword_signature
    lines, first = inspect.getsourcelines(function)
    edge = first + next(
        index for index, line in enumerate(lines)
        if "next(iter(_KEYWORD_SIGNATURE_CACHE)" in line
    )

    def trace(frame, event, _arg):
        if (frame.f_code is function.__code__ and event == "line"
                and frame.f_lineno == edge and not observations):
            assert len(cache) == 128
            retire.set()
            assert gone.wait(5)
            assert len(cache) == 0
            assert all(reference() is None for reference in references)
            observations.append("128 real keys automatically retired")
        return trace

    def fresh(*, value=None):
        pass

    prior_trace = sys.gettrace()
    owner.start()
    try:
        assert ready.wait(5)
        sys.settrace(trace)
        assert factory_module._callable_accepts_keyword(fresh, "value") is True
    finally:
        sys.settrace(prior_trace)
        retire.set()
        owner.join(5)
        assert not owner.is_alive()
    assert not errors
    assert observations == ["128 real keys automatically retired"]
    assert sys.gettrace() is prior_trace


@pytest.mark.parametrize("error", [StopIteration, RuntimeError])
def test_keyword_cache_retirement_guard_preserves_external_errors(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error("external inspection or factory error")

    with monkeypatch.context() as replacement:
        replacement.setattr(factory_module.inspect, "signature", fail)
        with pytest.raises(error, match="external inspection or factory error"):
            factory_module._callable_accepts_keyword(lambda value: None, "value")
    with pytest.raises(error, match="external inspection or factory error"):
        factory_module.invoke_parser_factory(fail, "report.pdf", source_inspection=object())
