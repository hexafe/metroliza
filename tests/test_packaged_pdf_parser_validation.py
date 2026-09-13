from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
import types
from pathlib import Path

import pytest

from metroliza.parsing import pdf_backend
import scripts.validate_packaged_pdf_parser as validator
from scripts.validate_packaged_pdf_parser import (
    PackagingValidationError,
    require_pdf_backend_available,
    require_header_ocr_available,
    validate_nuitka_report_has_pdf_backend,
    validate_nuitka_report_has_header_ocr,
    validate_third_party_notice,
    validate_vendored_header_ocr_models,
)


def test_require_pdf_backend_available_prefers_pymupdf(monkeypatch):
    class _FakeSpec:
        pass

    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: _FakeSpec() if name in {'pymupdf', 'fitz'} else None)
    monkeypatch.setattr(pdf_backend, '_PYMUPDF_BACKEND', types.SimpleNamespace(open=lambda *_args, **_kwargs: None))
    monkeypatch.setattr(pdf_backend, '_FITZ_BACKEND', types.SimpleNamespace(open=lambda *_args, **_kwargs: None))

    assert require_pdf_backend_available() == 'pymupdf'


def test_require_pdf_backend_available_raises_when_backend_missing(monkeypatch):
    monkeypatch.setattr(importlib.util, 'find_spec', lambda _name: None)

    with pytest.raises(PackagingValidationError):
        require_pdf_backend_available()


def test_validate_nuitka_report_has_pdf_backend_accepts_report(tmp_path):
    report = tmp_path / 'nuitka-build-report.xml'
    report.write_text(
        textwrap.dedent(
            '''
            <nuitka-report>
              <module name="metroliza.parsing.cmm_report_parser" />
              <module name="metroliza.parsing.report_parser_factory" />
              <module name="metroliza.reports.report_parser_factory" />
              <module name="metroliza.parsing.pdf_backend" />
              <module name="pymupdf" />
              <module name="pymupdf._mupdf" />
              <module name="pymupdf._extra" />
              <module name="pymupdf.extra" />
              <module name="pymupdf.mupdf" />
            </nuitka-report>
            '''
        ).strip(),
        encoding='utf-8',
    )

    assert validate_nuitka_report_has_pdf_backend(report) == ('pymupdf',)


def test_validate_nuitka_report_has_pdf_backend_rejects_missing_backend(tmp_path):
    report = tmp_path / 'nuitka-build-report.xml'
    report.write_text('<nuitka-report><module name="metroliza.parsing.cmm_report_parser" /></nuitka-report>', encoding='utf-8')

    with pytest.raises(PackagingValidationError):
        validate_nuitka_report_has_pdf_backend(report)


def test_validate_nuitka_report_has_pdf_backend_rejects_missing_runtime_modules(tmp_path):
    report = tmp_path / 'nuitka-build-report.xml'
    report.write_text(
        '<nuitka-report><module name="metroliza.parsing.cmm_report_parser" /><module name="pymupdf" /></nuitka-report>',
        encoding='utf-8',
    )

    with pytest.raises(PackagingValidationError, match='missing required PyMuPDF runtime modules'):
        validate_nuitka_report_has_pdf_backend(report)


def test_validate_nuitka_report_has_pdf_backend_rejects_missing_canonical_parser_modules(
    tmp_path,
):
    report = tmp_path / 'nuitka-build-report.xml'
    report.write_text(
        textwrap.dedent(
            '''
            <nuitka-report>
              <module name="pymupdf" />
              <module name="pymupdf._mupdf" />
              <module name="pymupdf._extra" />
              <module name="pymupdf.extra" />
              <module name="pymupdf.mupdf" />
            </nuitka-report>
            '''
        ).strip(),
        encoding='utf-8',
    )

    with pytest.raises(PackagingValidationError, match='missing required canonical PDF parser modules'):
        validate_nuitka_report_has_pdf_backend(report)


def test_require_header_ocr_available_reports_missing_dependency(monkeypatch):
    monkeypatch.setattr(importlib.util, 'find_spec', lambda _name: None)

    with pytest.raises(PackagingValidationError, match='Header OCR dependencies are missing'):
        require_header_ocr_available()


def test_require_header_ocr_available_reports_import_failure(monkeypatch):
    class _FakeSpec:
        origin = "fake"

    def _fake_import(name):
        if name == "onnxruntime":
            raise ImportError("DLL load failed")
        return types.SimpleNamespace()

    monkeypatch.setattr(importlib.util, 'find_spec', lambda _name: _FakeSpec())
    monkeypatch.setattr('scripts.validate_packaged_pdf_parser.importlib.import_module', _fake_import)

    with pytest.raises(PackagingValidationError, match='import failed: onnxruntime'):
        require_header_ocr_available()


