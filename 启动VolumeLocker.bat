@echo off
REM ============================================================
REM  VolumeLocker launcher  --  always use the project .venv
REM  Do NOT launch volume_locker.py by double-click or by the
REM  bare "python" command: on this machine those pick a Python
REM  that does not have pycaw installed.
REM ============================================================
setlocal
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\pythonw.exe"
set "SCRIPT=%~dp0volume_locker.py"

if not exist "%VENV_PY%" (
    echo [ERROR] venv not found: %VENV_PY%
    echo         Run setup_env.bat first to create it.
    pause
    exit /b 1
)
if not exist "%SCRIPT%" (
    echo [ERROR] script not found: %SCRIPT%
    pause
    exit /b 1
)

set PYTHONUTF8=1
start "" "%VENV_PY%" "%SCRIPT%"
exit /b 0
