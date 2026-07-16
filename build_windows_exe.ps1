[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$WithNative,
    [switch]$SkipInstall,

    [ValidateSet('onefile', 'onedir', 'both')]
    [string]$Mode = 'both'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$originalBuildProvenancePath = $env:METROLIZA_BUILD_PROVENANCE_PATH

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $repoRoot '.venv-build'
$venvPython = Join-Path $venvDir 'Scripts/python.exe'
$venvScripts = Join-Path $venvDir 'Scripts'
$onefileSpecPath = Join-Path $repoRoot 'packaging/metroliza_onefile.spec'
$onedirSpecPath = Join-Path $repoRoot 'packaging/metroliza_onedir.spec'
$distDir = Join-Path $repoRoot 'dist'
$buildDir = Join-Path $repoRoot 'build'
$provenanceManifestPath = Join-Path $buildDir 'provenance/build_provenance.json'

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "==> $Title"
    & $Action
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [string[]]$Arguments = @()
    )

    Write-Host "    $Executable $($Arguments -join ' ')"
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable $($Arguments -join ' ')"
    }
}

function New-BuildVenv {
    if (Test-Path -LiteralPath $venvPython) {
        return
    }

    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        Invoke-Checked -Executable 'py' -Arguments @('-3', '-m', 'venv', $venvDir)
        return
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw 'Python was not found on PATH. Install Python 3.11+ or the Python launcher for Windows, then rerun this script.'
    }

    Invoke-Checked -Executable 'python' -Arguments @('-m', 'venv', $venvDir)
}

function Get-PyInstallerBuildSpecs {
    $specs = @()
    if ($Mode -in @('onefile', 'both')) {
        $specs += [pscustomobject]@{ Label = 'onefile'; Path = $onefileSpecPath }
    }
    if ($Mode -in @('onedir', 'both')) {
        $specs += [pscustomobject]@{ Label = 'onedir'; Path = $onedirSpecPath }
    }
    return $specs
}

function Get-ExpectedPyInstallerArtifacts {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ReleaseLabel
    )

    $outputBase = "metroliza_P_$ReleaseLabel"
    $artifacts = @()
    if ($Mode -in @('onefile', 'both')) {
        $artifacts += Join-Path $distDir "$outputBase.exe"
    }
    if ($Mode -in @('onedir', 'both')) {
        $artifacts += Join-Path $distDir "${outputBase}_onedir/metroliza.exe"
    }
    return $artifacts
}

