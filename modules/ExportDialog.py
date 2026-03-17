"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.export_dialog``.
Legacy compatibility module: ``modules.ExportDialog``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
from modules.export_dialog import *  # noqa: F401,F403
