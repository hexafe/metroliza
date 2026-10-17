"""Pure-Python checks for the user-build payload exclusion rules (no PyInstaller needed)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
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


def _read_spec(spec_name: str) -> str:
    return (ROOT / "packaging" / spec_name).read_text(encoding="utf-8")


def test_legacy_onefile_spec_applies_payload_filter_before_building():
    spec = _read_spec("metroliza_onefile.spec")

    assert 'excludes=COLLECTION["excludes"]' in spec
    assert "a.binaries = filter_payload_toc(a.binaries)" in spec
    assert "a.datas = filter_payload_toc(a.datas)" in spec
    assert spec.index("filter_payload_toc(a.binaries)") < spec.index("PYZ(")


def test_onedir_spec_filters_application_analysis_before_collect():
    spec = _read_spec("metroliza_onedir.spec")

    assert (
        'excludes=[*ONEDIR_OFFLINE_ONNXRUNTIME_NAMESPACES, *COLLECTION["excludes"]]' in spec
    )
    app_binaries = spec.index("a.binaries = filter_payload_toc(a.binaries)")
    app_datas = spec.index("a.datas = filter_payload_toc(a.datas)")
    # The filter runs once Analysis (and the Windows hook checks) finished, before PYZ/COLLECT.
    assert spec.index("validate_setuptools_runtime_hook(a.scripts") < app_binaries
    assert max(app_binaries, app_datas) < spec.index("pyz = PYZ(a.pure")
    assert max(app_binaries, app_datas) < spec.index("coll = COLLECT(")


def test_onedir_spec_filters_ocr_worker_analysis_before_collect():
    spec = _read_spec("metroliza_onedir.spec")
    worker_analysis = spec[spec.index("ocr_analysis = Analysis(") : spec.index("coll = COLLECT(")]

    # The worker's own dependency scan feeds the same COLLECT, so it gets the same filter ...
    assert "ocr_analysis.binaries = filter_payload_toc(ocr_analysis.binaries)" in worker_analysis
    assert "ocr_analysis.datas = filter_payload_toc(ocr_analysis.datas)" in worker_analysis
    assert worker_analysis.index("ocr_analysis.datas = filter_payload_toc") < worker_analysis.index(
        "ocr_pyz = PYZ("
    )
    # ... and Analysis may not follow lazy imports into OpenVINO in the user flavor.
    excludes = worker_analysis[worker_analysis.index("excludes=[") : worker_analysis.index("noarchive")]
    assert '*COLLECTION["excludes"]' in excludes
    assert "ocr_packages = onedir_ocr_worker_packages()" in spec
    assert '"openvino"' not in spec[spec.index("ocr_packages = ") : spec.index("ocr_analysis = Analysis(")]


def test_onedir_spec_collected_files_are_not_refiltered_after_collect():
    spec = _read_spec("metroliza_onedir.spec")
    collect = spec.index("coll = COLLECT(")

    assert "filter_payload_toc" not in spec[collect:]
    # The launcher is a separate self-contained EXE (not part of COLLECT) that already
    # excludes the heavy runtimes, so it needs no payload filter.
    launcher = spec[spec.index("launcher_analysis = Analysis(") :]
    assert '"openvino"' in launcher and '"onnxruntime"' in launcher and '"cv2"' in launcher


def test_identity_manifest_is_written_from_the_collected_directory_after_collect():
    spec = _read_spec("metroliza_onedir.spec")

    assert spec.index("coll = COLLECT(") < spec.index("write_supervision_manifest(output_directory)")
    assert "output_directory = Path(DISTPATH) / OUTPUT_DIR_NAME" in spec


def test_identity_manifest_inputs_are_never_filtered_out():
    from metroliza.shared.diagnostic_package import COMPONENTS

    internal = [name.removeprefix("_internal/") for name in COMPONENTS if name.startswith("_internal/")]
    assert internal  # python DLL, base_library.zip, build provenance
    entries = _toc(*internal)
    assert common.filter_payload_toc(entries, flavor="user") == entries
    # The two executables are EXE outputs, never TOC entries, so no glob can reach them either.
    for name in COMPONENTS:
        assert not common.is_user_build_excluded_payload(name)


def test_portable_onefile_spec_packs_the_onedir_tree_unfiltered():
    spec = _read_spec("metroliza_portable_onefile.spec")

    # The envelope must contain exactly what the (already filtered) onedir build produced, or the
    # package identity manifest no longer matches the unpacked tree.
    assert "filter_payload_toc" not in spec
    assert "build_pyinstaller_collection" not in spec
    assert 'datas=[(str(INNER), "metroliza_payload")]' in spec
    assert "binaries=[]" in spec


def test_onedir_ocr_worker_packages_follow_the_build_flavor(monkeypatch):
    monkeypatch.delenv("METROLIZA_BUILD_FLAVOR", raising=False)

    assert common.onedir_ocr_worker_packages() == {"rapidocr", "onnxruntime", "cv2", "numpy"}
    assert common.onedir_ocr_worker_packages("user") == {"rapidocr", "onnxruntime", "cv2", "numpy"}
    assert common.onedir_ocr_worker_packages("benchmark") == {
        "rapidocr",
        "onnxruntime",
        "cv2",
        "numpy",
        "openvino",
    }
    monkeypatch.setenv("METROLIZA_BUILD_FLAVOR", "benchmark")
    assert "openvino" in common.onedir_ocr_worker_packages()


def _worker_hiddenimports(monkeypatch, flavor: str | None) -> list[str]:
    """Mirror the OCR worker hidden-import selection of metroliza_onedir.spec."""

    def fake_required(package_name):
        return ([], [], [package_name, f"{package_name}.runtime"])

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
    collection = common.build_pyinstaller_collection(ROOT)
    packages = common.onedir_ocr_worker_packages()
    return [
        name
        for name in common.filter_onedir_hiddenimports(collection["hiddenimports"])
        if name.split(".", 1)[0] in packages
    ]


@pytest.mark.parametrize("flavor", [None, "user"])
def test_user_flavor_ocr_worker_hidden_imports_contain_no_openvino(monkeypatch, flavor):
    hiddenimports = _worker_hiddenimports(monkeypatch, flavor)

    assert not [name for name in hiddenimports if name.split(".", 1)[0] == "openvino"]
    assert {"rapidocr", "onnxruntime", "cv2", "numpy"} <= set(hiddenimports)


def test_benchmark_flavor_ocr_worker_hidden_imports_keep_openvino(monkeypatch):
    hiddenimports = _worker_hiddenimports(monkeypatch, "benchmark")

    assert "openvino" in hiddenimports
    assert "openvino.runtime" in hiddenimports


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


def test_common_module_imports_with_the_spec_sys_path(tmp_path):
    # PyInstaller executes the specs with only packaging/ and src/ added to sys.path.
    repo = Path(__file__).resolve().parents[1]
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]];"
            "import pyinstaller_common as c; print(c.filter_payload_toc([('openvino/x.dll', 's', 'BINARY')], flavor='user'))",
            str(repo / "packaging"),
            str(repo / "src"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.strip() == "[]"


def test_common_module_imports_with_the_rc_spec_sys_path_and_manifest_helper(tmp_path):
    # metroliza_onedir.spec inserts packaging/ and then src/ at position 0 and later imports
    # scripts.build_diagnostic_manifest; the repo-root fallback in pyinstaller_common must keep
    # both `scripts.*` imports working from an unrelated working directory.
    repo = Path(__file__).resolve().parents[1]
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys;"
            "sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2]);"
            "import pyinstaller_common as c;"
            "from scripts.build_diagnostic_manifest import write_supervision_manifest;"
            "assert sys.path.index(sys.argv[3]) > 1;"
            "print(c.onedir_ocr_worker_packages('user') == frozenset({'rapidocr','onnxruntime','cv2','numpy'}))",
            str(repo / "packaging"),
            str(repo / "src"),
            str(repo),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.strip() == "True"


def test_packaged_ocr_worker_models_come_from_the_vendored_directory_not_rapidocr_models(tmp_path):
    # The packaged worker is handed absolute paths under <bundle>/metroliza/resources/ocr_models/
    # rapidocr (see default_rapidocr_latin_model_paths); this is the directory the vendored model
    # collection targets, so excluding rapidocr/models/* cannot remove a model the worker loads.
    from metroliza.parsing import header_ocr_backend as backend

    bundle = tmp_path / "bundle"
    (bundle / "metroliza").mkdir(parents=True)
    original = getattr(sys, "_MEIPASS", None)
    sys._MEIPASS = str(bundle)
    try:
        model_dir = backend.default_rapidocr_model_dir()
        paths = backend.default_rapidocr_latin_model_paths()
    finally:
        if original is None:
            del sys._MEIPASS
        else:
            sys._MEIPASS = original

    datas = common.collect_optional_vendored_model_data(ROOT)
    vendored_dests = {Path(dest).as_posix() for _source, dest in datas}
    assert model_dir == bundle / "metroliza" / "resources" / "ocr_models" / "rapidocr"
    assert vendored_dests == {"metroliza/resources/ocr_models/rapidocr"}
    for model_path in (paths.det_model_path, paths.cls_model_path, paths.rec_model_path):
        relative = Path(model_path).relative_to(bundle).as_posix()
        assert not common.is_user_build_excluded_payload(relative)
        assert Path(model_path).name in {Path(source).name for source, _dest in datas}


class _FakeAnalysis:
    """Stand-in for PyInstaller's Analysis: records its inputs and exposes seeded scan results."""

    created: list["_FakeAnalysis"] = []

    def __init__(self, scripts, **kwargs):
        self.entry = Path(scripts[0]).stem
        self.kwargs = kwargs
        # What PyInstaller's dependency scan would add on top of the declared binaries/datas.
        scanned_binaries = [(dest, f"/scan/{dest}", "BINARY") for dest in EXCLUDED_DESTS[:6] + KEPT_DESTS[:4]]
        scanned_datas = [(dest, f"/scan/{dest}", "DATA") for dest in EXCLUDED_DESTS[6:] + KEPT_DESTS[4:]]
        self.binaries = list(kwargs.get("binaries") or []) + scanned_binaries
        self.datas = list(kwargs.get("datas") or []) + scanned_datas
        self.pure = []
        self.zipfiles = []
        self.zipped_data = []
        self.scripts = [(self.entry, f"/scan/{self.entry}.py", "PYSOURCE")]
        _FakeAnalysis.created.append(self)


