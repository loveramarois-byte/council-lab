param([switch]$NoBrowser)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$PackageRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendExe = Join-Path $PackageRoot "backend\council-backend\council-backend.exe"
$NodeExe = Join-Path $PackageRoot "runtime\node.exe"
$WebDir = Join-Path $PackageRoot "web"
$ServerScript = Join-Path $WebDir "server.js"
$LocalRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME "AppData\Local" }
$LogDir = if ($env:COUNCIL_LOG_DIR) { $env:COUNCIL_LOG_DIR } else { Join-Path $LocalRoot "Council\logs" }
$PidFile = Join-Path $LogDir "council-bundled-pids.json"
$TokenFile = Join-Path $LogDir "mobile-access.token"
$BackendProcess = $null
$FrontendProcess = $null

$env:COUNCIL_PACKAGED = "1"
$env:COUNCIL_INSTALL_ROOT = $PackageRoot
$env:COUNCIL_VERSION = (Get-Content -Raw (Join-Path $PackageRoot "VERSION")).Trim()

function Test-Backend {
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/health" -TimeoutSec 2
        return $Health.status -eq "ok" -and $Health.service -eq "council-lab"
    }
    catch { return $false }
}

function Test-Frontend {
    try {
        $Response = Invoke-RestMethod -Uri "http://127.0.0.1:3000/mobile-access/health" -TimeoutSec 2
        return $Response.status -eq "ok" -and $Response.service -eq "council-mobile-access"
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

function Wait-Until([scriptblock]$Probe) {
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
        if (& $Probe) { return $true }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

try {
    foreach ($Required in @($BackendExe, $NodeExe, $ServerScript)) {
        if (-not (Test-Path $Required)) { throw "The download is incomplete. Download and extract Council again." }
    }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $Started = [ordered]@{ package_root = $PackageRoot }
    if (Test-Path $PidFile) {
        try {
            $Existing = Get-Content -Raw -Path $PidFile | ConvertFrom-Json
            if ([string]$Existing.package_root -eq $PackageRoot) {
                foreach ($Name in @("backend", "frontend")) {
                    $Property = $Existing.PSObject.Properties[$Name]
                    if ($null -ne $Property) { $Started[$Name] = [int]$Property.Value }
                }
            }
        }
        catch {
            # A stale or partial PID file is replaced after startup succeeds.
        }
    }

    if (-not (Test-Backend)) {
        if (Test-Port 8001) { throw "Port 8001 is used by another program. Close it, then start Council again." }
        $BackendProcess = Start-Process -FilePath $BackendExe -WorkingDirectory $PackageRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $LogDir "backend.stdout.log") `
            -RedirectStandardError (Join-Path $LogDir "backend.stderr.log")
        $Started.backend = $BackendProcess.Id
        if (-not (Wait-Until { Test-Backend })) { throw "The backend did not start. See $LogDir\backend.stderr.log" }
    }

    $RemoteToken = ""
    if ((Test-Frontend) -and (Test-Path $TokenFile)) {
        $RemoteToken = (Get-Content -Raw $TokenFile).Trim()
    }

    if (-not (Test-Frontend)) {
        if (Test-Port 3000) { throw "Port 3000 is used by another program. Close it, then start Council again." }
        $PreviousHost = $env:HOSTNAME
        $PreviousPort = $env:PORT
        $PreviousNodeEnv = $env:NODE_ENV
        $PreviousRemoteToken = $env:COUNCIL_REMOTE_TOKEN
        $RemoteToken = New-PairingToken
        Set-Content -Encoding ASCII -Path $TokenFile -Value $RemoteToken
        try {
            $env:HOSTNAME = "0.0.0.0"
            $env:PORT = "3000"
            $env:NODE_ENV = "production"
            $env:COUNCIL_REMOTE_TOKEN = $RemoteToken
            $FrontendProcess = Start-Process -FilePath $NodeExe -ArgumentList @("`"$ServerScript`"") `
                -WorkingDirectory $WebDir -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $LogDir "frontend.stdout.log") `
                -RedirectStandardError (Join-Path $LogDir "frontend.stderr.log")
            $Started.frontend = $FrontendProcess.Id
        }
        finally {
            foreach ($Entry in @(
                @{ Name = "HOSTNAME"; Value = $PreviousHost },
                @{ Name = "PORT"; Value = $PreviousPort },
                @{ Name = "NODE_ENV"; Value = $PreviousNodeEnv },
                @{ Name = "COUNCIL_REMOTE_TOKEN"; Value = $PreviousRemoteToken }
            )) {
                if ($null -eq $Entry.Value) { Remove-Item "Env:$($Entry.Name)" -ErrorAction SilentlyContinue }
                else { Set-Item "Env:$($Entry.Name)" $Entry.Value }
            }
        }
        if (-not (Wait-Until { Test-Frontend })) { throw "The web interface did not start. See $LogDir\frontend.stderr.log" }
    }

    if ($Started.Count -gt 1) { $Started | ConvertTo-Json | Set-Content -Encoding UTF8 -Path $PidFile }
    if (-not $NoBrowser) {
        $LaunchUrl = if ($RemoteToken) { "http://localhost:3000/pair#desktop:$RemoteToken" } else { "http://localhost:3000" }
        Start-Process $LaunchUrl
    }
    Write-Host "Council is running at http://localhost:3000" -ForegroundColor Green
}
catch {
    foreach ($Process in @($FrontendProcess, $BackendProcess)) {
        if ($null -ne $Process -and -not $Process.HasExited) { Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "Council could not start: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
