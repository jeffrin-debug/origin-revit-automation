@echo off
REM Rebuild per-room ceilings on the model CURRENTLY OPEN in Revit.
REM Nothing is saved - the change lands in the open session and Ctrl+Z undoes all of it.
REM
REM The ORIGIN Ceiling Bridge graph must be running in Dynamo in Periodic mode first.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0send_command.ps1" -Script "%~dp0ceiling_rebuild_current_doc.py" -TimeoutSec 300
echo.
pause