class _FakeBuildObject:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.name = kwargs.get("name", "fake")


def _exec_onedir_spec(monkeypatch, tmp_path, flavor: str | None):
    """Run metroliza_onedir.spec as the Windows supervised build with a stubbed PyInstaller."""
    import contextlib
    import shutil

    from scripts import build_diagnostic_manifest

    packaging_dir = ROOT / "packaging"
    monkeypatch.setattr(sys, "path", [str(packaging_dir), *sys.path])
    monkeypatch.delitem(sys.modules, "pyinstaller_common", raising=False)
    module = importlib.import_module("pyinstaller_common")
    monkeypatch.setitem(sys.modules, "pyinstaller_common", module)

    if flavor is None:
        monkeypatch.delenv("METROLIZA_BUILD_FLAVOR", raising=False)
    else:
        monkeypatch.setenv("METROLIZA_BUILD_FLAVOR", flavor)
    monkeypatch.setattr(module, "prepare_build_provenance_manifest", lambda _root: Path("prov.json"))
    monkeypatch.setattr(
        module,
        "collect_required_runtime_assets",
        lambda name: ([], [], [name, f"{name}.runtime"]),
    )
    monkeypatch.setattr(module, "collect_submodules", lambda _name: [])
    monkeypatch.setattr(module, "collect_optional_distribution_metadata", lambda _name: [])
    monkeypatch.setattr(module, "collect_windows_python_runtime_binaries", lambda: [])
    monkeypatch.setattr(module, "collect_optional_vendored_model_data", lambda _root: [])
    monkeypatch.setattr(module, "collect_setuptools_hook_metadata", lambda: [])
    monkeypatch.setattr(module, "onedir_binary_scanner_probe", contextlib.nullcontext)
    monkeypatch.setattr(module, "validate_runtime_audit_hook", lambda *_args: None)
    monkeypatch.setattr(module, "validate_setuptools_runtime_hook", lambda *_args: None)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "copy2", lambda *_args, **_kwargs: None)

    manifest_calls: list[Path] = []
    monkeypatch.setattr(
        build_diagnostic_manifest, "write_supervision_manifest", manifest_calls.append
    )
    collects: list[_FakeBuildObject] = []

    class _FakeCollect(_FakeBuildObject):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            collects.append(self)
            assert not manifest_calls, "manifest must be written after COLLECT"

    _FakeAnalysis.created = []
    namespace = {
        "SPECPATH": str(packaging_dir),
        "DISTPATH": str(tmp_path / "dist"),
        "Analysis": _FakeAnalysis,
        "PYZ": _FakeBuildObject,
        "EXE": _FakeBuildObject,
        "COLLECT": _FakeCollect,
    }
    spec_path = packaging_dir / "metroliza_onedir.spec"
    exec(compile(spec_path.read_text(encoding="utf-8"), str(spec_path), "exec"), namespace)
    analyses = {analysis.entry: analysis for analysis in _FakeAnalysis.created}
    assert set(analyses) == {
        "metroliza_package_entry",
        "metroliza_ocr_worker_entry",
        "metroliza_supervisor_entry",
    }
    (collect,) = collects
    collected_dests = {
        entry[0] for arg in collect.args if isinstance(arg, list) for entry in arg
    }
    return analyses, collected_dests, manifest_calls


