param(
    [string]$EntryPoint = "metroliza.py",
    [string]$OutputName,
    [string]$IconPath = "$PSScriptRoot/metroliza_icon2.ico",
    [string]$CredentialsPath = "credentials.json",
    [switch]$FastDev,
    [switch]$RequireNative,
    [switch]$EnableConsole,
    [switch]$AllowBrokenPdfParserBuild,
    [ValidateSet('auto', 'msvc', 'clang', 'gcc')]
    [string]$CompilerStrategy = 'auto',
    [switch]$AutoInstallCompiler,
    [switch]$OpenInstallHelp
)

$ErrorActionPreference = "Stop"
$isWindowsHost = $env:OS -eq "Windows_NT"
$isMacOSHost = $PSVersionTable.PSVersion -and $IsMacOS
$isLinuxHost = $PSVersionTable.PSVersion -and $IsLinux

$compilerInstallConfig = @{
    Windows = @{
        PreferredCompiler = 'msvc'
        InstallUrl = 'https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022'
        WingetId = 'Microsoft.VisualStudio.2022.BuildTools'
        WingetArgs = @(
            'install', '--id', 'Microsoft.VisualStudio.2022.BuildTools', '--exact', '--silent',
            '--override', '--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended'
        )
        Guidance = @(
            'Install Visual Studio 2022 Build Tools.',
            'Select the "Desktop development with C++" workload.',
            'Ensure the MSVC v143 build tools and a Windows 10/11 SDK are included.',
            'If compiler discovery still fails, rerun from Developer PowerShell or x64 Native Tools Command Prompt.'
        )
    }
    Linux = @{
        PreferredCompiler = 'clang'
        AptPackages = @{ clang = @('clang', 'lld'); gcc = @('build-essential') }
        DnfPackages = @{ clang = @('clang', 'lld'); gcc = @('gcc', 'gcc-c++') }
        YumPackages = @{ clang = @('clang', 'lld'); gcc = @('gcc', 'gcc-c++') }
        ApkPackages = @{ clang = @('clang', 'lld'); gcc = @('build-base') }
        PacmanPackages = @{ clang = @('clang', 'lld'); gcc = @('base-devel') }
    }
    macOS = @{
        PreferredCompiler = 'clang'
        InstallUrl = 'https://developer.apple.com/xcode/resources/'
        BrewPackages = @{ clang = @('llvm'); gcc = @('gcc') }
        Guidance = @(
            'Install Xcode Command Line Tools (`xcode-select --install`) for Apple clang.',
            'If you prefer Homebrew-managed toolchains, install `llvm` or `gcc` and ensure the binaries are on PATH.'
        )
    }
}

function Invoke-CheckedPythonCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Test-CommandAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    return $null -ne (Get-Command $CommandName -ErrorAction SilentlyContinue)
}

function New-CompilerCandidate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [bool]$Available,
        [Parameter(Mandatory = $true)]
        [string]$Reason,
        [string]$Command = '',
        [string]$Version = '',
        [int]$Priority = 100,
        [string[]]$NuitkaArgs = @()
    )

    return [pscustomobject]@{
        Name = $Name
        Available = $Available
        Reason = $Reason
        Command = $Command
        Version = $Version
        Priority = $Priority
        NuitkaArgs = $NuitkaArgs
    }
}

function Get-CommandVersionText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName,
        [string[]]$Arguments = @('--version')
    )

    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if (-not $command) {
        return $null
    }

    $output = & $command.Source @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    return (($output | Select-Object -First 1) -as [string])
}

