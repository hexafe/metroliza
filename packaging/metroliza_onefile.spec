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
OUTPUT_NAME = f"metroliza_P_{VERSION_LABEL}"
ICON_PATH = SPEC_DIR / "metroliza_icon2.ico"
SPLASH_IMAGE_PATH = SPEC_DIR / "metroliza_bootloader_splash.png"
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
splash = None
if sys.platform == "win32":
    splash = Splash(
        str(SPLASH_IMAGE_PATH),
        binaries=a.binaries,
        datas=a.datas,
        text_pos=(28, 188),
        text_size=13,
        text_color="#f8fafc",
        text_default="Metroliza is loading...",
    )
splash_target = [splash] if splash is not None else []
splash_binaries = splash.binaries if splash is not None else []

exe = EXE(
    pyz,
    *splash_target,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    splash_binaries,
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
