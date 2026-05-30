"""Compatibility shim for ``metroliza.charts.hexafe_plotstats_adapter``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.charts.hexafe_plotstats_adapter")
globals().update(_module.__dict__)
