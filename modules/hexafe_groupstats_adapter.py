"""Compatibility shim for ``metroliza.analytics.hexafe_groupstats_adapter``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.analytics.hexafe_groupstats_adapter")
globals().update(_module.__dict__)
