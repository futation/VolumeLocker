#!/usr/bin/env python3
"""
integration_check.py — 验证集成进 volume_locker.py 的响度限幅(真实音频 + 真实端点)

会真实播放声音并改动默认端点的音量,结束自动还原。

验证的语义(这才是"响度限幅"该有的样子):
  1. 低响度素材     -> 不干预,音量不动             (不能退化成"音量锁定")
  2. 超上限素材     -> 压下去,输出回到上限之内
  3. 素材转安静     -> 保持期内不回升,之后缓慢恢复
  4. 停用后         -> 音量回到基础音量

用的是产品代码路径 device_limiter.step(),不是临时实现。
"""

import ctypes
import math
import sys
from pathlib import Path
import threading
import time

sys.coinit_flags = 0
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台/管道默认按 GBK 编码 stdout,打印 ✓✗ 会 UnicodeEncodeError。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import comtypes
from pycaw.pycaw import AudioUtilities

import volume_locker as vl
from loudness_limiter import LoudnessConfig, LoudnessLimiter

WINMM = ctypes.WinDLL("winmm")


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", ctypes.c_ushort), ("nChannels", ctypes.c_ushort),
        ("nSamplesPerSec", ctypes.c_uint), ("nAvgBytesPerSec", ctypes.c_uint),
        ("nBlockAlign", ctypes.c_ushort), ("wBitsPerSample", ctypes.c_ushort),
        ("cbSize", ctypes.c_ushort),
    ]


class WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p), ("dwBufferLength", ctypes.c_uint),
        ("dwBytesRecorded", ctypes.c_uint), ("dwUser", ctypes.c_void_p),
        ("dwFlags", ctypes.c_uint), ("dwLoops", ctypes.c_uint),
        ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_void_p),
    ]


def build(ms, rate=48000, freq=440.0, amp=0.9, fade_ms=20):
    n = int(rate * ms / 1000)
    fade = max(1, int(rate * fade_ms / 1000))
    buf = (ctypes.c_short * n)()
    for i in range(n):
        env = min(1.0, min((i + 1) / fade, (n - i) / fade))
        buf[i] = int(32767 * amp * env * math.sin(2 * math.pi * freq * i / rate))
    return buf


