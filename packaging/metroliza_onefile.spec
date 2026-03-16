# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None
SPEC_DIR = Path(SPECPATH).resolve()
ROOT_DIR = SPEC_DIR.parent
VERSION_NS = {}
exec((ROOT_DIR / "VersionDate.py").read_text(encoding="utf-8"), VERSION_NS)
RELEASE_VERSION = VERSION_NS["RELEASE_VERSION"]
VERSION_DATE = VERSION_NS["VERSION_DATE"]
VERSION_LABEL = f"{RELEASE_VERSION}({VERSION_DATE})"
ICON_PATH = SPEC_DIR / 'metroliza_icon2.ico'


a = Analysis(
    [str(ROOT_DIR / 'metroliza.py')],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['_metroliza_cmm_native'],
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
    name='metroliza',
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
