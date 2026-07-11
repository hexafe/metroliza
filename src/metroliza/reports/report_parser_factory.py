"""Compatibility alias for :mod:`metroliza.parsing.report_parser_factory`.

Parser selection belongs to the parsing package.  Binding this historical import path to the
canonical module object preserves registry/cache identity for callers that still monkeypatch or
register parsers through ``metroliza.reports.report_parser_factory``.
"""

from importlib import import_module as _import_module
import sys as _sys


_module = _import_module("metroliza.parsing.report_parser_factory")
_sys.modules[__name__] = _module
globals().update(_module.__dict__)
