@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto setup
".venv\Scripts\python.exe" -c "import faster_whisper, pyaudiowpatch" >nul 2>&1
if errorlevel 1 goto setup
start "" ".venv\Scripts\pythonw.exe" "app.py"
exit /b
:setup
echo Setting up Meeting Notes. This needs internet access the first time.
py -3.13 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
start "" ".venv\Scripts\pythonw.exe" "app.py"
exit /b
:failed
echo Setup could not finish. See README.txt for instructions.
pause
