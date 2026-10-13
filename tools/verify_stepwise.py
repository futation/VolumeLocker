#!/usr/bin/env python3
"""
verify_stepwise.py — 离线验证"步步为营"释放机制(不着硬件)

场景:阶段1 响 -> 阶段2 静(释放爬升)-> 阶段3 又响
检验:阶段3 一开始,回升是否被立刻中断并重新压制。
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台/管道默认按 GBK 编码 stdout,打印 ✓✗ 会 UnicodeEncodeError。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from loudness_limiter import LoudnessConfig, LoudnessLimiter

DT = 0.008
BASE, CEIL = -10.30, -20.0


def sig(t):
    if t < 1.5:
        return math.pow(10, -6.0 / 20)      # 阶段1:响
    if t < 5.5:
        return math.pow(10, -40.0 / 20)     # 阶段2:静 -> 释放爬升
    return math.pow(10, -6.0 / 20)          # 阶段3:又响


def main():
    cfg = LoudnessConfig(ceiling_dbfs=CEIL, hold_seconds=2.0, release_db_per_s=1.5)
    lim = LoudnessLimiter(cfg, base_volume_db=BASE)
    vol = BASE
    t = 0.0
    rows = []
    while t < 8.0:
        vol = lim.update(sig(t), vol, t)
        rows.append((t, vol, lim.attenuation_db, lim._inhibit))
        t += DT

    print("阶段: 0~1.5s 响 | 1.5~5.5s 静(释放) | 5.5s 起又响")
    print()
    print(f"{'时刻':>16} {'写入音量':>10} {'衰减dB':>9} {'inhibit':>8}")
    print("-" * 46)
    for mark, label in ((0.5, "阶段1 响"), (2.0, "阶段2 +0.5s"),
                        (3.5, "阶段2 +2s"), (5.0, "阶段2 +3.5s"),
                        (5.49, "阶段3 前一刻"), (5.51, "阶段3 刚开始"),
                        (5.53, "阶段3 +20ms"), (5.60, "阶段3 +100ms"),
                        (6.0, "阶段3 +0.5s"), (7.0, "阶段3 +1.5s")):
        r = min(rows, key=lambda x: abs(x[0] - mark))
        print(f"{label:>16} {r[1]:>10.3f} {r[2]:>9.2f} {str(r[3]):>8}")

    pre = [r for r in rows if 4.5 <= r[0] < 5.5]
    post = [r for r in rows if 5.5 <= r[0] < 6.5]
    vp = max(r[1] for r in pre)
    vmin_post = min(r[1] for r in post)
    print()
    print(f"阶段2 末已释放到 : {vp:.3f} dB")
    print(f"阶段3 内最低音量 : {vmin_post:.3f} dB")
    print(f"=> 掉头幅度      : {vp - vmin_post:.3f} dB")

    # 掉头发生在"信号重新变响"之后的第几拍
    t_sig = next((r[0] for r in rows if r[0] > 5.49 and r[3] > -10.0), None)
    t_fall = None
    if t_sig is not None:
        t_fall = next((r[0] for r in rows if r[0] >= t_sig and r[1] < vp - 0.3), None)
    if t_sig is not None and t_fall is not None:
        print(f"信号变响于 {t_sig:.3f}s,音量掉头于 {t_fall:.3f}s"
              f" => 响应 {1000 * (t_fall - t_sig):.0f} ms"
              f" ({(t_fall - t_sig) / DT:.0f} 拍)")
    print()
    ok = vp - vmin_post > 1.0
    print("结论: " + ("✓ 回升被立刻中断并重新压制(步步为营生效)"
                     if ok else "✗ 未观察到掉头"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


