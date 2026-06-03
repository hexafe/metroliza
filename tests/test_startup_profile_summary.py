from __future__ import annotations

import json

from scripts.summarize_startup_profile import summarize_startup_profile


def test_summarize_startup_profile_reports_feedback_window_and_warmup(tmp_path):
    profile_path = tmp_path / "startup.jsonl"
    events = [
        {"name": "process_entry", "elapsed_ms": 1.0},
        {"name": "splash_shown", "elapsed_ms": 20.0},
        {"name": "main_window_show_called", "elapsed_ms": 120.0},
        {"name": "feature_warmup_start", "elapsed_ms": 140.0},
        {
            "name": "feature_warmup_module_done",
            "elapsed_ms": 150.0,
            "label": "Parse Reports",
            "module": "metroliza.ui.parsing_dialog",
            "status": "loaded",
        },
        {"name": "feature_warmup_done", "elapsed_ms": 240.0},
    ]
    profile_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events),
        encoding="utf-8",
    )

    summary = summarize_startup_profile(profile_path)

    assert summary["event_count"] == len(events)
    assert summary["first_feedback_ms"] == 20.0
    assert summary["startup_feedback_decision_ms"] == 20.0
    assert summary["first_window_show_ms"] == 120.0
    assert summary["feature_warmup_ms"] == 100.0
    assert summary["feature_warmup_modules"] == [
        {
            "label": "Parse Reports",
            "module": "metroliza.ui.parsing_dialog",
            "status": "loaded",
            "elapsed_ms": 150.0,
        }
    ]


def test_summarize_startup_profile_separates_disabled_splash_from_visual_feedback(tmp_path):
    profile_path = tmp_path / "startup.jsonl"
    events = [
        {"name": "splash_disabled", "elapsed_ms": 22.0},
        {"name": "main_window_show_called", "elapsed_ms": 110.0},
    ]
    profile_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events),
        encoding="utf-8",
    )

    summary = summarize_startup_profile(profile_path)

    assert summary["first_feedback_ms"] is None
    assert summary["startup_feedback_decision_ms"] == 22.0
