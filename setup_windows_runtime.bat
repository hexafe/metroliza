@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows_runtime.ps1" %*
exit /b %ERRORLEVEL%
