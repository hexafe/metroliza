"""Compatibility shim for ``metroliza.exporting.google_drive_export``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.exporting.google_drive_export")
globals().update(_module.__dict__)
