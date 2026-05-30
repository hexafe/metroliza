from pathlib import Path


def test_build_native_and_package_helper_covers_native_build_and_packaging_paths():
    script = Path("packaging/build_native_and_package.ps1").read_text(encoding="utf-8")

    assert "[ValidateSet('none', 'nuitka', 'pyinstaller')]" in script
    assert "[ValidateSet('all', 'cmm', 'chart', 'group-stats', 'comparison-stats', 'distribution-fit')]" in script
    assert "[ValidateSet('onefile', 'onedir', 'both')]" in script
    assert "[string]$PyInstallerMode = 'onefile'" in script
    assert "[string]$EntryPoint = 'packaging/metroliza_package_entry.py'" in script
    assert "metroliza_onedir.spec" in script
    assert "'src/metroliza/native/cmm_parser/Cargo.toml'" in script
    assert "'src/metroliza/native/chart_renderer/Cargo.toml'" in script
    assert "'src/metroliza/native/group_stats_coercion/Cargo.toml'" in script
    assert "'src/metroliza/native/comparison_stats_bootstrap/Cargo.toml'" in script
    assert "'src/metroliza/native/distribution_fit_ad/Cargo.toml'" in script
    assert '$invocationBoundParameters = @{}' in script
    assert 'Add-ValueArgumentIfBound -Arguments $nuitkaArgs -BoundParameters $invocationBoundParameters' in script
    assert '[switch]$BundleCredentials' in script
    assert "[string]$CredentialsPath = ''" in script
    assert "Add-SwitchArgumentIfNeeded -Arguments $nuitkaArgs -Enabled $BundleCredentials.IsPresent -SwitchName '-BundleCredentials'" in script
    assert "Add-SwitchArgumentIfNeeded -Arguments $nuitkaArgs -Enabled $AllowMissingOznakBuild.IsPresent -SwitchName '-AllowMissingOznakBuild'" in script
    assert "[AllowEmptyCollection()]\n        [System.Collections.Generic.List[string]]$Arguments" in script
    assert "@('-m', 'maturin', 'develop', '--release', '--manifest-path', $target.ManifestPath)" in script
    assert "build_backend_diagnostic_summary" in script
    assert "build_nuitka.ps1" in script
    assert "Get-PyInstallerSpecPathsForMode" in script
    assert "'PyInstaller'," in script
    assert "'--noconfirm'," in script
    assert "Windows native packaging is validated primarily on CPython 3.11 x64." in script
