@echo off
setlocal
cd /d "%~dp0"
echo Creates a private Python environment in this tool directory.
py -3.12 -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Setup complete. Run start.bat.
pause
exit /b 0
:fail
echo Setup failed. Python 3.12 and internet access to package sources are required.
pause
exit /b 1
