"""Compatibility shim for ``metroliza.charts.summary_plot_palette``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.summary_plot_palette")
globals().update(_module.__dict__)
