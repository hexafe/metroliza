"""Compatibility shim for ``metroliza.shared.grouping_filter_core``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.grouping_filter_core")
globals().update(_module.__dict__)
