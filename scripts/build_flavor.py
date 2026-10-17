"""Packaged build flavor selection shared by packaging scripts and validators."""

from __future__ import annotations

import os
from typing import Mapping

BUILD_FLAVOR_ENV = "METROLIZA_BUILD_FLAVOR"
USER_BUILD_FLAVOR = "user"
BENCHMARK_BUILD_FLAVOR = "benchmark"
BUILD_FLAVORS = (USER_BUILD_FLAVOR, BENCHMARK_BUILD_FLAVOR)


def resolve_build_flavor(env: Mapping[str, str] | None = None) -> str:
    """Return the requested build flavor; unset or blank means the user build."""

    source = os.environ if env is None else env
    value = (source.get(BUILD_FLAVOR_ENV) or "").strip().lower()
    if not value:
        return USER_BUILD_FLAVOR
    if value not in BUILD_FLAVORS:
        allowed = ", ".join(BUILD_FLAVORS)
        raise ValueError(f"Unsupported {BUILD_FLAVOR_ENV} {value!r}; expected one of: {allowed}.")
    return value


def flavor_includes_openvino(flavor: str) -> bool:
    """OpenVINO ships only in the explicitly named benchmark flavor."""

    return flavor == BENCHMARK_BUILD_FLAVOR
