[CmdletBinding()]
param(
    [string]$PdfPath,
    [string]$DbFile,
    [string]$OutputPath,
    [string]$VenvDir = '.venv',
    [switch]$Compact
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = if ([System.IO.Path]::IsPathRooted($VenvDir)) { $VenvDir } else { Join-Path $repoRoot $VenvDir }
$venvPython = Join-Path $venvPath 'Scripts/python.exe'

function Resolve-DiagnosticPython {
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }

    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        return 'py'
    }

    throw "No Python executable found. Run setup_windows_runtime.ps1 first."
}

Push-Location $repoRoot
try {
    $python = Resolve-DiagnosticPython
    $args = @('scripts/windows_ocr_runtime_diagnostics.py')

    if ($PdfPath) {
        $args += @('--pdf', $PdfPath)
    }
    if ($DbFile) {
        $args += @('--db-file', $DbFile)
    }
    if ($OutputPath) {
        $args += @('--output', $OutputPath)
    }
    if ($Compact) {
        $args += '--compact'
    }

    Write-Host "Using Python: $python"
    Write-Host "Running: $python $($args -join ' ')"
    & $python @args
    if ($LASTEXITCODE -ne 0) {
        throw "Windows OCR diagnostic failed with exit code $LASTEXITCODE."
    }

    if ($OutputPath) {
        Write-Host "Diagnostic JSON written to: $OutputPath"
    }
}
finally {
    Pop-Location
}
