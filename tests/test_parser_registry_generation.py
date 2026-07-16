from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Event, Lock
import time

import pytest

from metroliza.parsing import report_parser_factory as factory
from metroliza.parsing.pdf_backend import require_pdf_backend
from metroliza.parsing.parser_plugin_contracts import (
    BaseReportParserPlugin,
    PluginManifest,
    ProbeContext,
    ProbeOutcome,
    ProbeResult,
)
from metroliza.parsing.source_inspection import SourceInspectionContext


class _ParserBase(BaseReportParserPlugin):
    def __init__(self, file_path, database, connection=None):
        self.file_path = file_path
        self.database = database
        self.connection = connection

    @classmethod
    def probe(cls, _input_ref, _context):
        raise NotImplementedError

    def parse_to_v2(self):
        raise NotImplementedError

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        raise NotImplementedError


def _parser_type(
    plugin_id: str,
    result: ProbeResult,
    *,
    priority: int = 100,
):
    manifest = PluginManifest(
        plugin_id=plugin_id,
        display_name=plugin_id,
        version="1.0.0",
        supported_formats=("pdf",),
        priority=priority,
    )

    class Parser(_ParserBase):
        @classmethod
        def probe(cls, _input_ref, _context):
            return result

    Parser.manifest = manifest
    Parser.__name__ = f"{plugin_id.title()}Parser"
    return Parser


@contextmanager
def _isolated_registry(monkeypatch):
    original_map = dict(factory.PARSER_MAP)
    original_manifests = dict(factory.PARSER_MANIFESTS)
    original_detectors = dict(factory.PARSER_DETECTORS)
    monkeypatch.setattr(factory, "_ensure_external_plugins_loaded_once", lambda: None)
    factory.PARSER_MAP.clear()
    factory.PARSER_MANIFESTS.clear()
    factory.PARSER_DETECTORS.clear()
    factory.reset_probe_cache()
    try:
        yield
    finally:
        factory.PARSER_MAP.clear()
        factory.PARSER_MAP.update(original_map)
        factory.PARSER_MANIFESTS.clear()
        factory.PARSER_MANIFESTS.update(original_manifests)
        factory.PARSER_DETECTORS.clear()
        factory.PARSER_DETECTORS.update(original_detectors)
        factory.reset_probe_cache()


@contextmanager
def _preserved_factory_state():
    with factory._EXTERNAL_PLUGIN_REFRESH_LOCK, factory._PARSER_REGISTRY_LOCK:
        state = {
            "map": dict(factory.PARSER_MAP),
            "manifests": dict(factory.PARSER_MANIFESTS),
            "detectors": dict(factory.PARSER_DETECTORS),
            "snapshot": factory._REGISTRY_SNAPSHOT,
            "manual": factory._MANUAL_REGISTRATIONS.copy(),
            "direct": factory._DIRECT_EXTERNAL_REGISTRATIONS.copy(),
            "loaded": factory._EXTERNAL_PLUGINS_LOADED,
            "signature": factory._EXTERNAL_PLUGIN_CONFIG_SIGNATURE,
            "entry_points": factory._EXTERNAL_PLUGIN_ENTRY_POINTS,
            "loader_epoch": factory._EXTERNAL_PLUGIN_LOADER_EPOCH,
        }
    try:
        yield
    finally:
        with factory._EXTERNAL_PLUGIN_REFRESH_LOCK, factory._PARSER_REGISTRY_LOCK:
            factory.PARSER_MAP.clear()
            factory.PARSER_MAP.update(state["map"])
            factory.PARSER_MANIFESTS.clear()
            factory.PARSER_MANIFESTS.update(state["manifests"])
            factory.PARSER_DETECTORS.clear()
            factory.PARSER_DETECTORS.update(state["detectors"])
            factory._REGISTRY_SNAPSHOT = state["snapshot"]
            factory._MANUAL_REGISTRATIONS = state["manual"]
            factory._DIRECT_EXTERNAL_REGISTRATIONS = state["direct"]
            factory._EXTERNAL_PLUGINS_LOADED = state["loaded"]
            factory._EXTERNAL_PLUGIN_CONFIG_SIGNATURE = state["signature"]
            factory._EXTERNAL_PLUGIN_ENTRY_POINTS = state["entry_points"]
            factory._EXTERNAL_PLUGIN_LOADER_EPOCH = state["loader_epoch"]
            factory.reset_probe_cache()


