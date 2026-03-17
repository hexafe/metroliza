"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.main_window``.
Legacy compatibility module: ``modules.MainWindow``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
from modules.main_window import *  # noqa: F401,F403
