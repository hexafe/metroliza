"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.parsing_dialog``.
Legacy compatibility module: ``modules.ParsingDialog``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
from modules.parsing_dialog import *  # noqa: F401,F403
