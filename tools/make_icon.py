#!/usr/bin/env python3
"""从一张 PNG 生成 Windows 用的**多尺寸** .ico。

为什么需要这个脚本
====================================================================
`dist/VolumeControl.ico` 当时**其实是一张 PNG**(只改了扩展名,2048×2048)。
两个后果:
  * `root.iconbitmap()` 只吃真 ICO —— 窗口图标实际上没生效(代码里有
    try/except 兜着,所以不报错,只是静默没图标);
  * PyInstaller 的 `icon=` 也要真 ICO(它虽然能用 Pillow 转,但不保证
    生成多尺寸)。
而且**单尺寸的大图在托盘里会糊**:Windows 托盘是 16×16,任务栏 32×32,
Alt-Tab / 资源管理器大图标是 256×256 —— 必须把各档都写进同一个 ico。

用法
====================================================================
    .\\.venv\\Scripts\\python.exe tools\\make_icon.py

输入:`assets/VolumeControl.png`(原图,只读,绝不覆盖)
输出:`icon.ico`(项目根;窗口图标与托盘图标都用它 —— 这是"两处图标一致"
     唯一的保证,`volume_locker.ICO_PATH` 也指向它)
"""

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "VolumeControl.png")
OUT = os.path.join(ROOT, "icon.ico")

# Windows 各处的实际需求:托盘 16、列表 24/32、开始菜单 48、大图标 64/128、
# 资源管理器超大图标与 Alt-Tab 预览 256。
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> int:
    if not os.path.exists(SRC):
        print(f"✗ 找不到源图: {SRC}")
        return 1

    src = Image.open(SRC).convert("RGBA")
    print(f"源图    : {SRC}")
    print(f"          {src.size[0]}×{src.size[1]} {src.mode}")

    # Pillow 会从这张源图逐档缩放并写进同一个 ico(小尺寸用 BMP、256 用 PNG,
    # 两者 Windows 都认)。
    src.save(OUT, format="ICO", sizes=SIZES)

    # 立刻读回来验证 —— 不验证就等于没做
    back = Image.open(OUT)
    got = sorted(back.ico.sizes())
    want = sorted(SIZES)
    print(f"输出    : {OUT}  ({os.path.getsize(OUT) / 1024:.1f} KB)")
    print(f"内含尺寸: {got}")
    if got != want:
        print(f"✗ 尺寸不全,期望 {want}")
        return 1
    print("✓ 多尺寸 ico 生成完成(窗口图标与托盘图标共用它)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
