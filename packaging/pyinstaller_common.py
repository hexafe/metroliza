"""Shared PyInstaller collection rules for Metroliza artifacts."""

from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator

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


ONEDIR_OFFLINE_ONNXRUNTIME_NAMESPACES = (
    "onnxruntime.backend",
    "onnxruntime.datasets",
    "onnxruntime.quantization",
    "onnxruntime.tools",
    "onnxruntime.transformers",
)
_ONEDIR_SCANNER_PROBE_PYINSTALLER_VERSION = "6.22.3"
_ONEDIR_SCANNER_PROBE_ENV = "METROLIZA_PYINSTALLER_SCANNER_PROBE"
_TARGET6_OBSERVED_CHILD_EXIT_CODE = 3221225477
_ONEDIR_SCANNER_PARAMETERS = (
    "binaries",
    "import_packages",
    "symlink_suppression_patterns",
)


def read_version_label(root_dir: Path) -> str:
    """Return the release label used by packaged artifact names."""
    version_ns: dict[str, str] = {}
    exec((root_dir / "VersionDate.py").read_text(encoding="utf-8"), version_ns)
    return f"{version_ns['RELEASE_VERSION']}({version_ns['VERSION_DATE']})"


def prepare_build_provenance_manifest(root_dir: Path) -> Path:
    """Resolve or generate the manifest embedded into this exact build."""

    from scripts.build_provenance import (
        generate_build_provenance,
        validate_build_provenance_manifest,
    )

    configured_path = os.getenv("METROLIZA_BUILD_PROVENANCE_PATH")
    if configured_path:
        manifest_path = Path(configured_path).resolve()
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"Configured build provenance manifest is missing: {manifest_path}"
            )
    else:
        manifest_path = generate_build_provenance(
            root_dir / "build" / "provenance" / "build_provenance.json",
            packager="pyinstaller",
            repo_root=root_dir,
        )

    validate_build_provenance_manifest(
        manifest_path,
        expected_packager="pyinstaller",
        expected_release_label=read_version_label(root_dir),
    )
    return manifest_path


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


def filter_onedir_hiddenimports(hiddenimports: list[str]) -> list[str]:
    """Keep ONNX Runtime inference modules and all unrelated hidden imports."""
    inference_prefix = "onnxruntime.capi"
    return [
        module_name
        for module_name in hiddenimports
        if not module_name.startswith("onnxruntime.")
        or module_name == inference_prefix
        or module_name.startswith(f"{inference_prefix}.")
    ]


def _load_pyinstaller_binary_scanner() -> tuple[str, str, Any, Any]:
    from importlib.metadata import version as distribution_version

    import PyInstaller
    from PyInstaller.building import build_main
    from PyInstaller import isolated

    return (
        PyInstaller.__version__,
        distribution_version("onnxruntime"),
        build_main,
        isolated,
    )


def _scanner_signature_is_supported(scanner: object) -> bool:
    try:
        parameters = tuple(inspect.signature(scanner).parameters.values())
    except (TypeError, ValueError):
        return False
    return tuple(parameter.name for parameter in parameters) == _ONEDIR_SCANNER_PARAMETERS and all(
        parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        and parameter.default is inspect.Parameter.empty
        for parameter in parameters
    )


def _emit_scanner_probe(
    scenario: str,
    status: str,
    child_exit_code: int | None = None,
) -> None:
    payload = {
        "kind": "pyinstaller_scanner_probe",
        "scenario": scenario,
        "schema_version": 1,
        "status": status,
    }
    if child_exit_code is not None:
        payload["child_exit_code"] = child_exit_code
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def _run_scanner_probe(
    scanner: Any,
    subprocess_died_error: type[Exception],
    scenario: str,
    packages: list[str],
) -> tuple[str, int | None]:
    child_exit_code = None
    _emit_scanner_probe(scenario, "started")
    try:
        scanner([], packages, set())
    except subprocess_died_error as exc:
        status, candidate_code = _scanner_child_death_metadata(exc)
        if (
            isinstance(candidate_code, int)
            and not isinstance(candidate_code, bool)
            and -(2**31) <= candidate_code <= 2**32 - 1
        ):
            child_exit_code = candidate_code
    except Exception:
        status = "python_failed"
    else:
        status = "passed"
    _emit_scanner_probe(scenario, status, child_exit_code)
    return status, child_exit_code


