"""Realtime Oznak adapter boundary."""

from __future__ import annotations

from metroliza.industrial.realtime.oznak_source_adapter import OznakRealtimeSourceAdapter

OznakSqlSourceDbReader = OznakRealtimeSourceAdapter

__all__ = ["OznakRealtimeSourceAdapter", "OznakSqlSourceDbReader"]
