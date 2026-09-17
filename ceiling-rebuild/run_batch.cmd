@echo off
REM Rebuild per-room ceilings across every env in INPUT_DIR (set inside ceiling_rebuild_run.py).
REM Double-click this, or run it from any shell. Bypasses PowerShell's execution policy for
REM this one call only - it changes nothing on the machine.
REM
REM The ORIGIN Ceiling Bridge graph must be running in Dynamo in Periodic mode first.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0send_command.ps1" -Script "%~dp0ceiling_rebuild_run.py" -TimeoutSec 900
echo.
pause
