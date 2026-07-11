"""Validation helpers for the checked-in Google OAuth credential template."""

from __future__ import annotations

import json
from pathlib import Path


EXAMPLE_GOOGLE_CREDENTIALS_PATH = Path("config/google/credentials.example.json")


def validate_example_credentials_template_hygiene(
    path: str | Path = EXAMPLE_GOOGLE_CREDENTIALS_PATH,
) -> None:
    """Fail when the public OAuth example is incomplete or contains secret material."""

    template_path = Path(path)
    payload_text = template_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    installed = payload.get("installed")
    if not isinstance(installed, dict):
        raise AssertionError("Missing 'installed' OAuth section in credentials example template.")

    for key in ("client_id", "client_secret", "auth_uri", "token_uri"):
        if key not in installed:
            raise AssertionError(f"Missing required OAuth field in credentials template: {key}")

    if "YOUR_CLIENT_ID" not in str(installed["client_id"]):
        raise AssertionError("credentials.example.json must keep redacted client_id placeholder.")
    if "YOUR_CLIENT_SECRET" not in str(installed["client_secret"]):
        raise AssertionError("credentials.example.json must keep redacted client_secret placeholder.")
    if "AIza" in payload_text:
        raise AssertionError("credentials.example.json contains a real-looking API key prefix.")

    for disallowed_key in ("access_token", "refresh_token", "expires_at"):
        if disallowed_key in payload_text:
            raise AssertionError(
                f"credentials.example.json must not include runtime token key: {disallowed_key}"
            )


__all__ = [
    "EXAMPLE_GOOGLE_CREDENTIALS_PATH",
    "validate_example_credentials_template_hygiene",
]
