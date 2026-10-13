#!/usr/bin/env python3
"""
loudness_limiter.py — 输出响度限幅核心(纯逻辑,不依赖 Windows / pycaw)

和"音量锁定"的本质区别
====================================================================
音量锁定:把系统音量钉在一个值上,谁来改都顶回去。音量不随信号变化。

响度限幅:盯住**实际输出的响度**,只在超过你设的上限时才把音量压下去,
          安静时不动。这才是 Sound Lock 想做的事。

关键:控制量是"输出响度",不是"信号峰值"
--------------------------------------------------------------------
端点峰值表读的是**音量衰减之前**的信号(Microsoft Learn: Peak Meters)。所以:

    output_dbfs = signal_peak_dbfs + current_volume_db

    对白: -26 dBFS + (-10 dB) = -36 dBFS   -> 低于上限,不动
    爆炸: -0.5 dBFS + (-10 dB) = -10.5 dBFS -> 超标,压

拿信号峰值直接跟阈值比(很多这类程序就这么写),安静段会把音量放回上限、
爆炸又压下去,音量来回横跳 —— 听感上就退化成"以音量为基准的锁定"。

控制律在**音量域**上做,不在"衰减量"域上做
--------------------------------------------------------------------
踩过的坑:把"衰减量"和"音量"当成两个独立变量来推,会自相矛盾
(实测卡在衰减 0.952 dB 永不释放、或稳态长期超限 0.48 dB)。
真正被写入执行器的量只有**音量**,所以状态也只该是音量:

    volume_max = ceiling_dbfs - signal_dbfs      # 不超上限允许的最大音量
    target     = min(volume_max, 保持期内不高于 volume_held)

三条硬规则
--------------------------------------------------------------------
1. 上限即硬约束      volume 永远 <= volume_max -> 输出永远 <= ceiling(数学上成立)
   ⚠️ 成立的前提是 volume_max 里**没有** base_volume 项;历史版本多加了一个
      base,于是实际输出被限制到 `base + ceiling`(见 update() 里的长注释)。
   base_volume 只用于:夹住"绝不放大"、以及把 volume 换算成 attenuation。
2. 保持期(hold)    从处于压制的**那一刻**起续期,用于把音量留住"再压一会儿"
3. 缓慢释放          只允许音量向 base_volume 缓慢回升,由规则 1 兜住上限
"""

from dataclasses import dataclass
import math

# ── 安全下限:低于这个幅度的峰值一律当静音,避免 log10(0) ──
SILENCE_FLOOR_DBFS = -120.0

