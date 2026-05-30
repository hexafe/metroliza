"""Compatibility shim for ``metroliza.exporting.export_dialog_service``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.exporting.export_dialog_service")
globals().update(_module.__dict__)
