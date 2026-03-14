"""Pure helpers for export progress and status label messaging."""

from modules.progress_status import build_three_line_status


def clamp_progress(value):
    """Clamp arbitrary progress values to the inclusive ``[0, 100]`` range."""
    return max(0, min(100, int(round(value))))


def compute_stage_progress(stage_ranges, stage_name, *, fraction=1.0):
    """Map a stage/fraction pair into an absolute progress percentage."""
    start, end = stage_ranges[stage_name]
    safe_fraction = max(0.0, min(1.0, float(fraction)))
    return start + ((end - start) * safe_fraction)


def format_elapsed_or_eta(seconds):
    """Format elapsed/ETA seconds as ``M:SS`` or ``H:MM:SS``."""
    safe_seconds = max(0, int(seconds))
    minutes, remaining_seconds = divmod(safe_seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{remaining_minutes:02d}:{remaining_seconds:02d}"
    return f"{remaining_minutes:d}:{remaining_seconds:02d}"


def build_measurement_status_label(
    *,
    ref_index,
    total_references,
    completed_header_units,
    total_header_units,
    elapsed_seconds,
):
    """Build three-line measurement-stage status text with adaptive ETA display."""
    stage_line = "Building measurement sheets..."
    if total_header_units <= 0:
        detail_line = f"Ref {ref_index}/{total_references}, Headers remaining 0"
        return build_three_line_status(stage_line, detail_line, "ETA --")

    remaining_headers = max(0, total_header_units - completed_header_units)
    detail_line = (
        f"Ref {ref_index}/{total_references}, "
        f"Headers remaining {remaining_headers}/{total_header_units}"
    )

    if completed_header_units < 5 or elapsed_seconds < 2.0:
        return build_three_line_status(stage_line, detail_line, "ETA --")

    headers_per_second = completed_header_units / elapsed_seconds if elapsed_seconds > 0 else 0.0
    if headers_per_second <= 0:
        return build_three_line_status(stage_line, detail_line, "ETA --")

    eta_seconds = remaining_headers / headers_per_second
    elapsed_display = format_elapsed_or_eta(elapsed_seconds)
    eta_display = format_elapsed_or_eta(eta_seconds)
    eta_line = f"{elapsed_display} elapsed, ETA {eta_display}"
    return build_three_line_status(stage_line, detail_line, eta_line)