def _write_compressed_pdf(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    backend = require_pdf_backend()
    document = backend.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), text)
        document.save(str(path), garbage=4, deflate=True)
    finally:
        document.close()
    return path


def _external_plugin_source(plugin_id: str) -> str:
    return f'''\
from metroliza.parsing.parser_plugin_contracts import (
    BaseReportParserPlugin, PluginManifest, ProbeResult,
)

class ExternalParser(BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id="{plugin_id}",
        display_name="{plugin_id}",
        version="1.0.0",
        supported_formats=("pdf",),
    )

    @classmethod
    def probe(cls, _input_ref, _context):
        return ProbeResult(cls.manifest.plugin_id, False, 0)

    def __init__(self, file_path, database, connection=None):
        self.file_path = file_path
        self.database = database
        self.connection = connection

    def parse_to_v2(self):
        raise NotImplementedError

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        return []
'''


def _malformed_constructor_plugin_source(plugin_id: str) -> str:
    return f'''\
from metroliza.parsing.parser_plugin_contracts import (
    BaseReportParserPlugin, PluginManifest, ProbeResult,
)

class BrokenConstructorParser(BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id="{plugin_id}",
        display_name="{plugin_id}",
        version="1.0.0",
        supported_formats=("pdf",),
    )

    @classmethod
    def probe(cls, _input_ref, _context):
        return ProbeResult(cls.manifest.plugin_id, False, 0)

    def parse_to_v2(self):
        raise NotImplementedError

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        return []
'''


def test_probe_normalization_preserves_typed_outcome_and_semantic_tier():
    result = ProbeResult(
        plugin_id="semantic",
        can_parse=True,
        confidence=93,
        outcome=ProbeOutcome.MATCH,
        semantic_row_count=4,
    )

    normalized = factory._normalize_probe_result(
        plugin_id="semantic",
        raw_result=result,
        origin="probe",
        normalized_path="report.pdf",
    )

    assert normalized.outcome is ProbeOutcome.MATCH
    assert normalized.semantic_row_count == 4
    assert ProbeResult("legacy", True, 90).outcome is ProbeOutcome.MATCH
    assert ProbeResult("legacy", True, 90).semantic_row_count is None


def test_explicit_zero_row_match_is_an_inspection_error():
    normalized = factory._normalize_probe_result(
        plugin_id="empty",
        raw_result=ProbeResult(
            plugin_id="empty",
            can_parse=True,
            confidence=90,
            outcome=ProbeOutcome.MATCH,
            semantic_row_count=0,
        ),
        origin="probe",
        normalized_path="empty.pdf",
    )

    assert normalized.outcome is ProbeOutcome.INSPECTION_ERROR
    assert normalized.can_parse is False
    assert "semantic_match_without_rows" in normalized.reasons


def test_inconsistent_typed_and_legacy_probe_fields_are_inspection_error():
    normalized = factory._normalize_probe_result(
        plugin_id="broken_contract",
        raw_result=ProbeResult(
            plugin_id="broken_contract",
            can_parse=False,
            confidence=90,
            outcome=ProbeOutcome.MATCH,
            semantic_row_count=2,
        ),
        origin="probe",
        normalized_path="broken.pdf",
    )

    assert normalized.outcome is ProbeOutcome.INSPECTION_ERROR
    assert normalized.can_parse is False
    assert "invalid_probe_contract" in normalized.reasons