def test_require_header_ocr_preflight_does_not_need_defusedxml(monkeypatch, capsys):
    monkeypatch.setattr(
        validator,
        '_load_defusedxml_element_tree',
        lambda: (_ for _ in ()).throw(AssertionError('defusedxml should not be loaded')),
    )
    monkeypatch.setattr(validator, 'require_header_ocr_available', lambda **_kwargs: ('rapidocr',))
    monkeypatch.setattr(validator, 'validate_vendored_header_ocr_models', lambda *_args, **_kwargs: ('model.onnx',))
    monkeypatch.setattr(validator, 'validate_third_party_notice', lambda *_args, **_kwargs: None)

    assert validator.main(['--require-header-ocr']) == 0
    assert 'Validated packaged header OCR dependencies' in capsys.readouterr().out


def test_validate_vendored_header_ocr_models_rejects_missing_assets(tmp_path):
    with pytest.raises(PackagingValidationError, match='Vendored RapidOCR model validation failed'):
        validate_vendored_header_ocr_models(tmp_path)


def test_validate_nuitka_report_has_header_ocr_accepts_report(tmp_path):
    report = tmp_path / 'nuitka-build-report.xml'
    report.write_text(
        textwrap.dedent(
            '''
            <nuitka-report>
              <module name="metroliza.parsing.header_ocr_backend" />
              <module name="metroliza.parsing.header_ocr_geometry" />
              <module name="metroliza.reports.header_ocr_corrections" />
              <module name="metroliza.parsing.header_ocr_corrections" />
              <module name="rapidocr" />
              <module name="onnxruntime" />
              <module name="openvino" />
              <module name="cv2" />
              <module name="numpy" />
              <data-file name="metroliza/resources/ocr_models/rapidocr/ch_PP-OCRv4_det_mobile.onnx" />
              <data-file name="metroliza/resources/ocr_models/rapidocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx" />
              <data-file name="metroliza/resources/ocr_models/rapidocr/latin_PP-OCRv3_rec_mobile.onnx" />
              <data-file name="THIRD_PARTY_NOTICES.md" />
            </nuitka-report>
            '''
        ).strip(),
        encoding='utf-8',
    )

    assert 'rapidocr' in validate_nuitka_report_has_header_ocr(report)


def test_validate_nuitka_report_has_header_ocr_rejects_missing_model_data(tmp_path):
    report = tmp_path / 'nuitka-build-report.xml'
    report.write_text(
        textwrap.dedent(
            '''
            <nuitka-report>
              <module name="metroliza.parsing.header_ocr_backend" />
              <module name="metroliza.parsing.header_ocr_geometry" />
              <module name="metroliza.reports.header_ocr_corrections" />
              <module name="metroliza.parsing.header_ocr_corrections" />
              <module name="rapidocr" />
              <module name="onnxruntime" />
              <module name="openvino" />
              <module name="cv2" />
              <module name="numpy" />
            </nuitka-report>
            '''
        ).strip(),
        encoding='utf-8',
    )

    with pytest.raises(PackagingValidationError, match='missing vendored RapidOCR model data files'):
        validate_nuitka_report_has_header_ocr(report)


def test_validate_nuitka_report_has_header_ocr_rejects_missing_third_party_notice(tmp_path):
    report = tmp_path / 'nuitka-build-report.xml'
    report.write_text(
        textwrap.dedent(
            '''
            <nuitka-report>
              <module name="metroliza.parsing.header_ocr_backend" />
              <module name="metroliza.parsing.header_ocr_geometry" />
              <module name="metroliza.reports.header_ocr_corrections" />
              <module name="metroliza.parsing.header_ocr_corrections" />
              <module name="rapidocr" />
              <module name="onnxruntime" />
              <module name="openvino" />
              <module name="cv2" />
              <module name="numpy" />
              <data-file name="metroliza/resources/ocr_models/rapidocr/ch_PP-OCRv4_det_mobile.onnx" />
              <data-file name="metroliza/resources/ocr_models/rapidocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx" />
              <data-file name="metroliza/resources/ocr_models/rapidocr/latin_PP-OCRv3_rec_mobile.onnx" />
            </nuitka-report>
            '''
        ).strip(),
        encoding='utf-8',
    )

    with pytest.raises(PackagingValidationError, match='missing bundled third-party notices'):
        validate_nuitka_report_has_header_ocr(report)


def test_validate_third_party_notice_requires_ocr_license_terms(tmp_path):
    notice = tmp_path / 'THIRD_PARTY_NOTICES.md'
    notice.write_text(
        'RapidOCR Apache-2.0 Baidu ONNX Runtime MIT OpenVINO OpenCV NumPy BSD-3-Clause',
        encoding='utf-8',
    )

    assert validate_third_party_notice(notice) == notice.resolve()

    notice.write_text('RapidOCR only', encoding='utf-8')
    with pytest.raises(PackagingValidationError, match='missing required OCR license terms'):
        validate_third_party_notice(notice)


