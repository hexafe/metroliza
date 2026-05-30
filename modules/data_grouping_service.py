"""Compatibility shim for ``metroliza.tabular.data_grouping_service``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.tabular.data_grouping_service")
globals().update(_module.__dict__)
