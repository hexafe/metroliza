"""Compatibility shim for ``metroliza.parsing.parse_reports_thread``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.parsing.parse_reports_thread")
globals().update(_module.__dict__)
