@echo off
rem One-click wrapper for run_capture.ps1 (execution policy bypass).
rem Usage: run_capture.cmd probe
rem        run_capture.cmd sample
rem        run_capture.cmd full
setlocal
set MODE=%1
if "%MODE%"=="" set MODE=sample
shift
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_capture.ps1" -Mode %MODE% %*
endlocal
