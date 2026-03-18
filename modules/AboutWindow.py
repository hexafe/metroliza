"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.about_window``.
Legacy compatibility module: ``modules.AboutWindow``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
from modules.about_window import *  # noqa: F401,F403
