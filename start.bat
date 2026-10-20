@echo off
setlocal
cd /d "%~dp0"
set "MW_PYTHON="
if exist "%~dp0.venv\Scripts\python.exe" set "MW_PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined MW_PYTHON set "MW_PYTHON=python"
"%MW_PYTHON%" -X utf8 app.py
if errorlevel 1 (
  echo.
  echo Startup failed. See README.md or README.zh-CN.md for setup.
  pause
)
