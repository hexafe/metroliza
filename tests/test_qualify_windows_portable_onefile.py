from __future__ import annotations

from pathlib import Path

import pytest

from scripts import qualify_windows_portable_onefile as qualify

RUNTIME = "2026.09rc1_260927-0123456789ab_89abcdef"


def test_expect_cache_checks_the_last_launcher_outcome(tmp_path: Path) -> None:
    log = tmp_path / "launcher.log"
    log.write_text("cache=cold\nentry=started\nexit=0\n", encoding="utf-8")
    qualify._expect_cache(log, "cold")
    with pytest.raises(RuntimeError, match="launcher_cache_warm_expected"):
        qualify._expect_cache(log, "warm")
    log.write_text("cache=warm\ncache=repair\n", encoding="utf-8")
    qualify._expect_cache(log, "repair")
    with pytest.raises(RuntimeError, match="launcher_cache_warm_expected_got_none"):
        qualify._expect_cache(tmp_path / "missing.log", "warm")


def _runtime(root: Path, name: str = RUNTIME, marker: str | None = "hash") -> None:
    (root / name).mkdir(parents=True)
    if marker is not None:
        (root / name / ".complete").write_text(marker + "\n", encoding="utf-8")


def test_runtime_layout_accepts_one_complete_content_keyed_directory(tmp_path: Path) -> None:
    _runtime(tmp_path)
    (tmp_path / f"{RUNTIME}.use").write_text("", encoding="utf-8")
    (tmp_path / ".extract.lock").write_text("", encoding="utf-8")
    assert qualify._runtime_layout(tmp_path) == RUNTIME


def test_semver_runtime_keeps_full_label_and_content_key(tmp_path: Path) -> None:
    name = "0.8.0-dev.1-0123456789ab_89abcdef"
    _runtime(tmp_path, name=name)
    assert qualify._runtime_layout(tmp_path) == name
    (tmp_path / name).rename(tmp_path / (name + "private"))
    with pytest.raises(RuntimeError, match="expected_one_runtime_directory"):
        qualify._runtime_layout(tmp_path)


@pytest.mark.parametrize(
    "build,fragment",
    [
        (lambda r: None, "runtime_root_missing"),
        (lambda r: _runtime(r, marker=None), "completion_marker_missing"),
        (lambda r: _runtime(r, name="2026.09rc1_260927_01234567"), "expected_one_runtime_directory"),
        (lambda r: (_runtime(r), _runtime(r, name=RUNTIME.replace("0123", "4567"))),
         "expected_one_runtime_directory"),
    ],
)
def test_runtime_layout_rejects_missing_unkeyed_or_duplicate_runtimes(
    tmp_path: Path, build, fragment: str
) -> None:
    root = tmp_path / "runtime"
    if fragment != "runtime_root_missing":
        root.mkdir()
        build(root)
    with pytest.raises(RuntimeError, match=fragment):
        qualify._runtime_layout(root)


def test_runtime_layout_rejects_a_leftover_staging_directory(tmp_path: Path) -> None:
    _runtime(tmp_path)
    (tmp_path / f"{RUNTIME}.staging-4242").mkdir()
    with pytest.raises(RuntimeError, match="staging_directory_remained"):
        qualify._runtime_layout(tmp_path)


def test_failure_detail_reports_only_bounded_fixed_fields(tmp_path: Path) -> None:
    (tmp_path / "failure.json").write_text(
        '{"schema_version": 1, "stage": "preview", "reason": "qualification_export_unavailable", '
        '"cleanup": "complete", "secret": "C:/Users/someone/x"}',
        encoding="ascii",
    )
    log = tmp_path / "launcher.log"
    log.write_text(
        "cache=warm\nentry=started\nerror=Extraction C:/private/path\nexit=21\n",
        encoding="utf-8",
    )
    detail = qualify._failure_detail(tmp_path, log)
    assert detail == (
        "stage=preview;reason=qualification_export_unavailable;cleanup=complete;"
        "cache=warm;entry=started;exit=21"
    )
    assert "private" not in detail and "someone" not in detail


def test_failure_detail_survives_a_missing_or_garbled_receipt(tmp_path: Path) -> None:
    assert qualify._failure_detail(tmp_path) == "no_failure_receipt"
    (tmp_path / "failure.json").write_text("{not json", encoding="ascii")
    assert qualify._failure_detail(tmp_path) == "no_failure_receipt"


@pytest.mark.parametrize("frame_pid,error,frame_time,expected", [
    (42, 0.0, 120, True),
    (91, 0.0, 120, False),
    (42, 20.0, 120, False),
    (42, 0.0, 220, False),
])
def test_splash_receipt_requires_desktop_artwork_before_portable_entry(frame_pid, error, frame_time, expected):
    windows = [
        {"epoch_ms": 120, "windows": [{"pid": 42, "kind": "bootloader_splash"}]},
        {"epoch_ms": 400, "windows": [{"pid": 43, "kind": "main_window"}]},
    ]
    frames = [{"epoch_ms": frame_time, "bootloader_pid": frame_pid, "bootloader_image_error": error}]
    events = [
        {"epoch_ms": 200, "name": "portable_python_entry"},
        {"epoch_ms": 250, "name": "bootloader_splash_closed", "phase": "portable_handoff"},
        {"epoch_ms": 425, "name": "splash_finished_after_first_paint"},
    ]
    observation = qualify._splash_observations(
        windows, frames, events, {"launched_epoch_ms": 100, "process_id": 42, "status": "ok"},
    )

    assert observation["passed"] is expected
    assert observation["bootloader_visible_ms"] == [20.0]
    assert observation["splash_close_requested_ms"] == 150.0
    assert observation["first_qt_window_ms"] == 300.0
    assert observation["splash_to_qt_first_window_ms"] == 280.0

    # A matching frame at startup cannot pass if the splash vanished during verification.
    events[1]["epoch_ms"] = 600
    events[2]["epoch_ms"] = 640
    assert not qualify._splash_observations(
        windows, frames, events, {"launched_epoch_ms": 100, "process_id": 42, "status": "ok"},
    )["passed"]


def test_splash_image_comparison_rejects_a_blank_window():
    from PIL import Image
    from scripts.measure_windows_first_run_timeline import splash_image_error

    artwork = Path(__file__).resolve().parents[1] / "packaging" / "metroliza_bootloader_splash.png"
    with Image.open(artwork) as image:
        assert splash_image_error(image, artwork) == 0.0
        assert splash_image_error(Image.new("RGB", image.size), artwork) > 6.0
        assert splash_image_error(Image.new("RGB", image.size, (48, 48, 48)), artwork) > 6.0
