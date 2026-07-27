param([switch]$NoBrowser)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendPython = Join-Path $ProjectDir "backend\.venv\Scripts\python.exe"
$NextScript = Join-Path $ProjectDir "frontend\node_modules\next\dist\bin\next"
$BuildId = Join-Path $ProjectDir "frontend\.next\BUILD_ID"
$LocalRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME "AppData\Local" }
$LogDir = if ($env:COUNCIL_LOG_DIR) { $env:COUNCIL_LOG_DIR } else { Join-Path $LocalRoot "Council\logs" }
$PidFile = Join-Path $LogDir "council-pids.json"
$BackendProcess = $null
$FrontendProcess = $null

function Test-Backend {
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/health" -TimeoutSec 2
        return $Health.status -eq "ok" -and $Health.service -eq "council-lab"
    }
    catch { return $false }
}

function Test-Frontend {
    try {
        $Response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:3000/" -TimeoutSec 2
        return $Response.StatusCode -eq 200 -and $Response.Content -match "Council"
    }
    catch { return $false }
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
    if (-not (Test-Path $BackendPython) -or -not (Test-Path $NextScript) -or -not (Test-Path $BuildId)) {
        throw "Council is not installed yet. Double-click Install Council.cmd first."
    }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $Started = [ordered]@{ project_dir = $ProjectDir }

    if (-not (Test-Backend)) {
        if (Test-Port 8001) { throw "Port 8001 is used by another program. Close it, then start Council again." }
        $BackendProcess = Start-Process -FilePath $BackendPython `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8001") `
            -WorkingDirectory $ProjectDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $LogDir "backend.stdout.log") `
            -RedirectStandardError (Join-Path $LogDir "backend.stderr.log")
        $Started.backend = $BackendProcess.Id
        if (-not (Wait-Until { Test-Backend })) {
            throw "The backend did not start. See $LogDir\backend.stderr.log"
        }
    }

    if (-not (Test-Frontend)) {
        if (Test-Port 3000) { throw "Port 3000 is used by another program. Close it, then start Council again." }
        $PreviousApiUrl = $env:NEXT_PUBLIC_API_URL
        $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8001"
        try {
            $Node = (Get-Command "node.exe" -ErrorAction Stop).Source
            $FrontendProcess = Start-Process -FilePath $Node `
                -ArgumentList @("`"$NextScript`"", "start", "-H", "127.0.0.1", "-p", "3000") `
                -WorkingDirectory (Join-Path $ProjectDir "frontend") -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $LogDir "frontend.stdout.log") `
                -RedirectStandardError (Join-Path $LogDir "frontend.stderr.log")
            $Started.frontend = $FrontendProcess.Id
        }
        finally {
            if ($null -eq $PreviousApiUrl) { Remove-Item Env:NEXT_PUBLIC_API_URL -ErrorAction SilentlyContinue }
            else { $env:NEXT_PUBLIC_API_URL = $PreviousApiUrl }
        }
        if (-not (Wait-Until { Test-Frontend })) {
            throw "The web interface did not start. See $LogDir\frontend.stderr.log"
        }
    }

    if ($Started.Count -gt 1) {
        $Started | ConvertTo-Json | Set-Content -Encoding UTF8 -Path $PidFile
    }
    if (-not $NoBrowser) {
        Start-Process "http://localhost:3000"
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
