#!/usr/bin/env python3
"""
tune_control_filter.py — 量化"音量跳变"并测试对控制信号滤波的效果

用户观察:限幅是通过"拉低基础音量"实现的,所以音量本身在快速变化;
          释放速率一大,音量就频繁振动,听感"一炸一炸"。
          提议:对最终控制值做滤波,让它别跳变。

要量的东西(比"峰峰摆动"更贴近听感):
  reversals/s  音量改变方向的次数/秒  <- 这才是"频繁振动"的直接度量
  step_p95     单拍音量变化量的 95 分位(dB)
  swing        峰峰摆动(dB)
  lag_ms       滤波引入的额外反应延迟(信号转响到音量掉头)

测试的做法:在控制目标上加一个一阶低通(时间常数 tau),比较不同 tau。
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


def sig_step(t):
    return math.pow(10, (-45.0 if t < 2.0 else -4.0) / 20)


class FilteredLimiter:
    """在 LoudnessLimiter 的**控制输出**上加一阶低通。

    注意:滤波只作用于"最终下发值",不改变内部状态机 —— 这样迟滞、
    保持期、释放逻辑都保持原样,只是把输出磨平。
    压制方向(向下)不滤波,保证瞬态仍然能立刻压住;只对"回升"滤波。
    """

    def __init__(self, tau, **kw):
        self.lim = LoudnessLimiter(LoudnessConfig(ceiling_dbfs=CEIL,
                                                  hold_seconds=2.0, **kw),
                                   base_volume_db=BASE)
        self.tau = tau
        self.sent = BASE
        self.trace = []

    def step(self, sig, t):
        target = self.lim.update(sig, self.sent, t)
        if self.tau <= 0.0 or target <= self.sent:
            # 向下(压制)立刻生效,不过滤 —— 否则会漏瞬态
            self.sent = target
        else:
            a = DT / (self.tau + DT)
            self.sent += (target - self.sent) * a
            if self.sent > target:
                self.sent = target
        self.trace.append((t, self.sent, self.lim.attenuation_db))
        return self.sent


def run(sig, seconds, tau, **kw):
    fl = FilteredLimiter(tau, **kw)
    t = 0.0
    while t < seconds:
        fl.step(sig(t), t)
        t += DT
    return fl.trace


def metrics(rows, burn=7.0):
    seg = [r for r in rows if r[0] >= burn]
    if len(seg) < 3:
        return {}
    vals = [r[1] for r in seg]
    span = len(seg) * DT
    rev = 0
    dirn = 0
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        if abs(d) < 1e-9:
            continue
        s = 1 if d > 0 else -1
        if dirn and s != dirn:
            rev += 1
        dirn = s
    steps = sorted(abs(vals[i] - vals[i - 1]) for i in range(1, len(vals)))
    p95 = steps[int(len(steps) * 0.95)] if steps else 0.0
    return {
        "swing": max(vals) - min(vals),
        "rev_s": rev / span,
        "step_p95": p95,
        "step_max": max(steps) if steps else 0.0,
    }


def response_ms(rows, t_rise=2.0):
    v0 = next((r[1] for r in rows if r[0] >= t_rise - DT), None)
    if v0 is None:
        return float("nan")
    for r in rows:
        if r[0] >= t_rise and r[1] < v0 - 0.3:
            return (r[0] - t_rise) * 1000
    return float("nan")


def main():
    print("=" * 84)
    print("控制值滤波效果对比(基础音量 50% / 上限 -20 dBFS / 释放 1.5 dB/s)")
    print("=" * 84)
    print()
    print(f"  {'滤波tau':>9} {'摆动dB':>8} {'反转/秒':>9} {'单拍p95':>9} "
          f"{'单拍最大':>9} {'反应ms':>8}")
    print("  " + "-" * 58)
    for tau in (0.0, 0.05, 0.1, 0.2, 0.4, 0.8, 1.5):
        m = run(sig_music, 20.0, tau)
        s = run(sig_step, 8.0, tau)
        mm = metrics(m)
        print(f"  {tau:>9.2f} {mm['swing']:>8.2f} {mm['rev_s']:>9.1f} "
              f"{mm['step_p95']:>9.4f} {mm['step_max']:>9.4f} "
              f"{response_ms(s):>8.0f}")

    print()
    print("细碎响头场景:")
    print(f"  {'滤波tau':>9} {'摆动dB':>8} {'反转/秒':>9} {'单拍p95':>9}")
    print("  " + "-" * 40)
    for tau in (0.0, 0.1, 0.2, 0.4, 0.8, 1.5):
        m = run(sig_pulses, 20.0, tau)
        mm = metrics(m)
        print(f"  {tau:>9.2f} {mm['swing']:>8.2f} {mm['rev_s']:>9.1f} "
              f"{mm['step_p95']:>9.4f}")

    print()
    print("反转/秒 = 音量换方向的频率,是'频繁振动'的直接度量")
    print("反应ms  = 素材转响后音量开始下降的延迟(滤波会拖慢它)")


if __name__ == "__main__":
    main()

