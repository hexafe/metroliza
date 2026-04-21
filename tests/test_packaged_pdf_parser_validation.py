from __future__ import annotations

import importlib.util
import textwrap
import types
from pathlib import Path

import pytest

from modules import pdf_backend
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
              <module name="modules.cmm_report_parser" />
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
    report.write_text('<nuitka-report><module name="modules.cmm_report_parser" /></nuitka-report>', encoding='utf-8')

    with pytest.raises(PackagingValidationError):
        validate_nuitka_report_has_pdf_backend(report)


def test_validate_nuitka_report_has_pdf_backend_rejects_missing_runtime_modules(tmp_path):
    report = tmp_path / 'nuitka-build-report.xml'
    report.write_text(
        '<nuitka-report><module name="modules.cmm_report_parser" /><module name="pymupdf" /></nuitka-report>',
        encoding='utf-8',
    )

    with pytest.raises(PackagingValidationError, match='missing required PyMuPDF runtime modules'):
        validate_nuitka_report_has_pdf_backend(report)


def test_require_header_ocr_available_reports_missing_dependency(monkeypatch):
    monkeypatch.setattr(importlib.util, 'find_spec', lambda _name: None)

    with pytest.raises(PackagingValidationError, match='Header OCR dependencies are missing'):
        require_header_ocr_available()


def test_validate_vendored_header_ocr_models_rejects_missing_assets(tmp_path):
    with pytest.raises(PackagingValidationError, match='Vendored RapidOCR model validation failed'):
        validate_vendored_header_ocr_models(tmp_path)


