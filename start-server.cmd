@echo off
setlocal
cd /d "%~dp0"
set "PY="
py --version >nul 2>nul
if not errorlevel 1 set "PY=py"
if not defined PY (
  python --version >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY set "CODEX_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not defined PY if exist "%CODEX_PY%" set "PY=%CODEX_PY%"
if not defined PY (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% server.py
if errorlevel 1 pause
