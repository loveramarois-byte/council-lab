param(
    [Parameter(Mandatory = $true)][string]$NewRoot,
    [Parameter(Mandatory = $true)][string]$TargetRoot,
    [Parameter(Mandatory = $true)][string]$Stopper,
    [Parameter(Mandatory = $true)][string]$LogFile,
    [Parameter(Mandatory = $true)][string]$ResultFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Result([string]$Status, [string]$Message) {
    @{ status = $Status; message = $Message } | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 -Path $ResultFile
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogFile), (Split-Path $ResultFile) | Out-Null
Start-Transcript -Path $LogFile -Append | Out-Null
$RollbackFailed = $false

try {
    $NewRoot = (Resolve-Path $NewRoot).Path
    $TargetRoot = (Resolve-Path $TargetRoot).Path
    if ($TargetRoot -eq [System.IO.Path]::GetPathRoot($TargetRoot)) { throw "Refusing to update a drive root." }
    $Separator = [System.IO.Path]::DirectorySeparatorChar
    $TargetPrefix = $TargetRoot.TrimEnd($Separator) + $Separator
    $NewPrefix = $NewRoot.TrimEnd($Separator) + $Separator
    if ($NewRoot.Equals($TargetRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $NewRoot.StartsWith($TargetPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        $TargetRoot.StartsWith($NewPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The staged package and installed directory must not overlap."
    }
    foreach ($Required in @(
        (Join-Path $NewRoot "runtime\start-council.ps1"),
        (Join-Path $NewRoot "backend\council-backend\council-backend.exe"),
        (Join-Path $NewRoot "VERSION"),
        $Stopper
    )) {
        if (-not (Test-Path $Required -PathType Leaf)) { throw "The update package is incomplete: $Required" }
    }

    Start-Sleep -Seconds 1
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Stopper
    Start-Sleep -Seconds 1

    $BackupRoot = Join-Path (Split-Path $TargetRoot) (".Council.backup.{0}" -f $PID)
    if (Test-Path $BackupRoot) { Remove-Item -Recurse -Force $BackupRoot }
    & robocopy.exe $TargetRoot $BackupRoot /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP
    $BackupExit = $LASTEXITCODE
    if ($BackupExit -ge 8) { throw "Could not create the update backup (robocopy code $BackupExit)." }

    try {
        & robocopy.exe $NewRoot $TargetRoot /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP
        $CopyExit = $LASTEXITCODE
        if ($CopyExit -ge 8) { throw "File replacement failed with robocopy code $CopyExit." }
    }
    catch {
        & robocopy.exe $BackupRoot $TargetRoot /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP
        $RestoreExit = $LASTEXITCODE
        if ($RestoreExit -ge 8) {
            $RollbackFailed = $true
            throw "Update and rollback both failed (rollback robocopy code $RestoreExit). Backup retained at $BackupRoot."
        }
        throw "$($_.Exception.Message) The previous version was restored."
    }
    finally {
        if (-not $RollbackFailed -and (Test-Path $BackupRoot)) { Remove-Item -Recurse -Force $BackupRoot }
    }

    Write-Result "success" "Council updated successfully and is restarting."
    if ($env:COUNCIL_UPDATE_NO_RESTART -ne "1") {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $TargetRoot "runtime\start-council.ps1") -NoBrowser
    }
}
catch {
    Write-Result "error" $_.Exception.Message
    $Fallback = Join-Path $TargetRoot "runtime\start-council.ps1"
    if (-not $RollbackFailed -and (Test-Path $Fallback) -and $env:COUNCIL_UPDATE_NO_RESTART -ne "1") {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Fallback -NoBrowser
    }
    exit 1
}
finally {
    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
}
