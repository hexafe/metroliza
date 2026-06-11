"""Local user credential storage for Oznak industrial database access."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex


DEFAULT_INDUSTRIAL_CREDENTIAL_PATH = Path.home() / ".metroliza" / "industrial_credentials.env"
_ENV_PREFIX = "METROLIZA_INDUSTRIAL"


@dataclass(frozen=True)
class IndustrialStoredCredentials:
    """Credentials loaded from environment variables or the local user env file."""

    username: str = ""
    password: str = ""
    source: str = ""

    @property
    def has_values(self) -> bool:
        return bool(self.username or self.password)


def default_industrial_credential_path() -> Path:
    """Return the local, user-only credential env file path."""

    return DEFAULT_INDUSTRIAL_CREDENTIAL_PATH


def credential_env_keys(profile_key: str) -> tuple[str, str]:
    """Return deterministic env variable names for one production source profile."""

    suffix = re.sub(r"[^A-Za-z0-9]+", "_", str(profile_key or "").strip().upper()).strip("_")
    if not suffix:
        suffix = "DEFAULT"
    return (f"{_ENV_PREFIX}_{suffix}_USERNAME", f"{_ENV_PREFIX}_{suffix}_PASSWORD")


def load_industrial_credentials(
    profile_key: str,
    *,
    credential_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
) -> IndustrialStoredCredentials:
    """Load credentials for a production source, preferring process environment values."""

    username_key, password_key = credential_env_keys(profile_key)
    env = environ if environ is not None else os.environ
    env_username = str(env.get(username_key, "") or "")
    env_password = str(env.get(password_key, "") or "")
    if env_username or env_password:
        return IndustrialStoredCredentials(
            username=env_username,
            password=env_password,
            source="environment",
        )

    path = Path(credential_path or default_industrial_credential_path()).expanduser()
    values = _read_env_file(path)
    return IndustrialStoredCredentials(
        username=str(values.get(username_key, "") or ""),
        password=str(values.get(password_key, "") or ""),
        source=str(path) if username_key in values or password_key in values else "",
    )


def save_industrial_credentials(
    profile_key: str,
    *,
    username: str,
    password: str,
    credential_path: str | Path | None = None,
) -> Path:
    """Save credentials in a local env-style file with user-only permissions."""

    path = Path(credential_path or default_industrial_credential_path()).expanduser()
    username_key, password_key = credential_env_keys(profile_key)
    values = _read_env_file(path)
    values[username_key] = str(username or "")
    values[password_key] = str(password or "")
    _write_env_file(path, values)
    return path


def forget_industrial_credentials(
    profile_key: str,
    *,
    credential_path: str | Path | None = None,
) -> Path:
    """Remove locally saved credentials for one production source profile."""

    path = Path(credential_path or default_industrial_credential_path()).expanduser()
    username_key, password_key = credential_env_keys(profile_key)
    values = _read_env_file(path)
    values.pop(username_key, None)
    values.pop(password_key, None)
    if path.exists():
        _write_env_file(path, values)
    return path


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        values[key] = _parse_env_value(raw_value.strip())
    return values


def _parse_env_value(raw_value: str) -> str:
    if not raw_value:
        return ""
    try:
        parts = shlex.split(raw_value, comments=False, posix=True)
    except ValueError:
        return raw_value.strip("'\"")
    if not parts:
        return ""
    return parts[0]


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    lines = [
        "# Local Metroliza industrial database credentials.",
        "# This file is user-specific and should not be committed.",
    ]
    for key in sorted(values):
        lines.append(f"{key}={shlex.quote(str(values[key]))}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