def test_build_nuitka_script_fails_closed_by_default_and_names_unsafe_override():
    script = Path('packaging/build_nuitka.ps1').read_text(encoding='utf-8')

    assert '[switch]$AllowBrokenPdfParserBuild' in script
    assert '[switch]$AllowMissingHeaderOcrBuild' in script
    assert '[switch]$AllowMissingOznakBuild' in script
    assert '[switch]$BundleCredentials' in script
    assert '[string]$CredentialsPath = ""' in script
    assert '[string]$EntryPoint = "packaging/metroliza_package_entry.py"' in script
    assert "[ValidateSet('onefile', 'standalone')]" in script
    assert "[string]$Mode = 'onefile'" in script
    assert '-FastDev is a compatibility alias for -Mode standalone.' in script
    assert '-CredentialsPath no longer bundles credentials by itself.' in script
    assert '-BundleCredentials requires -CredentialsPath <path>.' in script
    assert "[ValidateSet('auto', 'gcc', 'clang')]" in script
    assert "[string]$CompilerStrategy = 'auto'" in script
    assert '[switch]$AutoInstallCompiler' in script
    assert '[switch]$OpenInstallHelp' in script
    assert 'PyMuPDF is required for packaged builds.' in script
    assert 'UNSAFE: continuing even though packaged PDF parsing may be broken.' in script
    assert 'RapidOCR header OCR is required for packaged builds.' in script
    assert 'UNSAFE: continuing even though packaged header OCR may be broken.' in script
    assert 'Oznak is required for packaged builds with industrial database integration.' in script
    assert 'UNSAFE: continuing even though packaged industrial database integration may be unavailable.' in script
    assert 'function Invoke-CheckedPythonCommand' in script
    assert 'function Resolve-PreferredCompiler' in script
    assert 'function Install-PreferredCompiler' in script
    assert 'function Show-CompilerInstallGuidance' in script
    assert "Requested compiler strategy: $CompilerStrategy" in script
    assert "Selected compiler: $($compilerResolution.Selected.Name)" in script
    assert "Auto-install attempted: $($compilerResolution.AutoInstallAttempted)" in script
    assert "Install MSYS2 or another MinGW-w64 distribution that provides gcc/g++ on PATH." in script
    assert 'Nuitka build failed. See the compiler output above. Selected compiler:' in script
    assert 'validate_packaged_pdf_parser.py' in script


def test_build_nuitka_script_defaults_to_release_onefile_and_includes_runtime_packages():
    script = Path('packaging/build_nuitka.ps1').read_text(encoding='utf-8')

    assert "$modeLabel = if ($Mode -eq 'standalone')" in script
    assert "Nuitka packaging mode: $Mode" in script
    assert "'--include-package=modules'" in script
    assert "'--include-package=metroliza'" in script
    assert "'--include-module=metroliza.parsing.cmm_report_parser'" in script
    assert "'--include-module=metroliza.parsing.report_parser_factory'" in script
    assert "'--include-module=metroliza.parsing.header_ocr_backend'" in script
    assert "'--include-module=metroliza.parsing.header_ocr_geometry'" in script
    assert "'--include-module=metroliza.parsing.header_ocr_corrections'" in script
    assert "'--include-module=metroliza.reports.header_ocr_corrections'" in script
    assert "'--include-module=metroliza.reports.report_parser_factory'" in script
    assert "'--include-module=metroliza.parsing.pdf_backend'" in script
    assert "'--include-package=hexafe_groupstats'" in script
    assert "'--include-package=hexafe_plotstats'" in script
    assert "'--include-distribution-metadata=hexafe-plotstats'" in script
    assert "$commonArgs += '--include-package=oznak'" in script
    assert "$commonArgs += '--include-distribution-metadata=oznak'" in script
    assert "$oznakPackageAvailable" in script
    assert "$oznakGateLabel" in script
    assert "'--include-module=modules.cmm_report_parser'" in script
    assert "'--include-module=modules.header_ocr_backend'" in script
    assert "'--include-module=modules.header_ocr_geometry'" in script
    assert "'--include-module=modules.header_ocr_corrections'" in script
    assert "'--include-module=_metroliza_cmm_native'" in script
    assert "'--include-module=_metroliza_chart_native'" in script
    assert "'--include-module=_metroliza_group_stats_native'" in script
    assert "'--include-module=_metroliza_comparison_stats_native'" in script
    assert "'--include-module=_metroliza_distribution_fit_native'" in script
    assert "'--include-module=modules.report_parser_factory'" in script
    assert "'--include-module=modules.pdf_backend'" in script
    assert "'--include-package-data=pymupdf'" in script
    assert "'--include-package-data=fitz'" in script
    assert "'--include-package=rapidocr'" in script
    assert "'--include-package=onnxruntime'" in script
    assert "'--include-package=openvino'" in script
    assert "'--include-package=cv2'" in script
    assert "'--include-package=numpy'" in script
    assert "'--include-package-data=rapidocr'" in script
    assert "'--include-package-data=onnxruntime'" in script
    assert "'--include-package-data=openvino'" in script
    assert "'--include-package-data=cv2'" in script
    assert "'--include-package-data=numpy'" in script
    assert "'--include-distribution-metadata=rapidocr'" in script
    assert "'--include-distribution-metadata=onnxruntime'" in script
    assert "'--include-distribution-metadata=openvino'" in script
    assert "'--include-distribution-metadata=opencv-python'" in script
    assert "'--include-distribution-metadata=numpy'" in script
    assert 'ch_PP-OCRv4_det_mobile.onnx' in script
    assert 'ch_ppocr_mobile_v2.0_cls_mobile.onnx' in script
    assert 'latin_PP-OCRv3_rec_mobile.onnx' in script
    assert 'THIRD_PARTY_NOTICES.md' in script
    assert '--include-data-files=$($resolvedThirdPartyNotices.Path)=THIRD_PARTY_NOTICES.md' in script
    assert '--require-header-ocr' in script
    assert "src/metroliza/resources/html_dashboard_assets/plotly-2.27.0.min.js" in script
    assert '--include-data-files=$($resolvedPlotlyDashboardAsset.Path)=metroliza/resources/html_dashboard_assets/plotly-2.27.0.min.js' in script
    assert 'if ($BundleCredentials)' in script
    assert "Credential bundling disabled; OAuth credentials must remain outside the packaged artifact." in script
    assert "Credential bundling was requested, but '$CredentialsPath' was not found." in script
    assert "$commonArgs += '--include-package=pymupdf'" in script
    assert "$commonArgs += '--include-package=fitz'" in script
    assert "'pymupdf._mupdf'" in script
    assert "'pymupdf._extra'" in script
    assert 'foreach ($moduleName in $requiredPdfBackendModules)' in script
    assert "$commonArgs += '--onefile'" in script
    assert "$commonArgs += '--standalone'" in script
    assert "$commonArgs += '--mingw64'" in script
    assert "$commonArgs += '--clang'" in script
    assert 'intentionally avoids MSVC/Visual Studio Build Tools and prefers MinGW-w64 GCC' in script


