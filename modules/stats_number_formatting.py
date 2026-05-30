"""Compatibility shim for ``metroliza.shared.stats_number_formatting``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.stats_number_formatting")
globals().update(_module.__dict__)
