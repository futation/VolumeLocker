#!/usr/bin/env python3
"""
capture_gui.py — 把界面截成 PNG,用于"看不见窗口时也能验证外观"。

为什么需要它:改配色/排版/自绘控件时,唯一的验收方式本来是"人打开看一眼"。
这个脚本让自动化也能看 —— 它启动真实窗口、等它画完、按 `ImageGrab` 抓客户区,
然后退出。改一版 → 截一组 → 看图再改,不用反复麻烦用户。

用法::

    .venv\\Scripts\\python.exe tools\\capture_gui.py --outdir D:\\tmp\\shots
    ... --demo           # 往电平表灌一组假数据,好看到图形部分的实际样子
    ... --only dark      # 只截深色

输出:outdir 下一组 PNG(浅色/深色 × 面板收起/高级设置/设置、锁定模式)。
配置被重定向到临时目录,所以不会碰用户的 config.json,也不需要单实例锁。
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.coinit_flags = 0
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PIL import ImageGrab

# 不管中途出什么事,到这个秒数就强制退出 —— 这个工具绝不能挂住
# (踩过:Tk 回调里抛异常会中断 after 链,主循环却还活着,于是进程一直空转)
HARD_TIMEOUT_S = 60
errors = []


def grab_window(root, pad=8, titlebar=44):
    """抓 Tk 窗口(含标题栏周围一点边距)。坐标都是屏幕物理像素。"""
    root.update_idletasks()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    scale = root.winfo_fpixels("1i") / 96.0
    margin = int(pad * scale)
    tb = int(titlebar * scale)
    left = max(0, x - margin)
    top = max(0, y - tb)
    right = x + w + margin
    bottom = y + h + margin
    return ImageGrab.grab(bbox=(left, top, right, bottom))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=os.path.join(tempfile.gettempdir(), "vl_shots"))
    ap.add_argument("--demo", action="store_true",
                    help="往电平表/读数灌一组假数据(限幅中)")
    ap.add_argument("--demo-ceiling", type=float, default=-6.0)
    ap.add_argument("--demo-out", type=float, default=-6.0)
    ap.add_argument("--demo-sig", type=float, default=-1.0)
    ap.add_argument("--prefix", default="", help="输出文件名前缀")
    ap.add_argument("--only", choices=["light", "dark"], default=None)
    ap.add_argument("--width", type=int, default=600)
    ap.add_argument("--height", type=int, default=620)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="vl_shot_")
    import volume_locker as vl
    vl.APP_DIR = tmp_dir
    vl.CONFIG_FILE = os.path.join(tmp_dir, "config.json")

    app = vl.VolumeLockerApp()
    theme = getattr(app, "theme", None)
    root = app.root
    root.geometry(f"{args.width}x{args.height}")

    def demo():
        if not args.demo:
            return
        # 直接推到控件上,模拟"限幅中"的一帧真实读数。
        # 注意:必须**接管** _update_limiter_meter,否则 1 秒后的定时刷新会把假数据
        # 覆盖成 "--"(演示数据只在两次刷新之间活着)。
        ceiling = args.demo_ceiling
        out_db = args.demo_out
        sig_db = args.demo_sig
        att = max(0.0, sig_db - out_db)
        holding = att > 0.5

        def fake_meter(limiter_on):
            # 按模式显隐的收尾动作。用 getattr 而不是直接点名 —— 这个私有方法
            # 改过一次名,直接调它的旧名字会让 it 抛 AttributeError,
            # 而异常发生在 Tk 回调里 → 后续 step() 不再被调度 → **整个工具挂死**
            # (实测踩过:进程一直空转、一张图都出不来、输出还被管道缓冲掉)。
            sync = getattr(app, "_sync_mode_visibility", None) \
                or getattr(app, "_sync_peak_bar", None)
            if sync:
                sync()
            meter = getattr(app, "level_meter", None)
            if meter is not None:
                # force=True:不然会被合帧节流挡掉,截出来的是一张空表
                meter.set_level(out_db, ceiling, sig_db, holding, force=True)
            for name, text, key in (
                    ("signal_value", f"{sig_db:.1f} dBFS", "text"),
                    ("output_value", f"{out_db:.1f} dBFS",
                     "danger" if holding else "ok"),
                    ("atten_value", f"-{att:.1f} dB" if holding else "0.0 dB",
                     "danger" if holding else "ok")):
                w = getattr(app, name, None)
                if w is not None:
                    w.config(text=text, foreground=app.theme.color(key))
            pill = getattr(app, "status_pill", None)
            if pill is not None:
                pill.set("限幅中" if holding else "限幅运行中",
                         "danger" if holding else "ok")

        app._update_limiter_meter = fake_meter
        fake_meter(True)

    states = []

    def add(name, appearance=None, advanced=False, settings=False, lock=False):
        states.append((name, appearance, advanced, settings, lock))

    modes = ["light", "dark"] if args.only is None else [args.only]
    for mode in modes:
        add(f"{mode}-collapsed", mode)
        add(f"{mode}-advanced", mode, advanced=True)
        add(f"{mode}-settings", mode, settings=True)
        add(f"{mode}-lock", mode, lock=True)
        # 锁定模式下"设置"面板必须照样能展开(踩过:闸门写错导致它是空的)
        add(f"{mode}-lock-settings", mode, settings=True, lock=True)

    shots = []

    def do_shot(name):
        for _ in range(3):
            root.update_idletasks()
            root.update()
            time.sleep(0.05)
        img = grab_window(root)
        path = outdir / f"{args.prefix}{name}.png"
        img.save(path)
        shots.append((name, path))
        print(f"  已保存 {path}  ({img.width}x{img.height})")

    def step(i):
        if i >= len(states):
            root.after(80, app._full_exit)
            return
        name, appearance, advanced, settings, lock = states[i]
        try:
            if theme is not None and appearance:
                theme.set_appearance(appearance)
                apply_theme = getattr(app, "_apply_theme_to_widgets", None)
                if apply_theme:
                    apply_theme()
            if lock:
                app.mode_var.set(vl.MODE_LOCK)
            else:
                app.mode_var.set(vl.MODE_LIMIT)
            app._on_mode_change()
            if advanced:
                app._toggle_advanced()
            if settings:
                app._toggle_settings()
            demo()
        except Exception:
            # **绝不能把异常漏出去**:Tk 回调里抛异常会中断 after 链,
            # 而主循环还活着 → 工具永远不退出(实测就是这么挂死的)
            print(f"✗ 准备状态 {name} 失败:")
            traceback.print_exc()
            root.after(0, app._full_exit)
            return

        def after():
            try:
                do_shot(name)
            except Exception:
                print(f"✗ 截图 {name} 失败:")
                traceback.print_exc()
                errors.append(name)
            try:
                # 还原状态,给下一张留个干净起点
                if advanced and getattr(app, "_advanced_open", False):
                    app._toggle_advanced()
                if settings and getattr(app, "_settings_open", False):
                    app._toggle_settings()
            except Exception:
                traceback.print_exc()
            step(i + 1)

        root.after(650, after)

    # 看门狗:无论中途出什么事,到点就退出 —— 保证这个工具永远不会挂住
    def watchdog():
        print(f"✗ 超时({HARD_TIMEOUT_S}s),强制退出")
        errors.append("hard timeout")
        try:
            app._full_exit()
        except Exception:
            os._exit(1)

    root.after(900, lambda: step(0))
    root.after(HARD_TIMEOUT_S * 1000, watchdog)
    app.run()

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print()
    print(f"共 {len(shots)} 张,目录: {outdir}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
