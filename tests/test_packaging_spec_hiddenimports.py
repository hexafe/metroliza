import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.vendored_plotly import PLOTLY_ASSET_DIRECTORY, PLOTLY_ASSET_HASHES, PLOTLY_NOTICE_FILENAME


def test_onefile_spec_includes_builtin_cmm_parser_hiddenimport():
    spec_text = Path("packaging/metroliza_onefile.spec").read_text(encoding="utf-8")
    common_text = Path("packaging/pyinstaller_common.py").read_text(encoding="utf-8")

    assert "build_pyinstaller_collection" in spec_text
    assert 'metroliza_package_entry.py' in spec_text
    assert 'pathex=[str(ROOT_DIR / "src"), str(ROOT_DIR)]' in spec_text
    assert "metroliza.parsing.cmm_report_parser" in common_text
    assert "metroliza.parsing.report_parser_factory" in common_text
    assert "metroliza.reports.header_ocr_corrections" in common_text
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
    assert 'collect_required_runtime_assets(\n            "openvino"\n        )' in spec_text
    assert "flavor_includes_openvino(resolve_build_flavor())" in spec_text
    assert 'collect_required_runtime_assets("cv2")' in spec_text
    assert 'collect_required_runtime_assets("numpy")' in spec_text
    assert 'collect_optional_distribution_metadata("rapidocr")' in spec_text
    assert 'collect_optional_distribution_metadata("onnxruntime")' in spec_text
    assert 'openvino_metadata = collect_optional_distribution_metadata("openvino")' in spec_text
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

    assert "@('-3.11', '-m', 'venv', $venvDir)" in script_text
    assert "@('-3', '-m', 'venv', $venvDir)" not in script_text
    assert "sys.version_info[:2] == (3, 11)" in script_text
    assert "Assert-BuildPythonVersion" in script_text
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


