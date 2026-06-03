from __future__ import annotations

import os
import sys
import types

from modules import matplotlib_runtime


def test_configure_headless_matplotlib_sets_writable_config_before_backend_use(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("MPLBACKEND", raising=False)
    monkeypatch.delenv("MPLCONFIGDIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    captured: dict[str, object] = {}

    def _use(backend: str, *, force: bool = False) -> None:
        captured["backend"] = backend
        captured["force"] = force
        captured["mplconfigdir"] = os.environ.get("MPLCONFIGDIR")

    monkeypatch.setitem(sys.modules, "matplotlib", types.SimpleNamespace(use=_use))

    matplotlib_runtime.configure_headless_matplotlib(cache_dir_name="mpl-cache")

    expected_cache = str(tmp_path / "Metroliza" / "mpl-cache")
    assert os.environ["MPLBACKEND"] == "Agg"
    assert os.environ["MPLCONFIGDIR"] == expected_cache
    assert captured == {
        "backend": "Agg",
        "force": True,
        "mplconfigdir": expected_cache,
    }


def test_configure_headless_matplotlib_respects_existing_config_dir(
    monkeypatch,
    tmp_path,
) -> None:
    existing_cache = tmp_path / "existing-mpl"
    monkeypatch.delenv("MPLBACKEND", raising=False)
    monkeypatch.setenv("MPLCONFIGDIR", str(existing_cache))

    captured: dict[str, object] = {}

    def _use(backend: str, *, force: bool = False) -> None:
        captured["backend"] = backend
        captured["force"] = force
        captured["mplconfigdir"] = os.environ.get("MPLCONFIGDIR")

    monkeypatch.setitem(sys.modules, "matplotlib", types.SimpleNamespace(use=_use))

    matplotlib_runtime.configure_headless_matplotlib(cache_dir_name="unused-cache")

    assert os.environ["MPLBACKEND"] == "Agg"
    assert os.environ["MPLCONFIGDIR"] == str(existing_cache)
    assert captured == {
        "backend": "Agg",
        "force": True,
        "mplconfigdir": str(existing_cache),
    }


def test_configure_headless_matplotlib_uses_temp_fallback_when_default_is_unwritable(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("MPLBACKEND", raising=False)
    monkeypatch.delenv("MPLCONFIGDIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "blocked"))

    checked_paths = []

    def _is_writable_directory(path):
        checked_paths.append(path)
        return len(checked_paths) > 1

    captured: dict[str, object] = {}

    def _use(backend: str, *, force: bool = False) -> None:
        captured["backend"] = backend
        captured["force"] = force
        captured["mplconfigdir"] = os.environ.get("MPLCONFIGDIR")

    monkeypatch.setattr(matplotlib_runtime, "_is_writable_directory", _is_writable_directory)
    monkeypatch.setattr(matplotlib_runtime.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    monkeypatch.setitem(sys.modules, "matplotlib", types.SimpleNamespace(use=_use))

    matplotlib_runtime.configure_headless_matplotlib(cache_dir_name="mpl-cache")

    expected_cache = str(tmp_path / "tmp" / "metroliza" / "mpl-cache")
    assert os.environ["MPLBACKEND"] == "Agg"
    assert os.environ["MPLCONFIGDIR"] == expected_cache
    assert captured == {
        "backend": "Agg",
        "force": True,
        "mplconfigdir": expected_cache,
    }