def _scanner_child_death_metadata(exc: BaseException) -> tuple[str, object]:
    current: BaseException | None = exc
    for _depth in range(4):
        status = getattr(current, "_metroliza_scanner_status", None)
        child_exit_code = getattr(current, "_metroliza_child_exit_code", None)
        observed_phase = (
            status == "scanner_child_died_during_onnxruntime_after_pyqt6"
        )
        if observed_phase or child_exit_code is not None:
            return (
                status if observed_phase else "scanner_child_died",
                child_exit_code,
            )
        cause = current.__cause__
        current = cause if isinstance(cause, BaseException) else None
        if current is None:
            break
    return "scanner_child_died", None


class _VerifiedOnnxRuntimePython:
    """Proxy one pinned scanner child and verify package imports in that child."""

    def __init__(
        self,
        python_type: Any,
        expected_onnxruntime_version: str,
        subprocess_died_error: type[Exception],
        preload: bool,
        *args: object,
        **kwargs: object,
    ) -> None:
        self._context = python_type(*args, **kwargs)
        self._expected_onnxruntime_version = expected_onnxruntime_version
        self._subprocess_died_error = subprocess_died_error
        self._preload = preload
        self._child: Any = None
        self._setup_complete = False
        self._preloaded = False
        self._pyqt6_loaded = False

    def __enter__(self) -> _VerifiedOnnxRuntimePython:
        self._child = self._context.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._context.__exit__(*args)

    def call(self, function: Any, *args: object, **kwargs: object) -> object:
        function_name = getattr(function, "__name__", None)
        if not self._setup_complete:
            if function_name != "setup":
                raise RuntimeError("Windows onedir scanner setup changed")
            result = self._child.call(function, *args, **kwargs)
            self._setup_complete = True
            return result
        if self._preload and not self._preloaded:
            if function_name != "import_library":
                raise RuntimeError("Windows onedir scanner import sequence changed")
            self._child.call(function, "onnxruntime")
            self._require_loaded_module("onnxruntime", self._expected_onnxruntime_version)
            self._preloaded = True
        try:
            result = self._child.call(function, *args, **kwargs)
        except self._subprocess_died_error as exc:
            self._annotate_scanner_child_death(exc, function_name, args)
            raise
        self._verify_observed_import(function_name, args)
        return result

    def _verify_observed_import(
        self,
        function_name: str | None,
        args: tuple[object, ...],
    ) -> None:
        if function_name != "import_library":
            return
        if args == ("PyQt6",):
            self._require_loaded_module("PyQt6", None)
            self._pyqt6_loaded = True
        elif not self._preload and args == ("onnxruntime",):
            self._require_loaded_module("onnxruntime", self._expected_onnxruntime_version)

    def _require_loaded_module(
        self,
        module_name: str,
        expected_version: str | None,
    ) -> None:
        loaded = self._child.call(
            _verify_loaded_module,
            module_name,
            expected_version,
        )
        if loaded is not True:
            raise RuntimeError("Windows onedir scanner module import failed")

    def _annotate_scanner_child_death(
        self,
        exc: Exception,
        function_name: str | None,
        args: tuple[object, ...],
    ) -> None:
        process = getattr(self._child, "_child", None)
        child_exit_code = getattr(process, "returncode", None)
        if isinstance(child_exit_code, int) and not isinstance(child_exit_code, bool):
            exc._metroliza_child_exit_code = child_exit_code
        if (
            self._pyqt6_loaded
            and function_name == "import_library"
            and args == ("onnxruntime",)
        ):
            exc._metroliza_scanner_status = (
                "scanner_child_died_during_onnxruntime_after_pyqt6"
            )


def _verify_loaded_module(module_name: str, expected_version: str | None) -> bool:
    import sys
    from types import ModuleType

    module = sys.modules.get(module_name)
    return isinstance(module, ModuleType) and (
        expected_version is None
        or getattr(module, "__version__", None) == expected_version
    )


def _import_and_verify_onnxruntime(expected_version: str) -> bool:
    import sys
    from types import ModuleType

    __import__("onnxruntime")
    module = sys.modules.get("onnxruntime")
    return isinstance(module, ModuleType) and getattr(module, "__version__", None) == expected_version


@contextmanager
def _verify_onnxruntime_in_scanner(
    isolated: Any,
    expected_onnxruntime_version: str,
    *,
    preload: bool,
) -> Iterator[None]:
    original_python = isolated.Python

    def _verified_python(*args: object, **kwargs: object) -> _VerifiedOnnxRuntimePython:
        return _VerifiedOnnxRuntimePython(
            original_python,
            expected_onnxruntime_version,
            isolated.SubprocessDiedError,
            preload,
            *args,
            **kwargs,
        )

    isolated.Python = _verified_python
    try:
        yield
    finally:
        isolated.Python = original_python


