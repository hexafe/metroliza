"""Compatibility shim for ``metroliza.reports.header_ocr_corrections``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.reports.header_ocr_corrections")
globals().update(_module.__dict__)
