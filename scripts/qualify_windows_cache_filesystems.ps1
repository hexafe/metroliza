$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows' -or
    $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or
    $env:GITHUB_EVENT_NAME -ne 'workflow_dispatch' -or -not $env:RUNNER_TEMP) {
    throw 'This probe requires a disposable GitHub-hosted Windows dispatch.'
}
$caller = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($caller)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'The hosted probe cannot provision disposable volumes without storage privileges.'
}

function New-ScratchVolume($root, $fileSystem) {
    $path = Join-Path $root "$fileSystem.vhdx"
    $commands = Join-Path $root "$fileSystem.diskpart"
    if (Test-Path -LiteralPath $path) { throw 'Expected an unused image filename.' }
    'create vdisk file="{0}" maximum=256 type=expandable' -f $path |
        Set-Content -LiteralPath $commands -Encoding ascii
    & (Join-Path ([Environment]::SystemDirectory) 'diskpart.exe') /s $commands | Out-Host
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw 'Could not create the disposable disk image.'
    }

    $existing = @(Get-Disk | ForEach-Object Number)
    Mount-DiskImage -ImagePath $path -StorageType VHDX -NoDriveLetter | Out-Null
    $image = Get-DiskImage -ImagePath $path
    $devicePrefix = [regex]::Escape('\\.\PhysicalDrive')
    if (-not $image.Attached -or $image.ImagePath -ne $path -or
        $image.DevicePath -notmatch "^$devicePrefix(\d+)$") {
        throw 'The attached image identity could not be verified.'
    }
    $number = [int]$Matches[1]
    $disk = Get-Disk -Number $number
    if ($disk.Number -in $existing -or $disk.IsBoot -or $disk.IsSystem -or
        $disk.PartitionStyle -ne 'RAW' -or $disk.NumberOfPartitions -ne 0 -or
        $disk.Size -ne 256MB) {
        throw 'The attached disk is not the newly created empty image.'
    }
    $partition = $disk | Initialize-Disk -PartitionStyle MBR -PassThru |
        New-Partition -UseMaximumSize -AssignDriveLetter
    if ($partition.DiskNumber -ne $number -or $partition.DriveLetter -notmatch '^[A-Z]$') {
        throw 'The new partition is not bound to the test image.'
    }
    $volume = $partition | Format-Volume -FileSystem $fileSystem -Confirm:$false
    if ($volume.FileSystem -ne $fileSystem -or $volume.DriveLetter -ne $partition.DriveLetter) {
        throw 'The scratch volume did not report the requested filesystem.'
    }
    $folder = Join-Path ('{0}:\' -f $volume.DriveLetter) 'Metroliza scratch'
    return (New-Item -ItemType Directory -Path $folder).FullName
}

