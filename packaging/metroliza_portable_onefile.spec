# -*- mode: python ; coding: utf-8 -*-
"""One visible EXE containing the separately qualified supervised onedir."""

from pathlib import Path
import re
import sys

SPEC_DIR = Path(SPECPATH).resolve()
ROOT_DIR = SPEC_DIR.parent
sys.path.insert(0, str(SPEC_DIR))
sys.path.insert(0, str(ROOT_DIR / "src"))

from pyinstaller_common import read_version_label
from metroliza_portable_entry import _verified_launcher

if sys.platform != "win32":
    raise RuntimeError("portable_onefile_is_windows_only")

VERSION_LABEL = read_version_label(ROOT_DIR)
match = re.fullmatch(r"([0-9]{4}\.[0-9]{2}[a-z0-9]+)\(([0-9]{6})\)", VERSION_LABEL)
if match is None:
    raise ValueError("portable_onefile_requires_versioned_release")
OUTPUT_NAME = f"metroliza_{match[1]}_{match[2]}"
INNER = Path(DISTPATH) / f"metroliza_P_{VERSION_LABEL}_onedir"
if _verified_launcher(INNER) is None:
    raise ValueError("portable_onefile_requires_verified_supervised_onedir")

analysis = Analysis(
    [str(SPEC_DIR / "metroliza_portable_entry.py")],
    pathex=[str(ROOT_DIR / "src"), str(ROOT_DIR)],
    binaries=[],
    datas=[(str(INNER), "metroliza_payload")],
    hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["PyQt6", "numpy", "matplotlib", "pymupdf", "fitz", "rapidocr",
              "onnxruntime", "openvino", "cv2", "metroliza.app.bootstrap",
              "metroliza.parsing", "metroliza.exporting", "metroliza.ui"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.zipfiles, analysis.datas,
    [], name=OUTPUT_NAME, debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=True,
    icon=[str(SPEC_DIR / "metroliza_icon2.ico")],
)
