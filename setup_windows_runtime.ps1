[CmdletBinding()]
param(
    [string]$PythonVersion = '3.12',
    [string]$VenvDir = '.venv',
    [switch]$Clean,
    [switch]$WithDev,
    [switch]$WithBuild,
    [switch]$SkipOcr,
    [switch]$SkipValidation,
    [switch]$InstallVcRedist
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = if ([System.IO.Path]::IsPathRooted($VenvDir)) { $VenvDir } else { Join-Path $repoRoot $VenvDir }
$venvPython = Join-Path $venvPath 'Scripts/python.exe'
# VC++ v14 x64 14.44.35211.0 from Microsoft's Visual Studio 2022 channel.
$vcRedistUrl = 'https://download.visualstudio.microsoft.com/download/pr/e9604e21-4b79-4096-a4b3-1b63d4b55b4d/CC0FF0EB1DC3F5188AE6300FAEF32BF5BEEBA4BDD6E8E445A9184072096B713B/VC_redist.x64.exe'
$vcRedistSha256 = 'cc0ff0eb1dc3f5188ae6300faef32bf5beeba4bdd6e8e445a9184072096b713b'
$vcRedistManual = 'Install the x64 package manually using https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/ and rerun setup.'

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

function Test-WindowsOs {
    return [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows
    )
}

function Test-VcRedistX64 {
    if (-not (Test-WindowsOs)) {
        return $true
    }

    $keys = @(
        'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
    )

    foreach ($key in $keys) {
        if (-not (Test-Path -LiteralPath $key)) {
            continue
        }
        $props = Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
        if ($null -ne $props -and $props.Installed -eq 1) {
            return $true
        }
    }

    return $false
}

function Install-VcRedistX64 {
    try {
        $workDir = Join-Path ([IO.Path]::GetTempPath()) ('metroliza-vcredist-' + [Guid]::NewGuid().ToString('N'))
        $null = New-Item -Path $workDir -ItemType Directory -ErrorAction Stop
    }
    catch {
        throw "Could not create the VC++ Redistributable temporary directory. $vcRedistManual"
    }

    $installer = Join-Path $workDir 'vc_redist.x64.exe'
    $installerFile = $null
    try {
        Write-Host '    Downloading the pinned Microsoft VC++ Redistributable x64.'
        try {
            Invoke-WebRequest -Uri $vcRedistUrl -OutFile $installer -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 90
            # Retain read access while denying writers and deletion through process completion.
            $installerFile = [IO.File]::Open($installer, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
            $digest = (Get-FileHash -InputStream $installerFile -Algorithm SHA256).Hash
        }
        catch {
            throw "Could not download or read the pinned VC++ Redistributable. $vcRedistManual"
        }
        if ($digest -ne $vcRedistSha256) {
            throw "VC++ Redistributable SHA-256 verification failed. $vcRedistManual"
        }

        try {
            $signature = Get-AuthenticodeSignature -LiteralPath $installer -ErrorAction Stop
            $approved = $signature.Status -eq 'Valid' -and $null -ne $signature.SignerCertificate -and
                $signature.SignerCertificate.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) -ceq 'Microsoft Corporation'
        }
        catch {
            $approved = $false
        }
        if (-not $approved) {
            throw "VC++ Redistributable Authenticode verification failed. $vcRedistManual"
        }

        Write-Host '    Microsoft VC++ Redistributable SHA-256 and Authenticode verified.'
        Write-Host '    Running the verified installer. Approve the Windows administrator prompt if shown.'
        try {
            $process = Start-Process -FilePath $installer -ArgumentList '/install', '/quiet', '/norestart' -Verb RunAs -Wait -PassThru
            $exitCode = if ($null -ne $process) { $process.ExitCode }
        }
        catch {
            throw "Could not start the verified VC++ Redistributable with administrator approval. $vcRedistManual"
        }
        if ($null -eq $exitCode) {
            throw "The VC++ Redistributable installer returned no exit code. $vcRedistManual"
        }
        if ($exitCode -notin @(0, 3010)) {
            throw "VC++ Redistributable installer failed with exit code $exitCode. $vcRedistManual"
        }
    }
    finally {
        try {
            if ($null -ne $installerFile) {
                $installerFile.Dispose()
            }
            [IO.File]::Delete($installer)
            [IO.Directory]::Delete($workDir)
        }
        catch {
            Write-Warning 'Could not remove the VC++ Redistributable temporary files.' -WarningAction Continue
        }
    }
}

function New-ProjectVenv {
    if (Test-Path -LiteralPath $venvPython) {
        return
    }

    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        Invoke-Checked -Executable 'py' -Arguments @("-$PythonVersion", '-m', 'venv', $venvPath)
        return
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw 'Python was not found on PATH. Install Python 3.11+ or the Python launcher for Windows, then rerun this script.'
    }

    Invoke-Checked -Executable 'python' -Arguments @('-m', 'venv', $venvPath)
}

