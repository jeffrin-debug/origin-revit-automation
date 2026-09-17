@echo off
REM ============================================================================
REM  ORIGIN ENV PIPELINE - double-click this.
REM
REM  Before running, Revit 2026 must be open with the bridge graph running:
REM      Manage > Dynamo > open  dynamo\ORIGIN Pipeline Bridge.dyn
REM      set the run mode (bottom-left) to Periodic, 1000 ms, and leave it open.
REM
REM  -ExecutionPolicy Bypass applies to this one call only; it changes nothing
REM  on the machine.
REM ============================================================================

title ORIGIN Env Pipeline
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pipeline.ps1"
