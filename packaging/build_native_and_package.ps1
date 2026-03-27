[CmdletBinding()]
param(
    [ValidateSet('none', 'nuitka', 'pyinstaller')]
    [string]$Packager = 'nuitka',
    [ValidateSet('all', 'cmm', 'chart', 'group-stats', 'comparison-stats', 'distribution-fit')]
    [string[]]$NativeTargets = @('all'),
    [switch]$SkipBuildRequirementsInstall,
    [switch]$SkipPipUpgrade,
    [switch]$SkipBackendVerification,
    [switch]$DryRun,
    [string]$PyInstallerSpecPath = "$PSScriptRoot/metroliza_onefile.spec",
    [string]$EntryPoint = 'metroliza.py',
    [string]$OutputName,
    [string]$IconPath = "$PSScriptRoot/metroliza_icon2.ico",
    [string]$CredentialsPath = 'credentials.json',
    [switch]$FastDev,
    [switch]$RequireNative,
    [switch]$EnableConsole,
    [switch]$AllowBrokenPdfParserBuild,
    [ValidateSet('auto', 'gcc', 'clang')]
    [string]$CompilerStrategy = 'auto',
    [switch]$AutoInstallCompiler,
    [switch]$OpenInstallHelp
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$invocationBoundParameters = @{}
foreach ($entry in $PSBoundParameters.GetEnumerator()) {
    $invocationBoundParameters[$entry.Key] = $entry.Value
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$nuitkaScriptPath = Join-Path $PSScriptRoot 'build_nuitka.ps1'

$nativeTargetCatalog = @(
    [pscustomobject]@{
        Name = 'cmm'
        ModuleName = '_metroliza_cmm_native'
        ManifestPath = 'modules/native/cmm_parser/Cargo.toml'
        VerifyCommand = 'from modules.cmm_native_parser import native_backend_available, native_persistence_backend_available; import sys; sys.exit(0 if native_backend_available() and native_persistence_backend_available() else 1)'
    }
    [pscustomobject]@{
        Name = 'chart'
        ModuleName = '_metroliza_chart_native'
        ManifestPath = 'modules/native/chart_renderer/Cargo.toml'
        VerifyCommand = 'from modules.chart_renderer import native_chart_backend_available; import sys; sys.exit(0 if native_chart_backend_available() else 1)'
    }
    [pscustomobject]@{
        Name = 'group-stats'
        ModuleName = '_metroliza_group_stats_native'
        ManifestPath = 'modules/native/group_stats_coercion/Cargo.toml'
        VerifyCommand = 'from modules.group_stats_native import native_backend_available; import sys; sys.exit(0 if native_backend_available() else 1)'
    }
    [pscustomobject]@{
        Name = 'comparison-stats'
        ModuleName = '_metroliza_comparison_stats_native'
        ManifestPath = 'modules/native/comparison_stats_bootstrap/Cargo.toml'
        VerifyCommand = 'from modules.comparison_stats_native import native_backend_available; import sys; sys.exit(0 if native_backend_available() else 1)'
    }
    [pscustomobject]@{
        Name = 'distribution-fit'
        ModuleName = '_metroliza_distribution_fit_native'
        ManifestPath = 'modules/native/distribution_fit_ad/Cargo.toml'
        VerifyCommand = 'from modules.distribution_fit_native import native_backend_available; import sys; sys.exit(0 if native_backend_available() else 1)'
    }
)

function Format-CommandForDisplay {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [AllowEmptyCollection()]
        [string[]]$Arguments = @()
    )

    $parts = @($Executable) + $Arguments
    return ($parts | ForEach-Object {
            if ($_ -match '\s') {
                '"' + $_.Replace('"', '\"') + '"'
            } else {
                $_
            }
        }) -join ' '
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [AllowEmptyCollection()]
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    $display = Format-CommandForDisplay -Executable $Executable -Arguments $Arguments
    Write-Host "      $display"
    if ($DryRun) {
        return
    }

    $commandExitCode = $null
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $hadNativePreference = Test-Path -LiteralPath 'variable:PSNativeCommandUseErrorActionPreference'
    if ($hadNativePreference) {
        $previousNativePreference = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        & $Executable @Arguments
        $commandExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($hadNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $previousNativePreference
        }
    }

    if ($commandExitCode -ne 0) {
        throw $FailureMessage
    }
}

function Get-CheckedCommandOutput {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [AllowEmptyCollection()]
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    $display = Format-CommandForDisplay -Executable $Executable -Arguments $Arguments
    Write-Host "      $display"
    if ($DryRun) {
        return $null
    }

    $commandExitCode = $null
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $hadNativePreference = Test-Path -LiteralPath 'variable:PSNativeCommandUseErrorActionPreference'
    if ($hadNativePreference) {
        $previousNativePreference = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        $output = & $Executable @Arguments 2>&1
        $commandExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($hadNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $previousNativePreference
        }
    }

    if ($commandExitCode -ne 0) {
        throw $FailureMessage
    }

    return (($output | Out-String).Trim())
}

function Invoke-CheckedPythonCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    Invoke-CheckedCommand -Executable 'python' -Arguments $Arguments -FailureMessage $FailureMessage
}

