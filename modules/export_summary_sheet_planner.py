"""Compatibility shim for ``metroliza.exporting.export_summary_sheet_planner``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.exporting.export_summary_sheet_planner")
globals().update(_module.__dict__)
