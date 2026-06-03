#!/usr/bin/env python3
"""Summarize Metroliza startup profile JSONL files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _first_elapsed(events: list[dict[str, Any]], *names: str) -> float | None:
    wanted = set(names)
    for event in events:
        if event.get("name") in wanted:
            return float(event.get("elapsed_ms") or 0.0)
    return None


def summarize_startup_profile(path: Path) -> dict[str, Any]:
    events = _load_events(path)
    first_feedback_ms = _first_elapsed(events, "splash_shown")
    startup_feedback_decision_ms = _first_elapsed(
        events,
        "splash_shown",
        "splash_disabled",
        "splash_failed",
    )
    first_window_ms = _first_elapsed(events, "main_window_show_called")
    first_event_loop_tick_ms = _first_elapsed(events, "first_event_loop_tick")
    warmup_start_ms = _first_elapsed(events, "feature_warmup_start")
    warmup_done_ms = _first_elapsed(events, "feature_warmup_done")

    module_warmups = [
        {
            "label": event.get("label"),
            "module": event.get("module"),
            "status": event.get("status"),
            "elapsed_ms": float(event.get("elapsed_ms") or 0.0),
        }
        for event in events
        if event.get("name") == "feature_warmup_module_done"
    ]

    return {
        "event_count": len(events),
        "first_feedback_ms": first_feedback_ms,
        "startup_feedback_decision_ms": startup_feedback_decision_ms,
        "first_window_show_ms": first_window_ms,
        "first_event_loop_tick_ms": first_event_loop_tick_ms,
        "feature_warmup_ms": (
            None
            if warmup_start_ms is None or warmup_done_ms is None
            else max(0.0, warmup_done_ms - warmup_start_ms)
        ),
        "feature_warmup_modules": module_warmups,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path, help="Startup profile JSONL path")
    args = parser.parse_args()

    print(json.dumps(summarize_startup_profile(args.profile), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
