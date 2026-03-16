param(
    [string]$EntryPoint = "metroliza.py",
    [string]$OutputName,
    [string]$IconPath = "$PSScriptRoot/metroliza_icon2.ico",
    [string]$CredentialsPath = "credentials.json",
    [switch]$FastDev,
    [switch]$RequireNative,
    [switch]$EnableConsole
)

$ErrorActionPreference = "Stop"

function Get-DefaultOutputName {
    $versionInfo = python -c "import sys,pathlib;root=pathlib.Path.cwd();vp=root/'VersionDate.py';ns={};exec(vp.read_text(encoding='utf-8'), ns);release=ns.get('RELEASE_VERSION');build=ns.get('VERSION_DATE');sys.stdout.write(f'{release}|{build}' if release and build else '')" 2>$null
    if ($LASTEXITCODE -eq 0 -and $versionInfo) {
        $parts = $versionInfo.Split("|")
        if ($parts.Count -eq 2 -and $parts[0] -and $parts[1]) {
            return "metroliza_N_$($parts[0])($($parts[1])).exe"
        }
    }

    Write-Warning "Could not read release/build metadata from VersionDate.py. Falling back to date-based output name."
    return "metroliza_N_$(Get-Date -Format yyMMdd).exe"
}

if (-not $OutputName) {
    $OutputName = Get-DefaultOutputName
}

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
$nativeModeLabel = if ($RequireNative) { "required" } else { "optional" }
$credentialsPathLabel = if ($CredentialsPath) { $CredentialsPath } else { "(disabled)" }
$consoleMode = if ($EnableConsole) { "force" } else { "disable" }

Write-Host "[2/4] Build mode: $modeLabel"
Write-Host "      Native parser module: $nativeModeLabel"
Write-Host "      Credentials bundle path: $credentialsPathLabel"
Write-Host "      Windows console mode: $consoleMode"

$nativeModuleAvailable = $false
python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('_metroliza_cmm_native') else 1)" 2>$null
if ($LASTEXITCODE -eq 0) {
    $nativeModuleAvailable = $true
}

if ($RequireNative -and -not $nativeModuleAvailable) {
    throw "Native module '_metroliza_cmm_native' is required but unavailable. Build/install it first: python -m maturin develop --manifest-path modules/native/cmm_parser/Cargo.toml"
}

$commonArgs = @(
    "-m", "nuitka", $EntryPoint,
    "--windows-console-mode=$consoleMode",
    "--enable-plugin=pyqt6",
    "--include-package=modules",
    "--windows-icon-from-ico=$IconPath",
    "--output-filename=$OutputName",
    "--assume-yes-for-downloads",
    "--remove-output",
    "--jobs=$jobs",
    "--report=nuitka-build-report.xml"
)

if ($nativeModuleAvailable) {
    $commonArgs += "--include-module=_metroliza_cmm_native"
} else {
    Write-Warning "Native module '_metroliza_cmm_native' not found in this environment. Building with pure-Python parser fallback only."
}

$tokenExcludePatterns = @(
    "token.json",
    "*token.json",
    "**/token.json",
    "**/*token.json"
)
foreach ($pattern in $tokenExcludePatterns) {
    $commonArgs += "--noinclude-data-files=$pattern"
}

if ($CredentialsPath) {
    $resolvedCredentialsPath = Resolve-Path -LiteralPath $CredentialsPath -ErrorAction SilentlyContinue
    if ($resolvedCredentialsPath) {
        $destinationName = [System.IO.Path]::GetFileName($resolvedCredentialsPath.Path)
        $commonArgs += "--include-data-files=$($resolvedCredentialsPath.Path)=$destinationName"
    } else {
        Write-Warning "Credentials file '$CredentialsPath' was not found. Continuing without bundling credentials.json."
    }
}

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
