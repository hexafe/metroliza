# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

block_cipher = None
SPEC_DIR = Path(SPECPATH).resolve()
ROOT_DIR = SPEC_DIR.parent
sys.path.insert(0, str(SPEC_DIR))
sys.path.insert(0, str(ROOT_DIR / "src"))

from pyinstaller_common import build_pyinstaller_collection, read_version_label

VERSION_LABEL = read_version_label(ROOT_DIR)
OUTPUT_DIR_NAME = f"metroliza_P_{VERSION_LABEL}_onedir"
EXE_NAME = "metroliza"
ICON_PATH = SPEC_DIR / "metroliza_icon2.ico"
COLLECTION = build_pyinstaller_collection(ROOT_DIR)


a = Analysis(
    [str(SPEC_DIR / "metroliza_package_entry.py")],
    pathex=[str(ROOT_DIR / "src"), str(ROOT_DIR)],
    binaries=COLLECTION["binaries"],
    datas=COLLECTION["datas"],
    hiddenimports=COLLECTION["hiddenimports"],
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
