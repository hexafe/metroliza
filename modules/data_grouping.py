"""Compatibility shim for ``metroliza.ui.data_grouping``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.ui.data_grouping")
globals().update(_module.__dict__)
