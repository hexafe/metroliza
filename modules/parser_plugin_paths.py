"""Compatibility shim for ``metroliza.parsing.parser_plugin_paths``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.parsing.parser_plugin_paths")
globals().update(_module.__dict__)
