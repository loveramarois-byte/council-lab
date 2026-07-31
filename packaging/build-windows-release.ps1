param([string]$OutputRoot = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Version = (Get-Content -Raw (Join-Path $ProjectDir "VERSION")).Trim()
if (-not $OutputRoot) { $OutputRoot = Join-Path $ProjectDir "artifacts" }
$PackageName = "Council-v$Version-Windows"
$StageDir = Join-Path $OutputRoot $PackageName
$ZipPath = Join-Path $OutputRoot "$PackageName.zip"
$PyInstallerWork = Join-Path $ProjectDir "build\pyinstaller-windows"
$PyInstallerDist = Join-Path $ProjectDir "dist\pyinstaller-windows"
$ReleaseDistDir = ".next-release"

New-Item -ItemType Directory -Force -Path $OutputRoot, (Join-Path $ProjectDir "build"), (Join-Path $ProjectDir "dist") | Out-Null
foreach ($Target in @($StageDir, $ZipPath, $PyInstallerWork, $PyInstallerDist)) {
    if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
}

Push-Location (Join-Path $ProjectDir "frontend")
$PreviousStandalone = $env:COUNCIL_STANDALONE
$PreviousNextDistDir = $env:COUNCIL_NEXT_DIST_DIR
try {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    $env:COUNCIL_STANDALONE = "1"
    $env:COUNCIL_NEXT_DIST_DIR = $ReleaseDistDir
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Next.js build failed" }
}
finally {
    if ($null -eq $PreviousStandalone) { Remove-Item Env:COUNCIL_STANDALONE -ErrorAction SilentlyContinue } else { $env:COUNCIL_STANDALONE = $PreviousStandalone }
    if ($null -eq $PreviousNextDistDir) { Remove-Item Env:COUNCIL_NEXT_DIST_DIR -ErrorAction SilentlyContinue } else { $env:COUNCIL_NEXT_DIST_DIR = $PreviousNextDistDir }
    Pop-Location
}

& python -m PyInstaller --noconfirm --clean --onedir --name council-backend `
    --paths (Join-Path $ProjectDir "backend") `
    --collect-all keyring `
    --collect-all tiktoken `
    --hidden-import tiktoken_ext.openai_public `
    --hidden-import uvicorn.logging `
    --hidden-import uvicorn.loops.auto `
    --hidden-import uvicorn.protocols.http.auto `
    --hidden-import uvicorn.protocols.websockets.auto `
    --hidden-import uvicorn.lifespan.on `
    --workpath $PyInstallerWork `
    --specpath $PyInstallerWork `
    --distpath $PyInstallerDist `
    (Join-Path $ProjectDir "backend\desktop_entry.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

New-Item -ItemType Directory -Force -Path $StageDir, (Join-Path $StageDir "backend"), (Join-Path $StageDir "runtime") | Out-Null
Copy-Item -Recurse (Join-Path $PyInstallerDist "council-backend") (Join-Path $StageDir "backend\council-backend")
Copy-Item -Recurse (Join-Path $ProjectDir "frontend\$ReleaseDistDir\standalone") (Join-Path $StageDir "web")
New-Item -ItemType Directory -Force -Path (Join-Path $StageDir "web\$ReleaseDistDir") | Out-Null
Copy-Item -Recurse (Join-Path $ProjectDir "frontend\$ReleaseDistDir\static") (Join-Path $StageDir "web\$ReleaseDistDir\static")
Copy-Item -Recurse (Join-Path $ProjectDir "frontend\public") (Join-Path $StageDir "web\public")
$NodeExe = (Get-Command node.exe -ErrorAction Stop).Source
Copy-Item $NodeExe (Join-Path $StageDir "runtime\node.exe")
Copy-Item (Join-Path $ProjectDir "desktop\start-bundled.ps1") (Join-Path $StageDir "runtime\start-council.ps1")
Copy-Item (Join-Path $ProjectDir "desktop\stop-bundled.ps1") (Join-Path $StageDir "runtime\stop-council.ps1")
Copy-Item (Join-Path $ProjectDir "desktop\update-windows.ps1") (Join-Path $StageDir "runtime\update-council.ps1")
Copy-Item (Join-Path $ProjectDir "desktop\create-bundled-shortcut.ps1") (Join-Path $StageDir "runtime\create-shortcut.ps1")
Copy-Item (Join-Path $ProjectDir "desktop\Start Bundled.cmd") (Join-Path $StageDir "Start Council.cmd")
Copy-Item (Join-Path $ProjectDir "desktop\Stop Bundled.cmd") (Join-Path $StageDir "Stop Council.cmd")
Copy-Item (Join-Path $ProjectDir "desktop\Create Desktop Shortcut.cmd") (Join-Path $StageDir "Create Desktop Shortcut.cmd")
Copy-Item (Join-Path $ProjectDir "packaging\README-Windows.txt") (Join-Path $StageDir "README-FIRST.txt")
Copy-Item (Join-Path $ProjectDir "LICENSE"), (Join-Path $ProjectDir "NOTICE") $StageDir
Copy-Item (Join-Path $ProjectDir "VERSION") $StageDir

Compress-Archive -Path $StageDir -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Output $ZipPath
