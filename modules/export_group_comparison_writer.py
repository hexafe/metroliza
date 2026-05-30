"""Compatibility shim for ``metroliza.exporting.export_group_comparison_writer``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.exporting.export_group_comparison_writer")
globals().update(_module.__dict__)