def test_inspection_errors_are_not_probe_cached(tmp_path):
    source_path = tmp_path / "broken.pdf"
    source_path.write_bytes(b"broken")
    context = ProbeContext(
        source_path=str(source_path),
        source_format="pdf",
        source_inspection=SourceInspectionContext.from_path(
            source_path,
            source_format="pdf",
        ),
    )

    class BrokenProbe(_ParserBase):
        probe_calls = 0

        @classmethod
        def probe(cls, _input_ref, _context):
            cls.probe_calls += 1
            return ProbeResult(
                plugin_id="broken",
                can_parse=False,
                confidence=0,
                outcome=ProbeOutcome.INSPECTION_ERROR,
            )

    factory.reset_probe_cache()
    try:
        first = factory._probe_with_cache("broken", BrokenProbe, str(source_path), context)
        second = factory._probe_with_cache("broken", BrokenProbe, str(source_path), context)
    finally:
        factory.reset_probe_cache()

    assert first.outcome is ProbeOutcome.INSPECTION_ERROR
    assert second.outcome is ProbeOutcome.INSPECTION_ERROR
    assert BrokenProbe.probe_calls == 2


def test_semantic_match_outranks_higher_confidence_legacy_match(monkeypatch, tmp_path):
    legacy = _parser_type(
        "legacy",
        ProbeResult("legacy", True, 100),
        priority=1000,
    )
    semantic = _parser_type(
        "semantic",
        ProbeResult(
            "semantic",
            True,
            80,
            outcome=ProbeOutcome.MATCH,
            semantic_row_count=1,
        ),
        priority=0,
    )

    with _isolated_registry(monkeypatch):
        factory.register_parser(legacy)
        factory.register_parser(semantic)
        diagnostics = factory.resolve_parser_with_diagnostics(tmp_path / "report.pdf")

    assert diagnostics.selected is not None
    assert diagnostics.selected.plugin_id == "semantic"


def test_equal_meaningful_evidence_rank_raises_ambiguity(monkeypatch, tmp_path):
    first = _parser_type(
        "first",
        ProbeResult(
            "first",
            True,
            90,
            outcome=ProbeOutcome.MATCH,
            semantic_row_count=1,
        ),
    )
    second = _parser_type(
        "second",
        ProbeResult(
            "second",
            True,
            90,
            outcome=ProbeOutcome.MATCH,
            semantic_row_count=7,
        ),
    )

    with _isolated_registry(monkeypatch):
        factory.register_parser(first)
        factory.register_parser(second)
        with pytest.raises(factory.ParserAmbiguityError) as exc_info:
            factory.resolve_parser_with_diagnostics(tmp_path / "ambiguous.pdf")

    assert exc_info.value.plugin_ids == ("first", "second")
    assert exc_info.value.diagnostics.rejected_reason == "ambiguous_parser_match"


def test_registration_rejects_duplicates_and_reserved_builtin(monkeypatch):
    first = _parser_type("duplicate", ProbeResult("duplicate", False, 0))
    replacement = _parser_type("duplicate", ProbeResult("duplicate", False, 0))
    reserved = _parser_type("cmm", ProbeResult("cmm", False, 0))

    with _isolated_registry(monkeypatch):
        factory.register_parser(first)
        with pytest.raises(factory.DuplicateParserRegistrationError):
            factory.register_parser(replacement)
        factory.register_parser(replacement, replace=True)
        assert factory.PARSER_MAP["duplicate"] is replacement

        with pytest.raises(factory.ReservedParserPluginError):
            factory.register_parser(reserved)


