[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$previousPipConstraint = $env:PIP_CONSTRAINT
Push-Location $root
try {
    $env:PIP_CONSTRAINT = Join-Path $root 'packaging/windows-rc-constraints.txt'
    & .\build_windows_exe.ps1 -Clean -WithNative -Mode onedir
    if ($LASTEXITCODE -ne 0) { throw 'Supervised onedir build failed' }

    $python = Join-Path $root '.venv-build/Scripts/python.exe'
    $names = & $python scripts/release_identity.py names | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Invalid canonical release identity' }
    $onedir = Join-Path $root "dist/$($names.onedir)"
    $provenancePath = Join-Path $onedir '_internal/metroliza/app/build_provenance.json'
    if (-not (Test-Path -LiteralPath $provenancePath -PathType Leaf)) {
        throw 'The exact supervised onedir provenance is required first'
    }
    $provenance = Get-Content -LiteralPath $provenancePath -Raw | ConvertFrom-Json
    $head = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $provenance.git_sha -ne $head -or $provenance.dirty) {
        throw 'Portable build requires a clean, exact-head supervised payload'
    }
    if ([string]$provenance.release_label -ne [string]$names.version) {
        throw 'Invalid canonical release identity or stale provenance'
    }
    $inventoryEvidence = Join-Path $root 'build/provenance/portable-inventory'
    & $python scripts/verify_third_party_inventory.py --onedir $onedir `
        --receipt (Join-Path $inventoryEvidence 'third-party-inventory.json') `
        --generated (Join-Path $inventoryEvidence 'third-party-inventory-generated.json')
    if ($LASTEXITCODE -ne 0) { throw 'The actual portable payload does not match the third-party inventory' }

    $outerName = [string]$names.portable
    $outer = Join-Path $root "dist/$outerName"
    if (Test-Path -LiteralPath $outer) { Remove-Item -LiteralPath $outer -Force }

    & $python -m PyInstaller --noconfirm --clean packaging/metroliza_portable_onefile.spec
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $outer -PathType Leaf)) {
        throw 'Portable onefile build failed'
    }
    & $python scripts/release_identity.py verify-pe --input $outer
    if ($LASTEXITCODE -ne 0) { throw 'Portable PE version mismatch' }
    & $python scripts/build_provenance.py stage --manifest $provenancePath --from-onedir $onedir --wrapper-format portable --artifact $outer
    if ($LASTEXITCODE -ne 0) { throw 'Portable provenance staging failed' }
    & $python scripts/stage_release_notices.py --dist-dir dist --artifact $outer --portable-splash
    if ($LASTEXITCODE -ne 0) { throw 'Portable notice staging failed' }
    Write-Host "Portable supervised EXE: $outer"
}
finally {
    $env:PIP_CONSTRAINT = $previousPipConstraint
    Pop-Location
}
