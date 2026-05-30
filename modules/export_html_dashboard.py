"""Compatibility shim for ``metroliza.charts.export_html_dashboard``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.export_html_dashboard")
globals().update(_module.__dict__)
