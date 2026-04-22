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
$vcRedistUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'

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
    $installer = Join-Path $env:TEMP 'vc_redist.x64.exe'
    Write-Host "    Downloading $vcRedistUrl"
    Invoke-WebRequest -Uri $vcRedistUrl -OutFile $installer
    Write-Host "    Running VC++ Redistributable installer. UAC/admin approval may be required."
    $process = Start-Process -FilePath $installer -ArgumentList '/install', '/quiet', '/norestart' -Wait -PassThru
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "VC++ Redistributable installer failed with exit code $($process.ExitCode)."
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
            Install-VcRedistX64
        }
        else {
            Write-Warning "Microsoft Visual C++ Redistributable 2015-2022 x64 was not detected. Install it from $vcRedistUrl or rerun this script with -InstallVcRedist."
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

    if (-not $SkipValidation -and -not $SkipOcr) {
        Invoke-Step 'Validating OCR runtime and model files' {
            Invoke-Checked -Executable $venvPython -Arguments @('scripts/windows_ocr_runtime_diagnostics.py', '--compact')
            Invoke-Checked -Executable $venvPython -Arguments @('scripts/validate_packaged_pdf_parser.py', '--require-header-ocr')
        }
    }

    Write-Host ""
    Write-Host "Windows runtime setup completed."
    Write-Host "Activate with:"
    Write-Host "    $venvPath\Scripts\Activate.ps1"
}
finally {
    Pop-Location
}
