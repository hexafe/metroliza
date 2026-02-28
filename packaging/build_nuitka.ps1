param(
    [string]$EntryPoint = "metroliza.py",
    [string]$OutputName = "metroliza_N_260223.exe",
    [string]$IconPath = "$PSScriptRoot/metroliza_icon2.ico",
    [switch]$FastDev
)

$ErrorActionPreference = "Stop"

Write-Host "[1/4] Validating environment"
python -c "import importlib.util,sys;mods=['nuitka','PyQt6'];missing=[m for m in mods if importlib.util.find_spec(m) is None];sys.exit(1 if missing else 0)" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Missing build requirements. Install with: pip install -r requirements-build.txt"
}

python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('PyQt5') else 1)" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Warning "PyQt5 detected in this environment. Remove it to avoid PyQt6 plugin/import conflicts: pip uninstall PyQt5"
}

$jobs = if ($env:NUMBER_OF_PROCESSORS) { $env:NUMBER_OF_PROCESSORS } else { 4 }
$modeLabel = if ($FastDev) { "standalone (faster dev build)" } else { "onefile (release-like build)" }

Write-Host "[2/4] Build mode: $modeLabel"

$commonArgs = @(
    "-m", "nuitka", $EntryPoint,
    "--windows-console-mode=disable",
    "--enable-plugin=pyqt6",
    "--windows-icon-from-ico=$IconPath",
    "--output-filename=$OutputName",
    "--assume-yes-for-downloads",
    "--remove-output",
    "--jobs=$jobs",
    "--report=nuitka-build-report.xml",
    "--include-module=_metroliza_cmm_native"
)

if (-not $FastDev) {
    $commonArgs += "--onefile"
} else {
    $commonArgs += "--standalone"
}

Write-Host "[3/4] Running Nuitka build"
python @commonArgs

Write-Host "[4/4] Done"
Write-Host "Build output name: $OutputName"
Write-Host "Dependency report: nuitka-build-report.xml"
Write-Host "Note: install Microsoft Visual C++ Redistributable (x64, 2015-2022) on target PCs if needed."
