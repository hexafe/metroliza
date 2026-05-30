"""Compatibility shim for ``metroliza.parsing.llm_plugin_factory``."""

import sys

from modules.compat import alias_module as _alias_module

_legacy_name = __name__
_module = _alias_module(_legacy_name, "metroliza.parsing.llm_plugin_factory")
globals().update(_module.__dict__)
_scaffold = _alias_module(
    "modules.llm_plugin_factory.scaffold",
    "metroliza.parsing.llm_plugin_factory.scaffold",
)
setattr(_module, "scaffold", _scaffold)
sys.modules[_legacy_name] = _module
