from pathlib import Path


def test_onefile_spec_includes_builtin_cmm_parser_hiddenimport():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")

    assert "modules.cmm_report_parser" in spec_text
    assert "modules.native_chart_compositor" in spec_text
    assert "_metroliza_cmm_native" in spec_text
    assert "_metroliza_chart_native" in spec_text
    assert "modules.header_ocr_backend" in spec_text
    assert "modules.header_ocr_geometry" in spec_text
    assert "modules.header_ocr_corrections" in spec_text


def test_onefile_spec_collects_hexafe_groupstats_hiddenimports():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")

    assert "_collect_optional_runtime_assets('hexafe_groupstats')" in spec_text
    assert "'hexafe_groupstats'" in spec_text
    assert "*hexafe_groupstats_hiddenimports" in spec_text


def test_onefile_spec_collects_ocr_runtime_assets_and_model_data():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")

    assert "copy_metadata" in spec_text
    assert "_collect_optional_runtime_assets('rapidocr')" in spec_text
    assert "_collect_optional_runtime_assets('onnxruntime')" in spec_text
    assert "_collect_optional_runtime_assets('cv2')" in spec_text
    assert "_collect_optional_runtime_assets('numpy')" in spec_text
    assert "_collect_optional_distribution_metadata('rapidocr')" in spec_text
    assert "_collect_optional_distribution_metadata('onnxruntime')" in spec_text
    assert "_collect_optional_distribution_metadata('opencv-python')" in spec_text
    assert "_collect_optional_distribution_metadata('numpy')" in spec_text
    assert "_collect_optional_vendored_model_data()" in spec_text
    assert "ROOT_DIR / 'ocr_models'" in spec_text
    assert "ROOT_DIR / 'modules' / 'ocr_models'" in spec_text
    assert "THIRD_PARTY_NOTICES.md" in spec_text
    assert "third_party_notice_datas" in spec_text
    assert "*rapidocr_hiddenimports" in spec_text
    assert "*onnxruntime_hiddenimports" in spec_text
    assert "*cv2_hiddenimports" in spec_text
    assert "*numpy_hiddenimports" in spec_text


def test_windows_pyinstaller_build_validates_ocr_packaging_inputs():
    script_text = Path("build_windows_exe.ps1").read_text(encoding="utf-8")

    assert "requirements-ocr.txt" in script_text
    assert "scripts/validate_packaged_pdf_parser.py" in script_text
    assert "--require-header-ocr" in script_text


def test_onefile_spec_uses_release_metadata_pyinstaller_output_name():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")

    assert 'OUTPUT_NAME = f"metroliza_P_{VERSION_LABEL}"' in spec_text
    assert "name=OUTPUT_NAME" in spec_text
