"""Compatibility shim for ``metroliza.charts.export_chart_payload_helpers``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.export_chart_payload_helpers")
globals().update(_module.__dict__)
