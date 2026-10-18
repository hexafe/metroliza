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