function Test-MsvcToolchain {
    $clCommand = Get-Command cl.exe -ErrorAction SilentlyContinue
    if ($clCommand) {
        $banner = & $clCommand.Source 2>&1
        if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq 1) {
            $versionLine = (($banner | Select-Object -First 1) -as [string]).Trim()
            $reason = "cl.exe responded on PATH"
            if ($env:VSCMD_VER -or $env:VCINSTALLDIR -or $env:VisualStudioVersion) {
                $reason += " and Developer Tools environment variables are present"
            }

            return New-CompilerCandidate -Name 'msvc' -Available $true -Reason $reason -Command $clCommand.Source -Version $versionLine -Priority 10 -NuitkaArgs @('--msvc=latest')
        }
    }

    $programFilesX86 = ${env:ProgramFiles(x86)}
    if (-not $programFilesX86) {
        return New-CompilerCandidate -Name 'msvc' -Available $false -Reason "ProgramFiles(x86) is unavailable, so Visual Studio discovery could not run" -Priority 10
    }

    $vswherePath = Join-Path $programFilesX86 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswherePath)) {
        return New-CompilerCandidate -Name 'msvc' -Available $false -Reason "vswhere.exe was not found and cl.exe is not on PATH" -Priority 10
    }

    $installationPath = & $vswherePath -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($installationPath)) {
        return New-CompilerCandidate -Name 'msvc' -Available $false -Reason "Visual Studio Build Tools with the MSVC workload were not discovered by vswhere" -Priority 10
    }

    return New-CompilerCandidate -Name 'msvc' -Available $true -Reason "Visual Studio Build Tools were discovered at '$installationPath', but run from Developer PowerShell if cl.exe is not yet on PATH" -Command $vswherePath -Version ($installationPath.Trim()) -Priority 10 -NuitkaArgs @('--msvc=latest')
}

function Test-ClangToolchain {
    param(
        [switch]$WindowsMode
    )

    $commandsToTry = if ($WindowsMode) { @('clang-cl.exe', 'clang.exe', 'clang-cl', 'clang') } else { @('clang', 'clang++') }
    foreach ($commandName in $commandsToTry) {
        $versionLine = Get-CommandVersionText -CommandName $commandName
        if ($versionLine) {
            $reason = if ($WindowsMode) {
                "LLVM/clang is callable; use only as an explicit fallback when MSVC is unavailable"
            } else {
                "clang is callable and reports a version"
            }

            return New-CompilerCandidate -Name 'clang' -Available $true -Reason $reason -Command $commandName -Version $versionLine.Trim() -Priority ($(if ($WindowsMode) { 30 } else { 10 }))
        }
    }

    $reason = if ($WindowsMode) {
        'Neither clang-cl nor clang reported a usable version'
    } else {
        'clang was not found or did not return a version banner'
    }
    return New-CompilerCandidate -Name 'clang' -Available $false -Reason $reason -Priority ($(if ($WindowsMode) { 30 } else { 10 }))
}

function Test-GccToolchain {
    param(
        [switch]$WindowsMode
    )

    if (-not (Test-CommandAvailable -CommandName 'g++') -and -not (Test-CommandAvailable -CommandName 'gcc')) {
        return New-CompilerCandidate -Name 'gcc' -Available $false -Reason 'gcc/g++ were not found on PATH' -Priority ($(if ($WindowsMode) { 50 } else { 20 }))
    }

    $compilerVersion = Get-CommandVersionText -CommandName 'g++'
    if (-not $compilerVersion) {
        $compilerVersion = Get-CommandVersionText -CommandName 'gcc'
    }

    if ($compilerVersion) {
        $reason = if ($WindowsMode) {
            'gcc/g++ are callable, but MinGW remains a lower-priority fallback for this Windows Nuitka packaging path'
        } else {
            'gcc/g++ are callable and report a version'
        }

        return New-CompilerCandidate -Name 'gcc' -Available $true -Reason $reason -Command 'g++' -Version $compilerVersion.Trim() -Priority ($(if ($WindowsMode) { 50 } else { 20 }))
    }

    return New-CompilerCandidate -Name 'gcc' -Available $false -Reason 'gcc/g++ were found but did not return a healthy version banner' -Priority ($(if ($WindowsMode) { 50 } else { 20 }))
}

function Get-WindowsCompilerCandidates {
    return @(
        Test-MsvcToolchain
        Test-ClangToolchain -WindowsMode
        Test-GccToolchain -WindowsMode
    )
}

function Get-PosixCompilerCandidates {
    $candidates = @(
        Test-ClangToolchain
        Test-GccToolchain
    )

    if ($isMacOSHost) {
        return $candidates | Sort-Object Priority, Name
    }

    $healthyClang = $candidates | Where-Object { $_.Name -eq 'clang' -and $_.Available }
    $healthyGcc = $candidates | Where-Object { $_.Name -eq 'gcc' -and $_.Available }
    if ($healthyGcc -and -not $healthyClang) {
        ($candidates | Where-Object { $_.Name -eq 'gcc' }).Priority = 10
        ($candidates | Where-Object { $_.Name -eq 'clang' }).Priority = 20
    }

    return $candidates | Sort-Object Priority, Name
}

