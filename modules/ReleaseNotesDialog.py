"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.release_notes_dialog``.
Legacy compatibility module: ``modules.ReleaseNotesDialog``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
from modules.release_notes_dialog import *  # noqa: F401,F403
