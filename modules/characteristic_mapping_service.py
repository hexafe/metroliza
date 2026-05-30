"""Compatibility shim for ``metroliza.reports.characteristic_mapping_service``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.reports.characteristic_mapping_service")
globals().update(_module.__dict__)