function Resolve-PreferredCompiler {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject[]]$Candidates,
        [Parameter(Mandatory = $true)]
        [string]$Strategy
    )

    $requested = $Strategy.ToLowerInvariant()
    $selectedCandidate = $null
    $selectionReason = ''

    if ($requested -eq 'auto') {
        $selectedCandidate = $Candidates | Where-Object { $_.Available } | Sort-Object Priority, Name | Select-Object -First 1
        if ($selectedCandidate) {
            $selectionReason = "Auto-selected the highest-priority healthy compiler for this platform ($($selectedCandidate.Name))."
        }
    } else {
        $selectedCandidate = $Candidates | Where-Object { $_.Name -eq $requested } | Select-Object -First 1
        if ($selectedCandidate -and $selectedCandidate.Available) {
            $selectionReason = "Explicit compiler strategy '$requested' was requested and that toolchain is healthy."
        } else {
            $selectedCandidate = $null
        }
    }

    return [pscustomobject]@{
        RequestedStrategy = $requested
        Candidates = $Candidates
        Selected = $selectedCandidate
        SelectionReason = $selectionReason
        AutoInstallAttempted = $false
    }
}

function Show-CompilerInstallGuidance {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Resolution
    )

    $platformKey = if ($isWindowsHost) { 'Windows' } elseif ($isMacOSHost) { 'macOS' } else { 'Linux' }
    $config = $compilerInstallConfig[$platformKey]
    $preferredCompiler = if ($Resolution.RequestedStrategy -eq 'auto') { $config.PreferredCompiler } else { $Resolution.RequestedStrategy }

    Write-Warning "No healthy compiler toolchain was available for strategy '$($Resolution.RequestedStrategy)'. Preferred compiler for this platform: $preferredCompiler"
    Write-Host 'Rejected compiler candidates:'
    foreach ($candidate in $Resolution.Candidates | Sort-Object Priority, Name) {
        $status = if ($candidate.Available) { 'healthy but not selected' } else { 'rejected' }
        $detail = if ($candidate.Version) { "$($candidate.Reason) [$($candidate.Version)]" } else { $candidate.Reason }
        Write-Host "      - $($candidate.Name): $status ($detail)"
    }

    if ($isWindowsHost) {
        Write-Host 'Recommended install action:'
        foreach ($item in $config.Guidance) {
            Write-Host "      - $item"
        }
        Write-Host "      - winget command: winget $($config.WingetArgs -join ' ')"
        Write-Host "      - download URL: $($config.InstallUrl)"
        return
    }

    if ($isMacOSHost) {
        Write-Host 'Recommended install action:'
        foreach ($item in $config.Guidance) {
            Write-Host "      - $item"
        }
        Write-Host "      - Homebrew clang: brew install $($config.BrewPackages.clang -join ' ')"
        Write-Host "      - Homebrew gcc: brew install $($config.BrewPackages.gcc -join ' ')"
        Write-Host "      - Apple tools URL: $($config.InstallUrl)"
        return
    }

    Write-Host 'Recommended install action:'
    if (Test-CommandAvailable -CommandName 'apt-get') {
        Write-Host "      - sudo apt-get update && sudo apt-get install -y $($config.AptPackages[$preferredCompiler] -join ' ')"
    }
    if (Test-CommandAvailable -CommandName 'dnf') {
        Write-Host "      - sudo dnf install -y $($config.DnfPackages[$preferredCompiler] -join ' ')"
    }
    if (Test-CommandAvailable -CommandName 'yum') {
        Write-Host "      - sudo yum install -y $($config.YumPackages[$preferredCompiler] -join ' ')"
    }
    if (Test-CommandAvailable -CommandName 'apk') {
        Write-Host "      - sudo apk add $($config.ApkPackages[$preferredCompiler] -join ' ')"
    }
    if (Test-CommandAvailable -CommandName 'pacman') {
        Write-Host "      - sudo pacman -S --needed $($config.PacmanPackages[$preferredCompiler] -join ' ')"
    }
}

