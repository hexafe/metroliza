"""Bounded, ordered per-group PNG rendering; workbook ownership stays in Qt.

Workers use the existing summary renderer against a recording worksheet. Only
plain request data, PNG bytes, write commands and telemetry cross the process
boundary. They never open the database, workbook, or dashboard output paths.
"""

from collections import deque
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from dataclasses import replace
from itertools import chain
import sys
import time

from metroliza.exporting.contracts import AppPaths, ExportRequest
from metroliza.shared.compute_budget import RENDER_MAX_WORKERS, RENDER_MIN_GROUPS, render_min_groups, render_workers
from metroliza.shared.env_utils import env_bool
from metroliza.shared.compute_worker import compute_workers_available, spawn_context


MIN_PARALLEL_GROUPS = RENDER_MIN_GROUPS
MAX_RENDER_WORKERS = RENDER_MAX_WORKERS
RESULT_POLL_SECONDS = 0.1
WORKER_EXIT_GRACE_SECONDS = 2.0
WORKER_STOP_GRACE_SECONDS = 0.5
_worker_cancel_event = None


class RecordingWorksheet:
    """Capture the two worksheet operations used by summary_sheet_fill."""

    def __init__(self):
        self.commands = []
        self.image_commands = {}

    def write(self, *args):
        self.commands.append(('write', args))

    def insert_image(self, row, col, _filename, options):
        options = dict(options)
        buffer = options.pop('image_data')
        self.image_commands[id(buffer)] = len(self.commands)
        self.commands.append(('image', (row, col, options, buffer.getvalue())))


