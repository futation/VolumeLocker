@echo off
REM ============================================================
REM  Rebuild the project virtual environment (.venv)
REM  Base interpreter is pinned to Python 3.11 (the machine has
REM  several Pythons; only 3.11 is a stable target here).
REM ============================================================
setlocal
cd /d "%~dp0"

set "BASE_PY=%LocalAppData%\Programs\Python\Python311\python.exe"

if not exist "%BASE_PY%" (
    echo [!] Pinned base interpreter not found, falling back to: py -3.11
    set "BASE_CMD=py -3.11"
) else (
    set "BASE_CMD="%BASE_PY%""
)

echo [1/3] Removing old .venv ...
if exist ".venv" rmdir /s /q ".venv"

echo [2/3] Creating .venv ...
%BASE_CMD% -m venv ".venv"
if errorlevel 1 (
    echo [ERROR] venv creation failed.
    pause
    exit /b 1
)

echo [3/3] Installing dependencies ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] dependency installation failed.
    pause
    exit /b 1
)

echo.
echo Done. Verify with:
echo   .venv\Scripts\python.exe -c "import pycaw, comtypes, pystray, PIL; print('OK')"
echo Launch with:
echo   启动VolumeLocker.bat
pause
