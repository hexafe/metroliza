# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

block_cipher = None
SPEC_DIR = Path(SPECPATH).resolve()
ROOT_DIR = SPEC_DIR.parent
VERSION_NS = {}
exec((ROOT_DIR / "VersionDate.py").read_text(encoding="utf-8"), VERSION_NS)
RELEASE_VERSION = VERSION_NS["RELEASE_VERSION"]
VERSION_DATE = VERSION_NS["VERSION_DATE"]
VERSION_LABEL = f"{RELEASE_VERSION}({VERSION_DATE})"
OUTPUT_NAME = f"metroliza_P_{VERSION_LABEL}"
ICON_PATH = SPEC_DIR / 'metroliza_icon2.ico'


def _collect_windows_python_runtime_binaries() -> list[tuple[str, str]]:
    """Include Python runtime DLLs needed by extension modules like _ctypes."""
    if sys.platform != 'win32':
        return []

    dll_dir = Path(sys.base_prefix) / 'DLLs'
    if not dll_dir.exists():
        return []

    runtime_globs = (
        'libffi*.dll',
        'python3.dll',
        'python3*.dll',
        'vcruntime*.dll',
        'msvcp*.dll',
    )

    binaries: list[tuple[str, str]] = []
    seen_paths: set[Path] = set()
    for pattern in runtime_globs:
        for dll_path in dll_dir.glob(pattern):
            resolved_path = dll_path.resolve()
            if resolved_path in seen_paths:
                continue
            binaries.append((str(resolved_path), '.'))
            seen_paths.add(resolved_path)
    return binaries


def _collect_optional_runtime_assets(package_name: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    try:
        datas = collect_data_files(package_name)
        binaries = collect_dynamic_libs(package_name)
        hiddenimports = collect_submodules(package_name)
    except Exception:
        return [], [], []
    return datas, binaries, hiddenimports


def _collect_optional_distribution_metadata(distribution_name: str) -> list[tuple[str, str]]:
    try:
        return copy_metadata(distribution_name)
    except Exception:
        return []


def _collect_optional_vendored_model_data() -> list[tuple[str, str]]:
    model_roots = (
        ROOT_DIR / 'ocr_models',
        ROOT_DIR / 'modules' / 'ocr_models',
    )
    datas: list[tuple[str, str]] = []
    for model_root in model_roots:
        if not model_root.exists():
            continue
        for file_path in model_root.rglob('*'):
            if file_path.is_file():
                datas.append((str(file_path), str(file_path.parent.relative_to(ROOT_DIR))))
    return datas


windows_runtime_binaries = _collect_windows_python_runtime_binaries()
pymupdf_datas, pymupdf_binaries, pymupdf_hiddenimports = _collect_optional_runtime_assets('pymupdf')
fitz_datas, fitz_binaries, fitz_hiddenimports = _collect_optional_runtime_assets('fitz')
hexafe_groupstats_datas, hexafe_groupstats_binaries, hexafe_groupstats_hiddenimports = _collect_optional_runtime_assets('hexafe_groupstats')
rapidocr_datas, rapidocr_binaries, rapidocr_hiddenimports = _collect_optional_runtime_assets('rapidocr')
onnxruntime_datas, onnxruntime_binaries, onnxruntime_hiddenimports = _collect_optional_runtime_assets('onnxruntime')
openvino_datas, openvino_binaries, openvino_hiddenimports = _collect_optional_runtime_assets('openvino')
cv2_datas, cv2_binaries, cv2_hiddenimports = _collect_optional_runtime_assets('cv2')
numpy_datas, numpy_binaries, numpy_hiddenimports = _collect_optional_runtime_assets('numpy')
rapidocr_metadata_datas = _collect_optional_distribution_metadata('rapidocr')
onnxruntime_metadata_datas = _collect_optional_distribution_metadata('onnxruntime')
openvino_metadata_datas = _collect_optional_distribution_metadata('openvino')
opencv_python_metadata_datas = _collect_optional_distribution_metadata('opencv-python')
numpy_metadata_datas = _collect_optional_distribution_metadata('numpy')
ocr_model_datas = _collect_optional_vendored_model_data()
html_dashboard_datas = [(str(ROOT_DIR / 'modules' / 'html_dashboard_assets' / 'plotly-2.27.0.min.js'), 'modules/html_dashboard_assets')]
third_party_notice_datas = [(str(ROOT_DIR / 'THIRD_PARTY_NOTICES.md'), '.')]


a = Analysis(
    [str(ROOT_DIR / 'metroliza.py')],
    pathex=[],
    binaries=windows_runtime_binaries + pymupdf_binaries + fitz_binaries + hexafe_groupstats_binaries + rapidocr_binaries + onnxruntime_binaries + openvino_binaries + cv2_binaries + numpy_binaries,
    datas=third_party_notice_datas + html_dashboard_datas + pymupdf_datas + fitz_datas + hexafe_groupstats_datas + rapidocr_datas + onnxruntime_datas + openvino_datas + cv2_datas + numpy_datas + rapidocr_metadata_datas + onnxruntime_metadata_datas + openvino_metadata_datas + opencv_python_metadata_datas + numpy_metadata_datas + ocr_model_datas,
    hiddenimports=[
        '_metroliza_cmm_native',
        '_metroliza_chart_native',
        'hexafe_groupstats',
        'pymupdf',
        'fitz',
        'rapidocr',
        'onnxruntime',
        'openvino',
        'cv2',
        'numpy',
        'modules.cmm_report_parser',
        'modules.header_ocr_backend',
        'modules.header_ocr_geometry',
        'modules.header_ocr_corrections',
        'modules.native_chart_compositor',
        *hexafe_groupstats_hiddenimports,
        *pymupdf_hiddenimports,
        *fitz_hiddenimports,
        *rapidocr_hiddenimports,
        *onnxruntime_hiddenimports,
        *openvino_hiddenimports,
        *cv2_hiddenimports,
        *numpy_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=OUTPUT_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(ICON_PATH)],
)
