param([switch]$NoBrowser)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendPython = Join-Path $ProjectDir "backend\.venv\Scripts\python.exe"
$NextScript = Join-Path $ProjectDir "frontend\node_modules\next\dist\bin\next"
$FrontendDistDir = ".next-runtime"
$BuildIdPath = Join-Path $ProjectDir "frontend\$FrontendDistDir\BUILD_ID"
$FrontendBuildId = ""
$LocalRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME "AppData\Local" }
$LogDir = if ($env:COUNCIL_LOG_DIR) { $env:COUNCIL_LOG_DIR } else { Join-Path $LocalRoot "Council\logs" }
$PidFile = Join-Path $LogDir "council-pids.json"
$TokenFile = Join-Path $LogDir "mobile-access.token"
$DesktopTokenFile = Join-Path $LogDir "desktop-access.token"
$InternalTokenFile = Join-Path $LogDir "backend-access.token"
$BackendProcess = $null
$FrontendProcess = $null

function Test-Backend {
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/health" -TimeoutSec 2
        return $Health.status -eq "ok" -and $Health.service -eq "council-lab" -and $Health.runtime_id -eq $env:COUNCIL_RUNTIME_ID -and $Health.internal_api_id -eq $InternalApiId
    }
    catch { return $false }
}

function Test-Frontend {
    try {
        $Response = Invoke-RestMethod -Uri "http://127.0.0.1:3000/mobile-access/health" -TimeoutSec 2
        return $Response.status -eq "ok" -and $Response.service -eq "council-mobile-access" -and $Response.runtime_id -eq $env:COUNCIL_RUNTIME_ID -and $Response.web_build_id -eq $FrontendBuildId -and $Response.internal_api_id -eq $InternalApiId
    }
    catch { return $false }
}

function New-PairingToken {
    $Bytes = New-Object byte[] 24
    $Generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Generator.GetBytes($Bytes) }
    finally { $Generator.Dispose() }
    return [BitConverter]::ToString($Bytes).Replace("-", "").ToLowerInvariant()
}

function Get-TokenIdentifier([string]$Token) {
    $TokenHasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Digest = $TokenHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Token))
        return ([BitConverter]::ToString($Digest).Replace("-", "").ToLowerInvariant()).Substring(0, 16)
    }
    finally { $TokenHasher.Dispose() }
}

function Test-Port([int]$Port) {
    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $Result = $Client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $Result.AsyncWaitHandle.WaitOne(500)) { return $false }
        $Client.EndConnect($Result)
        return $true
    }
    catch { return $false }
    finally { $Client.Dispose() }
}

