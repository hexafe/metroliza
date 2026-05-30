"""Compatibility shim for ``metroliza.parsing.cmm_parsing``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.parsing.cmm_parsing")
globals().update(_module.__dict__)
