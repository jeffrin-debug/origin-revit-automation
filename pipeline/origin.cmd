@echo off
rem origin.cmd - so you can type `origin sep` instead of `.\origin.ps1 sep`.
rem Add C:\Users\Origoncad\origin_pipeline to PATH and it works from any folder.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0origin.ps1" %*
