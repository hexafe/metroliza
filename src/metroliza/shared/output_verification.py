"""Metadata-only output receipts, without opening generated content."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from metroliza.shared.safe_bugreport_context import OutputVerificationKind


class OutputVerificationError(RuntimeError):
    """Raised when a generated output cannot be confirmed as nonempty."""


def _is_nonempty_file(output_file: str | Path) -> bool:
    path = Path(output_file)
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def require_nonempty_output_file(output_file: str | Path) -> None:
    """Guard staged output before replacing a previously completed file."""
    if not _is_nonempty_file(output_file):
        raise OutputVerificationError("Output file is missing or empty.")


def verify_published_output(
    output_file: str | Path,
    kind: OutputVerificationKind,
    *,
    operation_id: UUID | None = None,
) -> None:
    """Require a nonempty final file and record only a closed kind and verdict."""
    passed = _is_nonempty_file(output_file)
    try:
        from metroliza.shared.safe_bugreport import recorder

        recorder.record_output_verification(
            kind, passed,
            operation_id=operation_id if type(operation_id) is UUID else None,
        )
    except Exception:
        # Observation must not turn a valid output into a workflow failure.
        pass
    if not passed:
        raise OutputVerificationError("Published output file is missing or empty.")
