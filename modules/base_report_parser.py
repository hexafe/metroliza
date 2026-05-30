"""Compatibility shim for ``metroliza.parsing.base_report_parser``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.parsing.base_report_parser")
globals().update(_module.__dict__)