function Install-PreferredCompiler {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Resolution
    )

    $platformKey = if ($isWindowsHost) { 'Windows' } elseif ($isMacOSHost) { 'macOS' } else { 'Linux' }
    $config = $compilerInstallConfig[$platformKey]
    $preferredCompiler = if ($Resolution.RequestedStrategy -eq 'auto') { $config.PreferredCompiler } else { $Resolution.RequestedStrategy }

    Write-Host "Attempting compiler installation for strategy '$preferredCompiler'."

    if ($isWindowsHost) {
        if (-not (Test-CommandAvailable -CommandName 'winget')) {
            Write-Warning 'winget is not available, so automatic Visual Studio Build Tools installation cannot run.'
            return $false
        }

        Write-Host "      Running: winget $($config.WingetArgs -join ' ')"
        & winget @($config.WingetArgs)
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'winget install did not complete successfully.'
            return $false
        }

        return $true
    }

    if ($isMacOSHost) {
        if (-not (Test-CommandAvailable -CommandName 'brew')) {
            Write-Warning 'Homebrew is not available, so automatic compiler installation cannot run on macOS.'
            return $false
        }

        $packages = $config.BrewPackages[$preferredCompiler]
        if (-not $packages) {
            Write-Warning "No Homebrew package mapping is defined for compiler '$preferredCompiler'."
            return $false
        }

        Write-Host "      Running: brew install $($packages -join ' ')"
        & brew install @packages
        return ($LASTEXITCODE -eq 0)
    }

    if ((Test-CommandAvailable -CommandName 'apt-get') -and (Test-CommandAvailable -CommandName 'sudo')) {
        $packages = $config.AptPackages[$preferredCompiler]
        if ($packages) {
            Write-Host '      Running: sudo apt-get update'
            & sudo apt-get update
            if ($LASTEXITCODE -ne 0) {
                return $false
            }
            Write-Host "      Running: sudo apt-get install -y $($packages -join ' ')"
            & sudo apt-get install -y @packages
            return ($LASTEXITCODE -eq 0)
        }
    }

    if ((Test-CommandAvailable -CommandName 'dnf') -and (Test-CommandAvailable -CommandName 'sudo')) {
        $packages = $config.DnfPackages[$preferredCompiler]
        if ($packages) {
            Write-Host "      Running: sudo dnf install -y $($packages -join ' ')"
            & sudo dnf install -y @packages
            return ($LASTEXITCODE -eq 0)
        }
    }

    if ((Test-CommandAvailable -CommandName 'yum') -and (Test-CommandAvailable -CommandName 'sudo')) {
        $packages = $config.YumPackages[$preferredCompiler]
        if ($packages) {
            Write-Host "      Running: sudo yum install -y $($packages -join ' ')"
            & sudo yum install -y @packages
            return ($LASTEXITCODE -eq 0)
        }
    }

    if ((Test-CommandAvailable -CommandName 'apk') -and (Test-CommandAvailable -CommandName 'sudo')) {
        $packages = $config.ApkPackages[$preferredCompiler]
        if ($packages) {
            Write-Host "      Running: sudo apk add $($packages -join ' ')"
            & sudo apk add @packages
            return ($LASTEXITCODE -eq 0)
        }
    }

    if ((Test-CommandAvailable -CommandName 'pacman') -and (Test-CommandAvailable -CommandName 'sudo')) {
        $packages = $config.PacmanPackages[$preferredCompiler]
        if ($packages) {
            Write-Host "      Running: sudo pacman -S --needed $($packages -join ' ')"
            & sudo pacman -S --needed @packages
            return ($LASTEXITCODE -eq 0)
        }
    }

    Write-Warning 'No supported automatic compiler installation flow is available on this host.'
    return $false
}

function Get-DefaultOutputName {
    $versionInfo = python -c "import sys,pathlib;root=pathlib.Path.cwd();vp=root/'VersionDate.py';ns={};exec(vp.read_text(encoding='utf-8'), ns);release=ns.get('RELEASE_VERSION');build=ns.get('VERSION_DATE');sys.stdout.write(f'{release}|{build}' if release and build else '')" 2>$null
    if ($LASTEXITCODE -eq 0 -and $versionInfo) {
        $parts = $versionInfo.Split("|")
        if ($parts.Count -eq 2 -and $parts[0] -and $parts[1]) {
            return "metroliza_N_$($parts[0])($($parts[1])).exe"
        }
    }

    Write-Warning 'Could not read release/build metadata from VersionDate.py. Falling back to date-based output name.'
    return "metroliza_N_$(Get-Date -Format yyMMdd).exe"
}

if (-not $OutputName) {
    $OutputName = Get-DefaultOutputName
}

