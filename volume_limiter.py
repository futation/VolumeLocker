#!/usr/bin/env python3
"""
volume_limiter.py — 音量标尺换算工具(纯逻辑,不依赖 Windows / pycaw)

本模块只做两件事:
  1. peak_to_dbfs : 峰值表读数(0.0~1.0)-> dBFS
  2. VolumeScale  : Windows 音量标量与 dB 的查表换算(用于界面显示)

限幅的控制律**不在这里** —— 见 loudness_limiter.py。这里之所以单独留下,
是因为 Windows 的音量标量 -> dB 映射既不是线性、也不是单一幂函数,
必须用实测查表(见下),而那张表只跟"显示/百分比换算"有关,
与限幅控制律无关。
"""

import math

# ── 安全下限:低于这个幅度的峰值一律当静音,避免 log10(0) ──
SILENCE_FLOOR_DBFS = -120.0


def peak_to_dbfs(peak: float) -> float:
    """线性峰值幅度(1.0 = 数字满刻度)换算为 dBFS。

    Windows 的 IAudioMeterInformation::GetPeakValue 返回归一化峰值
    (|采样峰值| / 满刻度)。1.0 -> 0 dBFS,0.5 -> -6.02 dBFS。
    """
    if peak is None or peak <= 0.0:
        return SILENCE_FLOOR_DBFS
    return 20.0 * math.log10(peak)


# ══════════════════════════════════════════════════════════════════
# 音量标尺
# ══════════════════════════════════════════════════════════════════
# Windows 音量标量 -> dB **既不是线性,也不是单一幂函数**。
#
# 本机实测(蓝牙端点 GH-OWS,GetVolumeRange = -63.5..0.0 dB,步进 0.5):
#
#     scalar  0.02   0.10   0.20   0.30   0.40   0.50   0.60   0.70
#     dB    -60.00 -33.03 -23.56 -17.77 -13.58 -10.30  -7.61  -5.32
#     scalar  0.80   0.90   1.00
#     dB     -3.33  -1.58   0.00
#
# 试图用 db = max - span*(1-s)^p 拟合:**失败**。各区间拟合指数是
# 3.63 / 5.81 / 3.65 / 2.74 / 3.17,不是常数 —— 它根本不是幂函数。
# 所以这里不编造公式,直接用实测表 + 线性插值。
#
# 权威数值始终走 API,不要靠这张表:
#   读真实 dB:IAudioEndpointVolume::GetMasterVolumeLevel()
#   写目标 dB:IAudioEndpointVolume::SetMasterVolumeLevel()   实测误差 0.0000 dB
MEASURED_SCALAR_TO_DB = (
    (0.02, -60.00), (0.10, -33.03), (0.15, -27.57),
    (0.20, -23.56), (0.25, -20.39), (0.30, -17.77), (0.35, -15.53),
    (0.40, -13.58), (0.45, -11.86), (0.50, -10.30), (0.55, -8.90),
    (0.60, -7.61), (0.65, -6.42), (0.70, -5.32), (0.75, -4.30),
    (0.80, -3.33), (0.85, -2.43), (0.90, -1.58), (0.95, -0.77),
    (1.00, 0.00),
)
# 说明:0.05 那个采样点被刻意剔除。实测时写 0.05 读回 -10.3047(上一个
# 值),是蓝牙 AVRCP 异步同步吞掉写入造成的坏数据,不是真实映射。
# 标定该表所用端点的范围(用于给其它端点按比例映射):
MEASURED_SCALAR_TO_DB_MIN_DB = -63.5
MEASURED_SCALAR_TO_DB_MAX_DB = 0.0


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def _clamp_db(value: float, lo: float, hi: float) -> float:
    return min(max(value, lo), hi)


