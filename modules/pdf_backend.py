"""Compatibility shim for ``metroliza.parsing.pdf_backend``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.parsing.pdf_backend")
globals().update(_module.__dict__)