# Section: environment validation
Write-Host '[1/6] Validating environment'
python -c "import importlib.util,sys;mods=['nuitka','PyQt6'];missing=[m for m in mods if importlib.util.find_spec(m) is None];sys.exit(1 if missing else 0)" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'Missing build requirements. Install with: pip install -r requirements-build.txt'
}

python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('PyQt5') else 1)" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Warning 'PyQt5 detected in this environment. Remove it to avoid PyQt6 plugin/import conflicts: pip uninstall PyQt5'
}

$jobs = if ($env:NUMBER_OF_PROCESSORS) { $env:NUMBER_OF_PROCESSORS } else { 4 }
$modeLabel = if ($FastDev) { 'standalone (faster dev build)' } else { 'onefile (release-like build)' }
$nativeModeLabel = if ($RequireNative) { 'required' } else { 'optional' }
$credentialsPathLabel = if ($CredentialsPath) { $CredentialsPath } else { '(disabled)' }
$consoleMode = if ($EnableConsole) { 'force' } else { 'disable' }
$pdfGateLabel = if ($AllowBrokenPdfParserBuild) { 'UNSAFE OVERRIDE ENABLED' } else { 'strict' }

Write-Host '[2/6] Build mode'
Write-Host "      Native parser module: $nativeModeLabel"
Write-Host "      PDF parser gate: $pdfGateLabel"
Write-Host "      Credentials bundle path: $credentialsPathLabel"
Write-Host "      Windows console mode: $consoleMode"
Write-Host "      Requested compiler strategy: $CompilerStrategy"
Write-Host "      Auto-install compiler: $($AutoInstallCompiler.IsPresent)"
Write-Host "      Open install help: $($OpenInstallHelp.IsPresent)"

$nativeModuleAvailable = $false
python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('_metroliza_cmm_native') else 1)" 2>$null
if ($LASTEXITCODE -eq 0) {
    $nativeModuleAvailable = $true
}

$pdfBackendPackageAvailable = $false
python -c "import sys,pathlib;root=pathlib.Path.cwd();sys.path.insert(0, str(root));from scripts.validate_packaged_pdf_parser import require_pdf_backend_available;print(require_pdf_backend_available(allow_broken=False))" 2>$null
if ($LASTEXITCODE -eq 0) {
    $pdfBackendPackageAvailable = $true
}

if ($RequireNative -and -not $nativeModuleAvailable) {
    throw "Native module '_metroliza_cmm_native' is required but unavailable. Build/install it first: python -m maturin develop --manifest-path modules/native/cmm_parser/Cargo.toml"
}

if (-not $pdfBackendPackageAvailable -and -not $AllowBrokenPdfParserBuild) {
    throw 'PyMuPDF is required for packaged builds. Install PyMuPDF before invoking Nuitka, or pass -AllowBrokenPdfParserBuild only for explicitly unsafe local diagnostics.'
}

if ($AllowBrokenPdfParserBuild) {
    Write-Warning 'UNSAFE: continuing even though packaged PDF parsing may be broken. Do not use this switch for release artifacts.'
}

# Section: compiler detection / selection
Write-Host '[3/6] Detecting compiler toolchains'
$compilerCandidates = if ($isWindowsHost) { Get-WindowsCompilerCandidates } else { Get-PosixCompilerCandidates }
$compilerResolution = Resolve-PreferredCompiler -Candidates $compilerCandidates -Strategy $CompilerStrategy

Write-Host '      Detected compiler candidates:'
foreach ($candidate in $compilerResolution.Candidates | Sort-Object Priority, Name) {
    $status = if ($candidate.Available) { 'healthy' } else { 'rejected' }
    $detail = if ($candidate.Version) { "$($candidate.Reason) [$($candidate.Version)]" } else { $candidate.Reason }
    Write-Host "      - $($candidate.Name): $status ($detail)"
}

if (-not $compilerResolution.Selected -and $AutoInstallCompiler) {
    Write-Host '[4/6] Attempting compiler installation'
    $compilerResolution.AutoInstallAttempted = $true
    $installSucceeded = Install-PreferredCompiler -Resolution $compilerResolution
    if ($installSucceeded) {
        $compilerCandidates = if ($isWindowsHost) { Get-WindowsCompilerCandidates } else { Get-PosixCompilerCandidates }
        $compilerResolution = Resolve-PreferredCompiler -Candidates $compilerCandidates -Strategy $CompilerStrategy
        $compilerResolution.AutoInstallAttempted = $true
    }
}