class VolumeScale:
    """端点的音量标尺(min_db / max_db 来自 GetVolumeRange())。

    提供标量 <-> dB 的**查表插值**,用于界面显示和百分比换算。
    真正的读/写一律用 API 的 dB 接口。
    """

    __slots__ = ("min_db", "max_db", "increment_db", "table")

    def __init__(self, min_db: float = -63.5, max_db: float = 0.0,
                 increment_db: float = 0.5, table=None):
        self.min_db = min_db
        self.max_db = max_db
        self.increment_db = increment_db
        self.table = table or MEASURED_SCALAR_TO_DB

    @property
    def span_db(self) -> float:
        return self.max_db - self.min_db

    def _map_cal_db(self, cal_db: float) -> float:
        """把标定坐标系下的 dB 映射到本端点坐标系。

        必须**按比例映射**而不是整体平移:平移会把满刻度从 0 dB 挪走
        (Realtek 下限 -65.25 时 100% 会算成 -1.75 dB,而满刻度必须是 0)。
        """
        cal_span = MEASURED_SCALAR_TO_DB_MAX_DB - MEASURED_SCALAR_TO_DB_MIN_DB
        if cal_span <= 0.0 or self.span_db <= 0.0:
            return cal_db
        ratio = (cal_db - MEASURED_SCALAR_TO_DB_MIN_DB) / cal_span
        return self.min_db + ratio * self.span_db

    def _unmap_cal_db(self, db: float) -> float:
        """本端点 dB -> 标定坐标系 dB(_map_cal_db 的逆运算)。"""
        cal_span = MEASURED_SCALAR_TO_DB_MAX_DB - MEASURED_SCALAR_TO_DB_MIN_DB
        if cal_span <= 0.0 or self.span_db <= 0.0:
            return db
        ratio = (db - self.min_db) / self.span_db
        return MEASURED_SCALAR_TO_DB_MIN_DB + ratio * cal_span

    def scalar_to_db(self, scalar: float) -> float:
        """标量 -> dB(查表插值 + 按比例映射到本端点范围)。"""
        s = _clamp01(scalar)
        if s <= 1e-6:
            return self.min_db
        if s >= 1.0:
            return self.max_db
        if s <= self.table[1][0]:
            raw = self.table[1][1]
        else:
            lo, hi = self.table[1], self.table[1]
            for i in range(1, len(self.table) - 1):
                if self.table[i][0] <= s <= self.table[i + 1][0]:
                    lo, hi = self.table[i], self.table[i + 1]
                    break
            if hi[0] == lo[0]:
                raw = hi[1]
            else:
                ratio = (s - lo[0]) / (hi[0] - lo[0])
                raw = lo[1] + ratio * (hi[1] - lo[1])
        return _clamp_db(self._map_cal_db(raw), self.min_db, self.max_db)

    def db_to_scalar(self, db: float) -> float:
        """dB -> 标量(查表反插值 + 按比例映射)。"""
        if db <= self.min_db:
            return 0.0
        if db >= self.max_db:
            return 1.0
        cal_db = self._unmap_cal_db(db)
        seg = self.table[1:]
        if cal_db <= seg[0][1]:
            return seg[0][0]
        if cal_db >= seg[-1][1]:
            return 1.0
        for i in range(len(seg) - 1):
            s0, d0 = seg[i]
            s1, d1 = seg[i + 1]
            if d0 <= cal_db <= d1:
                if d1 == d0:
                    return s1
                return s0 + (cal_db - d0) / (d1 - d0) * (s1 - s0)
        return 1.0

    def clamp_db(self, db: float) -> float:
        return _clamp_db(db, self.min_db, self.max_db)


if __name__ == "__main__":
    print("VolumeScale 查表往返校验(必须精确往返):")
    bt = VolumeScale(-63.5, 0.0, 0.5)
    worst = 0.0
    for s, real in MEASURED_SCALAR_TO_DB[1:]:
        got = bt.scalar_to_db(s)
        back = bt.db_to_scalar(real)
        worst = max(worst, abs(back - s), abs(got - real))
    print(f"  标定端点最大误差 = {worst:.6f}")

    rt = VolumeScale(-65.25, 0.0, 0.031)
    print(f"  另一端点(Realtek): 0% -> {rt.scalar_to_db(0.0):.2f} dB (应 -65.25)")
    print(f"                     100% -> {rt.scalar_to_db(1.0):.2f} dB (应 0.00)")
    print(f"  限幅控制律见 loudness_limiter.py,验证见 test_loudness_limiter.py")
