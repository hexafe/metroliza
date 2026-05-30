"""Compatibility shim for ``metroliza.exporting.export_summary_composition_service``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.exporting.export_summary_composition_service")
globals().update(_module.__dict__)
