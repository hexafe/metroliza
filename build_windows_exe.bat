@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows_exe.ps1" %*
if errorlevel 1 (
    echo.
    echo Build failed. See the messages above.
    pause
    exit /b 1
)

echo.
echo Build finished.
