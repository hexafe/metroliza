"""Compatibility shim for ``metroliza.industrial.industrial_analytics_workbook_charts``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.industrial.industrial_analytics_workbook_charts")
globals().update(_module.__dict__)