# ── 默认参数 ──
DEFAULT_CEILING_DBFS = -6.0      # 输出响度上限
# 滑条下限 -60:这个值不是随便定的,它受两个**物理**下限约束(本机实测):
#   1. 音量端点本身的下限。实测本机默认设备 GetVolumeRange() = -65.25..0 dB,
#      写 -60 能读回 -60.00,但写 -70 会被设备**直接拒绝**
#      (COMError E_INVALIDARG —— 不是夹住,是拒绝)。
#   2. 限幅是靠"写音量"实现的 => 能压到的输出下限 = 音量下限 + 信号。
#      0 dBFS 的信号最多能被压到端点下限附近。
# 所以 -100 这类值**压不到**,只会变成空头承诺(而且每拍写一次被拒的错误)。
# -60 与电平表刻度(LevelMeter.MIN_DB)一致,保证上限线永远画得出来。
CEILING_MIN_DBFS = -60.0         # 滑条下限
CEILING_MAX_DBFS = 0.0           # 滑条上限(0 dBFS = 数字满刻度)
DEFAULT_HOLD_SECONDS = 0.0       # 压制后保持(0 = 不额外保持,释放只受迟滞闸门约束)
# 向 base_volume 回升的速率(慢,防泵动)。
# 关键关系(实测,见 diag_release_tradeoff.py):
#     "压一会松一会"的周期 ≈ 压缩深度 ÷ 释放速率
#    压缩深度 = 基础输出响度 - 上限。例如输出 -6 dBFS、上限 -20 dBFS 时为 14 dB。
#      释放 6.0 dB/s -> 摆动 3.84 dB、3.8s 一个周期(用户报告的"一炸一炸")
#      释放 5.0 dB/s -> 摆动约 3 dB、约 4s 一个周期      ← 默认(用户听感选定)
#      释放 1.5 dB/s -> 摆动 1.23 dB、完全释放约 11s
#      释放 0.5 dB/s -> 摆动 0.45 dB、完全释放约 30s
# 两者是反比关系:越慢越不炸,但一次爆炸压低后爬回来也越久。
# 用户可随时用界面上的"释放速率"滑条调整。
# 注意:这个默认值是**用户按听感选定**的(偏好快速恢复),不是防泵动的最优值。
# 一旦听出"一炸一炸",第一个该往小调的就是它。
DEFAULT_RELEASE_DB_PER_S = 5.0
# 最多能压多少 dB。它必须 >= |CEILING_MIN_DBFS|,否则"滑条能拖到的最严上限"
# 会有一段压不到(volume_max 被 floor 卡住,输出仍在限幅线上方)。
# 为什么取 60 而不是更大:volume_max = ceiling - signal,信号最强是 0 dBFS,
# 所以需要写到的最深音量就**等于**上限本身(-60);再大只会让音量有机会掉到
# 端点下限以下 —— 那种写入会被设备拒绝(E_INVALIDARG),不是被夹住。
DEFAULT_MAX_ATTENUATION_DB = 60.0
# 释放迟滞:输出必须比上限低这么多 dB 才允许开始回升。
# 少了它,只要输出贴上/略低于上限就会启动释放,而素材整体仍超限,
# 于是"放一点 -> 又被压回去"循环出现,听起来就是一炸一炸(泵动)。
# 实测把上限设到 -20 dBFS(压缩深度 14 dB)时最明显。
DEFAULT_RELEASE_THRESHOLD_DB = 1.5
# 节目平均电平平滑时间常数。实测:不加平滑时压缩 22 dB 会有 4 dB 的音量
# 起伏(跟着音乐呼吸);300ms 可把抖动压到 1 dB 量级。
DEFAULT_DETECTOR_SECONDS = 0.30
# 判释放用的短窗长度。
# 这不是普通的滑动窗,而是**峰值保持窗**:窗口内的最大值会被"记住",直到
# 它滑出窗口才允许下降。作用是把短促的响头连成一片 —— 否则一段 30ms 的响
# 在 50ms 后就滑出窗口、迟滞放开、释放探头,然后下一个响头又把它压回去,
# 形成"响一下→松一点→又响→又压"的细碎循环。
DEFAULT_RELEASE_WINDOW_SECONDS = 0.25
# 峰值保持的衰减速率(窗内无新高时按此速率下落),避免窗口一走完才突然跳变。
DEFAULT_PEAK_HOLD_DECAY_DB_PER_S = 12.0

def peak_to_dbfs(peak: float) -> float:
    """线性峰值幅度(1.0 = 数字满刻度)换算为 dBFS。"""
    if peak is None or peak <= 0.0:
        return SILENCE_FLOOR_DBFS
    return 20.0 * math.log10(peak)


