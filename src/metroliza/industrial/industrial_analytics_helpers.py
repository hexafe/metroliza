"""Shared formatting helpers for industrial and tabular analytics outputs."""

from __future__ import annotations

from typing import Any

import pandas as pd


def diagnostics_dataframe(diagnostics: tuple[Any, ...]) -> pd.DataFrame:
    """Return the standard Diagnostics workbook sheet payload."""
    if not diagnostics:
        return pd.DataFrame([{"severity": "info", "code": "ok", "message": "No diagnostics."}])
    return pd.DataFrame(
        [
            {
                "severity": diagnostic.severity,
                "code": diagnostic.code,
                "message": diagnostic.message,
                "context": diagnostic.context,
            }
            for diagnostic in diagnostics
        ]
    )


def format_time_bucket_label(value: Any, time_bucket: str) -> str:
    """Return the display label used for grouped time-bucket analytics."""
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(None)
    if time_bucket == "year":
        return timestamp.strftime("%Y")
    if time_bucket == "month":
        return timestamp.strftime("%Y-%m")
    if time_bucket == "day":
        return timestamp.strftime("%Y-%m-%d")
    if time_bucket == "week":
        return f"Week of {timestamp.strftime('%Y-%m-%d')}"
    if time_bucket == "hour":
        return timestamp.strftime("%Y-%m-%d %H:00")
    return timestamp.isoformat()
