param([switch]$NoBrowser)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$PackageRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendExe = Join-Path $PackageRoot "backend\council-backend\council-backend.exe"
$NodeExe = Join-Path $PackageRoot "runtime\node.exe"
$WebDir = Join-Path $PackageRoot "web"
$ServerScript = Join-Path $WebDir "server.js"
$WebBuildIdPath = Join-Path $WebDir ".next-release\BUILD_ID"
$WebBuildId = ""
$LocalRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME "AppData\Local" }
$LogDir = if ($env:COUNCIL_LOG_DIR) { $env:COUNCIL_LOG_DIR } else { Join-Path $LocalRoot "Council\logs" }
$PidFile = Join-Path $LogDir "council-bundled-pids.json"
$TokenFile = Join-Path $LogDir "mobile-access.token"
$DesktopTokenFile = Join-Path $LogDir "desktop-access.token"
$InternalTokenFile = Join-Path $LogDir "backend-access.token"
$BackendProcess = $null
$FrontendProcess = $null

$env:COUNCIL_PACKAGED = "1"
$env:COUNCIL_INSTALL_ROOT = $PackageRoot
$env:COUNCIL_VERSION = (Get-Content -Raw (Join-Path $PackageRoot "VERSION")).Trim()
$Hasher = [System.Security.Cryptography.SHA256]::Create()
try {
    $RuntimeSeed = "$PackageRoot$([char]0)$($env:COUNCIL_VERSION)"
    $RootHash = [BitConverter]::ToString($Hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($RuntimeSeed))).Replace("-", "").ToLowerInvariant()
}
finally { $Hasher.Dispose() }
$env:COUNCIL_RUNTIME_ID = "windows:$($RootHash.Substring(0, 24))"

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
        return $Response.status -eq "ok" -and $Response.service -eq "council-mobile-access" -and $Response.runtime_id -eq $env:COUNCIL_RUNTIME_ID -and $Response.web_build_id -eq $WebBuildId -and $Response.internal_api_id -eq $InternalApiId
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

function Test-CouncilProcessOwnership([int]$ProcessId, [string]$Service) {
    $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $Process) { return $false }
    $Executable = [string]$Process.ExecutablePath
    $CommandLine = [string]$Process.CommandLine
    if ($Service -eq "council-lab") {
        if ($Executable -match '\\backend\\council-backend\\council-backend\.exe$') {
            $Root = Split-Path (Split-Path (Split-Path $Executable -Parent) -Parent) -Parent
            return (Test-Path (Join-Path $Root "VERSION"))
        }
        return $CommandLine -match '\\backend\\\.venv\\Scripts\\python\.exe' -and $CommandLine -match 'uvicorn' -and $CommandLine -match 'app\.main:app'
    }
    if ($Service -eq "council-mobile-access") {
        if ($Executable -match '\\runtime\\node\.exe$') {
            $Root = Split-Path (Split-Path $Executable -Parent) -Parent
            return (Test-Path (Join-Path $Root "VERSION")) -and (Test-Path (Join-Path $Root "web\server.js"))
        }
        return $CommandLine -match '\\frontend\\node_modules\\next\\dist\\bin\\next' -and $CommandLine -match 'start'
    }
    return $false
}

