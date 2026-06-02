from typing import Any


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


def clamp_progress(value) -> int:
    """Clamp a numeric progress value into the 0-100 percent range."""
    return max(0, min(100, int(round(value))))


class MonotonicProgressEmitterMixin:
    """Mixin for Qt workers that expose an ``update_progress`` signal."""

    @staticmethod
    def _clamp_progress(value) -> int:
        return clamp_progress(value)

    def _emit_progress(self, value) -> None:
        clamped_value = self._clamp_progress(value)
        last_emitted_progress = getattr(self, "_last_emitted_progress", -1)
        progress_value = max(clamped_value, last_emitted_progress)
        if progress_value == last_emitted_progress:
            return
        self._last_emitted_progress = progress_value
        self.update_progress.emit(progress_value)


def diagnostic_progress_message(diagnostic: Any) -> str:
    """Return a user-safe one-line progress message from an adapter diagnostic."""
    message = getattr(diagnostic, "message", None)
    if not message:
        source = getattr(diagnostic, "source_alias", "")
        status = getattr(getattr(diagnostic, "status", None), "value", None) or getattr(
            diagnostic,
            "status",
            "",
        )
        message = f"{source}: {status}".strip(": ")
    return str(message)