@pytest.mark.parametrize(
    ("mode_args", "entry_name", "output_name", "expected_relative", "make_output"),
    [
        (("-Mode", "standalone"), "application.py", "example.exe", "application.dist/example.exe", True),
        (("-FastDev",), "alternate.app.py", "custom output.exe", "alternate.app.dist/custom output.exe", True),
        (("-Mode", "standalone"), "application.py", "example.exe", "application.dist/example.exe", False),
        ((), "application.py", "nested/onefile.exe", "nested/onefile.exe", True),
        pytest.param(
            ("-Mode", "standalone"), "application.py", "custom", "application.dist/custom.exe", True,
            marks=pytest.mark.skipif(sys.platform != "win32", reason="Nuitka adds .exe on Windows"),
        ),
    ],
)
def test_nuitka_stages_notices_for_the_exact_compiler_output(
    tmp_path, monkeypatch, mode_args, entry_name, output_name, expected_relative, make_output,
):
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell Core is not installed")
    if not any(shutil.which(name) for name in ("clang-cl", "clang")):
        pytest.skip("A Clang executable is needed by the build script's compiler probe")

    root = Path(__file__).resolve().parents[1]
    packaging = tmp_path / "packaging"
    packaging.mkdir()
    shutil.copyfile(root / "packaging/build_nuitka.ps1", packaging / "build_nuitka.ps1")
    (packaging / entry_name).touch()
    shutil.copyfile(root / "THIRD_PARTY_NOTICES.md", tmp_path / "THIRD_PARTY_NOTICES.md")
    asset_dir = Path("src") / PLOTLY_ASSET_DIRECTORY
    shutil.copytree(root / asset_dir, tmp_path / asset_dir)
    artifact = tmp_path / expected_relative
    artifact.parent.mkdir(exist_ok=True)
    stale_exe = tmp_path / artifact.name
    stale_exe.write_bytes(b"not the current build")
    monkeypatch.setenv("METROLIZA_TEST_NUITKA_PYTHON", sys.executable)
    monkeypatch.setenv("METROLIZA_TEST_NUITKA_STAGER", str(root / "scripts/stage_release_notices.py"))
    monkeypatch.setenv("METROLIZA_TEST_NUITKA_EMIT", "1" if make_output else "0")

    # Substitute the compiler and dependency probes, then execute the real notice stager.
    wrapper = tmp_path / "run-test.ps1"
    wrapper.write_text(
        r"""
param([string]$EntryPoint, [string]$OutputName, [string]$Mode, [switch]$FastDev)

function python {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq '-c') {
        if ($args[1] -match 'PyQt5|_metroliza_|openvino') { $global:LASTEXITCODE = 1 }
        return
    }
    if ($args[0] -eq '-m' -and $args[1] -eq 'nuitka') {
        if ($env:METROLIZA_TEST_NUITKA_EMIT -eq '0') { return }
        $name = ($args | Where-Object { $_.StartsWith('--output-filename=') }).Substring(18)
        if ($IsWindows -and [IO.Path]::GetExtension($name) -ine '.exe') { $name += '.exe' }
        if ($args -contains '--standalone') {
            $folder = $args | Where-Object { $_.StartsWith('--output-folder-name=') }
            $directory = if ($folder) { $folder.Substring(21) } else {
                [IO.Path]::GetFileNameWithoutExtension($args[2]) + '.dist'
            }
            $name = Join-Path $directory $name
        }
        [IO.File]::WriteAllText((Join-Path (Get-Location) $name), 'compiled fixture')
        return
    }
    $command = Split-Path $args[0] -Leaf
    if ($command -eq 'stage_release_notices.py') {
        $stagerArgs = @($args | Select-Object -Skip 1)
        & $env:METROLIZA_TEST_NUITKA_PYTHON $env:METROLIZA_TEST_NUITKA_STAGER @stagerArgs
        return
    }
    if ($command -notin @('vendored_plotly.py', 'validate_packaged_pdf_parser.py')) {
        throw 'Unexpected command in the isolated Nuitka build test'
    }
}
& ./packaging/build_nuitka.ps1 -CompilerStrategy clang @PSBoundParameters
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-File", str(wrapper),
         "-EntryPoint", f"packaging/{entry_name}", "-OutputName", output_name, *mode_args],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45, check=False,
    )

    assert not stale_exe.with_name(f"{stale_exe.name}.licenses").exists()
    if not make_output:
        assert result.returncode != 0
        assert "Failed to stage third-party notice sidecars" in result.stderr
        return

    assert result.returncode == 0, result.stdout + result.stderr
    assert artifact.read_bytes() == b"compiled fixture"
    sidecar = artifact.with_name(f"{artifact.name}.licenses")
    manifest = json.loads((sidecar / "NOTICE_MANIFEST.json").read_text(encoding="utf-8"))
    actual_notice_sha = hashlib.sha256((sidecar / PLOTLY_NOTICE_FILENAME).read_bytes()).hexdigest()
    assert actual_notice_sha == PLOTLY_ASSET_HASHES[PLOTLY_NOTICE_FILENAME]
    assert {"name": PLOTLY_NOTICE_FILENAME, "sha256": actual_notice_sha} in manifest["files"]


def test_windows_runtime_setup_and_diagnostic_scripts_cover_ocr_prerequisites():
    setup_text = Path("setup_windows_runtime.ps1").read_text(encoding="utf-8")
    diagnose_text = Path("diagnose_windows_ocr.ps1").read_text(encoding="utf-8")
    runtime_diag_text = Path("scripts/windows_ocr_runtime_diagnostics.py").read_text(encoding="utf-8")

    assert "requirements.txt" in setup_text
    assert "requirements-ocr.txt" in setup_text
    assert "vc_redist.x64.exe" in setup_text
    assert "scripts/validate_qt_runtime.py" in setup_text
    assert "diagnose_windows_ocr.ps1" in setup_text
    assert "Required OCR diagnostic validation failed" in setup_text

    assert "scripts/windows_ocr_runtime_diagnostics.py" in diagnose_text
    assert "--pdf" in diagnose_text
    assert "--db-file" in diagnose_text
    assert "--output" in diagnose_text

    assert "_selected_config" in runtime_diag_text
    assert "_selected_models" in runtime_diag_text
    assert "_engine_smoke_check" in runtime_diag_text



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
