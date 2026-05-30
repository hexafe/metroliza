"""Compatibility shim for ``metroliza.parsing.parser_plugin_contracts``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.parsing.parser_plugin_contracts")
globals().update(_module.__dict__)