if (-not $compilerResolution.Selected) {
    if ($OpenInstallHelp) {
        Show-CompilerInstallGuidance -Resolution $compilerResolution
        if ($isWindowsHost -and (Test-CommandAvailable -CommandName 'Start-Process')) {
            Start-Process $compilerInstallConfig.Windows.InstallUrl | Out-Null
        }
    } else {
        Show-CompilerInstallGuidance -Resolution $compilerResolution
    }

    throw "No usable compiler toolchain was found for strategy '$CompilerStrategy'."
}

Write-Host "      Selected compiler: $($compilerResolution.Selected.Name)"
Write-Host "      Selection reason: $($compilerResolution.SelectionReason)"
Write-Host "      Auto-install attempted: $($compilerResolution.AutoInstallAttempted)"
if ($isWindowsHost -and $compilerResolution.Selected.Name -eq 'msvc') {
    Write-Warning "Windows build is using '--msvc=latest' so bundled PyMuPDF stays on the preferred MSVC toolchain path."
}
if ($nativeModuleAvailable) {
    Write-Host '      Native parser packaging: include compiled native module'
} else {
    Write-Warning "Native module '_metroliza_cmm_native' not found in this environment. Building with pure-Python parser fallback only."
}

# Section: Nuitka argument assembly
# Keep parser/runtime imports explicit here because the rc1 plugin/backend refactor
# introduced dynamic import paths that packagers may not infer reliably on their own.
$commonArgs = @(
    '-m', 'nuitka', $EntryPoint,
    "--windows-console-mode=$consoleMode",
    '--enable-plugin=pyqt6',
    '--include-package=modules',
    '--include-module=modules.cmm_report_parser',
    '--include-module=modules.report_parser_factory',
    '--include-module=modules.pdf_backend',
    '--include-package-data=pymupdf',
    '--include-package-data=fitz',
    "--windows-icon-from-ico=$IconPath",
    "--output-filename=$OutputName",
    '--assume-yes-for-downloads',
    '--remove-output',
    "--jobs=$jobs",
    '--report=nuitka-build-report.xml'
)

if ($compilerResolution.Selected.NuitkaArgs) {
    $commonArgs += $compilerResolution.Selected.NuitkaArgs
}

if ($nativeModuleAvailable) {
    $commonArgs += '--include-module=_metroliza_cmm_native'
}

if ($pdfBackendPackageAvailable) {
    $commonArgs += '--include-package=pymupdf'
    $commonArgs += '--include-package=fitz'

    $requiredPdfBackendModules = @(
        'pymupdf._mupdf',
        'pymupdf._extra',
        'pymupdf.extra',
        'pymupdf.mupdf',
        'pymupdf.table',
        'pymupdf.utils',
        'fitz.table',
        'fitz.utils'
    )
    foreach ($moduleName in $requiredPdfBackendModules) {
        $commonArgs += "--include-module=$moduleName"
    }
}

$tokenExcludePatterns = @(
    'token.json',
    '*token.json',
    '**/token.json',
    '**/*token.json'
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
    $commonArgs += '--onefile'
} else {
    $commonArgs += '--standalone'
}

# Section: build execution
Write-Host '[5/6] Running Nuitka build'
Invoke-CheckedPythonCommand -Arguments $commonArgs -FailureMessage "Nuitka build failed. See the compiler output above. Selected compiler: $($compilerResolution.Selected.Name)."

# Section: post-build validation
Write-Host '[6/6] Validating packaged PDF parser dependencies'
$validationArgs = @('scripts/validate_packaged_pdf_parser.py', '--report', 'nuitka-build-report.xml')
if ($AllowBrokenPdfParserBuild) {
    $validationArgs += '--allow-broken-pdf-parser-build'
}
Invoke-CheckedPythonCommand -Arguments $validationArgs -FailureMessage "Packaged PDF parser dependency validation failed. See 'nuitka-build-report.xml' details above."

Write-Host 'Done'
Write-Host "Build output name: $OutputName"
Write-Host 'Dependency report: nuitka-build-report.xml'
Write-Host 'Note: install Microsoft Visual C++ Redistributable (x64, 2015-2022) on target PCs if needed.'
