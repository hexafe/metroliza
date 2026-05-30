"""Compatibility shim for ``metroliza.reports.cmm_schema``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.reports.cmm_schema")
globals().update(_module.__dict__)
