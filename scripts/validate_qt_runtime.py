"""Validate the PyQt6 runtime that Metroliza needs at startup."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
import traceback
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _version_major_minor(version: str | None) -> tuple[int, int] | None:
    if not version:
        return None
    pieces = version.split(".")
    if len(pieces) < 2:
        return None
    try:
        return int(pieces[0]), int(pieces[1])
    except ValueError:
        return None


def _vc_redist_registry_status() -> dict[str, Any]:
    if platform.system().lower() != "windows":
        return {"checked": False, "reason": "not_windows"}

    try:
        import winreg
    except ImportError as exc:
        return {"checked": False, "reason": f"winreg_unavailable:{exc}"}

    key_paths = (
        r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
    )
    rows: list[dict[str, Any]] = []
    installed = False
    for key_path in key_paths:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                values = {}
                for name in ("Installed", "Version", "Major", "Minor", "Bld", "Rbld"):
                    try:
                        values[name] = winreg.QueryValueEx(key, name)[0]
                    except OSError:
                        values[name] = None
                row_installed = values.get("Installed") == 1
                installed = installed or row_installed
                rows.append(
                    {
                        "key": key_path,
                        "present": True,
                        "installed": row_installed,
                        "values": values,
                    }
                )
        except OSError as exc:
            rows.append({"key": key_path, "present": False, "installed": False, "error": str(exc)})

    return {
        "checked": True,
        "installed": installed,
        "registry_rows": rows,
        "download_url": VC_REDIST_URL,
    }


def _import_pyqt_modules() -> tuple[Any, Any]:
    from PyQt6 import QtCore, QtWidgets

    return QtCore, QtWidgets


def _qt_library_paths(qtcore: Any) -> dict[str, str]:
    library_info = getattr(qtcore, "QLibraryInfo", None)
    if library_info is None or not hasattr(library_info, "LibraryPath"):
        return {}

    paths: dict[str, str] = {}
    for name in ("PrefixPath", "BinariesPath", "LibrariesPath", "PluginsPath"):
        enum_value = getattr(library_info.LibraryPath, name, None)
        if enum_value is None:
            continue
        try:
            paths[name] = library_info.path(enum_value)
        except Exception as exc:  # pragma: no cover - defensive for older Qt builds
            paths[name] = f"<unavailable:{type(exc).__name__}:{exc}>"
    return paths


def _qt_failure_hints() -> list[str]:
    return [
        r"Recreate the venv with: .\setup_windows_runtime.ps1 -Clean -InstallVcRedist",
        "Install the Microsoft Visual C++ Redistributable 2015-2022 x64 if it is missing.",
        "Keep PyQt6 and PyQt6-Qt6 on the same Qt major/minor line; mixed wheels can fail while importing QtCore.",
        "If the venv already exists, reinstall the Qt wheels or rebuild the venv after changing requirements.txt.",
    ]


def _environment_payload() -> dict[str, Any]:
    return {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cwd": str(Path.cwd()),
        "repo_root": str(REPO_ROOT),
        "vc_redist_x64": _vc_redist_registry_status(),
    }


def build_payload() -> dict[str, Any]:
    package_versions = {
        "PyQt6": _distribution_version("PyQt6"),
        "PyQt6-Qt6": _distribution_version("PyQt6-Qt6"),
        "PyQt6-sip": _distribution_version("PyQt6-sip"),
    }
    pyqt_line = _version_major_minor(package_versions["PyQt6"])
    qt_payload_line = _version_major_minor(package_versions["PyQt6-Qt6"])
    version_alignment_ok = pyqt_line is None or qt_payload_line is None or pyqt_line == qt_payload_line
    warnings: list[str] = []
    if not version_alignment_ok:
        warnings.append(
            "PyQt6 and PyQt6-Qt6 are installed from different Qt major/minor lines; "
            "rebuild the venv from requirements.txt."
        )

    payload: dict[str, Any] = {
        "ok": False,
        "environment": _environment_payload(),
        "pyqt": {
            "packages": package_versions,
            "version_alignment_ok": version_alignment_ok,
            "warnings": warnings,
            "import_ok": False,
            "error": None,
            "hints": [],
        },
    }

    try:
        qtcore, _qtwidgets = _import_pyqt_modules()
    except (ImportError, OSError, RuntimeError) as exc:
        payload["pyqt"].update(
            {
                "import_ok": False,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback_tail": traceback.format_exc().strip().splitlines()[-8:],
                },
                "hints": _qt_failure_hints(),
            }
        )
        return payload

    payload["pyqt"].update(
        {
            "import_ok": True,
            "qt_runtime_version": qtcore.qVersion(),
            "qt_build_version": getattr(qtcore, "QT_VERSION_STR", None),
            "pyqt_runtime_version": getattr(qtcore, "PYQT_VERSION_STR", None),
            "library_paths": _qt_library_paths(qtcore),
        }
    )
    payload["ok"] = bool(version_alignment_ok)
    if not version_alignment_ok:
        payload["pyqt"]["hints"] = _qt_failure_hints()
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Optional UTF-8 JSON output path. Defaults to stdout.")
    parser.add_argument("--compact", action="store_true", help="Write compact JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    payload = build_payload()
    indent = None if args.compact else 2
    output_text = json.dumps(payload, ensure_ascii=True, indent=indent, default=str)
    if args.output:
        Path(args.output).expanduser().resolve().write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
