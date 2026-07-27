@echo off
setlocal
chcp 65001 >nul

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\start-council.ps1"
if errorlevel 1 (
  echo.
  echo Council could not start. Read the message above, then press any key to close.
  pause >nul
  exit /b 1
)

exit /b 0
