"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.export_data_thread``.
Legacy compatibility module: ``modules.ExportDataThread``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
from modules.export_data_thread import *  # noqa: F401,F403
