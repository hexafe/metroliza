from pathlib import Path


def test_onefile_spec_includes_builtin_cmm_parser_hiddenimport():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")
    common_text = Path("packaging/pyinstaller_common.py").read_text(encoding="utf-8")

    assert "build_pyinstaller_collection" in spec_text
    assert 'metroliza_package_entry.py' in spec_text
    assert 'pathex=[str(ROOT_DIR / "src"), str(ROOT_DIR)]' in spec_text
    assert "metroliza.parsing.cmm_report_parser" in common_text
    assert "metroliza.charts.native_chart_compositor" in common_text
    assert "modules.cmm_report_parser" in common_text
    assert "modules.native_chart_compositor" in common_text
    assert "_metroliza_cmm_native" in common_text
    assert "_metroliza_chart_native" in common_text
    assert "_metroliza_group_stats_native" in common_text
    assert "_metroliza_comparison_stats_native" in common_text
    assert "_metroliza_distribution_fit_native" in common_text
    assert "modules.header_ocr_backend" in common_text
    assert "modules.header_ocr_geometry" in common_text
    assert "modules.header_ocr_corrections" in common_text


def test_onefile_spec_collects_hexafe_groupstats_hiddenimports():
    spec_text = Path("packaging/pyinstaller_common.py").read_text(encoding="utf-8")

    assert 'collect_required_runtime_assets("hexafe_groupstats")' in spec_text
    assert '"hexafe_groupstats"' in spec_text
    assert "*hexafe_groupstats_hiddenimports" in spec_text


def test_onefile_spec_collects_hexafe_plotstats_hiddenimports():
    spec_text = Path("packaging/pyinstaller_common.py").read_text(encoding="utf-8")

    assert 'collect_required_runtime_assets("hexafe_plotstats")' in spec_text
    assert 'collect_optional_distribution_metadata("hexafe-plotstats")' in spec_text
    assert '"hexafe_plotstats"' in spec_text
    assert "*hexafe_plotstats_hiddenimports" in spec_text


def test_onefile_spec_collects_optional_oznak_hiddenimports():
    spec_text = Path("packaging/pyinstaller_common.py").read_text(encoding="utf-8")

    assert 'collect_required_runtime_assets("oznak")' in spec_text
    assert 'collect_optional_distribution_metadata("oznak")' in spec_text
    assert '"oznak"' in spec_text
    assert "*oznak_hiddenimports" in spec_text


def test_onefile_spec_collects_ocr_runtime_assets_and_model_data():
    spec_text = Path("packaging/pyinstaller_common.py").read_text(encoding="utf-8")

    assert "copy_metadata" in spec_text
    assert 'collect_required_runtime_assets(\n        "rapidocr"\n    )' in spec_text
    assert 'collect_required_runtime_assets("onnxruntime")' in spec_text
    assert 'collect_required_runtime_assets(\n        "openvino"\n    )' in spec_text
    assert 'collect_required_runtime_assets("cv2")' in spec_text
    assert 'collect_required_runtime_assets("numpy")' in spec_text
    assert 'collect_optional_distribution_metadata("rapidocr")' in spec_text
    assert 'collect_optional_distribution_metadata("onnxruntime")' in spec_text
    assert 'collect_optional_distribution_metadata("openvino")' in spec_text
    assert 'collect_optional_distribution_metadata("opencv-python")' in spec_text
    assert 'collect_optional_distribution_metadata("numpy")' in spec_text
    assert "collect_optional_vendored_model_data(root_dir)" in spec_text
    assert 'root_dir / "ocr_models"' in spec_text
    assert 'root_dir / "modules" / "ocr_models"' in spec_text
    assert 'root_dir / "src" / "metroliza" / "resources" / "ocr_models"' in spec_text
    assert "THIRD_PARTY_NOTICES.md" in spec_text
    assert "third_party_notice_datas" in spec_text
    assert "*rapidocr_hiddenimports" in spec_text
    assert "*onnxruntime_hiddenimports" in spec_text
    assert "*openvino_hiddenimports" in spec_text
    assert "*cv2_hiddenimports" in spec_text
    assert "*numpy_hiddenimports" in spec_text


