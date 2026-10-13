#!/usr/bin/env python3
"""
test_loudness_limiter.py — 响度限幅控制律的自动化验证(纯离线,不碰 Windows 音频)

两条设计原则(都是被自己坑出来的)
--------------------------------------------------------------------
1. **闭环仿真**:真实链路是"限幅器算音量 -> 写下去 -> 下一拍读到新音量"。
   用理想音量当输入去测,结论会和真实运行不一致。
2. **期望值从控制律推导,不硬编码**:手算期望值我错了三次。凡是能从
   base / ceiling / signal 推出来的量,一律现场算。

核心不变量(任何场景都必须成立)
--------------------------------------------------------------------
INV-1  输出响度 <= 上限                 (限幅的本职)
INV-2  写出的音量 <= base_volume        (绝不放大)
INV-3  音量 >= base - max_attenuation   (不把音量打到 0 回不来)
INV-4  低响度素材不被干预               (不能退化成"音量锁定")
INV-5  长时间安静后必须回到 base_volume  (允许释放,不能永久压死)
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
BASE_VOLUME_DB = 0.0      # 0 dB = 满刻度。只有满刻度播放时才真正需要限幅
CEILING_DBFS = -6.0

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        failures.append(name)


def simulate(limiter, signal_fn, duration_s, base_volume_db=BASE_VOLUME_DB):
    """真实反馈环仿真。返回 [(t, signal_dbfs, written_volume, output_dbfs, atten)]"""
    limiter.set_base_volume_db(base_volume_db)
    trace = []
    volume_db = base_volume_db
    t = 0.0
    for _ in range(int(duration_s / DT)):
        sig = signal_fn(t)
        peak = math.pow(10.0, sig / 20.0) if sig > -119 else 0.0
        volume_db = limiter.update(peak, volume_db, t)
        trace.append((t, sig, volume_db, sig + volume_db,
                      max(0.0, base_volume_db - volume_db)))
        t += DT
    return trace


def check_invariants(label, trace, cfg, base=BASE_VOLUME_DB):
    """任何场景都必须成立的硬不变量。"""
    worst_out = max(x[3] for x in trace)
    max_vol = max(x[2] for x in trace)
    min_vol = min(x[2] for x in trace)
    check(f"{label}: INV-1 输出不超上限",
          worst_out <= cfg.ceiling_dbfs + 0.01,
          f"最差 {worst_out:.3f} > 上限 {cfg.ceiling_dbfs}")
    check(f"{label}: INV-2 绝不放大",
          max_vol <= base + 0.001,
          f"最高音量 {max_vol:.3f} > base {base}")
    check(f"{label}: INV-3 不过度压",
          min_vol >= base - cfg.max_attenuation_db - 0.001,
          f"最低音量 {min_vol:.3f}")


def expected_atten(signal_dbfs, base=BASE_VOLUME_DB, ceiling=CEILING_DBFS):
    """从控制律推导:该信号下应施加的衰减量。"""
    return max(0.0, (signal_dbfs + base) - ceiling)


def main():
    print("=" * 72)
    print("响度限幅控制律验证(闭环仿真 dt=8ms,base=%.1f dB,上限=%.1f dBFS)"
          % (BASE_VOLUME_DB, CEILING_DBFS))
    print("=" * 72)

    # ── C1:低响度素材完全不被动 ──
    print()
    print("C1  对白(-26 dBFS)持续 0.8s —— 不能退化成音量锁定")
    cfg = LoudnessConfig(ceiling_dbfs=CEILING_DBFS)
    tr = simulate(LoudnessLimiter(cfg), lambda t: -26.0, 0.8)
    check("衰减恒为 0", max(x[4] for x in tr) < 0.01,
          f"最大衰减 {max(x[4] for x in tr):.4f}")
    check("音量一动没动", all(abs(x[2] - BASE_VOLUME_DB) < 0.001 for x in tr),
          f"最低 {min(x[2] for x in tr):.4f}")
    check_invariants("C1", tr, cfg)

    # ── C2:超限素材压到正好够用 ──
    print()
    print("C2  爆炸(-1 dBFS)持续 3.2s —— 压到正好够用,输出回上限")
    cfg = LoudnessConfig(ceiling_dbfs=CEILING_DBFS)
    tr = simulate(LoudnessLimiter(cfg), lambda t: -1.0, 3.2)
    tail = tr[-50:]
    exp_att = expected_atten(-1.0)
    steady_att = tail[-1][4]
    print(f"     推导衰减 = ({-1.0} + {BASE_VOLUME_DB}) - {CEILING_DBFS} = {exp_att:.3f} dB")
    print(f"     实测稳态衰减 {steady_att:.3f} dB,稳态输出 {tail[-1][3]:.3f} dBFS")
    check("衰减等于推导值", abs(steady_att - exp_att) < 0.05,
          f"实测 {steady_att:.4f} vs 推导 {exp_att:.4f}")
    check("输出正好落在上限", abs(tail[-1][3] - CEILING_DBFS) < 0.05,
          f"实测 {tail[-1][3]:.4f}")
    check_invariants("C2", tr, cfg)

    # ── C3:保持期 —— 需要真正触发压制才能观察到 ──
    print()
    print("C3  爆炸(-1 dBFS)2s -> 转对白(-8 dBFS,仍在压制区) —— 保持期应稳住音量")
    hold = 3.0
    cfg = LoudnessConfig(ceiling_dbfs=CEILING_DBFS, hold_seconds=hold)
    tr = simulate(LoudnessLimiter(cfg), lambda t: -1.0 if t < 2.0 else -8.0, 2.0 + hold + 4.0)
    att_loud = [x[4] for x in tr if 1.5 <= x[0] < 2.0]
    inside = [(x[0], x[2]) for x in tr if 2.0 <= x[0] < 2.0 + hold - 0.05]
    later = [(x[0], x[2]) for x in tr if x[0] >= 2.0 + hold + 0.5]
    print(f"     压制期衰减 {max(att_loud):.3f} dB")
    print(f"     保持期内 音量 {inside[0][1]:.3f} -> {inside[-1][1]:.3f}")
    print(f"     保持期后 音量 {later[0][1]:.3f} -> {later[-1][1]:.3f}"
          f" (最终 {tr[-1][2]:.3f})")
    check("确实进入了压制", max(att_loud) > 1.0, f"只压了 {max(att_loud):.3f} dB")
    check("保持期内音量不变", abs(inside[-1][1] - inside[0][1]) < 0.05,
          f"{inside[0][1]:.3f} -> {inside[-1][1]:.3f}")
    check("保持期后开始回升", later[-1][1] > inside[-1][1] + 0.1,
          f"仍停在 {later[-1][1]:.3f}")
    check_invariants("C3", tr, cfg)

    # ── C4:释放速率 ──
    print()
    print("C4  释放速率应约等于配置值")
    rate = 6.0
    cfg = LoudnessConfig(ceiling_dbfs=CEILING_DBFS, hold_seconds=0.0,
                         release_db_per_s=rate)
    tr = simulate(LoudnessLimiter(cfg), lambda t: -1.0 if t < 1.0 else -12.0, 5.0)
    seg = [x for x in tr if 1.2 <= x[0] <= 2.0]
    # 只测纯线性段:末端的平台(音量已回到 0 不再上升)会把平均速率拉低。
    rising = []
    for a, b in zip(seg, seg[1:]):
        if b[2] > a[2] + 1e-9:
            rising.append(a)
            rising.append(b)
    if len(rising) > 4:
        t0, v0 = rising[0][0], rising[0][2]
        window = [p for p in rising if p[0] <= t0 + 0.3]
        t1, v1 = window[-1][0], window[-1][2]
        measured = (v1 - v0) / (t1 - t0) if t1 > t0 else 0.0
    else:
        measured = 0.0
    print(f"     实测 {measured:.2f} dB/s (配置 {rate})   线性段 {len(rising)} 拍")
    check("释放速率符合配置", abs(measured - rate) < 0.6, f"实测 {measured:.2f}")
    check_invariants("C4", tr, cfg)

    # ── C5:整段复杂素材 ──
    print()
    print("C5  整段:对白->爆炸->对白->更响爆炸->长静音")
    def varied(t):
        if t < 1.5:
            return -26.0
        if t < 3.5:
            return -2.0
        if t < 5.5:
            return -14.0
        if t < 8.0:
            return -0.5
        if t < 12.0:
            return -20.0
        return -60.0
    cfg = LoudnessConfig(ceiling_dbfs=CEILING_DBFS)
    tr = simulate(LoudnessLimiter(cfg), varied, 20.0)
    check_invariants("C5", tr, cfg)
    check("C5: 长静音后完全释放", abs(tr[-1][2] - BASE_VOLUME_DB) < 0.05,
          f"最终 {tr[-1][2]:.3f} vs base {BASE_VOLUME_DB}")
    check("C5: 低响度段落也未被干预",
          all(abs(x[2] - BASE_VOLUME_DB) < 0.05
              for x in tr if x[1] <= -26.0 and x[0] < 1.5),
          "第一段对白音量被改了")

    # ── C6:极严上限 + 上限可调 ──
    print()
    print("C6  上限滑到 -40 dBFS(极严):该压就压,且不超 max_attenuation")
    cfg = LoudnessConfig(ceiling_dbfs=-40.0, max_attenuation_db=40.0)
    tr = simulate(LoudnessLimiter(cfg), lambda t: -1.0, 3.0)
    check("确实在压", tr[-1][4] > 20.0, f"只压了 {tr[-1][4]:.2f} dB")
    check("不超 max_attenuation", tr[-1][4] <= 40.0 + 0.01, f"{tr[-1][4]:.2f}")
    check_invariants("C6", tr, cfg)

    # ── C7:上限滑条即时生效 ──
    print()
    print("C7  运行中把上限从 -6 调到 -20:应立即更用力压")
    lim = LoudnessLimiter(LoudnessConfig(ceiling_dbfs=CEILING_DBFS))
    tr1 = simulate(lim, lambda t: -1.0, 2.0)
    att_before = tr1[-1][4]
    lim.set_ceiling_dbfs(-20.0)
    tr2 = simulate(lim, lambda t: -1.0, 2.0)
    att_after = tr2[-1][4]
    print(f"     上限 -6 时衰减 {att_before:.2f} dB -> 上限 -20 时 {att_after:.2f} dB")
    check("调严上限后压得更狠", att_after > att_before + 5.0,
          f"{att_before:.2f} -> {att_after:.2f}")

    # ── C8:静音 ──
    print()
    print("C8  完全静音:不允许有任何干预")
    cfg = LoudnessConfig(ceiling_dbfs=CEILING_DBFS)
    tr = simulate(LoudnessLimiter(cfg), lambda t: -120.0, 2.0)
    check("静音时衰减为 0", max(x[4] for x in tr) < 0.01)
    check("静音时音量不动", all(abs(x[2] - BASE_VOLUME_DB) < 0.001 for x in tr))

    # ── C9:基础音量 ≠ 0 dB 时,上限仍是**绝对** dBFS 上限 ──
    # 🔴 这是历史上最大的测试盲区:上面 C1~C8 **全部**用 BASE_VOLUME_DB = 0,
    #    而控制律曾经写成 `volume_max = base + ceiling - signal` —— base=0 时
    #    那个错误项恰好消失,于是"实际输出被限制到 base+ceiling"这个 bug
    #    在 22 项断言 + 真实音频集成下藏了很久(用户改基础音量时上限被悄悄改动)。
    #    所以这一节的**存在本身**比它断言的内容更重要:换基准必须重跑。
    print()
    print("C9  基础音量 ≠ 0:上限必须仍然是绝对 dBFS 上限")
    for base in (0.0, -6.0, -10.58, -20.0):
        ceiling = -20.0
        cfg = LoudnessConfig(ceiling_dbfs=ceiling, hold_seconds=0.0)
        tr = simulate(LoudnessLimiter(cfg), lambda t: 0.0, 2.5,
                      base_volume_db=base)
        worst_out = max(x[3] for x in tr)
        att = max(x[4] for x in tr)
        # 期望值从定义推导:输出 = min(上限, 基础音量 + 信号)
        want_out = min(ceiling, base + 0.0)
        want_att = max(0.0, (0.0 + base) - ceiling)
        check(f"base={base:>7.2f} dB:输出 {want_out:.2f} dBFS"
              f"(而非旧 bug 的 base+上限={base + ceiling:.2f})",
              abs(worst_out - want_out) < 0.5, f"实测 {worst_out:.2f}")
        check(f"base={base:>7.2f} dB:衰减 {want_att:.2f} dB",
              abs(att - want_att) < 0.5, f"实测 {att:.2f}")

    # 另一侧:基础音量已经足够低时,不该插手
    cfg = LoudnessConfig(ceiling_dbfs=-20.0)
    tr = simulate(LoudnessLimiter(cfg), lambda t: -25.0, 2.0, base_volume_db=-30.0)
    check("base=-30dB 时输出 -55 dBFS(本就低于上限)不干预",
          max(x[4] for x in tr) < 0.01, f"压了 {max(x[4] for x in tr):.2f} dB")

    # ── C10:滑条最严那一端(-60 dBFS)必须真的压得到 ──
    # 滑条下限受两个物理约束:端点音量下限(本机 -65.25,写 -70 会被设备**拒绝**
    # 而不是夹住)与 max_attenuation_db。后者必须 >= |CEILING_MIN_DBFS|,
    # 否则拖到最底也压不到那条线(volume_max 被 floor 卡住)。
    from loudness_limiter import CEILING_MIN_DBFS, DEFAULT_MAX_ATTENUATION_DB
    print()
    print(f"C10 滑条最严端 {CEILING_MIN_DBFS:.0f} dBFS 必须真的压得到")
    check("max_attenuation >= |滑条下限|",
          DEFAULT_MAX_ATTENUATION_DB >= abs(CEILING_MIN_DBFS) - 0.01,
          f"max_att={DEFAULT_MAX_ATTENUATION_DB} < {abs(CEILING_MIN_DBFS)}")
    for base in (0.0, -10.58, -30.0):
        cfg = LoudnessConfig(ceiling_dbfs=CEILING_MIN_DBFS, hold_seconds=0.0)
        tr = simulate(LoudnessLimiter(cfg), lambda t: 0.0, 3.0, base_volume_db=base)
        worst = max(x[3] for x in tr)
        check(f"base={base:>7.2f} dB 时输出被压到 {CEILING_MIN_DBFS:.0f} dBFS 之内",
              worst <= CEILING_MIN_DBFS + 0.5, f"实测 {worst:.2f}")

    print()
    print("=" * 72)
    if failures:
        print(f"结果:✗ {len(failures)} 项失败")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("结果:✓ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())


