[CmdletBinding()]
param(
    # Build the PyInstaller onedir first (build_windows_exe.ps1 -Mode onedir). Without this switch
    # an existing onedir is packed: -OnedirPath, or the default dist/metroliza_P_<label>_onedir.
    [switch]$BuildOnedir,
    [switch]$WithNative,
    [switch]$Clean,

    # Pack the RC supervised onedir (entry metroliza.exe, metroliza_application.exe, the OCR worker
    # and supervision_manifest.json): requires the exact, clean-head build provenance and the same
    # verified supervisor identity the portable envelope requires. Use the same onedir that
    # build_windows_portable_exe.ps1 just built to compare the two deliveries.
    [switch]$Supervised,

    [string]$OnedirPath,

    # Relative path of the executable to start inside the onedir. It is recorded in the payload
    # manifest, so it can later name the supervisor instead of metroliza.exe.
    [string]$Entry = 'metroliza.exe',

    # Release label such as 2026.06rc2(260711). Default: read from VersionDate.py.
    [string]$ReleaseLabel,

    # Output EXE. Default: dist/metroliza_<version>_<yymmdd>_launcher.exe. The suffix keeps it
    # apart from the PyInstaller portable envelope dist/metroliza_<version>_<yymmdd>.exe.
    [string]$Output
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$crateDir = Join-Path $repoRoot 'packaging/launcher'
$distDir = Join-Path $repoRoot 'dist'
$venvPython = Join-Path $repoRoot '.venv-build/Scripts/python.exe'
$provenanceManifestPath = Join-Path $repoRoot 'build/provenance/build_provenance.json'

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    Write-Host ""
    Write-Host "==> $Title"
    & $Action
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$Arguments = @()
    )
    Write-Host "    $Executable $($Arguments -join ' ')"
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable"
    }
}

function Get-ReleaseLabel {
    if ($ReleaseLabel) {
        return $ReleaseLabel
    }
    $python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }
    $code = "import sys; sys.path.insert(0, 'packaging'); " +
        "from pathlib import Path; from pyinstaller_common import read_version_label; " +
        "print(read_version_label(Path('.')))"
    $label = & $python -c $code
    if ($LASTEXITCODE -ne 0 -or -not $label) {
        throw 'Could not read the release label from VersionDate.py'
    }
    return ([string]$label).Trim()
}

function Invoke-OptionalSigning {
    param([Parameter(Mandatory = $true)][string]$ExePath)

    # Signing happens on the FINAL exe: signing the stub and appending the payload afterwards
    # would invalidate the signature. The launcher finds its payload before the certificate table.
    $certFile = $env:METROLIZA_SIGNING_CERT_FILE
    $certPassword = $env:METROLIZA_SIGNING_CERT_PASSWORD
    if (-not $certFile -or -not $certPassword) {
        Write-Host '    signing skipped (METROLIZA_SIGNING_CERT_FILE / METROLIZA_SIGNING_CERT_PASSWORD not set)'
        return $false
    }
    if (-not (Test-Path -LiteralPath $certFile -PathType Leaf)) {
        throw 'METROLIZA_SIGNING_CERT_FILE does not point to a file'
    }
    $signtool = $env:METROLIZA_SIGNING_SIGNTOOL
    if (-not $signtool) {
        $found = Get-Command signtool.exe -ErrorAction SilentlyContinue
        if (-not $found) {
            throw 'Signing is configured but signtool.exe was not found (set METROLIZA_SIGNING_SIGNTOOL)'
        }
        $signtool = $found.Source
    }
    $timestampUrl = $env:METROLIZA_SIGNING_TIMESTAMP_URL
    if (-not $timestampUrl) {
        $timestampUrl = 'http://timestamp.digicert.com'
    }
    # The password is passed to signtool but deliberately not echoed.
    & $signtool sign /f $certFile /p $certPassword /fd sha256 /tr $timestampUrl /td sha256 $ExePath
    if ($LASTEXITCODE -ne 0) {
        throw 'signtool sign failed'
    }
    Invoke-Checked -Executable $signtool -Arguments @('verify', '/pa', $ExePath)
    return $true
}