def test_validate_nuitka_report_has_header_ocr_accepts_report(tmp_path):
    report = tmp_path / 'nuitka-build-report.xml'
    report.write_text(
        textwrap.dedent(
            '''
            <nuitka-report>
              <module name="modules.header_ocr_backend" />
              <module name="modules.header_ocr_geometry" />
              <module name="modules.header_ocr_corrections" />
              <module name="rapidocr" />
              <module name="onnxruntime" />
              <module name="cv2" />
              <module name="numpy" />
              <data-file name="modules/ocr_models/rapidocr/ch_PP-OCRv4_det_mobile.onnx" />
              <data-file name="modules/ocr_models/rapidocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx" />
              <data-file name="modules/ocr_models/rapidocr/latin_PP-OCRv3_rec_mobile.onnx" />
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
              <module name="modules.header_ocr_backend" />
              <module name="modules.header_ocr_geometry" />
              <module name="modules.header_ocr_corrections" />
              <module name="rapidocr" />
              <module name="onnxruntime" />
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
              <module name="modules.header_ocr_backend" />
              <module name="modules.header_ocr_geometry" />
              <module name="modules.header_ocr_corrections" />
              <module name="rapidocr" />
              <module name="onnxruntime" />
              <module name="cv2" />
              <module name="numpy" />
              <data-file name="modules/ocr_models/rapidocr/ch_PP-OCRv4_det_mobile.onnx" />
              <data-file name="modules/ocr_models/rapidocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx" />
              <data-file name="modules/ocr_models/rapidocr/latin_PP-OCRv3_rec_mobile.onnx" />
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
        'RapidOCR Apache-2.0 Baidu ONNX Runtime MIT OpenCV NumPy BSD-3-Clause',
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
    assert "[ValidateSet('auto', 'gcc', 'clang')]" in script
    assert "[string]$CompilerStrategy = 'auto'" in script
    assert '[switch]$AutoInstallCompiler' in script
    assert '[switch]$OpenInstallHelp' in script
    assert 'PyMuPDF is required for packaged builds.' in script
    assert 'UNSAFE: continuing even though packaged PDF parsing may be broken.' in script
    assert 'RapidOCR header OCR is required for packaged builds.' in script
    assert 'UNSAFE: continuing even though packaged header OCR may be broken.' in script
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

    assert "$modeLabel = if ($FastDev) { 'standalone (faster dev build)' } else { 'onefile (release-like build)' }" in script
    assert "'--include-package=modules'" in script
    assert "'--include-package=hexafe_groupstats'" in script
    assert "'--include-module=modules.cmm_report_parser'" in script
    assert "'--include-module=modules.header_ocr_backend'" in script
    assert "'--include-module=modules.header_ocr_geometry'" in script
    assert "'--include-module=modules.header_ocr_corrections'" in script
    assert "'--include-module=_metroliza_cmm_native'" in script
    assert "'--include-module=_metroliza_chart_native'" in script
    assert "'--include-module=modules.report_parser_factory'" in script
    assert "'--include-module=modules.pdf_backend'" in script
    assert "'--include-package-data=pymupdf'" in script
    assert "'--include-package-data=fitz'" in script
    assert "'--include-package=rapidocr'" in script
    assert "'--include-package=onnxruntime'" in script
    assert "'--include-package=cv2'" in script
    assert "'--include-package=numpy'" in script
    assert "'--include-package-data=rapidocr'" in script
    assert "'--include-package-data=onnxruntime'" in script
    assert "'--include-package-data=cv2'" in script
    assert "'--include-package-data=numpy'" in script
    assert "'--include-distribution-metadata=rapidocr'" in script
    assert "'--include-distribution-metadata=onnxruntime'" in script
    assert "'--include-distribution-metadata=opencv-python'" in script
    assert "'--include-distribution-metadata=numpy'" in script
    assert 'ch_PP-OCRv4_det_mobile.onnx' in script
    assert 'ch_ppocr_mobile_v2.0_cls_mobile.onnx' in script
    assert 'latin_PP-OCRv3_rec_mobile.onnx' in script
    assert 'THIRD_PARTY_NOTICES.md' in script
    assert '--include-data-files=$($resolvedThirdPartyNotices.Path)=THIRD_PARTY_NOTICES.md' in script
    assert '--require-header-ocr' in script
    assert "modules/html_dashboard_assets/plotly-2.27.0.min.js" in script
    assert '--include-data-files=$($resolvedPlotlyDashboardAsset.Path)=modules/html_dashboard_assets/plotly-2.27.0.min.js' in script
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

    assert 'from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata' in spec
    assert 'def _collect_windows_python_runtime_binaries()' in spec
    assert "pymupdf_datas, pymupdf_binaries, pymupdf_hiddenimports = _collect_optional_runtime_assets('pymupdf')" in spec
    assert "fitz_datas, fitz_binaries, fitz_hiddenimports = _collect_optional_runtime_assets('fitz')" in spec
    assert "rapidocr_datas, rapidocr_binaries, rapidocr_hiddenimports = _collect_optional_runtime_assets('rapidocr')" in spec
    assert "onnxruntime_datas, onnxruntime_binaries, onnxruntime_hiddenimports = _collect_optional_runtime_assets('onnxruntime')" in spec
    assert "cv2_datas, cv2_binaries, cv2_hiddenimports = _collect_optional_runtime_assets('cv2')" in spec
    assert "numpy_datas, numpy_binaries, numpy_hiddenimports = _collect_optional_runtime_assets('numpy')" in spec
    assert "rapidocr_metadata_datas = _collect_optional_distribution_metadata('rapidocr')" in spec
    assert "onnxruntime_metadata_datas = _collect_optional_distribution_metadata('onnxruntime')" in spec
    assert "opencv_python_metadata_datas = _collect_optional_distribution_metadata('opencv-python')" in spec
    assert "numpy_metadata_datas = _collect_optional_distribution_metadata('numpy')" in spec
    assert 'def _collect_optional_vendored_model_data()' in spec
    assert "html_dashboard_datas = [(str(ROOT_DIR / 'modules' / 'html_dashboard_assets' / 'plotly-2.27.0.min.js'), 'modules/html_dashboard_assets')]" in spec
    assert "third_party_notice_datas = [(str(ROOT_DIR / 'THIRD_PARTY_NOTICES.md'), '.')]" in spec
    assert "binaries=windows_runtime_binaries + pymupdf_binaries + fitz_binaries + hexafe_groupstats_binaries + rapidocr_binaries + onnxruntime_binaries + cv2_binaries + numpy_binaries" in spec
    assert "datas=third_party_notice_datas + html_dashboard_datas + pymupdf_datas + fitz_datas + hexafe_groupstats_datas + rapidocr_datas + onnxruntime_datas + cv2_datas + numpy_datas + rapidocr_metadata_datas + onnxruntime_metadata_datas + opencv_python_metadata_datas + numpy_metadata_datas + ocr_model_datas" in spec
    assert "'modules.cmm_report_parser'" in spec
    assert "'modules.native_chart_compositor'" in spec
    assert "'rapidocr'" in spec
    assert "'onnxruntime'" in spec
    assert "'cv2'" in spec
    assert "'numpy'" in spec
    assert '*rapidocr_hiddenimports' in spec
    assert '*onnxruntime_hiddenimports' in spec
    assert '*cv2_hiddenimports' in spec
    assert '*numpy_hiddenimports' in spec
    assert "runtime_tmpdir=None" in spec
    assert 'exe = EXE(' in spec
    assert 'COLLECT(' not in spec


def test_vendored_plotly_dashboard_asset_is_checked_in():
    asset = Path('modules/html_dashboard_assets/plotly-2.27.0.min.js')

    assert asset.exists()
    assert asset.stat().st_size > 1_000_000
