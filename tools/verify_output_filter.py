#!/usr/bin/env python3
"""
verify_output_filter.py — 验证"下发音量滤波"在生产代码路径里生效

用 volume_locker.DeviceLimiter(产品代码)离线跑:只覆盖 _read_peak / _write,
其余逻辑(含滤波、节流、迟滞、保持、释放)全部是生产实现。

量的是**真正下发到设备的音量序列**:
  swing        峰峰摆动(dB)     —— 越小越稳
  step_max     单拍最大变化(dB)  —— "跳变"的直接度量
  reversals/s  方向反转频率
  resp_ms      信号由静转响后音量开始下降的延迟 —— 不能被滤波拖慢
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

import comtypes
import volume_locker as vl
from loudness_limiter import LoudnessConfig, LoudnessLimiter

DT = 0.008
BASE, CEIL = -10.30, -20.0


def sig_music(t):
    return math.pow(10, (-6.0 + 4.0 * math.sin(2 * math.pi * 1.0 * t)) / 20)


def sig_step(t):
    return math.pow(10, (-45.0 if t < 2.0 else -4.0) / 20)


def sig_burst(t):
    """0~2s 大声,之后长期安静 —— 用来量"爆炸之后声音回不回得来"。"""
    return math.pow(10, (-4.0 if t < 2.0 else -45.0) / 20)


class OfflineLimiter(vl.DeviceLimiter):
    """把硬件访问换成内存模型,其余逻辑完全走产品实现。"""

    def __init__(self, filter_s):
        super().__init__(comtypes, vl.IAudioMeterInformationFull,
                         LoudnessLimiter,
                         LoudnessConfig(ceiling_dbfs=CEIL, hold_seconds=2.0,
                                        release_db_per_s=1.5))
        self.mode = vl.MODE_LIMIT
        self.base_volume_db = BASE
        self.volume_filter_seconds = filter_s
        self._fake_peak = 0.0
        self.sent = []
        # 让 ready 为真(只检查这两个字段非 None)
        self._meter = object()
        self._volume = object()
        self._lim = LoudnessLimiter(LoudnessConfig(ceiling_dbfs=CEIL,
                                                   hold_seconds=2.0,
                                                   release_db_per_s=1.5),
                                    base_volume_db=BASE)

    def _read_peak(self):
        return self._fake_peak

    def _write(self, target_db, now, force=False):
        # 保留产品的节流语义,只是不碰硬件;记录所有真正下发的值
        last = self._last_written
        if not force and last is not None:
            if abs(target_db - last) < self.MIN_WRITE_DELTA_DB:
                return
            if (now - self._last_write_at) < self.MIN_WRITE_INTERVAL:
                return
        self._last_written = target_db
        self._last_write_at = now
        self.sent.append(target_db)


def run(filter_s, sig, seconds):
    lim = OfflineLimiter(filter_s)
    t = 0.0
    trace = []
    while t < seconds:
        lim._fake_peak = sig(t)
        lim.step(t)
        trace.append((t, lim._sent_db))
        t += DT
    return trace


def metrics(rows, burn=7.0):
    vals = [r[1] for r in rows if r[0] >= burn and r[1] is not None]
    if len(vals) < 3:
        return {}
    steps = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
    dirn = rev = 0
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        if abs(d) < 1e-9:
            continue
        s = 1 if d > 0 else -1
        if dirn and s != dirn:
            rev += 1
        dirn = s
    return {"swing": max(vals) - min(vals),
            "step_max": max(steps),
            "rev_s": rev / (len(vals) * DT)}


def response_ms(rows, t_rise=2.0):
    v0 = next((r[1] for r in rows if r[0] >= t_rise - DT and r[1] is not None), None)
    if v0 is None:
        return float("nan")
    for r in rows:
        if r[0] >= t_rise and r[1] is not None and r[1] < v0 - 0.3:
            return (r[0] - t_rise) * 1000
    return float("nan")


def recovery_s(rows, t_quiet=2.0, base=None):
    """大声结束 -> 音量回到 base-0.5 dB 之内所用秒数。回不来返回 None。"""
    base = BASE if base is None else base
    return next((r[0] - t_quiet for r in rows
                 if r[0] >= t_quiet and r[1] is not None and r[1] >= base - 0.5), None)


def main():
    print("=" * 84)
    print("下发音量滤波验证(走 volume_locker.DeviceLimiter 的生产逻辑)")
    print("=" * 84)
    print()
    print(f"  {'滤波tau':>9} {'下发次数':>9} {'摆动dB':>9} {'单拍最大dB':>11} "
          f"{'反转/秒':>9} {'反应ms':>8} {'恢复s':>8}")
    print("  " + "-" * 74)
    results = {}
    for tau in (0.0, 0.05, 0.10, 0.20, 0.40):
        lim = OfflineLimiter(tau)
        t = 0.0
        rows = []
        while t < 20.0:
            lim._fake_peak = sig_music(t)
            lim.step(t)
            rows.append((t, lim._sent_db))
            t += DT
        m = metrics(rows)
        resp = response_ms(run(tau, sig_step, 8.0))
        rec = recovery_s(run(tau, sig_burst, 25.0))
        results[tau] = (m, resp, rec)
        print(f"  {tau:>9.2f} {len(lim.sent):>9} {m['swing']:>9.2f} "
              f"{m['step_max']:>11.4f} {m['rev_s']:>9.1f} {resp:>8.0f} "
              f"{('%.1f' % rec) if rec is not None else '回不来!':>8}")

    print()
    m0, r0, rec0 = results[0.0]
    m4, r4, rec4 = results[0.40]
    # 滤波的本职:磨平"写出去的值"。tau=0.40 那一档必须明显更平滑。
    good_swing = m4["swing"] < m0["swing"] * 0.65
    good_resp = r4 < 16.0
    # 🔴 回归断言:滤波**不得**影响释放速率。
    #    曾经把"滤波后的下发值"当反馈喂回控制律,等效释放速率被乘上
    #    dt/(tau+dt) —— tau=0.05(滑块默认值)时只剩 1/7,tau=0.10 时
    #    30 秒都回不到 0.5 dB 以内(用户报的"爆炸之后声音没回去")。
    recs = [res[2] for res in results.values()]
    missing = [t for t, res in results.items() if res[2] is None]
    good_recovery = not missing and max(recs) <= rec0 + 1.5
    print(f"  tau=0.00  摆动 {m0['swing']:.2f} dB  单拍最大 {m0['step_max']:.4f} dB"
          f"  恢复 {rec0:.1f} s")
    print(f"  tau=0.40  摆动 {m4['swing']:.2f} dB  单拍最大 {m4['step_max']:.4f} dB"
          f"  恢复 {rec4 if rec4 is None else round(rec4, 1)} s")
    print()
    print(f"  滤波显著降低摆动   : {'✓' if good_swing else '✗'}"
          f"  ({(1 - m4['swing'] / m0['swing']) * 100:.0f}% 降幅)")
    print(f"  压制反应未被拖慢   : {'✓' if good_resp else '✗'}  ({r4:.0f} ms)")
    print(f"  恢复速度与 tau 无关 : {'✓' if good_recovery else '✗'}"
          f"  (tau=0 时 {rec0:.1f} s,最慢 {max(recs) if recs else float('nan'):.1f} s"
          f"{'; 有 tau 回不来' if missing else ''})")
    ok = good_swing and good_resp and good_recovery
    print()
    print("结果: " + ("✓ 通过" if ok else "✗ 未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

