"""Compatibility shim for ``metroliza.charts.distribution_iqr_plotly_specs``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.distribution_iqr_plotly_specs")
globals().update(_module.__dict__)
