"""Shared PyInstaller collection rules for Metroliza artifacts."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

try:
    from PyInstaller.utils.hooks import (
        collect_data_files,
        collect_dynamic_libs,
        collect_submodules,
        copy_metadata,
    )
except ModuleNotFoundError as exc:
    _PYINSTALLER_IMPORT_ERROR = exc

    def _missing_pyinstaller_hook(*_args: object, **_kwargs: object) -> list:
        raise ModuleNotFoundError(
            "PyInstaller is required to build package collection metadata"
        ) from _PYINSTALLER_IMPORT_ERROR

    collect_data_files = _missing_pyinstaller_hook
    collect_dynamic_libs = _missing_pyinstaller_hook
    collect_submodules = _missing_pyinstaller_hook
    copy_metadata = _missing_pyinstaller_hook
else:
    _PYINSTALLER_IMPORT_ERROR = None


def read_version_label(root_dir: Path) -> str:
    """Return the release label used by packaged artifact names."""
    version_ns: dict[str, str] = {}
    exec((root_dir / "VersionDate.py").read_text(encoding="utf-8"), version_ns)
    return f"{version_ns['RELEASE_VERSION']}({version_ns['VERSION_DATE']})"


def collect_windows_python_runtime_binaries() -> list[tuple[str, str]]:
    """Include Python runtime DLLs needed by extension modules like _ctypes."""
    if sys.platform != "win32":
        return []

    dll_dir = Path(sys.base_prefix) / "DLLs"
    if not dll_dir.exists():
        return []

    runtime_globs = (
        "libffi*.dll",
        "python3.dll",
        "python3*.dll",
        "vcruntime*.dll",
        "msvcp*.dll",
    )

    binaries: list[tuple[str, str]] = []
    seen_paths: set[Path] = set()
    for pattern in runtime_globs:
        for dll_path in dll_dir.glob(pattern):
            resolved_path = dll_path.resolve()
            if resolved_path in seen_paths:
                continue
            binaries.append((str(resolved_path), "."))
            seen_paths.add(resolved_path)
    return binaries


def _collect_runtime_assets(
    package_name: str,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    return (
        collect_data_files(package_name),
        collect_dynamic_libs(package_name),
        collect_submodules(package_name),
    )


def _package_is_installed(package_name: str) -> bool:
    try:
        return importlib.util.find_spec(package_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def collect_required_runtime_assets(
    package_name: str,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    """Collect required package assets and fail with package context on any error."""

    if not _package_is_installed(package_name):
        raise RuntimeError(f"Required packaging dependency `{package_name}` is not installed")
    try:
        return _collect_runtime_assets(package_name)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to collect required packaging dependency `{package_name}`"
        ) from exc


def collect_optional_runtime_assets(
    package_name: str,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    """Collect an optional package only when it is installed."""

    if not _package_is_installed(package_name):
        return [], [], []
    return _collect_runtime_assets(package_name)


def collect_optional_distribution_metadata(distribution_name: str) -> list[tuple[str, str]]:
    """Collect distribution metadata if the package is installed."""
    try:
        return copy_metadata(distribution_name)
    except Exception:
        return []


def collect_optional_vendored_model_data(root_dir: Path) -> list[tuple[str, str]]:
    """Collect vendored OCR model files from legacy and current locations."""
    model_roots = (
        root_dir / "ocr_models",
        root_dir / "modules" / "ocr_models",
        root_dir / "src" / "metroliza" / "resources" / "ocr_models",
    )
    datas: list[tuple[str, str]] = []
    for model_root in model_roots:
        if not model_root.exists():
            continue
        for file_path in model_root.rglob("*"):
            if file_path.is_file():
                relative_parent = file_path.parent.relative_to(model_root)
                destination = Path("metroliza") / "resources" / "ocr_models" / relative_parent
                datas.append((str(file_path), str(destination)))
    return datas


def build_pyinstaller_collection(root_dir: Path) -> dict[str, list]:
    """Return shared PyInstaller binaries, datas, and hidden imports."""
    metroliza_hiddenimports = collect_submodules("metroliza")
    pymupdf_datas, pymupdf_binaries, pymupdf_hiddenimports = collect_required_runtime_assets(
        "pymupdf"
    )
    fitz_datas, fitz_binaries, fitz_hiddenimports = collect_required_runtime_assets("fitz")
    (
        hexafe_groupstats_datas,
        hexafe_groupstats_binaries,
        hexafe_groupstats_hiddenimports,
    ) = collect_required_runtime_assets("hexafe_groupstats")
    (
        hexafe_plotstats_datas,
        hexafe_plotstats_binaries,
        hexafe_plotstats_hiddenimports,
    ) = collect_required_runtime_assets("hexafe_plotstats")
    oznak_datas, oznak_binaries, oznak_hiddenimports = collect_required_runtime_assets("oznak")
    rapidocr_datas, rapidocr_binaries, rapidocr_hiddenimports = collect_required_runtime_assets(
        "rapidocr"
    )
    (
        onnxruntime_datas,
        onnxruntime_binaries,
        onnxruntime_hiddenimports,
    ) = collect_required_runtime_assets("onnxruntime")
    openvino_datas, openvino_binaries, openvino_hiddenimports = collect_required_runtime_assets(
        "openvino"
    )
    cv2_datas, cv2_binaries, cv2_hiddenimports = collect_required_runtime_assets("cv2")
    numpy_datas, numpy_binaries, numpy_hiddenimports = collect_required_runtime_assets("numpy")

    html_dashboard_datas = [
        (
            str(
                root_dir
                / "src"
                / "metroliza"
                / "resources"
                / "html_dashboard_assets"
                / "plotly-2.27.0.min.js"
            ),
            "metroliza/resources/html_dashboard_assets",
        )
    ]
    third_party_notice_datas = [
        (str(root_dir / "THIRD_PARTY_NOTICES.md"), "."),
        (
            str(root_dir / "docs" / "release_checks" / "third_party_inventory_260711.json"),
            ".",
        ),
    ]

    return {
        "binaries": (
            collect_windows_python_runtime_binaries()
            + pymupdf_binaries
            + fitz_binaries
            + hexafe_groupstats_binaries
            + hexafe_plotstats_binaries
            + oznak_binaries
            + rapidocr_binaries
            + onnxruntime_binaries
            + openvino_binaries
            + cv2_binaries
            + numpy_binaries
        ),
        "datas": (
            third_party_notice_datas
            + html_dashboard_datas
            + pymupdf_datas
            + fitz_datas
            + hexafe_groupstats_datas
            + hexafe_plotstats_datas
            + oznak_datas
            + rapidocr_datas
            + onnxruntime_datas
            + openvino_datas
            + cv2_datas
            + numpy_datas
            + collect_optional_distribution_metadata("rapidocr")
            + collect_optional_distribution_metadata("onnxruntime")
            + collect_optional_distribution_metadata("openvino")
            + collect_optional_distribution_metadata("opencv-python")
            + collect_optional_distribution_metadata("numpy")
            + collect_optional_distribution_metadata("hexafe-plotstats")
            + collect_optional_distribution_metadata("hexafe-groupstats")
            + collect_optional_distribution_metadata("oznak")
            + collect_optional_distribution_metadata("PyQt6")
            + collect_optional_distribution_metadata("PyQt6-Qt6")
            + collect_optional_distribution_metadata("PyMuPDF")
            + collect_optional_distribution_metadata("cryptography")
            + collect_optional_distribution_metadata("google-auth")
            + collect_optional_distribution_metadata("google-auth-oauthlib")
            + collect_optional_distribution_metadata("matplotlib")
            + collect_optional_distribution_metadata("Pillow")
            + collect_optional_distribution_metadata("scipy")
            + collect_optional_distribution_metadata("seaborn")
            + collect_optional_distribution_metadata("PyYAML")
            + collect_optional_distribution_metadata("XlsxWriter")
            + collect_optional_distribution_metadata("pandas")
            + collect_optional_distribution_metadata("SQLAlchemy")
            + collect_optional_vendored_model_data(root_dir)
        ),
        "hiddenimports": [
            "_metroliza_cmm_native",
            "_metroliza_chart_native",
            "_metroliza_group_stats_native",
            "_metroliza_comparison_stats_native",
            "_metroliza_distribution_fit_native",
            "hexafe_groupstats",
            "hexafe_plotstats",
            "oznak",
            "pymupdf",
            "fitz",
            "rapidocr",
            "onnxruntime",
            "openvino",
            "cv2",
            "numpy",
            "metroliza",
            "metroliza.parsing.cmm_report_parser",
            "metroliza.parsing.report_parser_factory",
            "metroliza.parsing.header_ocr_backend",
            "metroliza.parsing.header_ocr_geometry",
            "metroliza.parsing.header_ocr_corrections",
            "metroliza.reports.header_ocr_corrections",
            "metroliza.charts.native_chart_compositor",
            "modules.cmm_report_parser",
            "modules.header_ocr_backend",
            "modules.header_ocr_geometry",
            "modules.header_ocr_corrections",
            "modules.native_chart_compositor",
            *metroliza_hiddenimports,
            *hexafe_groupstats_hiddenimports,
            *hexafe_plotstats_hiddenimports,
            *oznak_hiddenimports,
            *pymupdf_hiddenimports,
            *fitz_hiddenimports,
            *rapidocr_hiddenimports,
            *onnxruntime_hiddenimports,
            *openvino_hiddenimports,
            *cv2_hiddenimports,
            *numpy_hiddenimports,
        ],
    }