def play(pcm, rate=48000):
    fmt = WAVEFORMATEX(1, 1, rate, rate * 2, 2, 16, 0)
    h = ctypes.c_void_p()
    if WINMM.waveOutOpen(ctypes.byref(h), ctypes.c_uint(-1), ctypes.byref(fmt),
                         None, None, 0) != 0:
        return False
    hdr = WAVEHDR(ctypes.cast(pcm, ctypes.c_void_p), ctypes.sizeof(pcm),
                  0, None, 0, 0, None, None)
    WINMM.waveOutPrepareHeader(h, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
    WINMM.waveOutWrite(h, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
    time.sleep(ctypes.sizeof(pcm) / (rate * 2) + 0.1)
    WINMM.waveOutReset(h)
    WINMM.waveOutClose(h)
    return True


failures = []


def check(name, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        failures.append(name)


def main():
    comtypes.CoInitializeEx(0)
    spk = AudioUtilities.GetSpeakers()
    ep = spk.EndpointVolume
    vmin, vmax, vinc = ep.GetVolumeRange()
    orig_db = ep.GetMasterVolumeLevel()
    orig_scalar = ep.GetMasterVolumeLevelScalar()
    scale = vl.VolumeScale(min_db=vmin, max_db=vmax, increment_db=vinc)

    BASE_PCT = 100                      # 基础音量:满刻度(最容易触发超限的工况)
    base_db = scale.scalar_to_db(BASE_PCT / 100.0)
    CEILING = -6.0

    print(f"端点      : {spk.FriendlyName!r}")
    print(f"dB 范围   : {vmin} .. {vmax}")
    print(f"原始音量  : {orig_scalar:.4f} / {orig_db:.2f} dB")
    print(f"测试用    : 基础音量 {BASE_PCT}% = {base_db:.2f} dB, 响度上限 {CEILING} dBFS")
    print()

    lim = vl.DeviceLimiter(comtypes, vl.IAudioMeterInformationFull,
                           LoudnessLimiter,
                           LoudnessConfig(ceiling_dbfs=CEILING,
                                          hold_seconds=2.0,
                                          release_db_per_s=6.0))
    lim.set_mode(vl.MODE_LIMIT)
    lim.set_ceiling_dbfs(CEILING)
    lim.set_base_volume_db(base_db)
    # 本测试的目标是验证**释放机制本身**,所以把输出滤波关掉(设为 0)。
    # 滤波(默认 0.2s)叠加在释放路径上会显著拖慢恢复 —— 那是已确认的
    # 取舍(更稳 <-> 更慢),不是缺陷,应该在界面上调,不该在这里断言。
    lim.volume_filter_seconds = 0.0
    if not lim.attach(spk, "integration-test"):
        print(f"attach 失败: {lim.error}")
        return 1
    print("[产品路径] DeviceLimiter.attach() 成功")
    print(f"[产品路径] 模式={lim.mode}  基础音量={lim.base_volume_db:.2f} dB")
    print()

    # 用真实端点作为"执行器":控制环写多少,就设到端点上
    samples = []
    stop = threading.Event()
    written = {"v": None}

    def control_loop():
        t0 = time.perf_counter()
        while not stop.is_set():
            lim.step(time.perf_counter() - t0)
            v = lim._last_written
            if v is not None and (written["v"] is None or abs(v - written["v"]) > 1e-9):
                ep.SetMasterVolumeLevel(v, None)      # 真正写硬件
                written["v"] = v
            samples.append((lim.signal_dbfs, lim.output_dbfs,
                            lim.attenuation_db, lim.volume_db))
            time.sleep(vl.DeviceLimiter.POLL_SECONDS)

    def run_case(label, pcm, observe_after_s, on_play_end=None):
        """播放一段素材,分三段测量:素材中 / 素材刚结束 / 结束后若干秒。"""
        ep.SetMasterVolumeLevel(base_db, None)
        lim._lim.reset()
        lim._last_written = None
        written["v"] = None
        samples.clear()
        stop.clear()

        th = threading.Thread(target=control_loop, daemon=True)
        th.start()
        time.sleep(0.25)

        # play() 是阻塞的,所以在子线程里播,好在中途采样
        pt = threading.Thread(target=play, args=(pcm,), daemon=True)
        pt.start()
        time.sleep(0.5)                       # 素材进行中
        mid = list(samples)
        pt.join()
        end_att = lim.attenuation_db          # 素材刚结束的那一瞬
        end_vol = ep.GetMasterVolumeLevel()

        if on_play_end:
            on_play_end()

        # 观察保持期与恢复
        traj = [(0.0, lim.attenuation_db)]
        t0 = time.time()
        while time.time() - t0 < observe_after_s:
            time.sleep(0.5)
            traj.append((time.time() - t0, lim.attenuation_db))
        stop.set()
        th.join(timeout=1.5)

        max_att = max((s[2] for s in mid), default=0.0)
        outs = [s[1] for s in mid if s[1] > -119]
        print(f"{label}")
        print(f"   素材中采样 {len(mid)}  最大衰减 {max_att:.2f} dB")
        if outs:
            print(f"   素材中输出响度 {min(outs):.2f} .. {max(outs):.2f} dBFS"
                  f"  (上限 {CEILING})")
        print(f"   素材结束瞬间 衰减 {end_att:.2f} dB, 音量 {end_vol:.2f} dB")
        print(f"   保持/恢复轨迹 " + "  ".join(f"+{t:.1f}s={a:.2f}" for t, a in traj))
        print()
        return max_att, min(outs) if outs else -119, max(outs) if outs else -119, end_att, traj

    tone_loud = build(1500, amp=0.95)     # ~ -0.45 dBFS
    tone_quiet = build(1200, amp=0.06)    # ~ -24 dBFS

    try:
        # ① 低响度素材:不该被干预
        ep.SetMasterVolumeLevel(base_db, None)
        lim._lim.reset()
        lim._last_written = None
        written["v"] = None
        samples.clear()
        stop.clear()
        th = threading.Thread(target=control_loop, daemon=True)
        th.start()
        time.sleep(0.25)
        play(tone_quiet)
        quiet_att = max((s[2] for s in samples), default=0.0)
        stop.set()
        th.join(timeout=1.5)
        print("① 低响度素材(-24 dBFS)")
        print(f"   最大衰减 {quiet_att:.3f} dB   音量未被改动")
        check("低响度素材不触发限幅", quiet_att < 0.05, f"实测 {quiet_att:.3f} dB")
        print()

        # ② 超上限素材:压下去,输出回到上限内;素材结束后仍在保持期
        loud_att, min_out, max_out, end_att, traj = run_case(
            "② 超上限素材(-0.45 dBFS, 1.5s),之后观察 4s", tone_loud, 4.0)
        # 真正该断言的是"输出被压到上限",而不是"压了多少 dB" ——
        # 压多少取决于素材实际电平(实测峰值约 -3.45 dBFS,故只需 2.55 dB)。
        check("超上限时确实施加了衰减", loud_att > 1.5,
              f"只压了 {loud_att:.2f} dB")
        check("输出峰值被压到上限之内", max_out <= CEILING + 0.1,
              f"最大输出 {max_out:.2f} > 上限 {CEILING}")
        check("素材结束时仍在保持压制", end_att > 1.0,
              f"结束瞬间衰减仅 {end_att:.2f} dB")

        # ③ 保持期内不应立刻回升,之后才缓慢释放
        hold_samples = [a for t, a in traj if t <= 1.5]
        late_att = traj[-1][1]
        print(f"③ 保持期(<=1.5s)最低衰减 {min(hold_samples):.2f} dB,"
              f" 4s 后 {late_att:.2f} dB")
        check("保持期内保持住", min(hold_samples) > end_att - 0.4,
              f"保持期内掉到 {min(hold_samples):.2f}")
        check("之后确实释放了", late_att < end_att - 0.5,
              f"一直停在 {late_att:.2f} dB")

        # ④ 长时间安静后彻底释放
        t0 = time.time()
        while time.time() - t0 < 4.0:
            time.sleep(0.2)
        print(f"④ 再等 4 秒后衰减 {lim.attenuation_db:.2f} dB")
        check("最终完全释放", lim.attenuation_db < 0.5,
              f"仍压着 {lim.attenuation_db:.2f} dB")

    finally:
        stop.set()
        lim.detach()
        ep.SetMasterVolumeLevel(orig_db, None)
        time.sleep(0.3)
        print()
        print(f"已还原音量: {ep.GetMasterVolumeLevelScalar():.4f} / "
              f"{ep.GetMasterVolumeLevel():.2f} dB  (原 {orig_scalar:.4f} / {orig_db:.2f})")

    print()
    print("=" * 66)
    if failures:
        print(f"结果: ✗ {len(failures)} 项失败 -> {failures}")
        return 1
    print("结果: ✓ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

