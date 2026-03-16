# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

block_cipher = None
SPEC_DIR = Path(SPECPATH).resolve()
ROOT_DIR = SPEC_DIR.parent
VERSION_NS = {}
exec((ROOT_DIR / "VersionDate.py").read_text(encoding="utf-8"), VERSION_NS)
RELEASE_VERSION = VERSION_NS["RELEASE_VERSION"]
VERSION_DATE = VERSION_NS["VERSION_DATE"]
VERSION_LABEL = f"{RELEASE_VERSION}({VERSION_DATE})"
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


windows_runtime_binaries = _collect_windows_python_runtime_binaries()


a = Analysis(
    [str(ROOT_DIR / 'metroliza.py')],
    pathex=[],
    binaries=windows_runtime_binaries,
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
