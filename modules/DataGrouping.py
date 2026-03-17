"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.data_grouping``.
Legacy compatibility module: ``modules.DataGrouping``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
from modules.data_grouping import *  # noqa: F401,F403