$root = (New-Item -ItemType Directory -Path (
    Join-Path $env:RUNNER_TEMP ('metroliza-cache-' + [guid]::NewGuid().ToString('N'))
)).FullName
$share = $null
$cleanupErrors = @()
try {
    $env:METROLIZA_CACHE_FS_FAT = New-ScratchVolume $root 'FAT32'
    $env:METROLIZA_CACHE_FS_EXFAT = New-ScratchVolume $root 'exFAT'
    $env:METROLIZA_CACHE_FS_NTFS = (New-Item -ItemType Directory -Path (Join-Path $root 'ntfs')).FullName
    $shareRoot = (New-Item -ItemType Directory -Path (Join-Path $root 'smb')).FullName
    $shareName = 'mzcache-' + [guid]::NewGuid().ToString('N')
    $shareOptions = @{
        Name = $shareName; Path = $shareRoot; Temporary = $true
        CachingMode = 'None'; FullAccess = $caller.Name; EncryptData = $true
    }
    $share = New-SmbShare @shareOptions
    $access = @(Get-SmbShareAccess -Name $shareName)
    if ($share.Path -ne $shareRoot -or $access.Count -ne 1 -or
        $access[0].AccountName -ne $caller.Name -or $access[0].AccessControlType -ne 'Allow' -or
        $access[0].AccessRight -ne 'Full') {
        throw 'The disposable share did not report the expected one-account access.'
    }
    $env:METROLIZA_CACHE_FS_SMB = "\\localhost\$shareName"
    Write-Host 'SMB fixture uses the local Windows Server SMB service through loopback.'

    $selector = 'tests/test_industrial_cache_publication.py::test_native_windows_cache_filesystem'
    $lines = @(& python -m pytest -v -s $selector)
    $testExit = $LASTEXITCODE
    $lines | Write-Host
    if ($testExit -ne 0) { throw 'The filesystem publication probe failed.' }
    $receipts = @($lines | ForEach-Object {
        if ($_ -match '(\{.*"probe": "cache_storage_qualification".*\})') {
            $Matches[1] | ConvertFrom-Json
        }
    })
    $sections = @($receipts | ForEach-Object requested)
    if ($receipts.Count -ne 4 -or (Compare-Object @('FAT', 'EXFAT', 'NTFS', 'SMB') $sections)) {
        throw 'Expected a native receipt for each of the four storage classes.'
    }
    foreach ($receipt in $receipts) {
        $save = $receipt.unused_destination.status
        $saveStage = $receipt.unused_destination.stage
        $commit = $receipt.commit_point_collision
        $collision = $commit.status
        $flushRefused = $save -eq 'refused_safely' -and $saveStage -eq 'flush'
        if (-not ($receipt.source_preserved -and $receipt.existing_entries_preserved -and
                  $receipt.staging_removed -and $receipt.scratch_removed)) {
            throw "Missing preservation or cleanup receipt for $($receipt.requested)."
        }
        foreach ($entry in @('main', '-wal', '-shm', '-journal')) {
            $check = $receipt.precommit_collisions.$entry
            if ($check -ne 'rejected_existing' -and -not ($flushRefused -and $check -eq 'not_reached')) {
                throw "Missing precommit result for $($receipt.requested) $entry."
            }
        }
        if ($save -eq 'published') {
            if ($collision -ne 'rejected_existing') { throw 'Missing native no-replace collision proof.' }
        } elseif ($save -ne 'refused_safely' -or $receipt.requested -eq 'NTFS' -or
                  $receipt.unused_destination.reason -notin @('unsupported_operation', 'permission_denied')) {
            throw "Invalid publication result for $($receipt.requested)."
        } elseif ($flushRefused) {
            if ($collision -ne 'rejected_existing' -and (
                $collision -ne 'not_reached' -or $commit.stage -ne 'flush' -or
                $commit.reason -ne $receipt.unused_destination.reason -or
                $commit.class -ne $receipt.unused_destination.class -or
                $commit.errno -ne $receipt.unused_destination.errno -or
                $commit.winerror -ne $receipt.unused_destination.winerror)) {
                throw 'Missing matching flush refusal for the commit-point probe.'
            }
        } elseif ($saveStage -ne 'rename' -or ($collision -ne 'rejected_existing' -and (
            $collision -ne 'refused_safely' -or $commit.stage -ne 'rename' -or
            $commit.reason -ne $receipt.unused_destination.reason))) {
            throw 'Missing native commit-point collision or rename refusal proof.'
        }
        Write-Host "Storage $($receipt.requested) save=$save collision=$collision"
    }
} catch {
    Write-Host "Cache filesystem trial failed before cleanup. $($_.Exception.Message)"
    throw
} finally {
    if ($null -ne $share) {
        try {
            $share | Remove-SmbShare -Confirm:$false -Force
        } catch {
            $cleanupErrors += 'share'
        }
    }
    foreach ($fileSystem in @('FAT32', 'exFAT')) {
        $imagePath = Join-Path $root "$fileSystem.vhdx"
        if (Test-Path -LiteralPath $imagePath -PathType Leaf) {
            try {
                if ((Get-DiskImage -ImagePath $imagePath).Attached) {
                    Dismount-DiskImage -ImagePath $imagePath
                }
            } catch {
                $cleanupErrors += $fileSystem
            }
        }
    }
    if ($cleanupErrors.Count) { throw "Disposable storage cleanup failed for $($cleanupErrors -join ', ')." }
    Remove-Item -LiteralPath $root -Recurse -Force
}
