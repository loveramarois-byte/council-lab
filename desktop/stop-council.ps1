Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LocalRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME "AppData\Local" }
$LogDir = if ($env:COUNCIL_LOG_DIR) { $env:COUNCIL_LOG_DIR } else { Join-Path $LocalRoot "Council\logs" }
$PidFile = Join-Path $LogDir "council-pids.json"
$TokenFile = Join-Path $LogDir "mobile-access.token"

try {
    if (-not (Test-Path $PidFile)) {
        Remove-Item -Force $TokenFile -ErrorAction SilentlyContinue
        Write-Host "No Council process record was found."
        exit 0
    }

    $Saved = Get-Content -Raw -Path $PidFile | ConvertFrom-Json
    foreach ($Name in @("backend", "frontend")) {
        $Property = $Saved.PSObject.Properties[$Name]
        if ($null -eq $Property) { continue }
        $PidValue = [int]$Property.Value
        $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $PidValue" -ErrorAction SilentlyContinue
        if ($null -eq $Process) { continue }
        $CommandLine = [string]$Process.CommandLine
        if ($CommandLine.IndexOf($ProjectDir, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            Stop-Process -Id $PidValue -Force -ErrorAction SilentlyContinue
        }
    }
    Set-Content -Encoding UTF8 -Path $PidFile -Value "{}"
    Remove-Item -Force $TokenFile -ErrorAction SilentlyContinue
    Write-Host "Council local services have stopped." -ForegroundColor Green
}
catch {
    Write-Host "Council could not stop cleanly: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