def test_windows_pyinstaller_build_validates_ocr_packaging_inputs():
    script_text = Path("build_windows_exe.ps1").read_text(encoding="utf-8")

    assert "[ValidateSet('onefile', 'onedir', 'both')]" in script_text
    assert "[string]$Mode = 'both'" in script_text
    assert "packaging/metroliza_onefile.spec" in script_text
    assert "packaging/metroliza_onedir.spec" in script_text
    assert "requirements-build.txt" in script_text
    assert "requirements-ocr.txt" in script_text
    assert "scripts/validate_packaged_pdf_parser.py" in script_text
    assert "--require-header-ocr" in script_text
    assert "Validating Oznak packaging inputs" in script_text
    assert "importlib.util.find_spec('oznak')" in script_text


def test_nuitka_includes_all_native_acceleration_modules_when_available():
    script = Path("packaging/build_nuitka.ps1").read_text(encoding="utf-8")

    for module_name in (
        "_metroliza_cmm_native",
        "_metroliza_chart_native",
        "_metroliza_group_stats_native",
        "_metroliza_comparison_stats_native",
        "_metroliza_distribution_fit_native",
    ):
        assert f"find_spec('{module_name}')" in script
        assert f"'--include-module={module_name}'" in script


def test_windows_runtime_setup_and_diagnostic_scripts_cover_ocr_prerequisites():
    setup_text = Path("setup_windows_runtime.ps1").read_text(encoding="utf-8")
    diagnose_text = Path("diagnose_windows_ocr.ps1").read_text(encoding="utf-8")
    runtime_diag_text = Path("scripts/windows_ocr_runtime_diagnostics.py").read_text(encoding="utf-8")

    assert "requirements.txt" in setup_text
    assert "requirements-ocr.txt" in setup_text
    assert "vc_redist.x64.exe" in setup_text
    assert "scripts/validate_qt_runtime.py" in setup_text
    assert "scripts/windows_ocr_runtime_diagnostics.py" in setup_text
    assert "scripts/validate_packaged_pdf_parser.py" in setup_text
    assert "--require-header-ocr" in setup_text

    assert "scripts/windows_ocr_runtime_diagnostics.py" in diagnose_text
    assert "--pdf" in diagnose_text
    assert "--db-file" in diagnose_text
    assert "--output" in diagnose_text

    assert "onnxruntime_basic" in runtime_diag_text
    assert "openvino_basic" in runtime_diag_text
    assert "cv2_then_onnxruntime" in runtime_diag_text
    assert "rapidocr_engine_load" in runtime_diag_text
    assert "vc_redist_x64" in runtime_diag_text


def test_onefile_spec_uses_release_metadata_pyinstaller_output_name():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")
    onedir_text = Path("packaging/metroliza_onedir.spec").read_text(encoding="utf-8")

    assert 'OUTPUT_NAME = f"metroliza_P_{VERSION_LABEL}"' in spec_text
    assert "name=OUTPUT_NAME" in spec_text
    assert 'OUTPUT_DIR_NAME = f"metroliza_P_{VERSION_LABEL}_onedir"' in onedir_text
    assert 'EXE_NAME = "metroliza"' in onedir_text
    assert 'metroliza_package_entry.py' in onedir_text


def test_onefile_spec_enables_windows_bootloader_splash_only():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")
    onedir_text = Path("packaging/metroliza_onedir.spec").read_text(encoding="utf-8")
    splash_asset = Path("packaging/metroliza_bootloader_splash.png")

    assert splash_asset.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert 'SPLASH_IMAGE_PATH = SPEC_DIR / "metroliza_bootloader_splash.png"' in spec_text
    assert 'if sys.platform == "win32":' in spec_text
    assert "splash = Splash(" in spec_text
    assert 'text_default="Metroliza is loading..."' in spec_text
    assert "*splash_target" in spec_text
    assert "splash.binaries" in spec_text
    assert "Splash(" not in onedir_text
    assert "metroliza_bootloader_splash.png" not in onedir_text
