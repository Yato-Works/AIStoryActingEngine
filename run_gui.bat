@echo off
setlocal
set "PATH=C:\msys64\mingw64\bin;%PATH%"
cd /d "%~dp0desktop\build"
start "" "aiae_desktop.exe"