function Stop-ProjectListener([int]$Port, [string]$ProjectPath) {
    $ReplaceableCouncil = $false
    try {
        $HealthUri = if ($Port -eq 8001) { "http://127.0.0.1:8001/api/health" } else { "http://127.0.0.1:3000/mobile-access/health" }
        $ExpectedService = if ($Port -eq 8001) { "council-lab" } else { "council-mobile-access" }
        $Health = Invoke-RestMethod -Uri $HealthUri -TimeoutSec 2
        $ReplaceableCouncil = $Health.service -eq $ExpectedService -and $Health.internal_api_id -eq $InternalApiId
    }
    catch { $ReplaceableCouncil = $false }
    $ProcessIds = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($ProcessId in $ProcessIds) {
        if ($ProcessId -le 1) { continue }
        $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
        if ($null -eq $Process) { continue }
        $CommandLine = [string]$Process.CommandLine
        if ($ReplaceableCouncil -or $CommandLine.IndexOf($ProjectPath, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        if (-not (Test-Port $Port)) { return $true }
        Start-Sleep -Milliseconds 100
    }
    return -not (Test-Port $Port)
}

function Wait-Until([scriptblock]$Probe) {
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
        if (& $Probe) { return $true }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

try {
    if (-not (Test-Path $BackendPython) -or -not (Test-Path $NextScript) -or -not (Test-Path $BuildIdPath)) {
        throw "Council is not installed yet. Double-click Install Council.cmd first."
    }
    $FrontendBuildId = (Get-Content -Raw $BuildIdPath).Trim()
    $env:COUNCIL_RUNTIME_ID = "source:$FrontendBuildId"
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $Started = [ordered]@{ project_dir = $ProjectDir }
    $InternalToken = if (Test-Path $InternalTokenFile) { (Get-Content -Raw $InternalTokenFile).Trim() } else { "" }
    if ($InternalToken.Length -lt 32) {
        $InternalToken = New-PairingToken
        Set-Content -Encoding ASCII -Path $InternalTokenFile -Value $InternalToken
    }
    $InternalApiId = Get-TokenIdentifier $InternalToken

    if (-not (Test-Backend)) {
        if ((Test-Port 8001) -and -not (Stop-ProjectListener 8001 $BackendPython)) { throw "Port 8001 is used by another program. Close it, then start Council again." }
        $PreviousInternalToken = [Environment]::GetEnvironmentVariable("COUNCIL_INTERNAL_API_TOKEN", "Process")
        $env:COUNCIL_INTERNAL_API_TOKEN = $InternalToken
        try {
            $BackendProcess = Start-Process -FilePath $BackendPython `
                -ArgumentList @("-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8001") `
                -WorkingDirectory $ProjectDir -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $LogDir "backend.stdout.log") `
                -RedirectStandardError (Join-Path $LogDir "backend.stderr.log")
        }
        finally {
            if ($null -eq $PreviousInternalToken) { Remove-Item Env:COUNCIL_INTERNAL_API_TOKEN -ErrorAction SilentlyContinue }
            else { $env:COUNCIL_INTERNAL_API_TOKEN = $PreviousInternalToken }
        }
        $Started.backend = $BackendProcess.Id
        if (-not (Wait-Until { Test-Backend })) {
            throw "The backend did not start. See $LogDir\backend.stderr.log"
        }
    }

    $RemoteToken = ""
    $DesktopToken = ""
    if ((Test-Frontend) -and (Test-Path $TokenFile) -and (Test-Path $DesktopTokenFile)) {
        $RemoteToken = (Get-Content -Raw $TokenFile).Trim()
        $DesktopToken = (Get-Content -Raw $DesktopTokenFile).Trim()
    }

    if (-not (Test-Frontend)) {
        if ((Test-Port 3000) -and -not (Stop-ProjectListener 3000 (Join-Path $ProjectDir "frontend"))) { throw "Port 3000 is used by another program. Close it, then start Council again." }
        $RemoteToken = New-PairingToken
        $DesktopToken = New-PairingToken
        Set-Content -Encoding ASCII -Path $TokenFile -Value $RemoteToken
        Set-Content -Encoding ASCII -Path $DesktopTokenFile -Value $DesktopToken
        $PreviousRemoteToken = $env:COUNCIL_REMOTE_TOKEN
        $PreviousDesktopToken = $env:COUNCIL_DESKTOP_TOKEN
        $PreviousInternalToken = [Environment]::GetEnvironmentVariable("COUNCIL_INTERNAL_API_TOKEN", "Process")
        $PreviousNextDistDir = $env:COUNCIL_NEXT_DIST_DIR
        $PreviousWebBuildId = $env:COUNCIL_WEB_BUILD_ID
        $env:COUNCIL_REMOTE_TOKEN = $RemoteToken
        $env:COUNCIL_DESKTOP_TOKEN = $DesktopToken
        $env:COUNCIL_INTERNAL_API_TOKEN = $InternalToken
        $env:COUNCIL_NEXT_DIST_DIR = $FrontendDistDir
        $env:COUNCIL_WEB_BUILD_ID = $FrontendBuildId
        try {
            $Node = (Get-Command "node.exe" -ErrorAction Stop).Source
            $FrontendProcess = Start-Process -FilePath $Node `
                -ArgumentList @("`"$NextScript`"", "start", "-H", "0.0.0.0", "-p", "3000") `
                -WorkingDirectory (Join-Path $ProjectDir "frontend") -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $LogDir "frontend.stdout.log") `
                -RedirectStandardError (Join-Path $LogDir "frontend.stderr.log")
            $Started.frontend = $FrontendProcess.Id
        }
        finally {
            if ($null -eq $PreviousRemoteToken) { Remove-Item Env:COUNCIL_REMOTE_TOKEN -ErrorAction SilentlyContinue }
            else { $env:COUNCIL_REMOTE_TOKEN = $PreviousRemoteToken }
            if ($null -eq $PreviousDesktopToken) { Remove-Item Env:COUNCIL_DESKTOP_TOKEN -ErrorAction SilentlyContinue }
            else { $env:COUNCIL_DESKTOP_TOKEN = $PreviousDesktopToken }
            if ($null -eq $PreviousInternalToken) { Remove-Item Env:COUNCIL_INTERNAL_API_TOKEN -ErrorAction SilentlyContinue }
            else { $env:COUNCIL_INTERNAL_API_TOKEN = $PreviousInternalToken }
            if ($null -eq $PreviousNextDistDir) { Remove-Item Env:COUNCIL_NEXT_DIST_DIR -ErrorAction SilentlyContinue }
            else { $env:COUNCIL_NEXT_DIST_DIR = $PreviousNextDistDir }
            if ($null -eq $PreviousWebBuildId) { Remove-Item Env:COUNCIL_WEB_BUILD_ID -ErrorAction SilentlyContinue }
            else { $env:COUNCIL_WEB_BUILD_ID = $PreviousWebBuildId }
        }
        if (-not (Wait-Until { Test-Frontend })) {
            throw "The web interface did not start. See $LogDir\frontend.stderr.log"
        }
    }

    if ($Started.Count -gt 1) {
        $Started | ConvertTo-Json | Set-Content -Encoding UTF8 -Path $PidFile
    }
    if (-not $NoBrowser) {
        $LaunchUrl = if ($DesktopToken) { "http://localhost:3000/pair#desktop:$DesktopToken" } else { "http://localhost:3000" }
        Start-Process $LaunchUrl
    }
    Write-Host "Council is running at http://localhost:3000" -ForegroundColor Green
}
catch {
    foreach ($Process in @($FrontendProcess, $BackendProcess)) {
        if ($null -ne $Process -and -not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "Council could not start: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
