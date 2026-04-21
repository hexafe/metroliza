[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$WithNative,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $repoRoot '.venv-build'
$venvPython = Join-Path $venvDir 'Scripts/python.exe'
$venvScripts = Join-Path $venvDir 'Scripts'
$specPath = Join-Path $repoRoot 'packaging/metroliza_onefile.spec'
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

Push-Location $repoRoot
try {
    Invoke-Step 'Checking paths' {
        if (-not (Test-Path -LiteralPath $specPath)) {
            throw "PyInstaller spec not found: $specPath"
        }
        Write-Host "    Repo: $repoRoot"
        Write-Host "    Build venv: $venvDir"
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
            Invoke-Checked -Executable $venvPython -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip', 'wheel')
            Invoke-Checked -Executable $venvPython -Arguments @('-m', 'pip', 'install', '-r', 'requirements.txt')
            Invoke-Checked -Executable $venvPython -Arguments @(
                '-m', 'pip', 'install',
                'pyinstaller>=6.11',
                'pyinstaller-hooks-contrib>=2025.0',
                'zstandard>=0.22.0'
            )

            $ocrRequirements = Join-Path $repoRoot 'requirements-ocr.txt'
            if (Test-Path -LiteralPath $ocrRequirements) {
                Invoke-Checked -Executable $venvPython -Arguments @('-m', 'pip', 'install', '-r', $ocrRequirements)
            }
        }
    }

    Invoke-Step 'Validating OCR packaging inputs' {
        Invoke-Checked -Executable $venvPython -Arguments @('scripts/validate_packaged_pdf_parser.py', '--require-header-ocr')
    }

    if ($WithNative) {
        Invoke-Step 'Building native modules and PyInstaller EXE' {
            $helper = Join-Path $repoRoot 'packaging/build_native_and_package.ps1'
            & $helper -Packager pyinstaller -SkipBuildRequirementsInstall -SkipPipUpgrade
            if ($LASTEXITCODE -ne 0) {
                throw "Native build/PyInstaller helper failed with exit code $LASTEXITCODE"
            }
        }
    }
    else {
        Invoke-Step 'Building PyInstaller onefile EXE' {
            Invoke-Checked -Executable $venvPython -Arguments @('-m', 'PyInstaller', '--noconfirm', $specPath)
        }
    }

    Invoke-Step 'Finding output EXE' {
        $exe = Get-ChildItem -LiteralPath $distDir -File -Filter '*.exe' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if (-not $exe) {
            throw "Build finished but no .exe was found in $distDir"
        }

        Write-Host ""
        Write-Host "Built EXE:"
        Write-Host "    $($exe.FullName)"
    }
}
finally {
    Pop-Location
}
