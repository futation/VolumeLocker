#!/usr/bin/env python3
"""
compare_variants.py — 客观对比"改动前 / 改动后"的关键指标

场景都基于用户的实际工况:基础音量 50%(-10.30 dB),上限 -20 dBFS。

指标:
  swing_pk   音乐段音量峰峰摆动(dB)   —— 主指标,越小越不"一炸一炸"
  overshoot  输出超上限最大值(dB)      —— 安全性
  recov_s    安静后完全释放用时(s)      —— 恢复速度
  resp_ms    信号变响 -> 音量掉头(ms)  —— 反应灵敏
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台/管道默认按 GBK 编码 stdout,中文/符号可能 UnicodeEncodeError。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from loudness_limiter import LoudnessConfig, LoudnessLimiter

DT = 0.008
BASE, CEIL = -10.30, -20.0


def db(p):
    return 20.0 * math.log10(p) if p > 1e-12 else -120.0


def sig_music(t):
    return math.pow(10, (-6.0 + 4.0 * math.sin(2 * math.pi * 1.0 * t)) / 20)


def sig_pulses(t):
    return math.pow(10, (-4.0 if (t % 0.30) < 0.04 else -45.0) / 20)


def sig_burst(t):
    """0~2s 响,之后长期安静 —— 用来量恢复时间"""
    return math.pow(10, (-4.0 if t < 2.0 else -45.0) / 20)


def sig_step(t):
    """0~2s 安静,2~6s 响 —— 用来量反应时间"""
    return math.pow(10, (-45.0 if t < 2.0 else -4.0) / 20)


def run(sig, seconds, **kw):
    cfg = LoudnessConfig(ceiling_dbfs=CEIL, hold_seconds=2.0, **kw)
    lim = LoudnessLimiter(cfg, base_volume_db=BASE)
    vol = BASE
    t = 0.0
    rows = []
    while t < seconds:
        p = sig(t)
        vol = lim.update(p, vol, t)
        rows.append((t, vol, lim.attenuation_db, db(p) + vol))
        t += DT
    return rows


def swing(rows, a, b):
    v = [r[2] for r in rows if a <= r[0] < b]
    return (max(v) - min(v)) if v else 0.0


def overshoot(rows):
    o = [r[3] - CEIL for r in rows if r[3] > CEIL]
    return max(o) if o else 0.0


def recovery(rows, q=2.0):
    att0 = next((r[2] for r in rows if r[0] >= q), 0.0)
    if att0 < 0.1:
        return 0.0
    for r in rows:
        if r[0] >= q and r[2] <= 0.01:
            return r[0] - q
    return float("nan")


def response_ms(rows, t_rise=2.0):
    """信号变响之后,音量掉头(开始下降)延迟"""
    v_before = next((r[1] for r in rows if r[0] >= t_rise - DT), None)
    if v_before is None:
        return float("nan")
    for r in rows:
        if r[0] >= t_rise and r[1] < v_before - 0.3:
            return (r[0] - t_rise) * 1000
    return float("nan")


VARIANTS = [
    ("改动前(释放1.5/检测0.3峰值跟随/迟滞失效)",
     dict(release_db_per_s=1.5, detector_seconds=0.30,
          release_threshold_db=1.5, release_window_seconds=0.05)),
    ("改动后(释放1.5/滑动均值0.3/闸门+峰值保持)",
     dict(release_db_per_s=1.5, detector_seconds=0.30,
          release_threshold_db=1.5, release_window_seconds=0.25)),
    ("改动后 + 释放1.0",
     dict(release_db_per_s=1.0, detector_seconds=0.30,
          release_threshold_db=1.5, release_window_seconds=0.25)),
    ("改动后 + 检测0.6",
     dict(release_db_per_s=1.5, detector_seconds=0.60,
          release_threshold_db=1.5, release_window_seconds=0.25)),
]


def main():
    print("=" * 82)
    print("对比:基础音量 50%(-10.30 dB),上限 -20 dBFS")
    print("=" * 82)
    print()
    print(f"  {'配置':<40}{'摆动dB':>8}{'超限dB':>8}{'恢复s':>8}{'反应ms':>8}")
    print("  " + "-" * 72)
    for label, kw in VARIANTS:
        m = run(sig_music, 14.0, **kw)
        pu = run(sig_pulses, 14.0, **kw)
        b = run(sig_burst, 45.0, **kw)
        s = run(sig_step, 8.0, **kw)
        sw = max(swing(m, 7.0, 14.0), swing(pu, 7.0, 14.0))
        ov = max(overshoot(m), overshoot(pu))
        print(f"  {label:<40}{sw:>8.2f}{ov:>8.2f}"
              f"{recovery(b):>8.1f}{response_ms(s):>8.0f}")
    print()
    print("摆动 = 音乐段与脉冲段的音量峰峰摆动(取较大者),越小越不'一炸一炸'")
    print("反应ms = 素材由静转响后,音量开始下降的延迟")


if __name__ == "__main__":
    main()

