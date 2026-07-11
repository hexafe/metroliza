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

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $repoRoot '.venv-build'
$venvPython = Join-Path $venvDir 'Scripts/python.exe'
$venvScripts = Join-Path $venvDir 'Scripts'
$onefileSpecPath = Join-Path $repoRoot 'packaging/metroliza_onefile.spec'
$onedirSpecPath = Join-Path $repoRoot 'packaging/metroliza_onedir.spec'
$distDir = Join-Path $repoRoot 'dist'
$buildDir = Join-Path $repoRoot 'build'

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

    Invoke-Step 'Finding output EXEs' {
        $executables = @(
            Get-ChildItem -LiteralPath $distDir -Recurse -File -Filter '*.exe' -ErrorAction SilentlyContinue |
                Sort-Object FullName
        )

        if (-not $executables -or $executables.Count -eq 0) {
            throw "Build finished but no .exe was found under $distDir"
        }

        Write-Host ""
        Write-Host "Built EXE artifacts:"
        foreach ($exe in $executables) {
            Write-Host "    $($exe.FullName)"
        }
    }

    Invoke-Step 'Staging third-party notice sidecars' {
        Invoke-Checked -Executable $venvPython -Arguments @(
            'scripts/stage_release_notices.py',
            '--dist-dir',
            $distDir
        )
    }
}
finally {
    Pop-Location
}
