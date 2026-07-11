"""Compatibility and package-boundary tests for the deprecated BOM manager."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import warnings

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_all_bom_manager_import_paths_share_module_and_class_identity() -> None:
    canonical = importlib.import_module("metroliza.ui.bom_manager")
    shared_compat = importlib.import_module("metroliza.shared.bom_manager")
    legacy_compat = importlib.import_module("modules.bom_manager")

    assert shared_compat is canonical
    assert legacy_compat is canonical
    assert shared_compat.BOMManager is canonical.BOMManager
    assert legacy_compat.BOMManager is canonical.BOMManager


def test_compatibility_alias_preserves_mutable_module_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    canonical = importlib.import_module("metroliza.ui.bom_manager")
    shared_compat = importlib.import_module("metroliza.shared.bom_manager")
    replacement = object()

    monkeypatch.setattr(shared_compat, "QMessageBox", replacement)

    assert canonical.QMessageBox is replacement


def test_bom_manager_deprecation_warning_is_emitted_once_per_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("metroliza.ui.bom_manager")
    monkeypatch.setattr(module, "_DEPRECATION_WARNING_EMITTED", False)

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        module._warn_deprecated_bom_manager()
        module._warn_deprecated_bom_manager()

    matching = [item for item in captured if str(item.message) == module.DEPRECATION_NOTICE]
    assert len(matching) == 1
    assert matching[0].category is DeprecationWarning


def test_bom_manager_compatibility_aliases_resolve_in_a_fresh_interpreter() -> None:
    script = "\n".join(
        [
            "import importlib",
            "shared = importlib.import_module('metroliza.shared.bom_manager')",
            "legacy = importlib.import_module('modules.bom_manager')",
            "canonical = importlib.import_module('metroliza.ui.bom_manager')",
            "assert shared is legacy is canonical",
            "assert shared.BOMManager is canonical.BOMManager",
        ]
    )

    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": f"{REPO_ROOT / 'src'}{os.pathsep}{REPO_ROOT}",
            "QT_QPA_PLATFORM": "offscreen",
        },
    )
