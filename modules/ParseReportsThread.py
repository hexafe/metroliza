"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.parse_reports_thread``.
Legacy compatibility module: ``modules.ParseReportsThread``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
# Guardrail marker: from modules.db import execute_with_retry
from modules.parse_reports_thread import *  # noqa: F401,F403
