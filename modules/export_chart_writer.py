"""Compatibility shim for ``metroliza.charts.export_chart_writer``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.export_chart_writer")
globals().update(_module.__dict__)