function Test-CommandAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    return $null -ne (Get-Command $CommandName -ErrorAction SilentlyContinue)
}

function Resolve-NativeTargets {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$RequestedTargets
    )

    if ($RequestedTargets -contains 'all') {
        return $nativeTargetCatalog
    }

    $requestedLookup = @{}
    foreach ($name in $RequestedTargets) {
        $requestedLookup[$name] = $true
    }

    return @($nativeTargetCatalog | Where-Object { $requestedLookup.ContainsKey($_.Name) })
}

function Add-SwitchArgumentIfNeeded {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.Generic.List[string]]$Arguments,
        [Parameter(Mandatory = $true)]
        [bool]$Enabled,
        [Parameter(Mandatory = $true)]
        [string]$SwitchName
    )

    if ($Enabled) {
        [void]$Arguments.Add($SwitchName)
    }
}

function Add-ValueArgumentIfBound {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.Generic.List[string]]$Arguments,
        [Parameter(Mandatory = $true)]
        [hashtable]$BoundParameters,
        [Parameter(Mandatory = $true)]
        [string]$ParameterName,
        [Parameter(Mandatory = $true)]
        [string]$SwitchName
    )

    if ($BoundParameters.ContainsKey($ParameterName)) {
        [void]$Arguments.Add($SwitchName)
        [void]$Arguments.Add([string]$BoundParameters[$ParameterName])
    }
}