def test_registration_rejects_incompatible_constructor_and_probe_signatures(monkeypatch):
    bad_manifest = PluginManifest(
        plugin_id="bad_signature",
        display_name="Bad Signature",
        version="1.0.0",
        supported_formats=("pdf",),
    )

    class BadConstructor(_ParserBase):
        manifest = bad_manifest

        def __init__(self):
            pass

        @classmethod
        def probe(cls, _input_ref, _context):
            return ProbeResult(cls.manifest.plugin_id, False, 0)

    class BadProbe(_ParserBase):
        manifest = bad_manifest

        @classmethod
        def probe(cls, _input_ref):
            return ProbeResult(cls.manifest.plugin_id, False, 0)

    with _isolated_registry(monkeypatch):
        with pytest.raises(factory.ParserRegistrationError, match="constructor must accept"):
            factory.register_parser(BadConstructor)
        with pytest.raises(factory.ParserRegistrationError, match="probe must accept"):
            factory.register_parser(BadProbe)

        assert "bad_signature" not in factory.PARSER_MAP


def test_inspection_error_takes_precedence_over_low_confidence_match(monkeypatch, tmp_path):
    low_confidence = _parser_type(
        "low_confidence",
        ProbeResult("low_confidence", True, 40),
    )
    inspection_error = _parser_type(
        "inspection_error",
        ProbeResult(
            "inspection_error",
            False,
            0,
            outcome=ProbeOutcome.INSPECTION_ERROR,
        ),
    )
    monkeypatch.setenv("PARSER_STRICT_MATCHING", "true")

    with _isolated_registry(monkeypatch):
        factory.register_parser(low_confidence)
        factory.register_parser(inspection_error)
        diagnostics = factory.resolve_parser_with_diagnostics(tmp_path / "report.pdf")

    assert diagnostics.selected is None
    assert diagnostics.rejected_reason == "parser_inspection_failed"


def test_builtin_registration_uses_cmm_manifest_source_of_truth():
    assert factory.PARSER_MANIFESTS["cmm"] is factory.CMMReportParser.manifest


def test_registry_snapshot_is_frozen_and_exposes_generation_metadata(monkeypatch):
    monkeypatch.setattr(factory, "_ensure_external_plugins_loaded_once", lambda: None)

    snapshot = factory.get_registry_snapshot()
    cmm = next(registration for registration in snapshot.registrations if registration.plugin_id == "cmm")

    assert snapshot.generation_id > 0
    assert snapshot.load_errors == ()
    assert cmm.origin == "builtin"
    assert cmm.origin_ref == "metroliza"
    with pytest.raises(FrozenInstanceError):
        snapshot.generation_id = 0
    with pytest.raises(FrozenInstanceError):
        cmm.origin = "manual"


