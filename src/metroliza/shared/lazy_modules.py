"""Lazy optional modules with one successful import per proxy instance."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any


class LazyModule:
    """Cache a module on first use while keeping its attributes live.

    Failed imports remain retryable. Attribute lookup is never cached, so module
    mutations and module-level ``__getattr__`` retain their normal behavior.
    Assigning an attribute on the proxy itself still overrides forwarding.
    """

    def __init__(self, module_name: str) -> None:
        self.__module_name = module_name
        self.__module: ModuleType | None = None

    def __getattr__(self, name: str) -> Any:
        module = self.__module
        if module is None:
            module = importlib.import_module(self.__module_name)
            self.__module = module
        return getattr(module, name)


class LazyPandas(LazyModule):
    """Pandas proxy that does not import pandas during construction."""

    def __init__(self) -> None:
        super().__init__("pandas")


class LazyNumpy(LazyModule):
    """NumPy proxy that does not import NumPy during construction."""

    def __init__(self) -> None:
        super().__init__("numpy")
