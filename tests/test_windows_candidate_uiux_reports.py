"""Source controls for the opt-in real Reports journeys; never EXE evidence."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import stat
from types import SimpleNamespace
import zipfile

import pytest

from metroliza.app import windows_candidate_uiux_reports as checks

FIXTURES = Path(__file__).parent / 'fixtures/windows_uiux/reports'


@pytest.fixture
def admitted(monkeypatch):
    for name in ('METROLIZA_STARTUP_SMOKE', 'METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION'):
        monkeypatch.setenv(name, '1')


def capture_to(root):
    def capture(name, widget, expected):
        assert expected == checks.CAPTURE_STATES[name]
        image = widget.grab()
        path = root / f'uiux-{name}.png'
        assert image.save(str(path), 'PNG')
        return dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    width=image.width(), height=image.height(), dpr=image.devicePixelRatio())
    return capture


def test_exact_fixtures_and_independent_literal_oracles(tmp_path):
    oracle = checks._stage(FIXTURES, tmp_path / 'pdf')
    assert len(oracle['members']) == 12
    assert sum(item['size'] for item in oracle['members']) == 83737
    assert oracle['expected']['counts'] == {'parsed_reports': 12, 'report_measurements': 1728, 'report_metadata': 12}
    assert oracle['scenarios'] == {'A': {'saved': 12, 'failed': 0, 'unknown': 0, 'cancelled': 0},
        'B': {'saved': 11, 'failed': 1, 'unknown': 0, 'cancelled': 0, 'failed_name': 'REF006_0006.pdf'},
        'C': {'saved': 1, 'failed': 0, 'unknown': 11, 'cancelled': 11, 'saved_name': 'REF001_0001.pdf'}}
    assert all(item['declared'] == item['actual'] == 144 for item in oracle['expected']['reports'].values())
    assert {p.name for p in (tmp_path / 'pdf').iterdir()} == {f'REF{i:03d}_{i:04d}.pdf' for i in range(1, 13)}


@pytest.mark.parametrize('missing', ['METROLIZA_STARTUP_SMOKE', 'METROLIZA_WINDOWS_CANDIDATE_QUALIFICATION'])
def test_missing_each_gate_is_closed_without_window_or_scratch(tmp_path, admitted, monkeypatch, missing):
    monkeypatch.delenv(missing)
    outcome = checks.run_reports_checks(tmp_path, FIXTURES, expected_dpr=1, capture=capture_to(tmp_path))
    assert outcome['status'] == 'failed' and outcome['error_codes'] == ['reports_gate_missing']
    assert outcome['facets'] == dict.fromkeys(checks.FACETS, 'failed')
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('change', ['bytes', 'extra', 'symlink'])
def test_fixture_tampering_rejected_before_private_extraction(tmp_path, change):
    copied = tmp_path / 'fixtures'
    shutil.copytree(FIXTURES, copied)
    if change == 'bytes':
        with (copied / 'reports-12.zip').open('ab') as stream:
            stream.write(b'changed')
    elif change == 'extra':
        (copied / 'extra.pdf').write_bytes(b'extra')
    else:
        (copied / 'reports-12.zip').unlink()
        (copied / 'reports-12.zip').symlink_to(FIXTURES.resolve() / 'reports-12.zip')
    with pytest.raises(checks.ReportsChecksFailure, match='^reports_fixture_invalid$'):
        checks._stage(copied, tmp_path / 'private')
    assert not (tmp_path / 'private').exists()


@pytest.mark.parametrize('change', ['traversal', 'duplicate', 'link', 'compressed', 'oversized', 'hash'])
def test_zip_boundary_rejects_malformed_member_before_any_write(tmp_path, monkeypatch, change):
    """Repin transport SHA only to reach the independent member/type boundary."""
    copied = tmp_path / 'fixtures'
    shutil.copytree(FIXTURES, copied)
    with zipfile.ZipFile(copied / 'reports-12.zip') as archive:
        items = [(item, archive.read(item)) for item in archive.infolist()]
    with zipfile.ZipFile(copied / 'reports-12.zip', 'w') as archive:
        for index, (item, data) in enumerate(items):
            if index == 0:
                if change == 'traversal':
                    item.filename = '../outside.pdf'
                elif change == 'duplicate':
                    item.filename = items[1][0].filename
                elif change == 'link':
                    item.external_attr = (stat.S_IFLNK | 0o600) << 16
                elif change == 'compressed':
                    item.compress_type = zipfile.ZIP_DEFLATED
                elif change == 'oversized':
                    data = b'x' * (64 * 1024 + 1)
                else:
                    data = b'x' * len(data)
            archive.writestr(item, data)
    transport_sha = hashlib.sha256((copied / 'reports-12.zip').read_bytes()).hexdigest()
    oracle = json.loads((copied / 'oracles.json').read_text())
    oracle['archive_sha256'] = transport_sha
    (copied / 'oracles.json').write_text(json.dumps(oracle))
    monkeypatch.setattr(checks, 'FIXTURE_HASHES', {'reports-12.zip': transport_sha,
        'oracles.json': hashlib.sha256((copied / 'oracles.json').read_bytes()).hexdigest()})
    with pytest.raises(checks.ReportsChecksFailure, match='^reports_fixture_invalid$'):
        checks._stage(copied, tmp_path / 'private')
    assert not (tmp_path / 'private').exists() and not (tmp_path / 'outside.pdf').exists()


def test_real_twelve_report_journeys_sql_receipts_cancel_and_captures(tmp_path, admitted, qapplication_session):
    app = qapplication_session
    print('REPORTS_SURFACE', app.platformName(), app.primaryScreen().geometry().getRect(),
          app.primaryScreen().availableGeometry().getRect(), app.primaryScreen().devicePixelRatio())
    outcome = checks.run_reports_checks(tmp_path, FIXTURES,
        expected_dpr=float(app.primaryScreen().devicePixelRatio()), capture=capture_to(tmp_path))
    (tmp_path / 'reports-observation.json').write_text(json.dumps(outcome, indent=2) + '\n')
    print('REPORTS_OBSERVATION', tmp_path / 'reports-observation.json', outcome['status'],
          outcome['error_codes'], outcome['evidence']['summaries'])
    assert outcome['status'] == 'passed', outcome
    assert set(outcome) == {'schema_version', 'status', 'facets', 'error_codes', 'evidence'}
    assert outcome['schema_version'] == 1 and outcome['error_codes'] == []
    assert outcome['facets'] == dict.fromkeys(checks.FACETS, 'passed')
    evidence = outcome['evidence']
    assert set(evidence) == {'fixture_hashes', 'context', 'A', 'B', 'C', 'summaries', 'captures', 'cleanup', 'failure'}
    assert set(evidence['captures']) == set(checks.CAPTURE_STATES)
    expected = {'A': (12, 0, 0), 'B': (11, 1, 0), 'C': (1, 0, 11)}
    for case, (saved, failed, unknown) in expected.items():
        result = evidence[case]
        assert set(result) == set(checks.CASE_KEYS)
        assert set(result['context']) == set(checks.CONTEXT_KEYS)
        assert result['review_counts'] == {'ready': 12, 'duplicate': 0, 'selected': 12}
        assert result['batch_counts'] == {'saved': saved, 'failed': failed, 'cancelled': unknown, 'total': 12}
        assert result['rereview_counts'] == {'ready': 12 - saved, 'duplicate': saved, 'selected': 12 - saved}
        assert result['database_counts'] == {'parsed_reports': saved, 'report_measurements': saved * 144, 'report_metadata': saved}
        rows = result['row_facts']
        assert len(rows) == 12
        assert [row['occurrence_id'] for row in rows] == [f'REF{i:03d}_{i:04d}.pdf' for i in range(1, 13)]
        assert all(set(row) == {'name', 'occurrence_id', 'state', 'readonly', 'attention'} and row['readonly'] for row in rows)
        assert dict(Counter(row['state'] for row in rows)) == {k: v for k, v in [('saved', saved), ('failed', failed), ('unknown', unknown)] if v}
        assert sum(row['attention'] for row in rows) == failed + unknown
        assert len(result['receipt_states']) == saved + failed
        assert len(result['numeric_digests']) == saved
        assert all(result['preservation'][key] for key in ('rereview_unchanged', 'seed_unchanged', 'sources_unchanged'))
    assert evidence['A']['context']['approval_invalidated'] and evidence['A']['context']['same_owner'] and evidence['A']['context']['same_result']
    assert all(evidence['C']['context'][key] for key in ('worker_running_at_cancel', 'cancel_clicked', 'cancel_flag', 'released', 'terminal'))
    assert evidence['C']['context']['first_accepted'] == 'REF001_0001.pdf'
    assert not evidence['C']['context']['barrier_expired']
    assert evidence['cleanup'] == {'joined': True, 'closed': True, 'sources_unchanged': True, 'callback_errors': []}
    assert evidence['failure'] is None and len(json.dumps(outcome).encode()) <= 24 * 1024
    assert app.activeModalWidget() is None


@pytest.fixture
def capture_journey(tmp_path, qapplication_session):
    from PyQt6.QtWidgets import QWidget, QTableWidget, QVBoxLayout
    window, table = QWidget(), QTableWidget(12, 1)
    layout = QVBoxLayout(window)
    layout.addWidget(table)
    window.resize(400, 300)
    window.show()
    qapplication_session.processEvents()
    journey = object.__new__(checks._Journey)
    journey.root, journey.window = tmp_path, window
    journey.workspace = SimpleNamespace(report_planner=SimpleNamespace(table=table))
    journey.dpr = float(qapplication_session.primaryScreen().devicePixelRatio())
    journey.capture, journey.evidence = capture_to(tmp_path), {'captures': {}}
    try:
        yield journey
    finally:
        window.close()


@pytest.mark.parametrize('change', ['missing', 'hash', 'dimensions', 'extra', 'symlink'])
def test_actual_png_capture_contract_rejects_missing_or_tampered_evidence(capture_journey, tmp_path, change):
    real = capture_journey.capture
    def corrupt(name, widget, state):
        value = real(name, widget, state)
        path = tmp_path / value['path']
        if change == 'missing':
            path.unlink()
        elif change == 'hash':
            value['sha256'] = '0' * 64
        elif change == 'dimensions':
            value['width'] += 1
        elif change == 'extra':
            value['ignored'] = True
        else:
            moved = tmp_path / 'real.png'
            path.rename(moved)
            path.symlink_to(moved)
        return value
    capture_journey.capture = corrupt
    with pytest.raises(checks.ReportsChecksFailure, match='^reports_capture_failed$'):
        capture_journey.take('reports-saved-top')
    assert capture_journey.evidence['captures'] == {}


def test_actual_png_capture_contract_accepts_real_widget(capture_journey):
    capture_journey.take('reports-saved-top')
    assert set(capture_journey.evidence['captures']) == {'reports-saved-top'}


def test_summary_control_rejects_real_clipped_wrapped_label(qapplication_session):
    from PyQt6.QtWidgets import QWidget, QLabel, QTableWidget, QVBoxLayout
    window, label, table = QWidget(), QLabel('Last import: ' + '12 saved results ' * 20), QTableWidget()
    label.setWordWrap(True)
    layout = QVBoxLayout(window)
    layout.addWidget(label)
    layout.addWidget(table)
    window.resize(320, 260)
    window.show()
    qapplication_session.processEvents()
    try:
        window.counts, window.table = label, table
        planner = window
        label.setFixedHeight(1)
        facts = checks._summary_snapshot(planner)
        assert facts['hfw'] > facts['height']
        with pytest.raises(checks.ReportsChecksFailure, match='^reports_summary_clipped$'):
            checks._check_summary(facts)
    finally:
        window.close()


def test_failed_cleanup_never_promotes_observation(tmp_path, admitted, monkeypatch):
    class RefusingJourney:
        def __init__(self, *args):
            self.phase = 'A'
        def run_case(self, case):
            raise checks.ReportsChecksFailure('reports_invariant_failed')
        def cleanup(self):
            raise checks.ReportsChecksFailure('reports_cleanup_failed')
    monkeypatch.setattr(checks, '_Journey', RefusingJourney)
    outcome = checks.run_reports_checks(tmp_path, FIXTURES, expected_dpr=1, capture=capture_to(tmp_path))
    assert outcome['status'] == 'failed'
    assert outcome['error_codes'] == ['reports_invariant_failed', 'reports_cleanup_failed']
    assert outcome['facets'] == dict.fromkeys(checks.FACETS, 'failed')


def test_refused_real_owner_is_retained_and_not_silently_retried(qapplication_session, monkeypatch):
    from threading import Event
    from PyQt6.QtWidgets import QWidget
    from metroliza.app.windows_candidate_native_check import ReportOwnerCleanupFailure
    window = QWidget()
    window.show()
    journey = object.__new__(checks._Journey)
    journey.app, journey.window, journey.workspace = qapplication_session, window, None
    journey.release, journey.close_failed = Event(), False
    try:
        with monkeypatch.context() as scope:
            scope.setattr(window, 'close', lambda: False)
            with pytest.raises(ReportOwnerCleanupFailure):
                journey.close()
            assert journey.close_failed and window.isVisible()
            assert journey.window is window and checks._RETAINED_WINDOWS[-1] is window
            with pytest.raises(checks.ReportsChecksFailure, match='^reports_cleanup_failed$'):
                journey.close()
        assert window.close() and not window.isVisible()
    finally:
        window.close()
        checks._RETAINED_WINDOWS[:] = [owned for owned in checks._RETAINED_WINDOWS if owned is not window]


def test_queued_summary_observer_failure_is_closed_without_qt_callback_exception(
        tmp_path, qapplication_session, monkeypatch):
    from PyQt6.QtWidgets import QWidget, QLabel, QTableWidget, QVBoxLayout
    window, label, table = QWidget(), QLabel('Last import'), QTableWidget()
    label.setWordWrap(True)
    layout = QVBoxLayout(window)
    layout.addWidget(label)
    layout.addWidget(table)
    window.counts, window.table = label, table
    window.show()
    journey = object.__new__(checks._Journey)
    journey.app, journey.workspace = qapplication_session, SimpleNamespace(report_planner=window)
    journey.evidence, journey.callback_errors = {'summaries': {}}, []
    import time
    journey.deadline = journey.case_deadline = time.monotonic() + 2
    original = checks._summary_snapshot
    calls = []
    def observe(planner):
        calls.append(True)
        if len(calls) > 1:
            raise RuntimeError('synthetic observer error')
        return original(planner)
    monkeypatch.setattr(checks, '_summary_snapshot', observe)
    try:
        with pytest.raises(checks.ReportsChecksFailure, match='^reports_callback_failed$'):
            journey.summary('A')
        assert len(calls) == 2 and journey.callback_errors == ['reports_callback_failed']
    finally:
        window.close()