def test_pyinstaller_spec_collects_windows_runtime_and_pdf_parser_dependencies():
    spec = Path('packaging/metroliza_onefile.spec').read_text(encoding='utf-8')
    entry = Path('packaging/metroliza_package_entry.py').read_text(encoding='utf-8')
    common = Path('packaging/pyinstaller_common.py').read_text(encoding='utf-8')

    assert 'from pyinstaller_common import build_pyinstaller_collection' in spec
    assert 'from metroliza.app.bootstrap import run_application' in entry
    assert 'This file intentionally is not named ``metroliza.py``.' in entry
    assert 'from PyInstaller.utils.hooks import (' in common
    assert 'def collect_windows_python_runtime_binaries()' in common
    assert 'collect_required_runtime_assets(\n        "pymupdf"\n    )' in common
    assert 'collect_required_runtime_assets("fitz")' in common
    assert 'collect_required_runtime_assets("hexafe_plotstats")' in common
    assert 'collect_required_runtime_assets("oznak")' in common
    assert 'collect_required_runtime_assets(\n        "rapidocr"\n    )' in common
    assert 'collect_required_runtime_assets("onnxruntime")' in common
    assert 'collect_required_runtime_assets(\n        "openvino"\n    )' in common
    assert 'collect_required_runtime_assets("cv2")' in common
    assert 'collect_required_runtime_assets("numpy")' in common
    assert 'collect_optional_distribution_metadata("rapidocr")' in common
    assert 'collect_optional_distribution_metadata("onnxruntime")' in common
    assert 'collect_optional_distribution_metadata("openvino")' in common
    assert 'collect_optional_distribution_metadata("opencv-python")' in common
    assert 'collect_optional_distribution_metadata("numpy")' in common
    assert 'collect_optional_distribution_metadata("hexafe-plotstats")' in common
    assert 'collect_optional_distribution_metadata("oznak")' in common
    assert 'def collect_optional_vendored_model_data(root_dir: Path)' in common
    assert 'plotly-2.27.0.min.js' in common
    assert 'THIRD_PARTY_NOTICES.md' in common
    assert 'binaries=COLLECTION["binaries"]' in spec
    assert 'datas=COLLECTION["datas"]' in spec
    assert 'hiddenimports=COLLECTION["hiddenimports"]' in spec
    assert '"metroliza.parsing.cmm_report_parser"' in common
    assert '"metroliza.charts.native_chart_compositor"' in common
    assert '"modules.cmm_report_parser"' in common
    assert '"modules.native_chart_compositor"' in common
    assert '"rapidocr"' in common
    assert '"onnxruntime"' in common
    assert '"openvino"' in common
    assert '"cv2"' in common
    assert '"numpy"' in common
    assert '"_metroliza_group_stats_native"' in common
    assert '"_metroliza_comparison_stats_native"' in common
    assert '"_metroliza_distribution_fit_native"' in common
    assert '"hexafe_plotstats"' in common
    assert '"oznak"' in common
    assert '*hexafe_plotstats_hiddenimports' in common
    assert '*oznak_hiddenimports' in common
    assert '*rapidocr_hiddenimports' in common
    assert '*onnxruntime_hiddenimports' in common
    assert '*openvino_hiddenimports' in common
    assert '*cv2_hiddenimports' in common
    assert '*numpy_hiddenimports' in common
    assert "runtime_tmpdir=None" in spec
    assert 'exe = EXE(' in spec
    assert 'COLLECT(' not in spec


