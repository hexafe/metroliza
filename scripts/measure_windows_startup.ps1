[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string[]]$ArtifactPath,

    [int]$Iterations = 3,
    [int]$WarmupRuns = 1,
    [switch]$Offscreen,
    [string]$OutputDirectory = "startup-artifacts"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Set-EnvVar {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [string]$Value
    )

    [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
}

function Restore-EnvVar {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [AllowNull()]
        [string]$Value
    )

    [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
}

function Invoke-StartupRun {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath,
        [Parameter(Mandatory = $true)]
        [string]$ProfilePath
    )

    $previousProfile = [Environment]::GetEnvironmentVariable('METROLIZA_STARTUP_PROFILE', 'Process')
    $previousProfilePath = [Environment]::GetEnvironmentVariable('METROLIZA_STARTUP_PROFILE_PATH', 'Process')
    $previousUiSmoke = [Environment]::GetEnvironmentVariable('METROLIZA_STARTUP_UI_SMOKE', 'Process')
    $previousLicense = [Environment]::GetEnvironmentVariable('METROLIZA_LICENSE_VERIFICATION', 'Process')
    $previousQtPlatform = [Environment]::GetEnvironmentVariable('QT_QPA_PLATFORM', 'Process')

    try {
        Set-EnvVar -Name 'METROLIZA_STARTUP_PROFILE' -Value '1'
        Set-EnvVar -Name 'METROLIZA_STARTUP_PROFILE_PATH' -Value $ProfilePath
        Set-EnvVar -Name 'METROLIZA_STARTUP_UI_SMOKE' -Value '1'
        Set-EnvVar -Name 'METROLIZA_LICENSE_VERIFICATION' -Value '0'
        if ($Offscreen) {
            Set-EnvVar -Name 'QT_QPA_PLATFORM' -Value 'offscreen'
        }

        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        & $ExecutablePath
        $exitCode = $LASTEXITCODE
        $stopwatch.Stop()

        return [pscustomobject]@{
            WallClockMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
            ExitCode = $exitCode
        }
    }
    finally {
        Restore-EnvVar -Name 'METROLIZA_STARTUP_PROFILE' -Value $previousProfile
        Restore-EnvVar -Name 'METROLIZA_STARTUP_PROFILE_PATH' -Value $previousProfilePath
        Restore-EnvVar -Name 'METROLIZA_STARTUP_UI_SMOKE' -Value $previousUiSmoke
        Restore-EnvVar -Name 'METROLIZA_LICENSE_VERIFICATION' -Value $previousLicense
        Restore-EnvVar -Name 'QT_QPA_PLATFORM' -Value $previousQtPlatform
    }
}

if ($Iterations -lt 1) {
    throw '-Iterations must be at least 1.'
}

if ($WarmupRuns -lt 0) {
    throw '-WarmupRuns cannot be negative.'
}

$resolvedOutputDirectory = Resolve-Path -LiteralPath $OutputDirectory -ErrorAction SilentlyContinue
if (-not $resolvedOutputDirectory) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    $resolvedOutputDirectory = Resolve-Path -LiteralPath $OutputDirectory
}

$allResults = @()
foreach ($artifact in $ArtifactPath) {
    $resolvedArtifact = Resolve-Path -LiteralPath $artifact -ErrorAction Stop
    $artifactName = [System.IO.Path]::GetFileNameWithoutExtension($resolvedArtifact.Path)
    Write-Host ""
    Write-Host "==> Measuring $($resolvedArtifact.Path)"

    $totalRuns = $WarmupRuns + $Iterations
    for ($index = 1; $index -le $totalRuns; $index++) {
        $phase = if ($index -le $WarmupRuns) { 'warmup' } else { 'sample' }
        $sampleNumber = $index - $WarmupRuns
        $profilePath = Join-Path $resolvedOutputDirectory.Path (
            "$artifactName-$phase-$index-startup-profile.jsonl"
        )
        Remove-Item -LiteralPath $profilePath -Force -ErrorAction SilentlyContinue

        $run = Invoke-StartupRun -ExecutablePath $resolvedArtifact.Path -ProfilePath $profilePath
        $events = @()
        if (Test-Path -LiteralPath $profilePath) {
            $events = @(Get-Content -LiteralPath $profilePath | ForEach-Object { $_ | ConvertFrom-Json })
        }
        $lastEvent = $events | Select-Object -Last 1
        $pythonElapsed = if ($lastEvent) { [double]$lastEvent.elapsed_ms } else { $null }

        Write-Host (
            "    {0} {1}: wall={2}ms python={3}ms exit={4} profile={5}" -f
            $phase,
            $index,
            $run.WallClockMs,
            $pythonElapsed,
            $run.ExitCode,
            $profilePath
        )

        if ($phase -eq 'sample') {
            $allResults += [pscustomobject]@{
                Artifact = $resolvedArtifact.Path
                Sample = $sampleNumber
                WallClockMs = $run.WallClockMs
                PythonElapsedMs = $pythonElapsed
                ExitCode = $run.ExitCode
                ProfilePath = $profilePath
            }
        }
    }
}

Write-Host ""
Write-Host "Startup samples:"
$allResults | Format-Table -AutoSize

$summaryPath = Join-Path $resolvedOutputDirectory.Path 'startup-summary.json'
$allResults | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
Write-Host ""
Write-Host "Summary JSON: $summaryPath"
