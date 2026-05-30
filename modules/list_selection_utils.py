"""Compatibility shim for ``metroliza.shared.list_selection_utils``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.list_selection_utils")
globals().update(_module.__dict__)
