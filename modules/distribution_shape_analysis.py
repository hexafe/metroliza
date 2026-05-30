"""Compatibility shim for ``metroliza.analytics.distribution_shape_analysis``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.analytics.distribution_shape_analysis")
globals().update(_module.__dict__)
