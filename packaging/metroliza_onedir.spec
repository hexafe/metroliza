# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys
import shutil

block_cipher = None
SPEC_DIR = Path(SPECPATH).resolve()
ROOT_DIR = SPEC_DIR.parent
sys.path.insert(0, str(SPEC_DIR))
sys.path.insert(0, str(ROOT_DIR / "src"))

from pyinstaller_common import (
    ONEDIR_OFFLINE_ONNXRUNTIME_NAMESPACES,
    build_pyinstaller_collection,
    collect_setuptools_hook_metadata,
    filter_onedir_hiddenimports,
    filter_payload_toc,
    onedir_binary_scanner_probe,
    onedir_ocr_worker_packages,
    read_version_label,
    validate_runtime_audit_hook,
    validate_setuptools_runtime_hook,
)

VERSION_LABEL = read_version_label(ROOT_DIR)
OUTPUT_DIR_NAME = f"metroliza_P_{VERSION_LABEL}_onedir"
EXE_NAME = "metroliza"
SUPERVISED_WINDOWS = sys.platform == "win32"
if SUPERVISED_WINDOWS:
    EXE_NAME = "metroliza_application"
ICON_PATH = SPEC_DIR / "metroliza_icon2.ico"
COLLECTION = build_pyinstaller_collection(ROOT_DIR)
WINDOWS_HOOKS = SPEC_DIR / "hooks" / "windows"
if SUPERVISED_WINDOWS:
    # Read this bundled distribution's version without importing its compiler
    # integration during GUI startup (which invokes a Windows version shell).
    COLLECTION["datas"] += collect_setuptools_hook_metadata()


# Windows builds preload ONNX Runtime after scanner path tracking begins. The
# targeted qualification additionally runs closed controls at this exact point.
# The adapter is pinned to PyInstaller 6.22.3 and fails closed on API drift.
with onedir_binary_scanner_probe():
    a = Analysis(
        [str(SPEC_DIR / "metroliza_package_entry.py")],
        pathex=[str(ROOT_DIR / "src"), str(ROOT_DIR)],
        binaries=COLLECTION["binaries"],
        datas=COLLECTION["datas"],
        hiddenimports=filter_onedir_hiddenimports(COLLECTION["hiddenimports"]),
        hookspath=[str(WINDOWS_HOOKS)] if SUPERVISED_WINDOWS else [],
        hooksconfig={},
        runtime_hooks=[str(WINDOWS_HOOKS / "rthooks/metroliza_rth_runtime_audit.py")] if SUPERVISED_WINDOWS else [],
        # User builds also exclude OpenVINO here so Analysis cannot follow lazy imports into it.
        excludes=[*ONEDIR_OFFLINE_ONNXRUNTIME_NAMESPACES, *COLLECTION["excludes"]],
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        cipher=block_cipher,
        noarchive=False,
    )
if SUPERVISED_WINDOWS:
    validate_runtime_audit_hook(a.scripts, WINDOWS_HOOKS)
    validate_setuptools_runtime_hook(a.scripts, WINDOWS_HOOKS)
# Drop payload that user builds do not use (benchmark flavor keeps everything). The
# supervision manifest is written from the collected directory below, so it only ever
# hashes files that survived this filter.
a.binaries = filter_payload_toc(a.binaries)
a.datas = filter_payload_toc(a.datas)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(ICON_PATH)],
)

