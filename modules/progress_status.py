def build_three_line_status(stage_line, detail_line="", timing_line="ETA --"):
    """Return a consistent 3-line progress status block for modal progress labels."""
    normalized_stage = (stage_line or "Working...").strip()
    normalized_detail = (detail_line or "").strip() or "Status pending"
    normalized_timing = (timing_line or "").strip() or "ETA --"
    return f"{normalized_stage}\n{normalized_detail}\n{normalized_timing}"
