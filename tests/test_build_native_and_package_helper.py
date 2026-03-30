from pathlib import Path


def test_build_native_and_package_helper_covers_native_build_and_packaging_paths():
    script = Path("packaging/build_native_and_package.ps1").read_text(encoding="utf-8")

    assert "[ValidateSet('none', 'nuitka', 'pyinstaller')]" in script
    assert "[ValidateSet('all', 'cmm', 'chart', 'group-stats', 'comparison-stats', 'distribution-fit')]" in script
    assert "'modules/native/cmm_parser/Cargo.toml'" in script
    assert "'modules/native/chart_renderer/Cargo.toml'" in script
    assert "'modules/native/group_stats_coercion/Cargo.toml'" in script
    assert "'modules/native/comparison_stats_bootstrap/Cargo.toml'" in script
    assert "'modules/native/distribution_fit_ad/Cargo.toml'" in script
    assert '$invocationBoundParameters = @{}' in script
    assert 'Add-ValueArgumentIfBound -Arguments $nuitkaArgs -BoundParameters $invocationBoundParameters' in script
    assert "@('-m', 'maturin', 'develop', '--release', '--manifest-path', $target.ManifestPath)" in script
    assert "build_backend_diagnostic_summary" in script
    assert "build_nuitka.ps1" in script
    assert "@('-m', 'PyInstaller', '--noconfirm', $PyInstallerSpecPath)" in script
    assert "Windows native packaging is validated primarily on CPython 3.11 x64." in script
