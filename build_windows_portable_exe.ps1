[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $root
try {
    & .\build_windows_exe.ps1 -Clean -WithNative -Mode onedir
    if ($LASTEXITCODE -ne 0) { throw 'Supervised onedir build failed' }

    $python = Join-Path $root '.venv-build/Scripts/python.exe'
    $provenancePath = Join-Path $root 'build/provenance/build_provenance.json'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
        -not (Test-Path -LiteralPath $provenancePath -PathType Leaf)) {
        throw 'The exact supervised onedir build is required first'
    }
    $provenance = Get-Content -LiteralPath $provenancePath -Raw | ConvertFrom-Json
    $head = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $provenance.git_sha -ne $head -or $provenance.dirty) {
        throw 'Portable build requires a clean, exact-head supervised payload'
    }
    $release = [string]$provenance.release_label
    if ($release -notmatch '^([0-9]{4}\.[0-9]{2}[a-z0-9]+)\(([0-9]{6})\)$') {
        throw 'Invalid versioned release label'
    }
    $outerName = "metroliza_$($Matches[1])_$($Matches[2]).exe"
    $outer = Join-Path $root "dist/$outerName"
    if (Test-Path -LiteralPath $outer) { Remove-Item -LiteralPath $outer -Force }

    & $python -m PyInstaller --noconfirm --clean packaging/metroliza_portable_onefile.spec
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $outer -PathType Leaf)) {
        throw 'Portable onefile build failed'
    }
    & $python scripts/build_provenance.py stage --manifest $provenancePath --artifact $outer
    if ($LASTEXITCODE -ne 0) { throw 'Portable provenance staging failed' }
    & $python scripts/stage_release_notices.py --dist-dir dist --artifact $outer
    if ($LASTEXITCODE -ne 0) { throw 'Portable notice staging failed' }
    Write-Host "Portable supervised EXE: $outer"
}
finally {
    Pop-Location
}
