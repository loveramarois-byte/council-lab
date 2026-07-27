@echo off
setlocal
chcp 65001 >nul

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\stop-council.ps1"
if errorlevel 1 (
  echo.
  echo Council could not stop cleanly. Press any key to close.
  pause >nul
  exit /b 1
)

timeout /t 2 /nobreak >nul
exit /b 0