Push-Location $repoRoot
try {
    Invoke-Step 'Checking Windows native prerequisite' {
        if (Test-VcRedistX64) {
            Write-Host '    Microsoft Visual C++ Redistributable x64: present or not required on this OS.'
        }
        elseif ($InstallVcRedist) {
            try {
                Install-VcRedistX64
            }
            catch {
                [Console]::Error.WriteLine($_.Exception.Message)
                exit 1
            }
        }
        else {
            throw "Microsoft Visual C++ Redistributable 2015-2022 x64 was not detected. Run setup with -InstallVcRedist for automatic installation. $vcRedistManual"
        }
    }

    if ($Clean -and (Test-Path -LiteralPath $venvPath)) {
        Invoke-Step 'Removing existing virtual environment' {
            Remove-Item -LiteralPath $venvPath -Recurse -Force
            Write-Host "    Removed $venvPath"
        }
    }

    Invoke-Step 'Creating virtual environment' {
        New-ProjectVenv
        if (-not (Test-Path -LiteralPath $venvPython)) {
            throw "Virtual environment Python was not created: $venvPython"
        }
        Write-Host "    Python: $venvPython"
    }

    Invoke-Step 'Installing runtime requirements' {
        Invoke-Checked -Executable $venvPython -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip', 'wheel')
        Invoke-Checked -Executable $venvPython -Arguments @('-m', 'pip', 'install', '-r', 'requirements.txt')
        if (-not $SkipOcr) {
            Invoke-Checked -Executable $venvPython -Arguments @('-m', 'pip', 'install', '-r', 'requirements-ocr.txt')
        }
        if ($WithDev) {
            Invoke-Checked -Executable $venvPython -Arguments @('-m', 'pip', 'install', '-r', 'requirements-dev.txt')
        }
        if ($WithBuild) {
            Invoke-Checked -Executable $venvPython -Arguments @('-m', 'pip', 'install', '-r', 'requirements-build.txt')
        }
    }

    if (-not $SkipValidation) {
        Invoke-Step 'Validating Qt runtime' {
            Invoke-Checked -Executable $venvPython -Arguments @('scripts/validate_qt_runtime.py', '--compact')
        }
    }

    if (-not $SkipValidation -and -not $SkipOcr) {
        Invoke-Step 'Validating OCR runtime and model files' {
            & (Join-Path $repoRoot 'diagnose_windows_ocr.ps1') -VenvDir $venvPath -Compact
            if ($LASTEXITCODE -ne 0) {
                [Console]::Error.WriteLine('Required OCR diagnostic validation failed. Inspect the safe check results.')
                exit 1
            }
        }
    }

    Write-Host ""
    if ($SkipValidation) {
        Write-Host 'Validation skipped (SkipValidation); OCR was not tested.'
    }
    elseif ($SkipOcr) {
        Write-Host 'OCR validation skipped (SkipOcr); OCR was not tested.'
    }
    Write-Host "Windows runtime setup completed."
    Write-Host "Activate with:"
    Write-Host "    $venvPath\Scripts\Activate.ps1"
}
finally {
    Pop-Location
}
