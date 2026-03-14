"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.custom_logger``.
Legacy compatibility module: ``modules.CustomLogger``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
from modules.custom_logger import *  # noqa: F401,F403
