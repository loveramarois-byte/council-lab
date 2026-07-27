Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PackageRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StartCommand = Join-Path $PackageRoot "Start Council.cmd"
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopDir "Council.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $env:ComSpec
$Shortcut.Arguments = '/c ""{0}""' -f $StartCommand
$Shortcut.WorkingDirectory = $PackageRoot
$Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
$Shortcut.Description = "Start Council Lab"
$Shortcut.Save()
Write-Host "Council shortcut created on the Desktop." -ForegroundColor Green
