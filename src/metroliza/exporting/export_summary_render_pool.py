"""Bounded, ordered per-group PNG rendering; workbook ownership stays in Qt.

Workers use the existing summary renderer against a recording worksheet. Only
plain request data, PNG bytes, write commands and telemetry cross the process
boundary. They never open the database, workbook, or dashboard output paths.
"""

from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import multiprocessing
import sys

from metroliza.exporting.contracts import AppPaths, ExportRequest
from metroliza.shared.env_utils import env_bool


MIN_PARALLEL_GROUPS = 8
MAX_RENDER_WORKERS = 4


class RecordingWorksheet:
    """Capture the two worksheet operations used by summary_sheet_fill."""

    def __init__(self):
        self.commands = []

    def write(self, *args):
        self.commands.append(('write', args))

    def insert_image(self, row, col, _filename, options):
        options = dict(options)
        payload = options.pop('image_data').getvalue()
        self.commands.append(('image', (row, col, options, payload)))


def _initialize_render_worker():
    # A failed native/scientific dependency must never generate desktop cores.
    if sys.platform != 'win32':
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def render_summary_group(task):
    """Spawn-importable entry point. No QApplication or Qt event loop is needed."""
    from metroliza.exporting.export_data_thread import ExportDataThread

    request = ExportRequest(
        paths=AppPaths(db_file='unused.sqlite', excel_file='unused.xlsx'),
        options=replace(task['options'], generate_html_dashboard=False, chart_worker_count=1),
    )
    thread = ExportDataThread(request)
    thread._prepared_grouping_df = task['grouping_df']
    thread._optimization_toggles = dict(task['toggles'])
    thread._lookup_sql_measurement_summary = lambda **_kwargs: task['sql_summary']
    sheet = RecordingWorksheet()
    labels = []
    thread.update_label.connect(labels.append)
    thread.summary_sheet_fill(sheet, task['header'], task['group'], task['col'])
    return {
        'commands': sheet.commands,
        'stage_timings': thread._stage_timings,
        'chart_timings': thread._chart_render_timings_by_type,
        'backend_counts': thread._chart_render_backend_counts,
        'backend_counts_by_type': thread._chart_render_backend_counts_by_type,
        'warnings': thread.completion_metadata.get('summary_sheet_warnings', []),
        'warning_details': thread.completion_metadata.get('summary_sheet_warning_details', []),
        'failed': thread._summary_sheet_failed,
        'labels': labels,
    }


def _render_task(owner, entry):
    header, group, bundle = entry
    group = owner._ensure_sample_number_column(group)
    first = group.iloc[0]
    from metroliza.exporting.export_summary_utils import resolve_nominal_and_limits

    limits = resolve_nominal_and_limits(group)
    reference, header_value, axis = first.get('REFERENCE'), first.get('HEADER'), first.get('AX')
    summary = None
    # Match summary_sheet_fill's guard: missing identity uses Python statistics,
    # never a broader SQL aggregate for an unknown-reference partition.
    if reference is not None and str(reference).strip() and header_value is not None and axis is not None:
        summary = owner._lookup_sql_measurement_summary(
            reference=reference, header=header_value, ax=axis,
            usl=limits['usl'], lsl=limits['lsl'],
        )
    return {
        'header': header, 'group': group, 'col': bundle['measurement_plan']['summary_column'] + 4,
        'options': owner._summary_render_options,
        'grouping_df': owner.prepared_grouping_df,
        'sql_summary': summary, 'toggles': dict(owner._optimization_toggles),
    }


def _pool_policy(owner, group_count):
    if not owner.generate_summary_sheet or owner.generate_html_dashboard:
        return 'serial_output_mode'
    if owner.chart_worker_count <= 1 or group_count < MIN_PARALLEL_GROUPS:
        return 'serial_small_export'
    if getattr(sys, 'frozen', False):
        # Current frozen entry points do not dispatch multiprocessing workers.
        # Do not relaunch the desktop application as a spawn worker.
        return 'serial_frozen_multiprocessing_unavailable'
    if not env_bool('METROLIZA_EXPORT_GROUP_MP', default=True):
        return 'serial_disabled'
    return 'spawn'


def iter_summary_render_results(owner, entries):
    """Yield entries in input order with at most queue_size outstanding groups.

    The first group follows the original serial path. Its timing-driven density
    policy is then known. A queued group is discarded if that policy changes.
    Pool startup, submission, or worker failure degrades the remaining work to
    the original serial path, without duplicating workbook writes.
    """
    policy = _pool_policy(owner, len(entries))
    telemetry = owner.completion_metadata.setdefault('summary_render_pool', {})
    telemetry.update(mode=policy, workers=0, max_pending=0, completed=0)
    if policy != 'spawn':
        for entry in entries:
            yield entry, None
        return

    yield entries[0], None
    workers = min(MAX_RENDER_WORKERS, owner.chart_worker_count, len(entries) - 1)
    bound = max(1, min(owner.chart_worker_queue_size, workers * 2))
    pending = deque()
    remaining = iter(entries[1:])
    executor = None
    try:
        executor = ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context('spawn'),
            initializer=_initialize_render_worker,
        )
        telemetry['workers'] = workers
        yield from _collect_ordered(owner, remaining, pending, executor, bound, telemetry)
    except Exception as exc:
        telemetry.update(mode='serial_pool_failure', exception_class=type(exc).__name__)
        for entry, future, _toggles in pending:
            if future is not None:
                future.cancel()
            yield entry, None
        for entry in remaining:
            yield entry, None
    finally:
        for _entry, future, _toggles in pending:
            if future is not None:
                future.cancel()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)


def _collect_ordered(owner, remaining, pending, executor, bound, telemetry):
    exhausted = False
    while not exhausted or pending:
        if owner._check_canceled():
            return
        while not exhausted and len(pending) < bound:
            entry = next(remaining, None)
            if entry is None:
                exhausted = True
            else:
                pending.append((entry, None, None))
                task = _render_task(owner, entry)
                # Preserve the entry even if submit fails.
                future = executor.submit(render_summary_group, task)
                pending[-1] = (entry, future, task['toggles'])
                telemetry['max_pending'] = max(telemetry['max_pending'], len(pending))
        if pending:
            entry, future, toggles = pending[0]
            result = future.result()
            pending.popleft()
            if toggles != owner._optimization_toggles:
                result = None
            else:
                telemetry['completed'] += 1
            yield entry, result


def apply_summary_render_result(owner, worksheet, result):
    """Replay ordered writes and account worker telemetry in the parent only."""
    for operation, args in result['commands']:
        if operation == 'write':
            worksheet.write(*args)
        else:
            row, col, options, payload = args
            worksheet.insert_image(row, col, '', {
                **options, 'image_data': owner._register_chart_image(payload),
            })
    for stage, elapsed in result['stage_timings'].items():
        owner._record_stage_timing(stage, elapsed)
    for chart, samples in result['chart_timings'].items():
        owner._chart_render_timings_by_type[chart].extend(samples)
    for backend, count in result['backend_counts'].items():
        owner._chart_render_backend_counts[backend] += count
    for chart, counts in result['backend_counts_by_type'].items():
        for backend, count in counts.items():
            owner._chart_render_backend_counts_by_type[chart][backend] += count
    owner._summary_sheet_failed |= result['failed']
    owner.completion_metadata.setdefault('summary_sheet_warnings', []).extend(result['warnings'])
    owner.completion_metadata.setdefault('summary_sheet_warning_details', []).extend(result['warning_details'])
    for label in result['labels']:
        owner.update_label.emit(label)