def test_pyinstaller_vendored_ocr_models_use_runtime_resource_destination(tmp_path):
    module_name = "_metroliza_pyinstaller_common_under_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path("packaging/pyinstaller_common.py"),
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    current_model = (
        tmp_path
        / "src"
        / "metroliza"
        / "resources"
        / "ocr_models"
        / "rapidocr"
        / "latin_PP-OCRv3_rec_mobile.onnx"
    )
    legacy_root_model = tmp_path / "ocr_models" / "rapidocr" / "legacy-root.onnx"
    legacy_modules_model = tmp_path / "modules" / "ocr_models" / "rapidocr" / "legacy-modules.onnx"
    for model_file in (current_model, legacy_root_model, legacy_modules_model):
        model_file.parent.mkdir(parents=True, exist_ok=True)
        model_file.write_bytes(b"model")

    datas = module.collect_optional_vendored_model_data(tmp_path)

    assert (
        str(current_model),
        "metroliza/resources/ocr_models/rapidocr",
    ) in datas
    assert (
        str(legacy_root_model),
        "metroliza/resources/ocr_models/rapidocr",
    ) in datas
    assert (
        str(legacy_modules_model),
        "metroliza/resources/ocr_models/rapidocr",
    ) in datas
    assert not any(destination.startswith("src/") for _source, destination in datas)


def test_pyinstaller_required_collection_fails_when_dependency_is_missing(monkeypatch):
    module_name = "_metroliza_pyinstaller_required_collection_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path("packaging/pyinstaller_common.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_package_is_installed", lambda _name: False)

    with pytest.raises(RuntimeError, match="required_dependency.*not installed"):
        module.collect_required_runtime_assets("required_dependency")

    assert module.collect_optional_runtime_assets("optional_dependency") == ([], [], [])


def test_pyinstaller_required_collection_does_not_hide_hook_failures(monkeypatch):
    module_name = "_metroliza_pyinstaller_failed_collection_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path("packaging/pyinstaller_common.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_package_is_installed", lambda _name: True)
    monkeypatch.setattr(
        module,
        "collect_data_files",
        lambda _name: (_ for _ in ()).throw(ValueError("broken hook")),
    )

    with pytest.raises(RuntimeError, match="Failed to collect.*required_dependency") as exc_info:
        module.collect_required_runtime_assets("required_dependency")

    assert isinstance(exc_info.value.__cause__, ValueError)


def test_pyinstaller_installed_optional_collection_does_not_hide_hook_failures(monkeypatch):
    module_name = "_metroliza_pyinstaller_optional_collection_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path("packaging/pyinstaller_common.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_package_is_installed", lambda _name: True)
    monkeypatch.setattr(
        module,
        "collect_data_files",
        lambda _name: (_ for _ in ()).throw(ValueError("broken optional hook")),
    )

    with pytest.raises(ValueError, match="broken optional hook"):
        module.collect_optional_runtime_assets("optional_dependency")


