"""Earliest app-only hook; ordinary execution does not install an observer."""
import os

if os.environ.get("METROLIZA_WINDOWS_RUNTIME_AUDIT") == "1":
    from metroliza.shared.diagnostic_runtime_audit import install

    install()