Push-Location $repoRoot
try {
    Write-Host '[1/6] Validating toolchain'
    if (-not (Test-CommandAvailable -CommandName 'python')) {
        throw "Python is required on PATH."
    }
    if (-not (Test-CommandAvailable -CommandName 'cargo')) {
        throw "Rust toolchain (cargo) is required on PATH. Install rustup before building native modules."
    }

    try {
        $pythonInfoRaw = Get-CheckedCommandOutput -Executable 'python' -Arguments @(
            '-c',
            'import json, platform, sys; print(json.dumps({"version": platform.python_version(), "platform": sys.platform, "executable": sys.executable, "major": sys.version_info[0], "minor": sys.version_info[1]}))'
        ) -FailureMessage 'Failed to inspect the active Python runtime.'
        if ($pythonInfoRaw) {
            $pythonInfoLine = @($pythonInfoRaw -split [Environment]::NewLine | ForEach-Object { $_.Trim() } | Where-Object { $_ }) | Where-Object { $_.StartsWith('{') -and $_.EndsWith('}') } | Select-Object -Last 1
            if (-not $pythonInfoLine) {
                throw 'Python runtime inspection did not return JSON output.'
            }

            $pythonInfo = $pythonInfoLine | ConvertFrom-Json
            Write-Host "      Active Python: $($pythonInfo.version) [$($pythonInfo.platform)]"
            Write-Host "      Python executable: $($pythonInfo.executable)"
            if ($pythonInfo.platform -eq 'win32' -and "$($pythonInfo.major).$($pythonInfo.minor)" -ne '3.11') {
                Write-Warning "Windows native packaging is validated primarily on CPython 3.11 x64. Current runtime is $($pythonInfo.version)."
            }
        }
    } catch {
        Write-Warning "Unable to inspect the active Python runtime details; continuing. $($_.Exception.Message)"
    }

    $cargoVersion = Get-CheckedCommandOutput -Executable 'cargo' -Arguments @('--version') -FailureMessage 'Failed to query cargo version.'
    if ($cargoVersion) {
        Write-Host "      Rust toolchain: $cargoVersion"
    }

    $selectedTargets = Resolve-NativeTargets -RequestedTargets $NativeTargets
    if (-not $selectedTargets -or $selectedTargets.Count -eq 0) {
        throw 'No native targets were selected for build.'
    }
    Write-Host "      Native targets: $($selectedTargets.Name -join ', ')"
    Write-Host "      Packager: $Packager"

    Write-Host '[2/6] Installing build requirements into the active Python environment'
    if ($SkipBuildRequirementsInstall) {
        Write-Host '      Skipping requirements-build.txt installation by request.'
    } else {
        if (-not $SkipPipUpgrade) {
            Invoke-CheckedPythonCommand -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip') -FailureMessage 'Failed to upgrade pip in the active build environment.'
        } else {
            Write-Host '      Skipping pip upgrade by request.'
        }
        Invoke-CheckedPythonCommand -Arguments @('-m', 'pip', 'install', '-r', 'requirements-build.txt') -FailureMessage 'Failed to install requirements-build.txt into the active build environment.'
    }

    Write-Host '[3/6] Building native extensions in release mode'
    foreach ($target in $selectedTargets) {
        Write-Host "      Building $($target.Name) -> $($target.ModuleName)"
        Invoke-CheckedPythonCommand -Arguments @('-m', 'maturin', 'develop', '--release', '--manifest-path', $target.ManifestPath) -FailureMessage "Failed to build/install $($target.ModuleName)."
    }

    if ($SkipBackendVerification) {
        Write-Host '[4/6] Backend verification skipped by request'
    } else {
        Write-Host '[4/6] Verifying native backend availability in the same Python environment'
        foreach ($target in $selectedTargets) {
            Write-Host "      Verifying $($target.ModuleName)"
            Invoke-CheckedPythonCommand -Arguments @('-c', $target.VerifyCommand) -FailureMessage "Backend verification failed for $($target.ModuleName)."
        }

        Invoke-CheckedPythonCommand -Arguments @(
            '-c',
            'import json; from modules.backend_diagnostics import build_backend_diagnostic_summary; print(json.dumps(build_backend_diagnostic_summary(), indent=2, sort_keys=True))'
        ) -FailureMessage 'Backend diagnostics summary failed.'
    }

    Write-Host '[5/6] Packaging'
    if ($Packager -eq 'none') {
        Write-Host '      Packaging disabled; native modules are built and verified only.'
    } elseif ($Packager -eq 'nuitka') {
        if (-not (Test-Path -LiteralPath $nuitkaScriptPath)) {
            throw "Nuitka helper script not found: $nuitkaScriptPath"
        }

        $nuitkaArgs = [System.Collections.Generic.List[string]]::new()
        Add-ValueArgumentIfBound -Arguments $nuitkaArgs -BoundParameters $invocationBoundParameters -ParameterName 'EntryPoint' -SwitchName '-EntryPoint'
        Add-ValueArgumentIfBound -Arguments $nuitkaArgs -BoundParameters $invocationBoundParameters -ParameterName 'OutputName' -SwitchName '-OutputName'
        Add-ValueArgumentIfBound -Arguments $nuitkaArgs -BoundParameters $invocationBoundParameters -ParameterName 'IconPath' -SwitchName '-IconPath'
        Add-ValueArgumentIfBound -Arguments $nuitkaArgs -BoundParameters $invocationBoundParameters -ParameterName 'CredentialsPath' -SwitchName '-CredentialsPath'
        Add-ValueArgumentIfBound -Arguments $nuitkaArgs -BoundParameters $invocationBoundParameters -ParameterName 'CompilerStrategy' -SwitchName '-CompilerStrategy'
        Add-SwitchArgumentIfNeeded -Arguments $nuitkaArgs -Enabled $FastDev.IsPresent -SwitchName '-FastDev'
        Add-SwitchArgumentIfNeeded -Arguments $nuitkaArgs -Enabled $EnableConsole.IsPresent -SwitchName '-EnableConsole'
        Add-SwitchArgumentIfNeeded -Arguments $nuitkaArgs -Enabled $AllowBrokenPdfParserBuild.IsPresent -SwitchName '-AllowBrokenPdfParserBuild'
        Add-SwitchArgumentIfNeeded -Arguments $nuitkaArgs -Enabled $AutoInstallCompiler.IsPresent -SwitchName '-AutoInstallCompiler'
        Add-SwitchArgumentIfNeeded -Arguments $nuitkaArgs -Enabled $OpenInstallHelp.IsPresent -SwitchName '-OpenInstallHelp'

        $enforceNativePackaging = $RequireNative.IsPresent -or ($selectedTargets.Name -contains 'cmm')
        Add-SwitchArgumentIfNeeded -Arguments $nuitkaArgs -Enabled $enforceNativePackaging -SwitchName '-RequireNative'

        $display = Format-CommandForDisplay -Executable $nuitkaScriptPath -Arguments $nuitkaArgs.ToArray()
        Write-Host "      $display"
        if (-not $DryRun) {
            if ($nuitkaArgs.Count -gt 0) {
                & $nuitkaScriptPath @($nuitkaArgs.ToArray())
            } else {
                & $nuitkaScriptPath
            }
        }
    } else {
        if (-not (Test-Path -LiteralPath $PyInstallerSpecPath)) {
            throw "PyInstaller spec file not found: $PyInstallerSpecPath"
        }

        Invoke-CheckedPythonCommand -Arguments @('-m', 'PyInstaller', '--noconfirm', $PyInstallerSpecPath) -FailureMessage 'PyInstaller packaging failed.'
    }

    Write-Host '[6/6] Done'
    Write-Host '      Native build/package helper completed successfully.'
} finally {
    Pop-Location
}
