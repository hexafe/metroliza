"""Compatibility shim for ``metroliza.shared.progress_status``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.progress_status")
globals().update(_module.__dict__)