@pytest.mark.parametrize("flavor", [None, "user"])
def test_executed_onedir_spec_collects_no_excluded_payload_in_user_flavor(monkeypatch, tmp_path, flavor):
    analyses, collected, manifest_calls = _exec_onedir_spec(monkeypatch, tmp_path, flavor)

    assert not {dest for dest in collected if common.is_user_build_excluded_payload(dest)}
    assert set(KEPT_DESTS) <= collected
    for entry in ("metroliza_package_entry", "metroliza_ocr_worker_entry"):
        assert "openvino" in analyses[entry].kwargs["excludes"]
        assert not [
            name
            for name in analyses[entry].kwargs["hiddenimports"]
            if name.split(".", 1)[0] == "openvino"
        ]
    label = common.read_version_label(ROOT)
    assert manifest_calls == [tmp_path / "dist" / f"metroliza_P_{label}_onedir"]


def test_executed_onedir_spec_keeps_full_payload_and_openvino_in_benchmark_flavor(monkeypatch, tmp_path):
    analyses, collected, manifest_calls = _exec_onedir_spec(monkeypatch, tmp_path, "benchmark")

    assert {dest for dest in EXCLUDED_DESTS if "\\" not in dest} <= collected
    assert set(KEPT_DESTS) <= collected
    assert "openvino" not in analyses["metroliza_package_entry"].kwargs["excludes"]
    assert "openvino" not in analyses["metroliza_ocr_worker_entry"].kwargs["excludes"]
    worker_imports = analyses["metroliza_ocr_worker_entry"].kwargs["hiddenimports"]
    assert "openvino" in worker_imports and "openvino.runtime" in worker_imports
    assert len(manifest_calls) == 1
