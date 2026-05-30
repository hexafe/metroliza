"""Compatibility shim for ``metroliza.resources.base64_encoded_files``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.resources.base64_encoded_files")
globals().update(_module.__dict__)
