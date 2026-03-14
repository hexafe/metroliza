"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.license_key_manager``.
Legacy compatibility module: ``modules.LicenseKeyManager``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
from modules.license_key_manager import *  # noqa: F401,F403
