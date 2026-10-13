# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 单文件 VolumeLocker.exe。

用它的方式(必须用 .venv 的解释器,只有它同时装了 pycaw 与 PyInstaller):
    .\\.venv\\Scripts\\python.exe -m PyInstaller --noconfirm --clean VolumeLocker.spec
或者双击 打包VolumeLocker.bat。

为什么用 .spec 而不是一长串命令行
====================================================================
1. `datas` 必须把两样东西塞进包里:
   * `icon.ico` —— 窗口图标与**托盘图标是同一个文件**(用户明确要求一致,
     也是 ICO_PATH 的唯一来源);放在包根,对应 `_MEIPASS/icon.ico`。
   * **ttkbootstrap 的资源**(23 个非 .py 文件:assets/elements/*.png、
     manifest.json 等)。这些是 ttk 元素的图片,2.x 的主题系统运行期要用;
     少了它们界面会退化成另一副样子(而且是"静默"的,不报错)。
     PyInstaller 没有 ttkbootstrap 的官方 hook,必须自己 collect。
2. `hiddenimports`:pystray 的后端、comtypes 的动态模块 —— 都是运行期
   才 import 的,静态分析看不到。
3. 版本资源:让 exe 的"属性 → 详细信息"里显示版本,而不是一片空白。
   版本号**从源码里解析**,不手写第二份 —— 免得两处漂移。

注意:`pycaw`/`comtypes`/`psutil`/`pystray` 由 pyinstaller-hooks-contrib 覆盖
(hook-comtypes.client.py / hook-psutil.py / hook-pystray.py)。
"""

import os
import re

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = SPECPATH  # PyInstaller 注入:spec 所在目录

# ── 版本号从源码解析(单一来源) ──
with open(os.path.join(ROOT, "volume_locker.py"), encoding="utf-8") as f:
    _src = f.read()
_m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', _src, re.M)
APP_VERSION = _m.group(1) if _m else "0.0.0"
_quad = tuple(([int(x) for x in re.findall(r"\d+", APP_VERSION)] + [0, 0, 0, 0])[:4])
VERSION_STR = ".".join(str(x) for x in _quad)

VERSION_INFO = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_quad, prodvers=_quad, mask=0x3F, flags=0x0,
                      OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([
            StringTable("080404B0", [   # 0x0804 简体中文 + 0x04B0 Unicode
                StringStruct("CompanyName", "VolumeLocker"),
                StringStruct("FileDescription", "VolumeLocker 响度限幅器"),
                StringStruct("FileVersion", VERSION_STR),
                StringStruct("InternalName", "VolumeLocker"),
                StringStruct("OriginalFilename", "VolumeLocker.exe"),
                StringStruct("ProductName", "VolumeLocker"),
                StringStruct("ProductVersion", VERSION_STR),
            ]),
        ]),
        VarFileInfo([VarStruct("Translation", [2052, 1200])]),
    ],
)

# ── 要打进包里的数据 ──
datas = [("icon.ico", ".")]                 # -> _MEIPASS/icon.ico
datas += collect_data_files("ttkbootstrap")  # 元素图片 + manifest,缺了界面会静默降级

# ── 运行期才 import、静态分析看不到的 ──
hiddenimports = [
    "pystray._win32",      # 托盘后端(按平台动态选)
    "comtypes.stream",     # comtypes 常用子模块
    "comtypes.client",
    "PIL._tkinter_finder",  # Pillow 与 tkinter 的桥
    "six",                 # pycaw/comtypes 的间接依赖,偶尔被延迟导入
]

# ── 明确排除:肯定用不到的大件(本环境里大多没装,写上是为了换机器也稳) ──
excludes = [
    "numpy", "pandas", "matplotlib", "scipy", "sympy",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    "IPython", "jupyter", "notebook", "pytest", "sphinx",
]

a = Analysis(
    [os.path.join(ROOT, "volume_locker.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VolumeLocker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX 会显著提高杀软误报率,不用
    runtime_tmpdir=None,       # onefile 解包到 %TEMP%\_MEIxxxxx
    console=False,             # 托盘程序:不要黑框
    disable_windowed_traceback=False,  # 崩了要能看到弹窗,别静默退出
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "icon.ico"),
    version=VERSION_INFO,
)
