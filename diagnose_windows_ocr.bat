@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0diagnose_windows_ocr.ps1" %*
exit /b %ERRORLEVEL%
