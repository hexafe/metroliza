"""Optional-import protocol and migration contracts."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from metroliza.shared.lazy_modules import LazyModule, LazyNumpy, LazyPandas


@pytest.fixture(params=[(LazyPandas, "pandas"), (LazyNumpy, "numpy")])
def proxy_case(request):
    return request.param


def test_first_access_imports_once_and_preserves_live_attributes(monkeypatch, proxy_case):
    factory, module_name = proxy_case
    module = ModuleType(module_name)
    original, replacement = object(), object()
    module.value = original
    calls = []

    def importer(name):
        calls.append(name)
        return module

    monkeypatch.setattr(importlib, "import_module", importer)
    proxy = factory()
    assert calls == []
    assert proxy.value is original
    assert proxy.value is original
    module.value = replacement
    assert proxy.value is replacement
    proxy.value = original
    assert proxy.value is original
    del proxy.value
    assert proxy.value is replacement
    assert calls == [module_name]


def test_missing_and_dynamic_attributes_keep_errors_and_callbacks(monkeypatch, proxy_case):
    factory, module_name = proxy_case
    module = ModuleType(module_name)
    monkeypatch.setattr(importlib, "import_module", lambda name: module)
    proxy = factory()
    for _ in range(2):
        with pytest.raises(AttributeError, match=f"module '{module_name}' has no attribute 'missing'"):
            proxy.missing
    module.missing = object()
    assert proxy.missing is module.missing
    calls = []
    error = ValueError("dynamic failure")

    def dynamic(name):
        calls.append(name)
        raise error

    module.__getattr__ = dynamic
    for _ in range(2):
        with pytest.raises(ValueError) as caught:
            proxy.dynamic
        assert caught.value is error
    assert calls == ["dynamic", "dynamic"]


@pytest.mark.parametrize("error", [ModuleNotFoundError("optional"), RuntimeError("broken")])
def test_failed_import_retries_without_swallowing_error(monkeypatch, proxy_case, error):
    factory, module_name = proxy_case
    module = ModuleType(module_name)
    module.value = object()
    calls = []

    def importer(name):
        calls.append(name)
        if len(calls) == 1:
            raise error
        return module

    monkeypatch.setattr(importlib, "import_module", importer)
    proxy = factory()
    with pytest.raises(type(error)) as caught:
        proxy.value
    assert caught.value is error
    assert proxy.value is module.value
    assert proxy.value is module.value
    assert calls == [module_name, module_name]


def test_generic_module_proxy_and_instances_are_independent(monkeypatch):
    first, second = ModuleType("first"), ModuleType("second")
    first.value, second.value = object(), object()
    modules = {"first": first, "second": second}
    calls = []

    def importer(name):
        calls.append(name)
        return modules[name]

    monkeypatch.setattr(importlib, "import_module", importer)
    a, b = LazyModule("first"), LazyModule("second")
    assert a.value is first.value
    assert b.value is second.value
    assert a.value is first.value
    assert calls == ["first", "second"]


def test_import_and_construction_keep_optional_modules_unloaded():
    root = Path(__file__).resolve().parents[1]
    script = """
import sys
from metroliza.shared.lazy_modules import LazyModule, LazyNumpy, LazyPandas
proxies = [LazyModule('scipy'), LazyNumpy(), LazyPandas()]
assert not {'pandas', 'numpy', 'scipy'}.intersection(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "module_name",
    [
        "ui.tabular_analytics_grouping_dialog",
        "ui.tabular_analytics_filter_dialog",
        "tabular.tabular_analytics_service",
        "tabular.data_grouping_service",
        "tabular.csv_summary_utils",
        "shared.grouping_filter_core",
        "industrial.industrial_tabular_bridge",
        "industrial.industrial_export_service",
        "industrial.industrial_analytics_workbook_charts",
        "industrial.industrial_analytics_workbook",
        "industrial.industrial_analytics_service",
        "industrial.industrial_analytics_dashboard",
    ],
)
def test_existing_proxies_use_shared_implementation(module_name):
    module = importlib.import_module(f"metroliza.{module_name}")
    assert module._LazyPandas is LazyPandas
    assert isinstance(module.pd, LazyPandas)
    if module_name == "tabular.data_grouping_service":
        assert module._LazyNumpy is LazyNumpy
        assert isinstance(module.np, LazyNumpy)