if SUPERVISED_WINDOWS:
    # OCR uses ONNX in a separate executable without Qt's Python/runtime hooks.
    # Both executables use the same immutable onedir assets and provenance.
    # OpenVINO belongs to the OCR worker only in the explicit benchmark flavor.
    ocr_packages = onedir_ocr_worker_packages()
    ocr_hiddenimports = [
        name for name in filter_onedir_hiddenimports(COLLECTION["hiddenimports"])
        if name.split(".", 1)[0] in ocr_packages
    ]
    ocr_analysis = Analysis(
        [str(SPEC_DIR / "metroliza_ocr_worker_entry.py")],
        pathex=[str(ROOT_DIR / "src"), str(ROOT_DIR)],
        binaries=[], datas=[], hiddenimports=ocr_hiddenimports,
        hookspath=[str(WINDOWS_HOOKS)], hooksconfig={}, runtime_hooks=[],
        excludes=["PyQt6", "matplotlib", "pandas", "metroliza.ui",
                  "metroliza.app.bootstrap", "pymupdf", "fitz",
                  *COLLECTION["excludes"]],
        noarchive=False,
    )
    forbidden_ocr_modules = ("PyQt6", "metroliza.ui", "metroliza.app.bootstrap")
    if any(
        name == prefix or name.startswith(prefix + ".")
        for name, _, _ in ocr_analysis.pure
        for prefix in forbidden_ocr_modules
    ) or any(
        "pyqt" in Path(source).name.lower() for _, source, _ in ocr_analysis.scripts
    ):
        raise RuntimeError("OCR worker must not bundle Qt runtime hooks or UI modules")
    # Same user-build payload filter as the application analysis; both feed one COLLECT.
    ocr_analysis.binaries = filter_payload_toc(ocr_analysis.binaries)
    ocr_analysis.datas = filter_payload_toc(ocr_analysis.datas)
    ocr_pyz = PYZ(ocr_analysis.pure, ocr_analysis.zipped_data, cipher=block_cipher)
    ocr_exe = EXE(
        ocr_pyz, ocr_analysis.scripts, [], exclude_binaries=True,
        name="metroliza_ocr_worker", debug=False, bootloader_ignore_signals=False,
        strip=False, upx=True, console=False, disable_windowed_traceback=True,
        icon=[str(ICON_PATH)],
    )

    compute_analysis = Analysis(
        [str(SPEC_DIR / "metroliza_compute_worker_entry.py")],
        pathex=[str(ROOT_DIR / "src"), str(ROOT_DIR)],
        binaries=[], datas=[],
        hiddenimports=["metroliza.exporting.export_summary_render_pool",
                       "metroliza.exporting.export_data_thread",
                       "metroliza.parsing.import_prepare_pool"],
        hookspath=[str(WINDOWS_HOOKS)], hooksconfig={}, runtime_hooks=[],
        excludes=["PyQt6", "metroliza.ui", "metroliza.app.bootstrap",
                  "rapidocr", "onnxruntime", "openvino", "cv2",
                  *COLLECTION["excludes"]], noarchive=False,
    )
    if any(
        name == prefix or name.startswith(prefix + ".")
        for name, _, _ in compute_analysis.pure
        for prefix in forbidden_ocr_modules
    ) or any("pyqt" in Path(source).name.lower() for _, source, _ in compute_analysis.scripts):
        raise RuntimeError("Compute worker must not bundle Qt runtime hooks or UI modules")
    compute_analysis.binaries = filter_payload_toc(compute_analysis.binaries)
    compute_analysis.datas = filter_payload_toc(compute_analysis.datas)
    compute_pyz = PYZ(compute_analysis.pure, compute_analysis.zipped_data, cipher=block_cipher)
    compute_exe = EXE(
        compute_pyz, compute_analysis.scripts, [], exclude_binaries=True,
        name="metroliza_compute_worker", debug=False, bootloader_ignore_signals=False,
        strip=False, upx=True, console=False, disable_windowed_traceback=True,
        icon=[str(ICON_PATH)],
    )

coll = COLLECT(
    exe,
    *([ocr_exe, compute_exe] if SUPERVISED_WINDOWS else []),
    a.binaries,
    *([ocr_analysis.binaries] if SUPERVISED_WINDOWS else []),
    *([compute_analysis.binaries] if SUPERVISED_WINDOWS else []),
    a.zipfiles,
    *([ocr_analysis.zipfiles] if SUPERVISED_WINDOWS else []),
    *([compute_analysis.zipfiles] if SUPERVISED_WINDOWS else []),
    a.datas,
    *([ocr_analysis.datas] if SUPERVISED_WINDOWS else []),
    *([compute_analysis.datas] if SUPERVISED_WINDOWS else []),
    strip=False,
    upx=True,
    upx_exclude=[],
    name=OUTPUT_DIR_NAME,
)

if SUPERVISED_WINDOWS:
    # The minimal launcher carries its own stdlib runtime. It can still report
    # a missing/incompatible child Python DLL instead of dying before observation.
    launcher_analysis = Analysis(
        [str(SPEC_DIR / "metroliza_supervisor_entry.py")],
        pathex=[str(ROOT_DIR / "src"), str(ROOT_DIR)],
        binaries=[], datas=[], hiddenimports=[], hookspath=[], hooksconfig={},
        runtime_hooks=[],
        excludes=["PyQt6", "numpy", "matplotlib", "pymupdf", "fitz", "rapidocr",
                  "onnxruntime", "openvino", "cv2", "metroliza.app.bootstrap",
                  "metroliza.parsing", "metroliza.exporting", "metroliza.ui"],
        noarchive=False,
    )
    launcher_pyz = PYZ(launcher_analysis.pure)
    launcher_exe = EXE(
        launcher_pyz, launcher_analysis.scripts, launcher_analysis.binaries,
        launcher_analysis.datas, [], name="metroliza", debug=False,
        bootloader_ignore_signals=False, strip=False, upx=True, console=False,
        disable_windowed_traceback=True, icon=[str(ICON_PATH)],
    )
    output_directory = Path(DISTPATH) / OUTPUT_DIR_NAME
    shutil.copy2(launcher_exe.name, output_directory / "metroliza.exe")
    from scripts.build_diagnostic_manifest import write_supervision_manifest

    write_supervision_manifest(output_directory)
