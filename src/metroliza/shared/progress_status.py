def build_three_line_status(stage_line, detail_line="", timing_line="ETA --"):
    """Return a consistent 3-line progress status block for modal progress labels."""
    normalized_stage = (stage_line or "Working...").strip()
    normalized_detail = (detail_line or "").strip() or "Status pending"
    normalized_timing = (timing_line or "").strip() or "ETA --"
    return f"{normalized_stage}\n{normalized_detail}\n{normalized_timing}"


def format_progress_duration(seconds):
    """Return a compact M:SS or H:MM:SS duration for progress labels."""
    safe_seconds = max(0, int(seconds))
    minutes, remaining_seconds = divmod(safe_seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{remaining_minutes:02d}:{remaining_seconds:02d}"
    return f"{remaining_minutes:d}:{remaining_seconds:02d}"
