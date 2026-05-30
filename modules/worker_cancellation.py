"""Compatibility shim for ``metroliza.shared.worker_cancellation``."""

from modules.compat import alias_module as _alias_module

_module = _alias_module(__name__, "metroliza.shared.worker_cancellation")
globals().update(_module.__dict__)