def _run_preloaded_scanner_probe(
    scanner: Any,
    isolated: Any,
    expected_onnxruntime_version: str,
    packages: list[str],
) -> tuple[str, int | None]:
    with _verify_onnxruntime_in_scanner(
        isolated,
        expected_onnxruntime_version,
        preload=True,
    ):
        return _run_scanner_probe(
            scanner,
            isolated.SubprocessDiedError,
            "onnxruntime_before_pyqt6",
            packages,
        )


def _run_observed_scanner_probe(
    scanner: Any,
    isolated: Any,
    expected_onnxruntime_version: str,
    scenario: str,
    packages: list[str],
) -> tuple[str, int | None]:
    with _verify_onnxruntime_in_scanner(
        isolated,
        expected_onnxruntime_version,
        preload=False,
    ):
        return _run_scanner_probe(
            scanner,
            isolated.SubprocessDiedError,
            scenario,
            packages,
        )


def _run_direct_onnxruntime_probe(
    isolated: Any,
    expected_onnxruntime_version: str,
) -> tuple[str, int | None]:
    _emit_scanner_probe("onnxruntime_direct", "started")
    try:
        loaded = isolated.call(
            _import_and_verify_onnxruntime,
            expected_onnxruntime_version,
        )
    except isolated.SubprocessDiedError:
        status = "scanner_child_died"
    except Exception:
        status = "python_failed"
    else:
        status = "passed" if loaded is True else "module_invalid"
    _emit_scanner_probe("onnxruntime_direct", status)
    return status, None


@contextmanager
def onedir_binary_scanner_probe() -> Iterator[None]:
    """Preload ORT in the pinned Windows scanner and optionally run controls."""
    if sys.platform != "win32":
        yield
        return

    (
        version,
        expected_onnxruntime_version,
        build_main,
        isolated,
    ) = _load_pyinstaller_binary_scanner()
    original = getattr(build_main, "find_binary_dependencies", None)
    if (
        version != _ONEDIR_SCANNER_PROBE_PYINSTALLER_VERSION
        or not _scanner_signature_is_supported(original)
    ):
        raise RuntimeError(
            "Windows onedir scanner probe requires PyInstaller 6.22.3 "
            "with its expected binary dependency scanner API"
        )

    def _probed_find_binary_dependencies(
        binaries: object,
        import_packages: list[str],
        symlink_suppression_patterns: object,
    ) -> object:
        if os.getenv(_ONEDIR_SCANNER_PROBE_ENV) == "1":
            probe_results = (
                _run_direct_onnxruntime_probe(
                    isolated,
                    expected_onnxruntime_version,
                ),
                _run_observed_scanner_probe(
                    original,
                    isolated,
                    expected_onnxruntime_version,
                    "onnxruntime_scanner",
                    ["onnxruntime"],
                ),
                _run_observed_scanner_probe(
                    original,
                    isolated,
                    expected_onnxruntime_version,
                    "pyqt6_then_onnxruntime",
                    ["PyQt6", "onnxruntime"],
                ),
                _run_preloaded_scanner_probe(
                    original,
                    isolated,
                    expected_onnxruntime_version,
                    ["PyQt6", "onnxruntime"],
                ),
            )
            if probe_results != (
                ("passed", None),
                ("passed", None),
                (
                    "scanner_child_died_during_onnxruntime_after_pyqt6",
                    _TARGET6_OBSERVED_CHILD_EXIT_CODE,
                ),
                ("passed", None),
            ):
                raise RuntimeError("Windows onedir scanner probe failed")
        with _verify_onnxruntime_in_scanner(
            isolated,
            expected_onnxruntime_version,
            preload=True,
        ):
            return original(
                binaries,
                import_packages,
                symlink_suppression_patterns,
            )

    build_main.find_binary_dependencies = _probed_find_binary_dependencies
    try:
        yield
    finally:
        build_main.find_binary_dependencies = original


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
    build_provenance_manifest = prepare_build_provenance_manifest(root_dir)
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
    build_provenance_datas = [
        (str(build_provenance_manifest), "metroliza/app"),
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
            build_provenance_datas
            + third_party_notice_datas
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