def test_pyinstaller_onedir_collects_only_onnx_inference_runtime_graph():
    onedir = Path("packaging/metroliza_onedir.spec").read_text(encoding="utf-8")
    onefile = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")
    common = Path("packaging/pyinstaller_common.py").read_text(encoding="utf-8")
    module_name = "_metroliza_pyinstaller_onedir_onnx_runtime_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path("packaging/pyinstaller_common.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    hiddenimports = [
        "onnxruntime",
        "onnxruntime.backend",
        "onnxruntime.capi",
        "onnxruntime.capi.onnxruntime_inference_collection",
        "onnxruntime.capi._pybind_state",
        "onnxruntime.datasets",
        "onnxruntime.future_offline",
        "onnxruntime.quantization",
        "onnxruntime.tools",
        "onnxruntime.transformers.models.gpt2",
        "rapidocr.inference_engine.onnxruntime",
        "metroliza.parsing.header_ocr_backend",
    ]

    assert module.filter_onedir_hiddenimports(hiddenimports) == [
        "onnxruntime",
        "onnxruntime.capi",
        "onnxruntime.capi.onnxruntime_inference_collection",
        "onnxruntime.capi._pybind_state",
        "rapidocr.inference_engine.onnxruntime",
        "metroliza.parsing.header_ocr_backend",
    ]
    assert module.ONEDIR_OFFLINE_ONNXRUNTIME_NAMESPACES == (
        "onnxruntime.backend",
        "onnxruntime.datasets",
        "onnxruntime.quantization",
        "onnxruntime.tools",
        "onnxruntime.transformers",
    )

    assert 'filter_onedir_hiddenimports(COLLECTION["hiddenimports"])' in onedir
    assert "excludes=list(ONEDIR_OFFLINE_ONNXRUNTIME_NAMESPACES)" in onedir
    assert 'collect_required_runtime_assets("onnxruntime")' in common
    assert "+ onnxruntime_binaries" in common
    assert "+ onnxruntime_datas" in common
    assert "*onnxruntime_hiddenimports" in common
    assert 'collect_optional_distribution_metadata("onnxruntime")' in common
    assert "collect_optional_vendored_model_data(root_dir)" in common
    assert 'hiddenimports=COLLECTION["hiddenimports"]' in onefile
    assert "filter_onedir_hiddenimports" not in onefile
    for root in (Path("src/metroliza"), Path("modules")):
        assert not any(
            any(
                namespace in source.read_text(encoding="utf-8")
                for namespace in module.ONEDIR_OFFLINE_ONNXRUNTIME_NAMESPACES
            )
            for source in root.rglob("*.py")
        )


