"""Compatibility shim for ``metroliza.reports.db``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.reports.db")
globals().update(_module.__dict__)