Push-Location $repoRoot
try {
    $buildSpecs = @(Get-PyInstallerBuildSpecs)

    Invoke-Step 'Checking paths' {
        foreach ($spec in $buildSpecs) {
            if (-not (Test-Path -LiteralPath $spec.Path)) {
                throw "PyInstaller $($spec.Label) spec not found: $($spec.Path)"
            }
        }
        Write-Host "    Repo: $repoRoot"
        Write-Host "    Build venv: $venvDir"
        Write-Host "    PyInstaller mode: $Mode"
    }

    if ($Clean) {
        Invoke-Step 'Cleaning previous build output' {
            foreach ($path in @($distDir, $buildDir)) {
                if (Test-Path -LiteralPath $path) {
                    Remove-Item -LiteralPath $path -Recurse -Force
                    Write-Host "    Removed $path"
                }
            }
        }
    }

    Invoke-Step 'Creating build virtual environment' {
        New-BuildVenv
        if (-not (Test-Path -LiteralPath $venvPython)) {
            throw "Build venv Python was not created: $venvPython"
        }
    }

    $env:Path = "$venvScripts;$env:Path"

    if (-not $SkipInstall) {
        Invoke-Step 'Installing packaging dependencies' {
            Invoke-Checked -Executable $venvPython -Arguments @(
                '-m',
                'pip',
                'install',
                '--upgrade',
                'pip',
                'wheel'
            )
            Invoke-Checked -Executable $venvPython -Arguments @(
                '-m',
                'pip',
                'install',
                '-r',
                'requirements-build.txt'
            )

            $ocrRequirements = Join-Path $repoRoot 'requirements-ocr.txt'
            if (Test-Path -LiteralPath $ocrRequirements) {
                Invoke-Checked -Executable $venvPython -Arguments @(
                    '-m',
                    'pip',
                    'install',
                    '-r',
                    $ocrRequirements
                )
            }
        }
    }

    Invoke-Step 'Validating OCR packaging inputs' {
        Invoke-Checked -Executable $venvPython -Arguments @(
            'scripts/validate_packaged_pdf_parser.py',
            '--require-header-ocr'
        )
    }

    Invoke-Step 'Validating Oznak packaging inputs' {
        Invoke-Checked -Executable $venvPython -Arguments @(
            '-c',
            "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('oznak') else 1)"
        )
    }

    Invoke-Step 'Generating build provenance' {
        Invoke-Checked -Executable $venvPython -Arguments @(
            'scripts/build_provenance.py',
            'generate',
            '--output',
            $provenanceManifestPath,
            '--packager',
            'pyinstaller'
        )
        $env:METROLIZA_BUILD_PROVENANCE_PATH = $provenanceManifestPath
    }
    Invoke-Checked -Executable $venvPython -Arguments @(
        'scripts/build_provenance.py',
        'validate',
        '--manifest',
        $provenanceManifestPath,
        '--packager',
        'pyinstaller'
    )
    $buildProvenance = Get-Content -LiteralPath $provenanceManifestPath -Raw | ConvertFrom-Json
    $expectedExecutables = @(
        Get-ExpectedPyInstallerArtifacts -ReleaseLabel $buildProvenance.release_label
    )

    Invoke-Step 'Removing previous exact output EXEs' {
        foreach ($exe in $expectedExecutables) {
            if (Test-Path -LiteralPath $exe -PathType Leaf) {
                Remove-Item -LiteralPath $exe -Force
                Write-Host "    Removed $exe"
            }
        }
    }

    if ($WithNative) {
        Invoke-Step 'Building native modules and PyInstaller artifacts' {
            $helper = Join-Path $repoRoot 'packaging/build_native_and_package.ps1'
            & $helper -Packager pyinstaller -PyInstallerMode $Mode -SkipBuildRequirementsInstall -SkipPipUpgrade
            if ($LASTEXITCODE -ne 0) {
                throw "Native build/PyInstaller helper failed with exit code $LASTEXITCODE"
            }
        }
    }
    else {
        foreach ($spec in $buildSpecs) {
            Invoke-Step "Building PyInstaller $($spec.Label) artifact" {
                Invoke-Checked -Executable $venvPython -Arguments @(
                    '-m',
                    'PyInstaller',
                    '--noconfirm',
                    $spec.Path
                )
            }
        }
    }

    Invoke-Step 'Validating exact output EXEs' {
        Write-Host ""
        Write-Host "Built EXE artifacts:"
        foreach ($exe in $expectedExecutables) {
            if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
                throw "Expected packaged artifact is missing: $exe"
            }
            Write-Host "    $exe"
        }
    }

    Invoke-Step 'Staging third-party notice sidecars' {
        $noticeArguments = [System.Collections.Generic.List[string]]::new()
        foreach ($argument in @(
            'scripts/stage_release_notices.py',
            '--dist-dir',
            $distDir
        )) {
            [void]$noticeArguments.Add($argument)
        }
        foreach ($exe in $expectedExecutables) {
            [void]$noticeArguments.Add('--artifact')
            [void]$noticeArguments.Add($exe)
        }
        Invoke-Checked -Executable $venvPython -Arguments $noticeArguments.ToArray()
    }

    Invoke-Step 'Staging exact artifact provenance sidecars' {
        $provenanceArguments = [System.Collections.Generic.List[string]]::new()
        foreach ($argument in @(
            'scripts/build_provenance.py',
            'stage',
            '--manifest',
            $provenanceManifestPath
        )) {
            [void]$provenanceArguments.Add($argument)
        }
        foreach ($exe in $expectedExecutables) {
            [void]$provenanceArguments.Add('--artifact')
            [void]$provenanceArguments.Add($exe)
        }
        Invoke-Checked -Executable $venvPython -Arguments $provenanceArguments.ToArray()
    }
}
finally {
    if ($null -eq $originalBuildProvenancePath) {
        Remove-Item Env:METROLIZA_BUILD_PROVENANCE_PATH -ErrorAction SilentlyContinue
    }
    else {
        $env:METROLIZA_BUILD_PROVENANCE_PATH = $originalBuildProvenancePath
    }
    Pop-Location
}
