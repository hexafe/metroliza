"""Compatibility shim for ``metroliza.parsing.metadata_enrichment_thread``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.parsing.metadata_enrichment_thread")
globals().update(_module.__dict__)