def _load_pyinstaller_common(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path("packaging/pyinstaller_common.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _fake_scanner_isolated(native_death):
    import_sessions = []

    class _Child:
        def __init__(self):
            self.imported = []
            self._child = types.SimpleNamespace(returncode=3221225477)

        def call(self, function, *args, **kwargs):
            if function.__name__ == "_verify_loaded_module":
                return args[0] in self.imported
            if function.__name__ == "import_library":
                package = args[0]
                if (
                    package == "onnxruntime"
                    and "PyQt6" in self.imported
                    and package not in self.imported
                ):
                    raise native_death("expected control crash")
                if package not in self.imported:
                    self.imported.append(package)
                return None
            return function(*args, **kwargs)

    class _Python:
        def __enter__(self):
            child = _Child()
            import_sessions.append(child.imported)
            return child

        def __exit__(self, *_args):
            return False

    isolated = types.SimpleNamespace(
        Python=_Python,
        SubprocessDiedError=native_death,
        call=lambda *_args, **_kwargs: True,
    )
    return isolated, import_sessions, _Python


def _run_fake_scanner_child(isolated, setup, import_library, packages):
    try:
        with isolated.Python() as child:
            child.call(setup, [])
            for package in packages:
                child.call(import_library, package)
    except isolated.SubprocessDiedError as inner:
        raise isolated.SubprocessDiedError("outer scanner failure") from inner


def test_windows_onedir_scanner_probe_delegates_full_scan_and_restores(
    monkeypatch,
    capsys,
):
    module = _load_pyinstaller_common("_metroliza_pyinstaller_probe_delegate_test")
    calls = []

    class SubprocessDiedError(RuntimeError):
        pass

    isolated, isolated_imports, original_python = _fake_scanner_isolated(
        SubprocessDiedError
    )

    def setup(suppressed_imports):
        return suppressed_imports

    def original(binaries, import_packages, symlink_suppression_patterns):
        calls.append((binaries, import_packages, symlink_suppression_patterns))
        _run_fake_scanner_child(isolated, setup, import_library, import_packages)
        return ["expanded"]

    def import_library(package):
        return package

    build_main = types.SimpleNamespace(find_binary_dependencies=original)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("METROLIZA_PYINSTALLER_SCANNER_PROBE", "1")
    monkeypatch.setattr(
        module,
        "_load_pyinstaller_binary_scanner",
        lambda: ("6.22.3", "1.30.0", build_main, isolated),
    )
    binaries, packages, patterns = ["binary"], ["cv2", "onnxruntime"], {"pattern"}

    with module.onedir_binary_scanner_probe():
        installed = build_main.find_binary_dependencies
        assert installed is not original
        assert installed(binaries, packages, patterns) == ["expanded"]

    assert build_main.find_binary_dependencies is original
    assert isolated.Python is original_python
    assert calls == [
        ([], ["onnxruntime"], set()),
        ([], ["PyQt6", "onnxruntime"], set()),
        ([], ["PyQt6", "onnxruntime"], set()),
        (binaries, packages, patterns),
    ]
    assert isolated_imports == [
        ["onnxruntime"],
        ["PyQt6"],
        ["onnxruntime", "PyQt6"],
        ["onnxruntime", "cv2"],
    ]
    output = capsys.readouterr().out
    assert "outer scanner failure" not in output
    payloads = [json.loads(line) for line in output.splitlines()]
    assert payloads == [
        {
            "kind": "pyinstaller_scanner_probe",
            "scenario": "onnxruntime_direct",
            "schema_version": 1,
            "status": "started",
        },
        {
            "kind": "pyinstaller_scanner_probe",
            "scenario": "onnxruntime_direct",
            "schema_version": 1,
            "status": "passed",
        },
        {
            "kind": "pyinstaller_scanner_probe",
            "scenario": "onnxruntime_scanner",
            "schema_version": 1,
            "status": "started",
        },
        {
            "kind": "pyinstaller_scanner_probe",
            "scenario": "onnxruntime_scanner",
            "schema_version": 1,
            "status": "passed",
        },
        {
            "kind": "pyinstaller_scanner_probe",
            "scenario": "pyqt6_then_onnxruntime",
            "schema_version": 1,
            "status": "started",
        },
        {
            "child_exit_code": 3221225477,
            "kind": "pyinstaller_scanner_probe",
            "scenario": "pyqt6_then_onnxruntime",
            "schema_version": 1,
            "status": "scanner_child_died_during_onnxruntime_after_pyqt6",
        },
        {
            "kind": "pyinstaller_scanner_probe",
            "scenario": "onnxruntime_before_pyqt6",
            "schema_version": 1,
            "status": "started",
        },
        {
            "kind": "pyinstaller_scanner_probe",
            "scenario": "onnxruntime_before_pyqt6",
            "schema_version": 1,
            "status": "passed",
        },
    ]


def test_windows_onedir_scanner_probe_runs_both_cases_and_closes_failures(
    monkeypatch,
    capsys,
):
    module = _load_pyinstaller_common("_metroliza_pyinstaller_probe_failure_test")
    calls = []

    class SubprocessDiedError(RuntimeError):
        pass

    class _Child:
        def call(self, function, *args, **kwargs):
            if function.__name__ == "import_library" and args == ("onnxruntime",):
                raise SubprocessDiedError("raw corrected native details")
            if function.__name__ == "_verify_loaded_module":
                return True
            return function(*args, **kwargs)

    class _Python:
        def __enter__(self):
            return _Child()

        def __exit__(self, *_args):
            return False

    isolated = types.SimpleNamespace(Python=_Python, call=lambda *_args, **_kwargs: True)

    def setup(suppressed_imports):
        return suppressed_imports

    def import_library(package):
        return package

    def original(binaries, import_packages, symlink_suppression_patterns):
        calls.append(import_packages)
        failure = {
            1: SubprocessDiedError("raw native details"),
            2: ValueError("raw python details"),
        }.get(len(calls))
        if failure is not None:
            raise failure
        with isolated.Python() as child:
            child.call(setup, [])
            child.call(import_library, "PyQt6")
        return []

    isolated.SubprocessDiedError = SubprocessDiedError
    build_main = types.SimpleNamespace(find_binary_dependencies=original)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("METROLIZA_PYINSTALLER_SCANNER_PROBE", "1")
    monkeypatch.setattr(
        module,
        "_load_pyinstaller_binary_scanner",
        lambda: ("6.22.3", "1.30.0", build_main, isolated),
    )

    with pytest.raises(RuntimeError, match="Windows onedir scanner probe failed"):
        with module.onedir_binary_scanner_probe():
            build_main.find_binary_dependencies(["binary"], ["actual"], {"pattern"})

    assert build_main.find_binary_dependencies is original
    assert isolated.Python is _Python
    assert calls == [
        ["onnxruntime"],
        ["PyQt6", "onnxruntime"],
        ["PyQt6", "onnxruntime"],
    ]
    output = capsys.readouterr().out
    assert "raw native details" not in output
    assert "raw python details" not in output
    assert "raw corrected native details" not in output
    payloads = [json.loads(line) for line in output.splitlines()]
    assert [payload["status"] for payload in payloads] == [
        "started",
        "passed",
        "started",
        "scanner_child_died",
        "started",
        "python_failed",
        "started",
        "scanner_child_died",
    ]


def test_windows_onedir_scanner_probe_preserves_full_scan_failure(monkeypatch):
    module = _load_pyinstaller_common("_metroliza_pyinstaller_probe_full_failure_test")
    full_failure = LookupError("full scanner failed")
    call_count = 0

    class SubprocessDiedError(RuntimeError):
        pass

    isolated, _imports, original_python = _fake_scanner_isolated(SubprocessDiedError)

    def setup(suppressed_imports):
        return suppressed_imports

    def import_library(package):
        return package

    def original(binaries, import_packages, symlink_suppression_patterns):
        nonlocal call_count
        call_count += 1
        with isolated.Python() as child:
            child.call(setup, [])
            for package in import_packages:
                child.call(import_library, package)
        if call_count == 4:
            raise full_failure
        return []

    build_main = types.SimpleNamespace(find_binary_dependencies=original)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("METROLIZA_PYINSTALLER_SCANNER_PROBE", "1")
    monkeypatch.setattr(
        module,
        "_load_pyinstaller_binary_scanner",
        lambda: ("6.22.3", "1.30.0", build_main, isolated),
    )

    with pytest.raises(LookupError) as exc_info:
        with module.onedir_binary_scanner_probe():
            build_main.find_binary_dependencies(["binary"], ["actual"], {"pattern"})

    assert exc_info.value is full_failure
    assert build_main.find_binary_dependencies is original
    assert isolated.Python is original_python


@pytest.mark.parametrize(
    ("version", "scanner"),
    [
        ("6.22.4", lambda binaries, import_packages, symlink_suppression_patterns: []),
        ("6.22.3", lambda binaries, import_packages: []),
    ],
)
def test_windows_onedir_scanner_probe_fails_closed_on_pyinstaller_drift(
    monkeypatch,
    version,
    scanner,
):
    module = _load_pyinstaller_common("_metroliza_pyinstaller_probe_drift_test")
    build_main = types.SimpleNamespace(find_binary_dependencies=scanner)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("METROLIZA_PYINSTALLER_SCANNER_PROBE", "1")
    monkeypatch.setattr(
        module,
        "_load_pyinstaller_binary_scanner",
        lambda: (
            version,
            "1.30.0",
            build_main,
            types.SimpleNamespace(
                Python=object,
                SubprocessDiedError=RuntimeError,
                call=lambda *_args, **_kwargs: True,
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="PyInstaller 6.22.3"):
        with module.onedir_binary_scanner_probe():
            pass

    assert build_main.find_binary_dependencies is scanner


def test_onedir_binary_scanner_probe_skips_non_windows(monkeypatch):
    module = _load_pyinstaller_common("_metroliza_pyinstaller_probe_opt_in_test")
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.delenv("METROLIZA_PYINSTALLER_SCANNER_PROBE", raising=False)
    monkeypatch.setattr(
        module,
        "_load_pyinstaller_binary_scanner",
        lambda: (_ for _ in ()).throw(AssertionError("must not load PyInstaller")),
    )

    with module.onedir_binary_scanner_probe():
        pass


def test_windows_onedir_scanner_preload_is_default_without_controls(
    monkeypatch,
    capsys,
):
    module = _load_pyinstaller_common("_metroliza_pyinstaller_preload_default_test")

    class SubprocessDiedError(RuntimeError):
        pass

    isolated, imports, original_python = _fake_scanner_isolated(SubprocessDiedError)

    def setup(suppressed_imports):
        return suppressed_imports

    def import_library(package):
        return package

    def original(binaries, import_packages, symlink_suppression_patterns):
        with isolated.Python() as child:
            child.call(setup, [])
            for package in import_packages:
                child.call(import_library, package)
        return binaries, symlink_suppression_patterns

    build_main = types.SimpleNamespace(find_binary_dependencies=original)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.delenv("METROLIZA_PYINSTALLER_SCANNER_PROBE", raising=False)
    monkeypatch.setattr(
        module,
        "_load_pyinstaller_binary_scanner",
        lambda: ("6.22.3", "1.30.0", build_main, isolated),
    )

    with module.onedir_binary_scanner_probe():
        assert build_main.find_binary_dependencies(["binary"], ["PyQt6"], set()) == (
            ["binary"],
            set(),
        )

    assert imports == [["onnxruntime", "PyQt6"]]
    assert capsys.readouterr().out == ""
    assert build_main.find_binary_dependencies is original
    assert isolated.Python is original_python


def test_onedir_binary_scanner_probe_is_targeted_application_analysis_only():
    onedir = Path("packaging/metroliza_onedir.spec").read_text(encoding="utf-8")
    onefile = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    build_requirements = Path("requirements-build.txt").read_text(encoding="utf-8")
    application_analysis, launcher_analysis = onedir.split("launcher_analysis = Analysis(", maxsplit=1)
    build_step = workflow.split(
        "- name: Build actual Windows onedir and minimal incident launcher",
        maxsplit=1,
    )[1].split("- name: Qualify actual packaged incident flow", maxsplit=1)[0]

    assert application_analysis.count("with onedir_binary_scanner_probe():") == 1
    assert "a = Analysis(" in application_analysis
    assert "with onedir_binary_scanner_probe():" not in launcher_analysis
    assert "onedir_binary_scanner_probe" not in onefile
    assert 'METROLIZA_PYINSTALLER_SCANNER_PROBE: "1"' in build_step
    assert "pyinstaller==6.22.3" in build_requirements.splitlines()


def test_vendored_plotly_dashboard_asset_is_checked_in():
    asset = Path('src/metroliza/resources/html_dashboard_assets/plotly-2.27.0.min.js')

    assert asset.exists()
    assert asset.stat().st_size > 1_000_000