Push-Location $repoRoot
try {
    if ($BuildOnedir) {
        Invoke-Step 'Building the PyInstaller onedir' {
            $arguments = @{ Mode = 'onedir' }
            if ($Clean) { $arguments['Clean'] = $true }
            if ($WithNative) { $arguments['WithNative'] = $true }
            & (Join-Path $repoRoot 'build_windows_exe.ps1') @arguments
            if ($LASTEXITCODE -ne 0) { throw 'Onedir build failed' }
        }
    }

    $label = Get-ReleaseLabel
    if ($label -notmatch '^([0-9]{4}\.[0-9]{2}[a-z0-9]+)\(([0-9]{6})\)$') {
        throw "Release label does not look like 2026.06rc2(260711): $label"
    }
    $version = "$($Matches[1])_$($Matches[2])"
    if (-not $OnedirPath) {
        $OnedirPath = Join-Path $distDir "metroliza_P_${label}_onedir"
    }
    if (-not $Output) {
        $Output = Join-Path $distDir "metroliza_${version}_launcher.exe"
    }
    $gitSha = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $gitSha -notmatch '^[0-9a-f]{40}$') {
        throw 'Could not determine the git commit'
    }
    if (@(git status --porcelain).Count -ne 0) {
        Write-Warning 'The working tree is dirty; the EXE records the commit id only.'
    }

    if ($Supervised) {
        Invoke-Step 'Checking the supervised onedir (exact head, verified identity)' {
            if ($Entry -ne 'metroliza.exe') {
                throw '-Supervised starts the supervisor: the entry must be metroliza.exe'
            }
            if (-not (Test-Path -LiteralPath $OnedirPath -PathType Container)) {
                throw "Onedir not found: $OnedirPath (use -BuildOnedir or -OnedirPath)"
            }
            foreach ($required in @('metroliza.exe', 'metroliza_application.exe',
                                    'metroliza_ocr_worker.exe', 'supervision_manifest.json')) {
                if (-not (Test-Path -LiteralPath (Join-Path $OnedirPath $required) -PathType Leaf)) {
                    throw "The supervised onedir is incomplete: $required is missing"
                }
            }
            if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf) -or
                -not (Test-Path -LiteralPath $provenanceManifestPath -PathType Leaf)) {
                throw 'The exact supervised onedir build (build venv and provenance) is required first'
            }
            $provenance = Get-Content -LiteralPath $provenanceManifestPath -Raw | ConvertFrom-Json
            if ($provenance.git_sha -ne $gitSha -or $provenance.dirty) {
                throw 'The launcher needs a clean, exact-head supervised payload'
            }
            if ([string]$provenance.release_label -ne $label) {
                throw 'The release label does not match the build provenance'
            }
            # The same check the portable envelope runs: complete package identity plus the exact
            # supervisor executable sidecar, bound to the commit recorded in the launcher.
            $verify = "import sys; sys.path[:0] = ['packaging', 'src']; from pathlib import Path; " +
                "from metroliza_portable_entry import _verified_launcher; " +
                "from metroliza.shared.diagnostic_package import inspect_package; " +
                "root = Path(sys.argv[1]); identity = inspect_package(root); " +
                "sys.exit(0 if identity.valid and identity.git_sha == sys.argv[2] " +
                "and _verified_launcher(root) is not None else 1)"
            & $venvPython -c $verify $OnedirPath $gitSha
            if ($LASTEXITCODE -ne 0) {
                throw 'The supervised onedir identity is not verified'
            }
        }
    }

    Invoke-Step 'Checking inputs' {
        if (-not (Test-Path -LiteralPath $OnedirPath -PathType Container)) {
            throw "Onedir not found: $OnedirPath (use -BuildOnedir or -OnedirPath)"
        }
        $entryPath = Join-Path $OnedirPath $Entry
        if (-not (Test-Path -LiteralPath $entryPath -PathType Leaf)) {
            throw "Entry executable not found in the onedir: $Entry"
        }
        Write-Host "    Onedir:  $OnedirPath"
        Write-Host "    Entry:   $Entry"
        Write-Host "    Version: $version  Commit: $($gitSha.Substring(0, 8))"
        Write-Host "    Output:  $Output"
    }

    Invoke-Step 'Building the launcher and packer (cargo build --release --locked)' {
        # Run from the crate directory so packaging/launcher/.cargo/config.toml applies
        # (static C runtime: no VC++ redistributable needed on the target machine).
        Push-Location $crateDir
        try {
            Invoke-Checked -Executable 'cargo' -Arguments @('build', '--release', '--locked')
        }
        finally {
            Pop-Location
        }
    }

    $releaseDir = Join-Path $crateDir 'target/release'
    $stub = Join-Path $releaseDir 'metroliza-launcher.exe'
    $packer = Join-Path $releaseDir 'metroliza-packer.exe'

    Invoke-Step 'Packing the onedir into one EXE' {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Output) | Out-Null
        if (Test-Path -LiteralPath $Output) { Remove-Item -LiteralPath $Output -Force }
        # --content-key appends the onedir content hash to the version, so the runtime cache
        # directory (<version>-<hash12>_<sha8>) follows the packed files, not only the label.
        $packerArguments = @(
            '--input', $OnedirPath,
            '--entry', $Entry,
            '--version', $version,
            '--content-key',
            '--git-sha', $gitSha,
            '--stub', $stub,
            '--output', $Output
        )
        Write-Host "    $packer $($packerArguments -join ' ')"
        $packerOutput = & $packer @packerArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Packer failed with exit code ${LASTEXITCODE}"
        }
        if (-not (Test-Path -LiteralPath $Output -PathType Leaf)) {
            throw 'Packer did not produce the output EXE'
        }
        $script:packSummary = ([string]($packerOutput | Select-Object -Last 1)) | ConvertFrom-Json
        Write-Host "    runtime key: $($script:packSummary.dir_name)"
        Write-Host "    content SHA-256: $($script:packSummary.content_sha256)"
    }

    Invoke-Step 'Signing (optional)' {
        [void](Invoke-OptionalSigning -ExePath $Output)
    }

    if ((Test-Path -LiteralPath $venvPython) -and (Test-Path -LiteralPath $provenanceManifestPath)) {
        # Sidecars describe the final bytes, so they are staged after signing.
        Invoke-Step 'Staging provenance and notice sidecars' {
            Invoke-Checked -Executable $venvPython -Arguments @(
                'scripts/build_provenance.py', 'stage',
                '--manifest', $provenanceManifestPath,
                '--artifact', $Output
            )
            Invoke-Checked -Executable $venvPython -Arguments @(
                'scripts/stage_release_notices.py',
                '--dist-dir', $distDir,
                '--artifact', $Output
            )
        }
    }
    else {
        Write-Host ""
        Write-Host '==> Provenance and notice sidecars skipped (no build provenance manifest or build venv)'
    }

    $sha = (Get-FileHash -LiteralPath $Output -Algorithm SHA256).Hash.ToLowerInvariant()
    $size = (Get-Item -LiteralPath $Output).Length
    Write-Host ""
    Write-Host "Launcher EXE: $Output"
    Write-Host "    size $size bytes, SHA-256 $sha"
    Write-Host "    runtime cache directory: $($script:packSummary.dir_name)"
}
finally {
    Pop-Location
}
