"""Compatibility shim for ``metroliza.charts.export_histogram_layout``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.export_histogram_layout")
globals().update(_module.__dict__)
