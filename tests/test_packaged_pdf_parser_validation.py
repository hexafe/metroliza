from __future__ import annotations

import importlib.util
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
    assert "'--include-module=metroliza.parsing.header_ocr_backend'" in script
    assert "'--include-module=metroliza.parsing.header_ocr_geometry'" in script
    assert "'--include-module=metroliza.parsing.header_ocr_corrections'" in script
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


def test_vendored_plotly_dashboard_asset_is_checked_in():
    asset = Path('src/metroliza/resources/html_dashboard_assets/plotly-2.27.0.min.js')

    assert asset.exists()
    assert asset.stat().st_size > 1_000_000