@dataclass
class LoudnessConfig:
    """限幅参数。

    ceiling_dbfs:        输出响度上限。信号越响 -> dBFS 越接近 0。
    hold_seconds:        压制后保持的时间。太短会让对白被抽得忽大忽小。
    release_db_per_s:    向起始音量回升的速率。太快产生"抽吸感"(pumping)。
    release_threshold_db:释放迟滞。输出低于 (上限 - 该值) 才允许回升。
    max_attenuation_db:  相对起始音量最多压多少,防止异常峰值把音量打到 0。
    silence_peak:        低于此值视为静音。
    """

    ceiling_dbfs: float = DEFAULT_CEILING_DBFS
    hold_seconds: float = DEFAULT_HOLD_SECONDS
    release_db_per_s: float = DEFAULT_RELEASE_DB_PER_S
    max_attenuation_db: float = DEFAULT_MAX_ATTENUATION_DB
    silence_peak: float = 1e-5
    release_threshold_db: float = DEFAULT_RELEASE_THRESHOLD_DB
    # 节目平均电平的平滑时间常数(秒)。决定"稳态该压多深"跟随得多慢。
    #   太小 -> 音量跟着音乐起伏呼吸(泵动);太大 -> 对整体响度变化反应迟钝。
    detector_seconds: float = DEFAULT_DETECTOR_SECONDS
    # 判释放用的短窗长度(峰值保持窗,见常量注释)
    release_window_seconds: float = DEFAULT_RELEASE_WINDOW_SECONDS
    # 峰值保持的衰减速率(dB/s)
    peak_hold_decay_db_per_s: float = DEFAULT_PEAK_HOLD_DECAY_DB_PER_S


@dataclass
class LimiterReading:
    """供界面显示的快照。"""

    ceiling_dbfs: float
    signal_dbfs: float        # 信号峰值(衰减前)
    volume_db: float          # 已写入的音量
    output_dbfs: float        # 估算的实际输出响度
    attenuation_db: float     # 相对"不压制时"的衰减量(= base - volume)
    limiting: bool


