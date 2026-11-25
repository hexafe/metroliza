"""Bind the CMM parser used in a benchmark to an explicit freshly built wheel."""

from hashlib import file_digest
from importlib.machinery import EXTENSION_SUFFIXES, ExtensionFileLoader
from pathlib import Path, PurePosixPath
import sys
from zipfile import BadZipFile, ZipFile


_MODULE = "_metroliza_cmm_native"


def _active_extension() -> Path:
    from metroliza.native_bridges import cmm_native_parser

    if not cmm_native_parser.native_backend_available():
        raise RuntimeError("CMM parser guardrail requires the native parser extension")

    parser = cmm_native_parser._native_parse_blocks
    actual = {
        Path(spec.origin).resolve()
        for name, module in sys.modules.copy().items()
        if name in (_MODULE, f"{_MODULE}.{_MODULE}")
        and (spec := getattr(module, "__spec__", None)) is not None
        and isinstance(spec.loader, ExtensionFileLoader)
        and getattr(module, "parse_blocks", None) is parser
    }
    if len(actual) != 1:
        raise RuntimeError("CMM parser guardrail could not identify the active native parser extension")
    return actual.pop()


def _wheel_extension_hash(wheel: Path, extension: Path) -> str:
    try:
        with ZipFile(wheel) as archive:
            candidates = [
                name for name in archive.namelist()
                if (leaf := PurePosixPath(name).name).startswith(_MODULE)
                and leaf.endswith(tuple(EXTENSION_SUFFIXES))
            ]
            if len(candidates) != 1 or PurePosixPath(candidates[0]).name != extension.name:
                raise RuntimeError("CMM parser guardrail wheel has no unique compatible native parser extension")
            with archive.open(candidates[0]) as file:
                return file_digest(file, "sha256").hexdigest()
    except (OSError, BadZipFile) as error:
        raise RuntimeError("CMM parser guardrail could not read the native parser wheel") from error


def _sha256(path: Path) -> str:
    with path.open("rb") as file:
        return file_digest(file, "sha256").hexdigest()


def verify_cmm_wheel(wheel: Path) -> dict[str, str]:
    """Verify the active bridge function comes from the same extension as the wheel."""
    extension = _active_extension()
    expected = _wheel_extension_hash(wheel, extension)
    try:
        current = _sha256(extension)
        wheel_sha256 = _sha256(wheel)
    except OSError as error:
        raise RuntimeError("CMM parser guardrail could not read the native wheel or loaded extension") from error
    if current != expected:
        raise RuntimeError("CMM parser guardrail loaded a different native parser extension than the built wheel")
    return {"wheel": wheel.name, "wheel_sha256": wheel_sha256,
            "extension": extension.name, "extension_sha256": expected}
