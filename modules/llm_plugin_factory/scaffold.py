"""Compatibility shim for ``metroliza.parsing.llm_plugin_factory.scaffold``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.parsing.llm_plugin_factory.scaffold")
globals().update(_module.__dict__)