def _initialize_render_worker(cancel_event=None):
    from metroliza.shared.compute_worker import initialize_compute_runtime
    initialize_compute_runtime()
    global _worker_cancel_event
    _worker_cancel_event = cancel_event
    # A failed native/scientific dependency must never generate desktop cores.
    if sys.platform != 'win32':
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def render_summary_group(task):
    """Spawn-importable entry point. No QApplication or Qt event loop is needed."""
    from metroliza.shared.compute_worker import initialize_compute_runtime
    initialize_compute_runtime()
    from metroliza.exporting.export_data_thread import ExportDataThread

    request = ExportRequest(
        paths=AppPaths(db_file='unused.sqlite', excel_file='unused.xlsx', html_dashboard_file='unused.html'),
        options=replace(task['options'], chart_worker_count=1),
    )
    thread = ExportDataThread(request)
    if _worker_cancel_event is not None:
        # Observe cancellation at the existing chart boundaries without emitting
        # parent-owned Qt cancellation/progress signals from a child process.
        thread._check_canceled = _worker_cancel_event.is_set
    thread._prepared_grouping_df = task['grouping_df']
    thread._optimization_toggles = dict(task['toggles'])
    thread._lookup_sql_measurement_summary = lambda **_kwargs: task['sql_summary']
    sheet = RecordingWorksheet() if task['options'].generate_summary_sheet else None
    labels = []
    thread.update_label.connect(labels.append)
    if not thread._check_canceled():
        thread.summary_sheet_fill(sheet, task['header'], task['group'], task['col'])
    for section in thread._html_dashboard_sections:
        for chart in section['charts']:
            # Reuse the worksheet payload across the process boundary as well as
            # its registered parent buffer. HTML-only charts still carry bytes.
            buffer = chart['image_buffer']
            command = sheet.image_commands.get(id(buffer)) if sheet is not None else None
            chart['image_buffer'] = (('worksheet_image', command) if command is not None
                                     else buffer.getvalue())
    return {
        'dashboard_sections': thread._html_dashboard_sections,
        'commands': sheet.commands if sheet is not None else [],
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
    if not (owner.generate_summary_sheet or owner.generate_html_dashboard):
        return 'serial_output_mode'
    minimum = _minimum_groups()
    if (render_workers(owner.chart_worker_count, group_count, cap=MAX_RENDER_WORKERS) <= 1
            or group_count < max(2, minimum or 40)):
        return 'serial_small_export'
    if not env_bool('METROLIZA_EXPORT_GROUP_MP', default=True):
        return 'serial_disabled'
    # Last: on a frozen build this validates (hashes) the package identity.
    if not compute_workers_available():
        return 'serial_frozen_multiprocessing_unavailable'
    return 'spawn'


def _minimum_groups():
    return render_min_groups()


def _render_canceled(owner, cancel_event):
    if owner._check_canceled():
        cancel_event.set()
        return True
    return False


def _await_render_result(owner, future, cancel_event):
    while not _render_canceled(owner, cancel_event):
        try:
            return future.result(timeout=RESULT_POLL_SECONDS)
        except TimeoutError:
            if future.done():
                # A worker-raised TimeoutError is a task failure, not a poll.
                return future.result()
    return None


def _join_render_processes(processes, timeout):
    deadline = time.monotonic() + timeout
    for process in processes:
        process.join(timeout=max(0.0, deadline - time.monotonic()))


def _shutdown_render_pool(executor, pending, cancel_event):
    cancel_event.set()
    for _entry, future, _toggles in pending:
        if future is not None:
            future.cancel()
    # Python 3.11 has no public executor terminate_workers(). Snapshot only this
    # executor's processes before shutdown clears its references. Never wait
    # indefinitely for a chart/native call that cannot observe the shared event.
    processes = list((getattr(executor, '_processes', None) or {}).values())
    manager = getattr(executor, '_executor_manager_thread', None)
    executor.shutdown(wait=False, cancel_futures=True)
    _join_render_processes(processes, WORKER_EXIT_GRACE_SECONDS)
    for process in processes:
        if process.is_alive():
            process.terminate()
    _join_render_processes(processes, WORKER_STOP_GRACE_SECONDS)
    for process in processes:
        if process.is_alive():
            process.kill()
    _join_render_processes(processes, WORKER_STOP_GRACE_SECONDS)
    if manager is not None:
        manager.join(timeout=WORKER_STOP_GRACE_SECONDS)


class SummaryRenderPool:
    """Own one lazy, bounded render pool for all reference partitions in an export."""

    def __init__(self, owner, group_count):
        self.owner = owner
        self.policy = _pool_policy(owner, group_count)
        self.workers = render_workers(owner.chart_worker_count, group_count, cap=MAX_RENDER_WORKERS)
        self.bound = max(1, min(owner.chart_worker_queue_size, self.workers * 2))
        self.pending = deque()
        self.executor = None
        self.cancel_event = None
        self.closed = False
        self.telemetry = owner.completion_metadata.setdefault('summary_render_pool', {})
        self.telemetry.update(mode=self.policy, workers=0, max_pending=0, completed=0)

    def close(self):
        """Release only this export's workers, including stuck native chart calls."""
        self.closed = True
        if self.executor is not None:
            executor, self.executor = self.executor, None
            _shutdown_render_pool(executor, self.pending, self.cancel_event)
        self.pending.clear()

    def _ensure_executor(self):
        if self.executor is None:
            context = spawn_context()
            self.cancel_event = context.Event()
            self.executor = ProcessPoolExecutor(
                max_workers=self.workers, mp_context=context,
                initializer=_initialize_render_worker, initargs=(self.cancel_event,),
            )
            self.telemetry['workers'] = self.workers
        return self.executor

    def iter_results(self, entries):
        """Keep each reference's first group serial and replay remaining results in order.

        The parent applies the timing-driven density policy after every result.
        Results queued under an older policy are discarded by the collector.
        A failed pool stays serial for the rest of this export.
        """
        if self.closed or not entries:
            return
        if self.policy != 'spawn':
            for entry in entries:
                if self.owner._check_canceled():
                    return
                yield entry, None
            return
        yield entries[0], None
        remaining = iter(entries[1:])
        try:
            if self.owner._check_canceled() or len(entries) < 2:
                return
            executor = self._ensure_executor()
            yield from _collect_ordered(
                self.owner, remaining, self.pending, executor, self.bound,
                self.telemetry, self.cancel_event,
            )
        except Exception as exc:
            # Retain the uncollected entries before shutdown clears the queue.
            replay = [entry for entry, _future, _toggles in self.pending]
            self.close()
            self.closed = False
            self.policy = 'serial_pool_failure'
            self.telemetry.update(mode=self.policy, exception_class=type(exc).__name__)
            for entry in chain(replay, remaining):
                if self.owner._check_canceled():
                    return
                yield entry, None


def iter_summary_render_results(owner, entries, *, render_pool=None):
    """Use an export-owned pool, or a bounded standalone pool for direct callers."""
    session = render_pool if render_pool is not None else SummaryRenderPool(owner, len(entries))
    try:
        yield from session.iter_results(entries)
    finally:
        if render_pool is None:
            session.close()


def _collect_ordered(owner, remaining, pending, executor, bound, telemetry, cancel_event):
    exhausted = False
    while not exhausted or pending:
        if _render_canceled(owner, cancel_event):
            return
        while not exhausted and len(pending) < bound:
            if _render_canceled(owner, cancel_event):
                return
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
            result = _await_render_result(owner, future, cancel_event)
            if _render_canceled(owner, cancel_event):
                return
            pending.popleft()
            if toggles != owner._optimization_toggles:
                result = None
            else:
                telemetry['completed'] += 1
            yield entry, result


def apply_summary_render_result(owner, worksheet, result):
    """Replay ordered writes and account worker telemetry in the parent only."""
    image_buffers = {}
    for index, (operation, args) in enumerate(result['commands']):
        if operation == 'write':
            worksheet.write(*args)
        else:
            row, col, options, payload = args
            image_buffers[index] = owner._register_chart_image(payload)
            worksheet.insert_image(row, col, '', {
                **options, 'image_data': image_buffers[index],
            })
    for section in result.get('dashboard_sections', []):
        for chart in section['charts']:
            payload = chart['image_buffer']
            chart['image_buffer'] = (image_buffers[payload[1]] if isinstance(payload, tuple)
                                     and payload[0] == 'worksheet_image'
                                     else owner._register_chart_image(payload))
        owner._html_dashboard_sections.append(section)
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