class LoudnessLimiter:
    """输出响度限幅器。纯逻辑,不碰任何 Windows API。

    每拍调用:
        target_volume_db = update(signal_peak, current_volume_db, now)

    返回的**就是要写入执行器的音量(dB)**,调用方直接
    SetMasterVolumeLevel(target, ctx) 即可。不回读、不验证。
    """

    __slots__ = ("config", "base_volume_db", "_volume_db", "_hold_until",
                 "_last_update", "_reading", "_peaks", "_inhibit",
                 "_hold_dbfs", "_env_buf", "_env_sum", "_env_win")

    def __init__(self, config: LoudnessConfig | None = None,
                 base_volume_db: float = -10.0):
        self.config = config or LoudnessConfig()
        self.base_volume_db = base_volume_db
        self._volume_db = base_volume_db
        self._hold_until = 0.0
        self._last_update: float | None = None
        # 短窗峰值队列 [(t, peak)],用于**判释放**(抗瞬时抖动)
        self._peaks: list = []
        # 释放迟滞状态:True = 仍处于"该压"的状态,禁止释放
        self._inhibit = False
        # 滑动均值检测器(节目平均电平),用于决定稳态压制深度。
        # 窗口长度由 detector_seconds 换算;固定按 8ms 节拍估算。
        self._env_win = max(1, int(round(self.config.detector_seconds / 0.008)))
        self._env_buf = []
        self._env_sum = 0.0
        # 峰值保持值(dBFS):判释放的基准
        self._hold_dbfs = SILENCE_FLOOR_DBFS
        self._reading = LimiterReading(
            self.config.ceiling_dbfs, SILENCE_FLOOR_DBFS, base_volume_db,
            SILENCE_FLOOR_DBFS + base_volume_db, 0.0, False,
        )

    # ── 参数 ──
    def set_ceiling_dbfs(self, ceiling_dbfs: float) -> None:
        self.config.ceiling_dbfs = min(max(float(ceiling_dbfs), CEILING_MIN_DBFS),
                                       CEILING_MAX_DBFS)

    @property
    def ceiling_dbfs(self) -> float:
        return self.config.ceiling_dbfs

    def set_base_volume_db(self, base_volume_db: float) -> None:
        """用户期望的音量(不超过上限时的音量)。

        只在未初始化时同步内部状态。初始化后再改基数不应重置当前音量,
        否则限幅过程中的滑条调整会把音量瞬间跳回。
        """
        first_time = self._volume_db == self.base_volume_db
        self.base_volume_db = float(base_volume_db)
        if first_time:
            self._volume_db = self.base_volume_db

    @property
    def volume_db(self) -> float:
        return self._volume_db

    @property
    def attenuation_db(self) -> float:
        return max(0.0, self.base_volume_db - self._volume_db)

    @property
    def reading(self) -> LimiterReading:
        return self._reading

    def diagnostics(self) -> dict:
        """只读诊断快照(排查用,不影响控制)。"""
        return {
            "volume_db": self._volume_db,
            "hold_until": self._hold_until,
            "last_update": self._last_update,
            "base_volume_db": self.base_volume_db,
            "ceiling_dbfs": self.config.ceiling_dbfs,
        }

    def reset(self, now: float = 0.0) -> None:
        self._volume_db = self.base_volume_db
        self._hold_until = 0.0
        self._last_update = None
        self._peaks.clear()
        self._inhibit = False
        self._env_buf.clear()
        self._env_sum = 0.0
        self._hold_dbfs = SILENCE_FLOOR_DBFS

    # ── 每拍 ──
    def update(self, signal_peak: float, current_volume_db: float, now: float) -> float:
        """喂入一拍信号,返回应写入的音量(dB)。

        current_volume_db 只用于显示(算实际输出响度);控制律本身不依赖它 ——
        **函数的返回值就是唯一真相**,调用方写下去即可。控制律不依赖自己上一步
        的输出,这就避免了"读到自己旧值"导致的死区。
        """
        cfg = self.config

        if signal_peak is None or signal_peak <= cfg.silence_peak:
            # 静音按"下限"处理:output 会是一个很大的负数,need_db 归零,
            # 于是保持期计时开始、到点后正常释放。
            signal_peak = 0.0
            signal_dbfs = SILENCE_FLOOR_DBFS
        else:
            signal_dbfs = 20.0 * math.log10(signal_peak)

        dt = 0.0 if self._last_update is None else max(0.0, now - self._last_update)
        self._last_update = now

        # ── 电平检测:两条路径分工 ──
        #   瞬时峰值    -> 只用于"抓瞬态",保证不漏掉爆炸的起头
        #   滑动均值    -> 用于决定**稳态**该压多深
        # 踩过的两个坑:
        #   1) 只拿瞬时峰值当控制量时,音乐起伏会一比一变成音量起伏(泵动);
        #   2) 包络若写成"上升立刻跟随"(峰值跟随),它会一路跟踪信号**波峰**,
        #      算出的稳态需求比均值深 8 dB 以上(实测 volume 被压到 -28.3,
        #      而均值对应的正解是 -17.7)—— 所以必须用**均值**,不能用峰值跟随。
        self._env_buf.append(signal_peak)
        self._env_sum += signal_peak
        if len(self._env_buf) > self._env_win:
            self._env_sum -= self._env_buf.pop(0)
        env_mean = self._env_sum / len(self._env_buf) if self._env_buf else 0.0
        env_dbfs = peak_to_dbfs(env_mean)

        # 短窗峰值 + **峰值保持**:判释放用。
        # 音乐瞬时掉一下不代表整体不再超限;而且短促的响头如果只被 50ms 窗口
        # 记住,窗口一滑走迟滞就放开、释放探头,下一个响头又把它压回去 —— 
        # 这就是"响一下→松一点→又响→又压"的细碎循环。
        # 峰值保持窗把短促响头连成一片,直到素材真的安静下来才允许释放。
        self._peaks.append((now, signal_peak))
        horizon = now - cfg.release_window_seconds
        while self._peaks and self._peaks[0][0] < horizon:
            self._peaks.pop(0)
        window_peak = max((p for _, p in self._peaks), default=0.0)
        window_dbfs = peak_to_dbfs(window_peak)

        # 峰值保持:有新高立刻抬上去;否则按固定速率下落(不是窗口一走完就跳变)
        if window_dbfs > self._hold_dbfs:
            self._hold_dbfs = window_dbfs
        else:
            self._hold_dbfs -= cfg.peak_hold_decay_db_per_s * dt
            if self._hold_dbfs < window_dbfs:
                self._hold_dbfs = window_dbfs
            if self._hold_dbfs < SILENCE_FLOOR_DBFS:
                self._hold_dbfs = SILENCE_FLOOR_DBFS

        # 输出响度(按当前实际音量估算)
        output_dbfs = signal_dbfs + current_volume_db

        # ★ 不超上限所允许的最大音量:
        #     output = signal_dbfs + volume <= ceiling
        #     => volume <= ceiling - signal_dbfs        ← 就这一步,没有别的项
        #   两个来源取更严的那个:瞬时(抓瞬态)+ 平滑(稳态不呼吸)。
        #
        # ⚠️ 这里曾经写成 `base_volume_db + ceiling - signal`(注释里的推导也跟着
        #    错写成了 "=> volume <= ceiling - signal + base_volume")。后果是
        #    **实际被限制到的是 `基础音量 + 上限`**,而不是上限:
        #        基础音量 0 dB    -> 输出 -20.00(对)
        #        基础音量 -6 dB   -> 输出 -26.00(差 6 dB)
        #        基础音量 -10.58  -> 输出 -30.58(差 10.58 dB)
        #    也就是说"改基础音量会悄悄改掉有效上限",而且电平表上那条上限线
        #    永远够不到。两套测试都用 base = 0 dB,恰好让错误项消失,所以
        #    22 项离线断言 + 真实音频集成全都照不出来 —— 现已补 base ≠ 0 的用例。
        #    base 在这里只用于两件事:夹住"绝不放大"的上界、以及算衰减量。
        vmax_instant = cfg.ceiling_dbfs - signal_dbfs
        vmax_env = cfg.ceiling_dbfs - env_dbfs
        volume_max = vmax_instant if vmax_instant < vmax_env else vmax_env
        if volume_max > self.base_volume_db:
            volume_max = self.base_volume_db            # 绝不放大
        volume_floor = self.base_volume_db - cfg.max_attenuation_db
        if volume_max < volume_floor:
            volume_max = volume_floor                   # 最多压这么多

        # ── 噪声门:整段素材都远低于上限时,没必要参与,直接放开 ──
        # (材料安静 -> 期望音量回到 base,不产生任何压制)
        # ── 释放迟滞 ──
        # 进入:峰值预示"在这个音量下会顶到上限" —— 代表这段素材够响,不许松手
        # 退出:峰值预示的输出比上限还低 release_threshold_db,才算真安全
        # 两个阈值形成死区。之前用 base+ceiling-signal 那类算术判定是**错的**
        # (那个量永远够不到阈值),导致 _inhibit 恒为 False、迟滞形同虚设 —— 
        # 实测占比 0%,这正是"压一会松一会"始终没治住的真正原因。
        gate = (signal_dbfs + self.base_volume_db) > cfg.ceiling_dbfs
        if gate:
            if self._hold_dbfs > cfg.ceiling_dbfs - current_volume_db:
                self._inhibit = True
            elif self._hold_dbfs < (cfg.ceiling_dbfs - cfg.release_threshold_db
                                    - current_volume_db):
                self._inhibit = False
        else:
            self._inhibit = False

        volume = current_volume_db
        if output_dbfs > cfg.ceiling_dbfs and volume > volume_max:
            volume = volume_max                 # 快压(用瞬时值,抓瞬态)
        if volume > volume_max:
            volume = volume_max

        if self._inhibit:
            # 仍该压 -> 保持期不断续期,不允许回升
            self._hold_until = now + cfg.hold_seconds
        elif now >= self._hold_until:
            # 确实已安全且保持期已过 -> 缓慢释放
            volume += cfg.release_db_per_s * dt
            if volume > volume_max:
                volume = volume_max

        if volume > self.base_volume_db:
            volume = self.base_volume_db

        self._volume_db = volume
        self._reading = LimiterReading(
            ceiling_dbfs=cfg.ceiling_dbfs,
            signal_dbfs=signal_dbfs,
            volume_db=volume,
            output_dbfs=signal_dbfs + volume,
            attenuation_db=max(0.0, self.base_volume_db - volume),
            limiting=volume < self.base_volume_db - 0.01,
        )
        return volume


if __name__ == "__main__":
    print(__doc__)
    print("控制律的自动化验证请运行: py test_loudness_limiter.py")








