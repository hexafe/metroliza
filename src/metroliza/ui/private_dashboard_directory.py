"""Compatibility import for the shared pinned private-directory primitive."""

from metroliza.shared.private_temporary_directory import (
    PrivateDashboardDirectoryError,
    create_private_dashboard_directory,
)

__all__ = ["PrivateDashboardDirectoryError", "create_private_dashboard_directory"]
