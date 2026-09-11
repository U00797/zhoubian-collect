@echo off
setlocal
cd /d "%~dp0"
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% server.py
if errorlevel 1 pause
