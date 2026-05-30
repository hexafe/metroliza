"""Compatibility shim for ``metroliza.tabular.tabular_column_selection``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.tabular.tabular_column_selection")
globals().update(_module.__dict__)
