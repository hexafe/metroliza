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
    filter_onedir_hiddenimports,
    read_version_label,
)

VERSION_LABEL = read_version_label(ROOT_DIR)
OUTPUT_DIR_NAME = f"metroliza_P_{VERSION_LABEL}_onedir"
EXE_NAME = "metroliza"
SUPERVISED_WINDOWS = sys.platform == "win32"
if SUPERVISED_WINDOWS:
    EXE_NAME = "metroliza_application"
ICON_PATH = SPEC_DIR / "metroliza_icon2.ico"
COLLECTION = build_pyinstaller_collection(ROOT_DIR)


a = Analysis(
    [str(SPEC_DIR / "metroliza_package_entry.py")],
    pathex=[str(ROOT_DIR / "src"), str(ROOT_DIR)],
    binaries=COLLECTION["binaries"],
    datas=COLLECTION["datas"],
    hiddenimports=filter_onedir_hiddenimports(COLLECTION["hiddenimports"]),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(ONEDIR_OFFLINE_ONNXRUNTIME_NAMESPACES),
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
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
