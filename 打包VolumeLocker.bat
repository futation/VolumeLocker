@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  打包 VolumeLocker 为单文件 exe
echo ============================================================
echo.
echo 必须用 .venv 的解释器:只有它同时装了 pycaw 与 PyInstaller。
echo (全局 Python311 里有 PyInstaller,但没有 ttkbootstrap,打出来会缺界面库)
echo.
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 找不到 .venv\Scripts\python.exe
    echo         先运行 setup_env.bat 建环境。
    pause
    exit /b 1
)
if not exist "icon.ico" (
    echo [提示] 缺少 icon.ico,先从原图生成……
    ".venv\Scripts\python.exe" tools\make_icon.py || (echo [错误] 图标生成失败 & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean VolumeLocker.spec
if errorlevel 1 (
    echo.
    echo [失败] 打包出错,请看上面的信息。
    pause
    exit /b 1
)
echo.
echo ============================================================
echo  完成: dist\VolumeLocker.exe
echo ============================================================
pause