def test_refresh_removes_deleted_and_disabled_python_plugins(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_path = plugin_dir / "supplier.py"
    plugin_path.write_text(_external_plugin_source("supplier_pdf"), encoding="utf-8")
    disabled_ids: set[str] = set()

    monkeypatch.setattr(
        factory.parser_plugin_paths,
        "configured_external_plugin_path_entries",
        lambda *args, **kwargs: (str(plugin_dir),),
    )
    monkeypatch.setattr(
        factory.parser_plugin_paths,
        "disabled_plugin_ids",
        lambda *args, **kwargs: frozenset(disabled_ids),
    )
    monkeypatch.setattr(factory, "_discover_external_plugin_entry_points", lambda **kwargs: ())
    monkeypatch.setattr(factory, "_current_declarative_profile_signature", lambda: ())
    monkeypatch.setattr(
        factory,
        "_load_approved_declarative_profiles",
        lambda: (factory.ExternalPluginLoadResult(), ()),
    )

    with _preserved_factory_state():
        factory.reset_external_plugin_loader_state()
        loaded = factory.get_registry_snapshot()
        assert {registration.plugin_id for registration in loaded.registrations} == {
            "cmm",
            "supplier_pdf",
        }
        assert next(
            registration
            for registration in loaded.registrations
            if registration.plugin_id == "supplier_pdf"
        ).origin == "python_path"

        disabled_ids.add("supplier_pdf")
        disabled = factory.get_registry_snapshot()
        assert tuple(registration.plugin_id for registration in disabled.registrations) == ("cmm",)

        disabled_ids.clear()
        restored = factory.get_registry_snapshot()
        assert "supplier_pdf" in {
            registration.plugin_id for registration in restored.registrations
        }

        plugin_path.unlink()
        removed = factory.get_registry_snapshot()
        assert tuple(registration.plugin_id for registration in removed.registrations) == ("cmm",)
        assert factory.PARSER_MAP["cmm"] is factory.CMMReportParser


def test_external_cmm_collision_is_isolated_and_builtin_is_restored(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "collision.py").write_text(
        _external_plugin_source("cmm"),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        factory.parser_plugin_paths,
        "configured_external_plugin_path_entries",
        lambda *args, **kwargs: (str(plugin_dir),),
    )
    monkeypatch.setattr(factory.parser_plugin_paths, "disabled_plugin_ids", lambda: frozenset())
    monkeypatch.setattr(factory, "_discover_external_plugin_entry_points", lambda **kwargs: ())
    monkeypatch.setattr(factory, "_current_declarative_profile_signature", lambda: ())
    monkeypatch.setattr(
        factory,
        "_load_approved_declarative_profiles",
        lambda: (factory.ExternalPluginLoadResult(), ()),
    )

    with _preserved_factory_state():
        factory.PARSER_MAP.pop("cmm", None)
        factory.PARSER_MANIFESTS.pop("cmm", None)
        factory.PARSER_DETECTORS.pop("cmm", None)
        factory.reset_external_plugin_loader_state()

        snapshot = factory.get_registry_snapshot()

        assert tuple(registration.plugin_id for registration in snapshot.registrations) == ("cmm",)
        assert snapshot.registrations[0].origin == "builtin"
        assert snapshot.registrations[0].parser_cls is factory.CMMReportParser
        assert any("conflicts with builtin" in error for error in snapshot.load_errors)


def test_malformed_profile_is_omitted_without_blocking_valid_profile(monkeypatch):
    valid_parser = _parser_type("valid_profile", ProbeResult("valid_profile", False, 0))

    class MalformedProfile(_ParserBase):
        manifest = object()

    monkeypatch.setattr(factory.parser_plugin_paths, "configured_external_plugin_path_entries", lambda: ())
    monkeypatch.setattr(factory.parser_plugin_paths, "disabled_plugin_ids", lambda: frozenset())
    monkeypatch.setattr(factory, "_discover_external_plugin_entry_points", lambda **kwargs: ())
    monkeypatch.setattr(factory, "_current_declarative_profile_signature", lambda: (("profiles",),))

    def _profiles():
        return (
            factory.ExternalPluginLoadResult(),
            (
                factory.ParserRegistration(
                    plugin_id="malformed_profile",
                    parser_cls=MalformedProfile,
                    manifest=MalformedProfile.manifest,
                    detector=None,
                    origin="approved_profile",
                ),
                factory.ParserRegistration(
                    plugin_id="valid_profile",
                    parser_cls=valid_parser,
                    manifest=valid_parser.manifest,
                    detector=None,
                    origin="approved_profile",
                ),
            ),
        )

    monkeypatch.setattr(factory, "_load_approved_declarative_profiles", _profiles)

    with _preserved_factory_state():
        factory.reset_external_plugin_loader_state()
        snapshot = factory.get_registry_snapshot()

        assert "valid_profile" in {
            registration.plugin_id for registration in snapshot.registrations
        }
        assert "malformed_profile" not in {
            registration.plugin_id for registration in snapshot.registrations
        }
        assert any("manifest must be a PluginManifest" in error for error in snapshot.load_errors)


def test_malformed_external_constructor_is_isolated_from_valid_plugin(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "bad.py").write_text(
        _malformed_constructor_plugin_source("bad_constructor"),
        encoding="utf-8",
    )
    (plugin_dir / "good.py").write_text(
        _external_plugin_source("valid_external"),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        factory.parser_plugin_paths,
        "configured_external_plugin_path_entries",
        lambda: (str(plugin_dir),),
    )
    monkeypatch.setattr(factory.parser_plugin_paths, "disabled_plugin_ids", lambda: frozenset())
    monkeypatch.setattr(factory, "_discover_external_plugin_entry_points", lambda **kwargs: ())
    monkeypatch.setattr(factory, "_current_declarative_profile_signature", lambda: ())
    monkeypatch.setattr(
        factory,
        "_load_approved_declarative_profiles",
        lambda: (factory.ExternalPluginLoadResult(), ()),
    )

    with _preserved_factory_state():
        factory.reset_external_plugin_loader_state()
        snapshot = factory.get_registry_snapshot()

        assert {registration.plugin_id for registration in snapshot.registrations} == {
            "cmm",
            "valid_external",
        }
        assert any("constructor must accept" in error for error in snapshot.load_errors)


def test_python_plugin_import_is_cached_by_path_and_content_digest(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_path = plugin_dir / "side_effect.py"
    counter_path = tmp_path / "imports.txt"
    plugin_path.write_text(
        "from pathlib import Path\n"
        f"_counter = Path({str(counter_path)!r})\n"
        "_counter.write_text(_counter.read_text() + 'x' if _counter.exists() else 'x')\n"
        + _external_plugin_source("side_effect_pdf"),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        factory.parser_plugin_paths,
        "configured_external_plugin_path_entries",
        lambda: (str(plugin_dir),),
    )
    monkeypatch.setattr(factory.parser_plugin_paths, "disabled_plugin_ids", lambda: frozenset())
    monkeypatch.setattr(factory, "_discover_external_plugin_entry_points", lambda **kwargs: ())
    monkeypatch.setattr(factory, "_current_declarative_profile_signature", lambda: ())
    monkeypatch.setattr(
        factory,
        "_load_approved_declarative_profiles",
        lambda: (factory.ExternalPluginLoadResult(), ()),
    )

    with _preserved_factory_state():
        factory.reset_external_plugin_loader_state()
        first = factory.get_registry_snapshot()
        second = factory.get_registry_snapshot()
        assert first is second
        assert counter_path.read_text(encoding="utf-8") == "x"

        plugin_path.write_text(
            plugin_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        changed = factory.get_registry_snapshot()
        assert changed.generation_id > second.generation_id
        assert counter_path.read_text(encoding="utf-8") == "xx"


def test_concurrent_first_refresh_builds_one_registry_generation(monkeypatch):
    load_calls = 0
    load_lock = Lock()

    monkeypatch.setattr(factory.parser_plugin_paths, "configured_external_plugin_path_entries", lambda: ())
    monkeypatch.setattr(factory.parser_plugin_paths, "disabled_plugin_ids", lambda: frozenset())
    monkeypatch.setattr(factory, "_discover_external_plugin_entry_points", lambda **kwargs: ())
    monkeypatch.setattr(factory, "_current_declarative_profile_signature", lambda: (("stable",),))

    def _profiles():
        nonlocal load_calls
        with load_lock:
            load_calls += 1
        time.sleep(0.05)
        return factory.ExternalPluginLoadResult(), ()

    monkeypatch.setattr(factory, "_load_approved_declarative_profiles", _profiles)

    with _preserved_factory_state():
        factory.reset_external_plugin_loader_state()
        with ThreadPoolExecutor(max_workers=8) as executor:
            snapshots = tuple(executor.map(lambda _index: factory.get_registry_snapshot(), range(8)))

        assert load_calls == 1
        assert len({snapshot.generation_id for snapshot in snapshots}) == 1
        assert all(snapshot is snapshots[0] for snapshot in snapshots)


def test_unregister_cannot_be_resurrected_by_inflight_refresh(monkeypatch):
    removable = _parser_type("removable", ProbeResult("removable", False, 0))
    refresh_build_started = Event()
    allow_refresh_publish = Event()
    original_append = factory._append_registration
    blocked_once = False
    block_lock = Lock()

    monkeypatch.setattr(factory.parser_plugin_paths, "configured_external_plugin_path_entries", lambda: ())
    monkeypatch.setattr(factory.parser_plugin_paths, "disabled_plugin_ids", lambda: frozenset())
    monkeypatch.setattr(factory, "_discover_external_plugin_entry_points", lambda **kwargs: ())
    monkeypatch.setattr(factory, "_current_declarative_profile_signature", lambda: (("stable",),))
    monkeypatch.setattr(
        factory,
        "_load_approved_declarative_profiles",
        lambda: (factory.ExternalPluginLoadResult(), ()),
    )

    def _blocking_append(registrations, registration, errors):
        nonlocal blocked_once
        should_block = False
        with block_lock:
            if registration.plugin_id == "cmm" and not blocked_once:
                blocked_once = True
                should_block = True
        if should_block:
            refresh_build_started.set()
            assert allow_refresh_publish.wait(timeout=5)
        return original_append(registrations, registration, errors)

    monkeypatch.setattr(factory, "_append_registration", _blocking_append)

    with _preserved_factory_state():
        factory.register_parser(removable)
        factory.reset_external_plugin_loader_state()
        with ThreadPoolExecutor(max_workers=2) as executor:
            refresh_future = executor.submit(factory.get_registry_snapshot)
            assert refresh_build_started.wait(timeout=5)
            unregister_future = executor.submit(factory._unregister_parser, "removable")
            time.sleep(0.02)
            assert not unregister_future.done()
            allow_refresh_publish.set()
            refresh_future.result(timeout=5)
            unregister_future.result(timeout=5)

        final_snapshot = factory.get_registry_snapshot(refresh=False)
        assert "removable" not in {
            registration.plugin_id for registration in final_snapshot.registrations
        }


def test_compressed_pdf_coexistence_selects_parser_by_row_grammar(monkeypatch, tmp_path):
    class AlternatePdfParser(_ParserBase):
        manifest = PluginManifest(
            plugin_id="alternate_pdf",
            display_name="Alternate PDF",
            version="1.0.0",
            supported_formats=("pdf",),
            priority=500,
        )

        @classmethod
        def probe(cls, _input_ref, context):
            text = context.source_inspection.get_pdf_text(max_chars=100_000)
            semantic_rows = sum(
                line.startswith("ALTROW ") for line in text.splitlines()
            )
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse=semantic_rows > 0,
                confidence=95 if semantic_rows else 0,
                outcome=(ProbeOutcome.MATCH if semantic_rows else ProbeOutcome.NO_MATCH),
                semantic_row_count=semantic_rows,
            )

    cmm_pdf = _write_compressed_pdf(
        tmp_path / "cmm" / "report.pdf",
        "CMM REPORT\nREFERENCE: REF01\nDATE: 2026-07-16\n"
        "#FEATURE 1\nDIM\nX 10 0.2 -0.2 10.1 0.1 0\n",
    )
    alternate_pdf = _write_compressed_pdf(
        tmp_path / "alternate" / "report.pdf",
        "ALTERNATE REPORT\nALTROW X 10 10.1\n",
    )
    assert b"CMM REPORT" not in cmm_pdf.read_bytes()[:65_536].upper()
    monkeypatch.setattr(factory, "_ensure_external_plugins_loaded_once", lambda: None)

    with _preserved_factory_state():
        factory.register_parser(AlternatePdfParser)
        cmm_diagnostics = factory.resolve_parser_with_diagnostics(cmm_pdf)
        alternate_diagnostics = factory.resolve_parser_with_diagnostics(alternate_pdf)

        assert cmm_pdf.name == alternate_pdf.name == "report.pdf"
        assert cmm_diagnostics.selected is not None
        assert cmm_diagnostics.selected.plugin_id == "cmm"
        assert alternate_diagnostics.selected is not None
        assert alternate_diagnostics.selected.plugin_id == "alternate_pdf"
        assert cmm_diagnostics.registry_generation_id == alternate_diagnostics.registry_generation_id
        assert dict(cmm_diagnostics.registration_origins) == {
            "cmm": "builtin",
            "alternate_pdf": "manual",
        }
