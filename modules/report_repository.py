"""Compatibility shim for ``metroliza.reports.report_repository``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.reports.report_repository")
globals().update(_module.__dict__)
