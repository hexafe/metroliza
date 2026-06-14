"""Lazy import helpers for optional ML anomaly detector dependencies."""

from __future__ import annotations

import importlib
from types import ModuleType

ANOMALY_REQUIREMENTS_FILE = "requirements-anomaly.txt"


class OptionalAnomalyDependencyError(ImportError):
    """Raised when an opt-in anomaly dependency is requested but unavailable."""


class OptionalDependencyUnavailable(OptionalAnomalyDependencyError):
    """Backward-compatible name for optional anomaly dependency failures."""


def _dependency_name(
    module_name: str,
    package_name: str | None,
    package_hint: str | None,
) -> str:
    return package_name or package_hint or module_name.split(".", maxsplit=1)[0]


def import_optional_dependency(
    module_name: str,
    *,
    package_name: str | None = None,
    package_hint: str | None = None,
    purpose: str = "ML-backed industrial anomaly detection",
) -> ModuleType:
    """Import an optional anomaly dependency only when a caller needs it."""

    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        package = _dependency_name(module_name, package_name, package_hint)
        missing_name = getattr(exc, "name", None) or module_name
        raise OptionalDependencyUnavailable(
            f"Optional anomaly dependency '{package}' is required for {purpose}. "
            f"Install optional ML dependencies with "
            f"`python -m pip install -r {ANOMALY_REQUIREMENTS_FILE}`. "
            f"Missing Python module: {missing_name}."
        ) from exc


def optional_dependency_available(module_name: str) -> bool:
    """Return whether an optional dependency can be imported."""

    try:
        importlib.import_module(module_name)
    except ImportError:
        return False
    return True


def import_sklearn() -> ModuleType:
    """Return the lazily imported scikit-learn package."""

    return import_optional_dependency(
        "sklearn",
        package_name="scikit-learn",
        purpose="scikit-learn anomaly detectors",
    )


def import_river() -> ModuleType:
    """Return the lazily imported river package."""

    return import_optional_dependency(
        "river",
        package_name="river",
        purpose="river streaming anomaly detectors",
    )


def load_sklearn_ensemble() -> ModuleType:
    """Load sklearn.ensemble lazily for optional isolation-forest models."""

    return import_optional_dependency(
        "sklearn.ensemble",
        package_name="scikit-learn",
        purpose="scikit-learn isolation-forest anomaly detectors",
    )


def load_river_drift() -> ModuleType:
    """Load river.drift lazily for optional online drift detectors."""

    return import_optional_dependency(
        "river.drift",
        package_name="river",
        purpose="river online drift detectors",
    )


__all__ = [
    "ANOMALY_REQUIREMENTS_FILE",
    "OptionalAnomalyDependencyError",
    "OptionalDependencyUnavailable",
    "import_optional_dependency",
    "import_river",
    "import_sklearn",
    "load_river_drift",
    "load_sklearn_ensemble",
    "optional_dependency_available",
]
