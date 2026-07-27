param(
    [switch]$CheckOnly,
    [switch]$NoLaunch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $ProjectDir "backend"
$FrontendDir = Join-Path $ProjectDir "frontend"
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"

function Stop-Install([string]$Message) {
    throw $Message
}

function Test-Python([string]$Command, [string[]]$Prefix) {
    try {
        & $Command @Prefix -c "import sys; raise SystemExit(sys.version_info < (3, 12))" 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

try {
    $PythonCommand = $null
    [string[]]$PythonPrefix = @()
    $PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $PyLauncher -and (Test-Python $PyLauncher.Source @("-3"))) {
        $PythonCommand = $PyLauncher.Source
        $PythonPrefix = @("-3")
    }
    else {
        $Python = Get-Command "python.exe" -ErrorAction SilentlyContinue
        if ($null -ne $Python -and (Test-Python $Python.Source @())) {
            $PythonCommand = $Python.Source
        }
    }
    if ($null -eq $PythonCommand) {
        Stop-Install "Python 3.12 or newer was not found. Install it from https://www.python.org/downloads/windows/ and enable 'Add python.exe to PATH'."
    }

    $Node = Get-Command "node.exe" -ErrorAction SilentlyContinue
    $Npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($null -eq $Node -or $null -eq $Npm) {
        Stop-Install "Node.js 22 or newer was not found. Install the LTS version from https://nodejs.org/."
    }
    $NodeMajor = [int]((& $Node.Source -p "process.versions.node.split('.')[0]").Trim())
    if ($NodeMajor -lt 22) {
        Stop-Install "Node.js is too old. Council requires Node.js 22 or newer."
    }

    Write-Host "Prerequisites OK: Python 3.12+ and Node.js $NodeMajor." -ForegroundColor Green
    if ($CheckOnly) {
        exit 0
    }

    Write-Host "1/3 Installing backend dependencies..."
    if (-not (Test-Path $VenvPython)) {
        & $PythonCommand @PythonPrefix -m venv (Join-Path $BackendDir ".venv")
        if ($LASTEXITCODE -ne 0) { Stop-Install "Could not create the Python virtual environment." }
    }
    if (-not (Test-Python $VenvPython @())) {
        Stop-Install "backend\.venv uses an older Python. Delete that folder and run Install Council.cmd again."
    }
    & $VenvPython -m pip install --disable-pip-version-check -q -r (Join-Path $BackendDir "requirements.lock")
    if ($LASTEXITCODE -ne 0) { Stop-Install "Backend dependency installation failed." }

    Write-Host "2/3 Installing and building the web interface..."
    Push-Location $FrontendDir
    $PreviousApiUrl = $env:NEXT_PUBLIC_API_URL
    try {
        & $Npm.Source ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { Stop-Install "Frontend dependency installation failed." }
        $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8001"
        & $Npm.Source run build
        if ($LASTEXITCODE -ne 0) { Stop-Install "Frontend build failed." }
    }
    finally {
        if ($null -eq $PreviousApiUrl) {
            Remove-Item Env:NEXT_PUBLIC_API_URL -ErrorAction SilentlyContinue
        }
        else {
            $env:NEXT_PUBLIC_API_URL = $PreviousApiUrl
        }
        Pop-Location
    }

    Write-Host "3/3 Creating the Desktop shortcut..."
    $DesktopDir = [Environment]::GetFolderPath("Desktop")
    $ShortcutPath = Join-Path $DesktopDir "Council.lnk"
    $StartCommand = Join-Path $ProjectDir "Start Council.cmd"
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $env:ComSpec
    $Shortcut.Arguments = '/c ""{0}""' -f $StartCommand
    $Shortcut.WorkingDirectory = $ProjectDir
    $Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
    $Shortcut.Description = "Start Council Lab"
    $Shortcut.Save()

    Write-Host "Council is installed. Use the Council shortcut on your Desktop." -ForegroundColor Green
    if (-not $NoLaunch) {
        Start-Process -FilePath $StartCommand
    }
}
catch {
    Write-Host ""
    Write-Host "Installation failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
