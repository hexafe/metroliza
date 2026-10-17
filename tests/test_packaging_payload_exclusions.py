"""Pure-Python checks for the user-build payload exclusion rules (no PyInstaller needed)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "metroliza_pyinstaller_common_under_test", ROOT / "packaging" / "pyinstaller_common.py"
)
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)


def _toc(*dest_names: str) -> list[tuple[str, str, str]]:
    return [(name, f"/build/{name}", "BINARY") for name in dest_names]


EXCLUDED_DESTS = (
    "openvino/libs/openvino.dll",
    "openvino/libs/openvino_intel_npu_compiler.dll",
    "openvino/libs/openvino_intel_gpu_plugin.dll",
    "openvino/__init__.py",
    "openvino_telemetry/main.py",
    "openvino-2026.1.0.dist-info/METADATA",
    "cv2/opencv_videoio_ffmpeg4120_64.dll",
    "cv2\\opencv_videoio_ffmpeg4120_64.dll",
    "cv2/data/haarcascade_frontalface_default.xml",
    "rapidocr/models/ch_PP-OCRv4_det_infer.onnx",
    "rapidocr/models/ppocr_keys_v1.txt",
    "PyQt6/Qt6/bin/opengl32sw.dll",
    "PyQt6\\Qt6\\bin\\opengl32sw.dll",
)

KEPT_DESTS = (
    "onnxruntime/capi/onnxruntime_pybind11_state.pyd",
    "onnxruntime/capi/onnxruntime.dll",
    "cv2/cv2.pyd",
    "cv2/config.py",
    "cv2/__init__.py",
    "cv2/data/__init__.py",
    "numpy/core/_multiarray_umath.pyd",
    "rapidocr/config.yaml",
    "rapidocr/default_models.yaml",
    "rapidocr/inference_engine/onnxruntime/main.py",
    "metroliza/resources/ocr_models/rapidocr/ch_PP-OCRv4_det_mobile.onnx",
    "metroliza/resources/ocr_models/rapidocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "metroliza/resources/ocr_models/rapidocr/latin_PP-OCRv3_rec_mobile.onnx",
    "PyQt6/Qt6/plugins/platforms/qwindows.dll",
    "PyQt6/Qt6/bin/Qt6Core.dll",
    "PyQt6/Qt6/bin/Qt6Widgets.dll",
)


@pytest.mark.parametrize("dest", EXCLUDED_DESTS)
def test_user_flavor_excludes_unused_payload(dest):
    assert common.filter_payload_toc(_toc(dest), flavor="user") == []


@pytest.mark.parametrize("dest", KEPT_DESTS)
def test_user_flavor_keeps_required_runtime_assets(dest):
    entries = _toc(dest)
    assert common.filter_payload_toc(entries, flavor="user") == entries


def test_filter_preserves_order_and_tuple_shape():
    entries = _toc(KEPT_DESTS[0], EXCLUDED_DESTS[0], KEPT_DESTS[2], EXCLUDED_DESTS[6])

    assert common.filter_payload_toc(entries, flavor="user") == [entries[0], entries[2]]


def test_benchmark_flavor_keeps_full_payload():
    entries = _toc(*EXCLUDED_DESTS, *KEPT_DESTS)

    assert common.filter_payload_toc(entries, flavor="benchmark") == entries


def test_default_flavor_is_user_build(monkeypatch):
    monkeypatch.delenv("METROLIZA_BUILD_FLAVOR", raising=False)
    entries = _toc(*EXCLUDED_DESTS)

    assert common.filter_payload_toc(entries) == []
    monkeypatch.setenv("METROLIZA_BUILD_FLAVOR", "benchmark")
    assert common.filter_payload_toc(entries) == entries


def test_unknown_flavor_is_rejected(monkeypatch):
    monkeypatch.setenv("METROLIZA_BUILD_FLAVOR", "openvino")

    with pytest.raises(ValueError, match="METROLIZA_BUILD_FLAVOR"):
        common.filter_payload_toc(_toc(KEPT_DESTS[0]))


def test_vendored_ocr_models_are_collected_and_survive_the_filter():
    datas = common.collect_optional_vendored_model_data(ROOT)
    dests = [
        (str(Path(dest) / Path(source).name), source, "DATA") for source, dest in datas
    ]
    model_names = {Path(source).name for _dest, source, _kind in dests}

    assert {
        "ch_PP-OCRv4_det_mobile.onnx",
        "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "latin_PP-OCRv3_rec_mobile.onnx",
    } <= model_names
    assert common.filter_payload_toc(dests, flavor="user") == dests


def _patched_collection(monkeypatch, flavor: str | None):
    collected: list[str] = []

    def fake_required(package_name):
        collected.append(package_name)
        return ([], [], [package_name])

    if flavor is None:
        monkeypatch.delenv("METROLIZA_BUILD_FLAVOR", raising=False)
    else:
        monkeypatch.setenv("METROLIZA_BUILD_FLAVOR", flavor)
    monkeypatch.setattr(common, "prepare_build_provenance_manifest", lambda _root: Path("prov.json"))
    monkeypatch.setattr(common, "collect_required_runtime_assets", fake_required)
    monkeypatch.setattr(common, "collect_submodules", lambda _name: [])
    monkeypatch.setattr(common, "collect_optional_distribution_metadata", lambda _name: [])
    monkeypatch.setattr(common, "collect_windows_python_runtime_binaries", lambda: [])
    monkeypatch.setattr(common, "collect_optional_vendored_model_data", lambda _root: [])
    return collected, common.build_pyinstaller_collection(ROOT)


@pytest.mark.parametrize("flavor", [None, "user"])
def test_user_collection_does_not_collect_or_import_openvino(monkeypatch, flavor):
    collected, collection = _patched_collection(monkeypatch, flavor)

    assert "openvino" not in collected
    assert "openvino" not in collection["hiddenimports"]
    assert {"onnxruntime", "cv2", "rapidocr", "numpy"} <= set(collected)
    # Keep PyInstaller from following lazy `import openvino` inside RapidOCR into the bundle.
    assert "openvino" in collection["excludes"]


def test_benchmark_collection_collects_openvino(monkeypatch):
    collected, collection = _patched_collection(monkeypatch, "benchmark")

    assert "openvino" in collected
    assert "openvino" in collection["hiddenimports"]
    assert collection["excludes"] == []


@pytest.mark.parametrize("spec_name", ["metroliza_onefile.spec", "metroliza_onedir.spec"])
def test_specs_apply_payload_filter_before_building(spec_name):
    spec = (ROOT / "packaging" / spec_name).read_text(encoding="utf-8")

    assert 'excludes=COLLECTION["excludes"]' in spec
    assert "a.binaries = filter_payload_toc(a.binaries)" in spec
    assert "a.datas = filter_payload_toc(a.datas)" in spec
    assert spec.index("filter_payload_toc(a.binaries)") < spec.index("PYZ(")


def test_openvino_is_not_a_user_build_requirement():
    def requirement_lines(name: str) -> list[str]:
        text = (ROOT / name).read_text(encoding="utf-8").lower()
        return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]

    assert not any("openvino" in line for line in requirement_lines("requirements-ocr.txt"))
    benchmark = requirement_lines("requirements-ocr-benchmark.txt")
    assert "-r requirements-ocr.txt" in benchmark
    assert any(line.startswith("openvino") for line in benchmark)


def test_nuitka_user_flavor_excludes_match_pyinstaller_rules():
    script = (ROOT / "packaging" / "build_nuitka.ps1").read_text(encoding="utf-8")

    assert "'--nofollow-import-to=openvino'" in script
    assert "'--noinclude-dlls=*opencv_videoio_ffmpeg*.dll'" in script
    assert "'--noinclude-dlls=opengl32sw.dll'" in script
    assert "'--noinclude-data-files=cv2/data/*.xml'" in script
    assert "'--noinclude-data-files=rapidocr/models/*'" in script
    benchmark_branch = script.index("if ($resolvedBuildFlavor -eq 'benchmark')")
    assert script.index("'--include-package=openvino'") > benchmark_branch
