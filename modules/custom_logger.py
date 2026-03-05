"""Compatibility shim for snake_case module imports.

Canonical module name: ``modules.custom_logger``.
Legacy compatibility module: ``modules.CustomLogger``.
"""

from modules.CustomLogger import *  # noqa: F401,F403