function Stop-ExistingCouncilService([int]$Port, [string]$Uri, [string]$Service) {
    try {
        $ProcessIdsBefore = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
        $Health = Invoke-RestMethod -Uri $Uri -TimeoutSec 2
        if ($Health.service -ne $Service) { return $false }
        $ProcessIdsAfter = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
        foreach ($ProcessId in $ProcessIdsAfter) {
            if ($ProcessId -gt 1 -and $ProcessIdsBefore -contains $ProcessId -and (Test-CouncilProcessOwnership $ProcessId $Service)) {
                Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
            if (-not (Test-Port $Port)) { return $true }
            Start-Sleep -Milliseconds 100
        }
    }
    catch { return $false }
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
    foreach ($Required in @($BackendExe, $NodeExe, $ServerScript, $WebBuildIdPath)) {
        if (-not (Test-Path $Required)) { throw "The download is incomplete. Download and extract Council again." }
    }
    $WebBuildId = (Get-Content -Raw $WebBuildIdPath).Trim()
    $env:COUNCIL_WEB_BUILD_ID = $WebBuildId
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $Started = [ordered]@{ package_root = $PackageRoot }
    $InternalToken = if (Test-Path $InternalTokenFile) { (Get-Content -Raw $InternalTokenFile).Trim() } else { "" }
    if ($InternalToken.Length -lt 32) {
        $InternalToken = New-PairingToken
        Set-Content -Encoding ASCII -Path $InternalTokenFile -Value $InternalToken
    }
    $InternalApiId = Get-TokenIdentifier $InternalToken
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
        if ((Test-Port 8001) -and -not (Stop-ExistingCouncilService 8001 "http://127.0.0.1:8001/api/health" "council-lab")) {
            throw "Port 8001 is used by another program. Close it, then start Council again."
        }
        $PreviousInternalToken = [Environment]::GetEnvironmentVariable("COUNCIL_INTERNAL_API_TOKEN", "Process")
        $env:COUNCIL_INTERNAL_API_TOKEN = $InternalToken
        try {
            $BackendProcess = Start-Process -FilePath $BackendExe -WorkingDirectory $PackageRoot -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $LogDir "backend.stdout.log") `
                -RedirectStandardError (Join-Path $LogDir "backend.stderr.log")
        }
        finally {
            if ($null -eq $PreviousInternalToken) { Remove-Item Env:COUNCIL_INTERNAL_API_TOKEN -ErrorAction SilentlyContinue }
            else { $env:COUNCIL_INTERNAL_API_TOKEN = $PreviousInternalToken }
        }
        $Started.backend = $BackendProcess.Id
        if (-not (Wait-Until { Test-Backend })) { throw "The backend did not start. See $LogDir\backend.stderr.log" }
    }

    $RemoteToken = ""
    $DesktopToken = ""
    if ((Test-Frontend) -and (Test-Path $TokenFile) -and (Test-Path $DesktopTokenFile)) {
        $RemoteToken = (Get-Content -Raw $TokenFile).Trim()
        $DesktopToken = (Get-Content -Raw $DesktopTokenFile).Trim()
    }

    if (-not (Test-Frontend)) {
        if ((Test-Port 3000) -and -not (Stop-ExistingCouncilService 3000 "http://127.0.0.1:3000/mobile-access/health" "council-mobile-access")) {
            throw "Port 3000 is used by another program. Close it, then start Council again."
        }
        $PreviousHost = $env:HOSTNAME
        $PreviousPort = $env:PORT
        $PreviousNodeEnv = $env:NODE_ENV
        $PreviousRemoteToken = $env:COUNCIL_REMOTE_TOKEN
        $PreviousDesktopToken = $env:COUNCIL_DESKTOP_TOKEN
        $PreviousInternalToken = [Environment]::GetEnvironmentVariable("COUNCIL_INTERNAL_API_TOKEN", "Process")
        $RemoteToken = New-PairingToken
        $DesktopToken = New-PairingToken
        Set-Content -Encoding ASCII -Path $TokenFile -Value $RemoteToken
        Set-Content -Encoding ASCII -Path $DesktopTokenFile -Value $DesktopToken
        try {
            $env:HOSTNAME = "0.0.0.0"
            $env:PORT = "3000"
            $env:NODE_ENV = "production"
            $env:COUNCIL_REMOTE_TOKEN = $RemoteToken
            $env:COUNCIL_DESKTOP_TOKEN = $DesktopToken
            $env:COUNCIL_INTERNAL_API_TOKEN = $InternalToken
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
                @{ Name = "COUNCIL_REMOTE_TOKEN"; Value = $PreviousRemoteToken },
                @{ Name = "COUNCIL_DESKTOP_TOKEN"; Value = $PreviousDesktopToken },
                @{ Name = "COUNCIL_INTERNAL_API_TOKEN"; Value = $PreviousInternalToken }
            )) {
                if ($null -eq $Entry.Value) { Remove-Item "Env:$($Entry.Name)" -ErrorAction SilentlyContinue }
                else { Set-Item "Env:$($Entry.Name)" $Entry.Value }
            }
        }
        if (-not (Wait-Until { Test-Frontend })) { throw "The web interface did not start. See $LogDir\frontend.stderr.log" }
    }

    if ($Started.Count -gt 1) { $Started | ConvertTo-Json | Set-Content -Encoding UTF8 -Path $PidFile }
    if (-not $NoBrowser) {
        $LaunchUrl = if ($DesktopToken) { "http://localhost:3000/pair#desktop:$DesktopToken" } else { "http://localhost:3000" }
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
