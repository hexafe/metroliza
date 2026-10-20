"""Review reports in a process pool (#1148 C2): identical results, registry-consistent workers."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
from pathlib import Path
import shutil

import pytest

from metroliza.parsing import report_parser_factory as factory
from metroliza.parsing import review_pool
import metroliza.parsing.preflight as preflight_module
from metroliza.parsing.metadata_review import MODE_FAST, MetadataReviewReader
from metroliza.parsing.parser_plugin_contracts import ProbeOutcome, ProbeResult
from metroliza.parsing.pdf_backend import require_pdf_backend
from metroliza.parsing.preflight import (
    ImportPlan,
    ParsePreflightService,
    ParsePreflightStatus,
)
from metroliza.shared.compute_budget import REVIEW_WORKERS_ENV
from metroliza.shared.parse_contracts import ParseRequest
from tests.test_import_prepare_pool import _write_synthetic_reports
from tests.test_parser_registry_generation import _parser_type, _preserved_factory_state


@pytest.fixture
def review_source(tmp_path, monkeypatch):
    """Synthetic CMM reports plus every non-READY outcome the scan can produce."""

    monkeypatch.setattr(review_pool, "CHUNK_SIZE", 4)
    source = tmp_path / "reports"
    reports = _write_synthetic_reports(source, 14)
    shutil.copyfile(reports[2], source / "zz_copy_of_two.pdf")  # duplicate in the source
    (source / "broken.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    (source / "empty.pdf").write_bytes(b"")  # discovery failure
    document = require_pdf_backend().open()
    document.new_page().insert_text((40, 40), "An unrelated letter, not a CMM report.")
    document.save(str(source / "letter.pdf"))
    document.close()
    nested = source / "nested"
    nested.mkdir()
    shutil.copyfile(reports[5], nested / "again_five.pdf")
    # One report already matches the destination: the scan marks it DUPLICATE.
    known = ParsePreflightService._inspect_file(
        reports[7], display_name=reports[7].name, existing_fingerprints=frozenset()
    ).fingerprint
    monkeypatch.setattr(
        preflight_module, "load_existing_report_fingerprints",
        lambda *_args, **_kwargs: frozenset({known}),
    )
    return source, tmp_path / "review.sqlite"


def _scan(source, database, *, workers, **kwargs):
    return ParsePreflightService().scan_source(
        source_path=source, database_path=database, metadata_parsing_mode="light",
        workers=workers, **kwargs,
    )


def _read_all(result, *, workers):
    readings = []
    ready = [item.stable_occurrence_id for item in result.files if item.parser_id]
    summary = MetadataReviewReader(result).read(
        ready, mode=MODE_FAST, on_reading=readings.append, workers=workers
    )
    return summary, readings


@pytest.fixture
def advanced_parent_generation():
    """Move the parent's generation counter away from a fresh worker's (same registry)."""

    with _preserved_factory_state():
        for _ in range(3):
            with factory._PARSER_REGISTRY_LOCK:
                snapshot = factory.get_registry_snapshot(refresh=False)
                factory._publish_registry_locked(snapshot.registrations,
                                                 load_errors=snapshot.load_errors)
        yield factory.get_registry_snapshot().generation_id


def _accept_spy(monkeypatch):
    calls = []
    original = review_pool._accepted

    def spy(value, fingerprint, generation, pool):
        accepted = original(value, fingerprint, generation, pool)
        calls.append(accepted is not None)
        return accepted

    monkeypatch.setattr(review_pool, "_accepted", spy)
    return calls


def test_pooled_scan_and_metadata_read_equal_the_in_process_review(
    review_source, monkeypatch, advanced_parent_generation
):
    source, database = review_source
    serial = _scan(source, database, workers=0)
    calls = _accept_spy(monkeypatch)
    killed = []
    monkeypatch.setattr(review_pool, "_stop_executor", killed.append)
    pooled = _scan(source, database, workers=2)

    assert calls and all(calls)  # every chunk came from a worker
    assert not killed and not multiprocessing.active_children()  # graceful shutdown
    assert pooled == serial  # every field, including registry_generation_id
    assert pooled.result_id == serial.result_id
    statuses = {item.display_name: (item.status, item.reason_codes) for item in serial.files}
    assert statuses["zz_copy_of_two.pdf"][0] is ParsePreflightStatus.DUPLICATE
    assert "duplicate_in_selected_source" in statuses["zz_copy_of_two.pdf"][1]
    assert statuses[str(Path("nested") / "again_five.pdf")][0] is ParsePreflightStatus.DUPLICATE
    assert statuses["empty.pdf"][0] is ParsePreflightStatus.UNREADABLE
    assert {status for status, _codes in statuses.values()} >= {
        ParsePreflightStatus.READY, ParsePreflightStatus.DUPLICATE,
        ParsePreflightStatus.UNSUPPORTED, ParsePreflightStatus.UNREADABLE,
    }
    generation = factory.get_registry_snapshot().generation_id
    assert generation == advanced_parent_generation
    assert {item.registry_generation_id for item in pooled.files if item.parser_id} == {generation}

    request = ParseRequest(source_directory=str(source), db_file=str(database),
                           metadata_parsing_mode="light")
    assert (ImportPlan.all_atomic_candidates(request, pooled).selected_reports
            == ImportPlan.all_atomic_candidates(request, serial).selected_reports)

    calls.clear()
    serial_summary, serial_readings = _read_all(serial, workers=0)
    pooled_summary, pooled_readings = _read_all(pooled, workers=2)
    assert calls and all(calls)
    assert not killed and not multiprocessing.active_children()
    assert pooled_summary == serial_summary
    assert pooled_readings == serial_readings
    assert all(reading.status == "ok" for reading in pooled_readings)


def test_a_worker_registry_that_differs_from_the_parent_falls_back_in_process(review_source, monkeypatch):
    source, database = review_source
    extra = _parser_type(
        "zz.review_extra",
        ProbeResult(plugin_id="zz.review_extra", can_parse=False, confidence=0,
                    reasons=("not_this_format",), outcome=ProbeOutcome.NO_MATCH),
    )
    with _preserved_factory_state():
        # Registered only in the parent: spawned workers cannot reproduce it.
        factory.register_parser(extra)
        serial = _scan(source, database, workers=0)
        assert any(c.parser_id == "zz.review_extra" for c in serial.ready_files[0].candidates)
        calls = _accept_spy(monkeypatch)
        pooled = _scan(source, database, workers=2)
        readings_serial = _read_all(serial, workers=0)
        readings_pooled = _read_all(pooled, workers=2)

    assert calls and not any(calls)  # no worker item was accepted
    assert pooled == serial
    assert readings_pooled == readings_serial


def test_an_unexpected_fingerprint_is_never_accepted(review_source, monkeypatch):
    source, database = review_source
    serial = _scan(source, database, workers=0)
    real_state = review_pool.registry_state
    monkeypatch.setattr(review_pool, "registry_state",
                        lambda: (real_state()[0], "sha256:not-the-workers"))
    calls = _accept_spy(monkeypatch)

    assert _scan(source, database, workers=2) == serial
    assert calls and not any(calls)  # every chunk was inspected in-process


def test_a_dying_worker_falls_back_in_process(review_source, monkeypatch):
    source, database = review_source
    serial = _scan(source, database, workers=0)
    serial_readings = _read_all(serial, workers=0)
    original_submit = ProcessPoolExecutor.submit
    submitted = []

    def killing_submit(self, function, *args, **kwargs):
        submitted.append(function)
        if len(submitted) % 3 == 2:
            return original_submit(self, os._exit, 1)
        return original_submit(self, function, *args, **kwargs)

    monkeypatch.setattr(ProcessPoolExecutor, "submit", killing_submit)
    calls = _accept_spy(monkeypatch)
    pooled = _scan(source, database, workers=2)
    pooled_readings = _read_all(pooled, workers=2)

    assert False in calls
    assert pooled == serial
    assert pooled_readings == serial_readings
    assert not multiprocessing.active_children()


def test_a_parent_generation_change_mid_scan_is_never_mixed_with_worker_results(review_source, monkeypatch):
    source, database = review_source
    original = review_pool._accepted
    seen = []

    def republish_after_first_chunk(value, fingerprint, generation, pool):
        seen.append(generation)
        if len(seen) == 2:
            with factory._PARSER_REGISTRY_LOCK:
                factory._publish_registry_locked(factory._REGISTRY_SNAPSHOT.registrations,
                                                 load_errors=factory._REGISTRY_SNAPSHOT.load_errors)
        return original(value, fingerprint, generation, pool)

    monkeypatch.setattr(review_pool, "_accepted", republish_after_first_chunk)
    with _preserved_factory_state():
        before = factory.get_registry_snapshot().generation_id
        pooled = _scan(source, database, workers=2)
        after = factory.get_registry_snapshot().generation_id

    assert after == before + 1
    generations = [item.registry_generation_id for item in pooled.files if item.parser_id]
    first_chunk = review_pool.CHUNK_SIZE
    assert set(generations[:first_chunk]) == {before}
    assert set(generations[first_chunk:]) == {after}  # read in-process after the change
    request = ParseRequest(source_directory=str(source), db_file=str(database),
                           metadata_parsing_mode="light")
    with pytest.raises(ValueError, match="stale"):
        ImportPlan.all_atomic_candidates(request, pooled)


def test_cancel_stops_the_scan_and_reaps_the_workers(review_source):
    source, database = review_source
    progress = []

    def on_progress(done, _total, _name):
        progress.append(done)

    result = _scan(source, database, workers=2,
                   should_cancel=lambda: len(progress) >= 6, on_progress=on_progress)

    assert result.cancelled
    assert len(result.files) == 6
    assert not multiprocessing.active_children()


def test_metadata_read_cancel_keeps_the_ordered_prefix(review_source):
    source, database = review_source
    result = _scan(source, database, workers=0)
    ready = [item.stable_occurrence_id for item in result.files if item.parser_id]
    serial = []
    MetadataReviewReader(result).read(ready, on_reading=serial.append, workers=0)
    pooled = []
    summary = MetadataReviewReader(result).read(
        ready, on_reading=pooled.append, workers=2, should_cancel=lambda: len(pooled) >= 5
    )

    assert pooled == serial[:5]
    assert summary.cancelled == len(ready) - 5
    assert not multiprocessing.active_children()


def test_small_batches_patched_readers_and_ocr_stay_in_process(review_source, monkeypatch):
    source, database = review_source
    monkeypatch.delenv(REVIEW_WORKERS_ENV, raising=False)
    started = []
    monkeypatch.setattr(review_pool, "OrderedChunkPool",
                        lambda *a, **k: started.append(a) or pytest.fail("pool started"))

    result = _scan(source, database, workers=None)  # 19 files: below the pool minimum
    reader = MetadataReviewReader(result, parser_factory=factory.get_parser)
    ready = [item.stable_occurrence_id for item in result.files if item.parser_id]
    assert reader._pool_size(len(ready), "complete", 4) == 0  # OCR reads stay in-process
    assert MetadataReviewReader(result, parser_factory=lambda *a, **k: None)._pool_size(
        200, MODE_FAST, 4) == 0
    original_inspect = ParsePreflightService._inspect_file
    monkeypatch.setattr(ParsePreflightService, "_inspect_file",
                        staticmethod(lambda *args, **kwargs: original_inspect(*args, **kwargs)))
    assert _scan(source, database, workers=4) == result  # patched inspection: in-process
    assert not started


def test_registry_fingerprint_is_deterministic_and_tracks_registrations():
    snapshot = factory.get_registry_snapshot()
    fingerprint = factory.registry_configuration_fingerprint(snapshot)
    assert fingerprint == factory.registry_configuration_fingerprint(snapshot)
    assert fingerprint.startswith("sha256:")
    extra = _parser_type(
        "zz.fingerprint_extra",
        ProbeResult(plugin_id="zz.fingerprint_extra", can_parse=False, confidence=0,
                    outcome=ProbeOutcome.NO_MATCH),
    )
    with _preserved_factory_state():
        factory.register_parser(extra)
        changed = factory.registry_configuration_fingerprint(factory.get_registry_snapshot())
    assert changed != fingerprint
    assert factory.registry_configuration_fingerprint(factory.get_registry_snapshot()) == fingerprint


def _partial_registration_fingerprint(argument):
    from dataclasses import replace
    from functools import partial

    snapshot = factory.get_registry_snapshot()
    registration = snapshot.registrations[0]
    detector = partial(_partial_registration_fingerprint, argument)
    snapshot = replace(snapshot, registrations=(replace(registration, detector=detector),))
    return factory.registry_configuration_fingerprint(snapshot)


def test_partial_registration_fingerprint_matches_across_processes():
    arguments = {'threshold': 0.5, 'formats': ['pdf', 'csv'], 'enabled': True, 'opaque': object()}
    expected = _partial_registration_fingerprint(arguments)
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as executor:
        actual = executor.submit(_partial_registration_fingerprint, arguments).result(timeout=60)
    assert actual == expected
    assert _partial_registration_fingerprint({'threshold': 0.6}) != expected


def test_callable_instance_identity_uses_its_type_without_an_address():
    class Detector:
        def __call__(self):
            pass
    left, right = Detector(), Detector()
    assert factory._code_identity(left) == factory._code_identity(right)


def test_registry_mismatch_is_in_completion_telemetry(review_source, monkeypatch, caplog):
    source, database = review_source
    real_state = review_pool.registry_state
    monkeypatch.setattr(review_pool, 'registry_state', lambda: (real_state()[0], 'forced-mismatch'))
    completed = []
    original_close = review_pool.OrderedChunkPool.close
    def close(pool, **kwargs):
        original_close(pool, **kwargs)
        completed.append(pool.completion_metadata['review_pool'].copy())
    monkeypatch.setattr(review_pool.OrderedChunkPool, 'close', close)
    with caplog.at_level('INFO', logger=review_pool.__name__):
        result = _scan(source, database, workers=2)
    assert result.files
    assert completed[-1]['mode'] == 'serial_fallback'
    assert completed[-1]['fallback_reason'] == 'registry_fingerprint_mismatch'
    assert any(getattr(record, 'completion_metadata', {}).get('review_pool', {}).get(
        'fallback_reason') == 'registry_fingerprint_mismatch' for record in caplog.records)


def test_callable_path_plugin_identity_ignores_process_local_module_counter(monkeypatch):
    from functools import partial
    import sys
    from types import ModuleType

    identities = []
    for counter in (1, 9):
        name = f"metroliza_external_parser_plugin_{counter}"
        module = ModuleType(name)
        module.__file__ = __file__
        monkeypatch.setitem(sys.modules, name, module)
        detector = type('Detector', (), {'__module__': name, '__call__': lambda self: None})()
        identities.append((factory._code_identity(detector), factory._code_identity(partial(detector))))
    assert identities[0] == identities[1]
