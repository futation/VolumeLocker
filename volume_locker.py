# 注意: 这里刻意不写 shebang。
# Windows 上 .py 文件关联到 py.exe，若首行是 `#!/usr/bin/env python3`，py.exe 会去
# PATH 里找 python3 —— 本机命中的是 pyenv 的 3.12（没装 pycaw），结果是启动失败
# 或静默退出（实测 exit 9009，脚本一行都没跑）。
# 统一用同目录的「启动VolumeLocker.bat」启动，它写死了 .venv 的解释器。
"""
VolumeLocker v2.0.0 — 多设备音量锁定工具 (Windows 11)
为每个音频输出设备独立锁定音量，支持系统托盘后台运行。
轻量化设计，占用资源极小。

v2.0.2 — 多设备独立锁定 + 系统托盘 + COM 自动恢复 | 修复: 睡眠唤醒后音量锁失效
v2.1.0 — UI 重排:退出按钮移除(改由托盘菜单退出)、释放速率/保持时间/音量平滑
         收进底部「高级设置」折叠面板、开关项收进「设置」折叠面板、
         电平条只在响度限幅模式下显示
v2.2.0 — 外观层重做(路线 A+B):DPI 感知、ttkbootstrap 主题、深浅色跟随系统、
         Canvas 手绘电平表(刻度/渐变/上限标线/信号游标/峰值保持)、状态药丸、
         卡片式布局、颜色全部集中到 theme.py 的调色板
v2.2.1 — 修控件"自带底色":卡片里的滑条/单选改用 `bootstyle="@card"` 声明表面,
         下拉框聚焦高亮 map 回卡片色,进度条换成自绘 MiniBar;
         卡片底色改为问主题要(card 表面)而不是自己推算
v2.2.2 — 补齐:`bootstyle="@card"` 只重烘图片,**不管控件自己的 background**,
         于是轨道上下还露着窗口底色(实测 #212529 vs 卡片 #2e3236)——
         现在把 @card.* 系列的 background/focuscolor 一并配成卡片色
v2.3.0 — 音量锁定模式下**隐藏**"限幅专用"的三块(响度上限 / 电平表 /
         高级设置整块),而不是把它们置灰:高级设置默认收起,置灰在收起状态下
         等于没有提示。统一成一条规则——只显示当前模式用得上的东西。
         同时去掉底部"退出:右键托盘图标"那行提示。
v2.3.1 — 修两个用户报的问题:
         (1) 模式记不住:mode 从"每设备一份"改为**全局偏好**(顶层 config["mode"]),
             老配置从上次选中的设备继承一次;控制环侧也改读全局,避免
             "界面显示锁定、后台却不钉音量"的错位。
         (2) 锁定模式下点"设置"什么都没出来:折叠面板的 mode_gated 闸门
             被写进了公共函数,把与模式无关的"设置"面板也挡住了。
v2.3.2 — 修"切到响度限幅但整个软件不工作":
         根因是一段**死代码** —— _clock() 被插在 DeviceLimiter.__init__ 中间,
         它 return 之后的初始化(含界面要读的 output_dbfs/attenuation_db)
         永不执行;启动即锁定模式时界面刷新抛 AttributeError,而 _update_ui
         的 except 把 polling_active 置 False,轮询线程与控制环线程双双退出。
         修:把 _clock() 移出 __init__、界面字段读取全部加兜底、
         _update_ui 出错只记日志绝不停音频控制;并加 AST 死代码审计。
v2.4.0 — 修控制律的**上限公式**:历史版本写成
         `volume_max = base + ceiling - signal`,导致实际被限制到的是
         `基础音量 + 上限`(50% 基础音量下差 10.58 dB),改基础音量会悄悄
         改掉有效上限、电平表的上限线永远够不到。现在去掉 base 项,
         上限就是**绝对 dBFS 输出上限**;测试补 C9(base≠0 的用例),
         界面提示也改成"它比素材峰值低一个基础音量的量"。
         注意:上限数值的含义变了,老配置需要按听感重新拖一次。
v2.4.1 — 上限滑条范围 -40..0 -> **-60..0**,并把 max_attenuation_db 40 -> 60
         (否则最严那端压不到)。下限 -60 不是随便定的:端点音量下限
         (本机 -65.25,写 -70 会被设备拒绝 E_INVALIDARG)+ 限幅靠写音量
         实现,决定了能压到的输出下限;再往下就是空头承诺,所以没做 -100。
         另给 _write() 加了"夹到端点真实范围"的保险,避免被拒绝的写入。
v2.5.0 — 修"音量平滑"的语义(用户报"爆炸之后声音没回去"):
         滤波曾经**偷偷把释放速率乘上 dt/(tau+dt)** —— tau=0.05(滑条默认值)
         时只剩 1/7,恢复要 25 秒,tau=0.1 时 30 秒都回不来。
         根因是喂给控制律的反馈量用了"滤波后的下发值",释放被算了两遍。
         现在反馈量用限幅器上一拍的命令值,滤波只磨平"写出去的值":
         各 tau 的恢复都回到 1~2.6 秒,而滤波压泵动的能力反而更强。
         滑条范围 0..1(且无分辨率)-> **0..0.5、步进 0.01**;
         配置里的拖拽残渣(0.011037593818985 之类)载入时会归整并落盘。
v2.6.0 — 开机自启**不再弹界面**(用户要求"自启后在后台自动开始工作",
         但双击 exe 仍要弹界面)。
         做法:自启命令带 `--tray`;启动时按它决定隐藏还是显示,
         并且在**建控件之前** withdraw,避免窗口闪一下。
         旧版本写下的自启项没有这个标志,启动时自愈补上
         (ConfigManager.ensure_auto_start_flag)。
         另有安全兜底:托盘不可用时即使带 --tray 也照常显示窗口,
         否则用户没有任何入口能把界面叫出来。
"""

# ══════════════════════════════════════════════════════════════════
# CRITICAL: 必须在导入 pycaw/comtypes 之前设置 (MMNotificationClient 要求)
# ══════════════════════════════════════════════════════════════════
import sys
sys.coinit_flags = 0

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pycaw")

import tkinter as tk
import threading
import time
import os
import json
import winreg
import queue
import msvcrt
from datetime import datetime, timedelta
from collections import namedtuple
from typing import List, Optional, Dict

# ── 第三方依赖 ──
try:
    import comtypes
    from pycaw.pycaw import AudioUtilities
    from pycaw.constants import EDataFlow, DEVICE_STATE
    from pycaw.callbacks import MMNotificationClient
except ImportError:
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        0,
        "缺少必需的 Python 库。\n\n请以管理员身份运行:\n  pip install pycaw comtypes",
        "VolumeLocker - 错误",
        0x10,
    )
    sys.exit(1)

# 系统托盘 (可选依赖)
try:
    import pystray
    from PIL import Image, ImageDraw
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False
    print("[Tray] pystray/Pillow 未安装，系统托盘功能不可用")

# ── 限幅算法(纯逻辑,无 Windows 依赖) ──
#   loudness_limiter : 响度限幅的控制律(输出响度域,本程序的主模式)
#   volume_limiter   : 仅提供 VolumeScale(百分比<->dB 查表)与 peak_to_dbfs
try:
    from comtypes import CLSCTX_ALL
    from loudness_limiter import (
        CEILING_MAX_DBFS,
        CEILING_MIN_DBFS,
        DEFAULT_CEILING_DBFS,
        DEFAULT_HOLD_SECONDS,
        DEFAULT_RELEASE_DB_PER_S,
        LoudnessConfig,
        LoudnessLimiter,
    )
    from volume_limiter import VolumeScale, peak_to_dbfs
    LIMITER_AVAILABLE = True
except ImportError as _e:
    LIMITER_AVAILABLE = False
    print(f"[Limiter] 限幅功能不可用: {_e}")

# ── 外观层(纯 UI,不依赖音频库) ──
#   theme    : DPI 感知 / 配色 / 字体 / ttk 样式 / 深浅主题 / 深色标题栏
#   widgets  : Canvas 自绘的电平表、状态药丸、折叠标题条
from theme import (  # noqa: E402
    APPEARANCE_CHOICES,
    APPEARANCE_LABELS,
    APPEARANCE_SYSTEM,
    TTKBOOTSTRAP,
    TTKBOOTSTRAP_VERSION,
    ThemeManager,
    enable_dpi_awareness,
)
from theme import ui  # noqa: E402  (ttkbootstrap 可选:装了就是它,没装是 ttk 替身)
from widgets import LevelMeter, MiniBar, SectionHeader, StatusPill  # noqa: E402

# DPI 感知**必须在创建任何 Tk 窗口之前**声明。实测本机屏幕 125% 缩放:不声明的
# 话 Windows 会把整个窗口按 125% 位图拉伸,字和线条全是糊的。
enable_dpi_awareness()

# ── 完整 vtable 的 IAudioMeterInformation ──
# pycaw 自带的 IAudioMeterInformation 定义不完整(缺 GetMeteringChannelCount
# 等方法),而且新版 AudioDevice 根本没有 AudioMeterInformation 属性,
# 所以必须自己声明并用 IMMDevice::Activate 单独取。
if LIMITER_AVAILABLE:
    try:
        from comtypes import COMMETHOD, GUID, HRESULT
        from ctypes import POINTER, c_float, c_uint
        import comtypes as _comtypes

        class IAudioMeterInformationFull(_comtypes.IUnknown):
            _iid_ = GUID("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")
            _methods_ = [
                COMMETHOD([], HRESULT, "GetPeakValue",
                          (["out"], POINTER(c_float), "pfPeak")),
                COMMETHOD([], HRESULT, "GetMeteringChannelCount",
                          (["out"], POINTER(c_uint), "pnChannelCount")),
                COMMETHOD([], HRESULT, "GetChannelsPeakValues",
                          (["in"], c_uint, "u32ChannelCount"),
                          (["out"], POINTER(c_float), "afPeakValues")),
                COMMETHOD([], HRESULT, "QueryHardwareSupport",
                          (["out"], POINTER(c_uint), "pdwHardwareSupportMask")),
            ]
        METER_AVAILABLE = True
    except Exception as _e:
        METER_AVAILABLE = False
        print(f"[Limiter] IAudioMeterInformation 声明失败: {_e}")
else:
    METER_AVAILABLE = False

# ══════════════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════════════
APP_NAME = "VolumeLocker"
APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
# 开机自启时加在命令行后面的标志:见到它就**只进托盘、不弹窗口**。
# 用户双击 exe / 双击 bat 时没有这个参数,所以照常显示界面 —— 一个标志位
# 就把"被系统自启拉起"和"用户主动打开"分开了。
AUTOSTART_FLAG = "--tray"
POLL_INTERVAL = 0.20
APP_VERSION = "2.6.0"
DEVICE_REFRESH_MS = 5000   # 设备列表刷新间隔 (DeviceWatcher 负责实时通知)
CACHE_TTL = 10.0           # 设备缓存有效期 (秒)

# 窗口图标与托盘图标**必须是同一个文件** —— 这是"任务栏图标和托盘图标一致"
# 的唯一保证,所以全程序只有这一个 ICO_PATH,两处都读它。
# 该文件由 tools/make_icon.py 从原图生成。注意:用户原先给的
# `dist\VolumeControl.ico` **其实是一张 PNG**(只改了扩展名),而
# `root.iconbitmap()` 与 PyInstaller 的 icon= 都只吃真 ICO —— 所以必须由
# 原图重新生成一份多尺寸的(托盘 16×16 到资源管理器 256×256 各一档)。
if getattr(sys, "frozen", False):
    # onefile 解包到 sys._MEIPASS;onedir(或把 ico 放在 exe 旁边)也兜一下
    ICO_PATH = os.path.join(
        getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable))),
        "icon.ico")
else:
    ICO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")

# ══════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════
DeviceInfo = namedtuple("DeviceInfo", ["id", "friendly_name", "state"])

DEFAULT_DEVICE_CONFIG = {
    "friendly_name": "",
    # ── 模式 ──
    # "limit" = 响度限幅(主模式,仿 Sound Lock);"lock" = 音量锁定(旧行为)
    "mode": "limit",
    "enabled": False,          # 是否启用了该设备的限制(任一种模式)
    # ── 响度限幅 ──
    # ceiling_dbfs:输出响度上限,0 dBFS = 数字满刻度。
    #   信号峰值在 -10 dBFS 左右(对白),爆炸/高潮接近 0 dBFS。
    "ceiling_dbfs": -6.0,
    "hold_seconds": DEFAULT_HOLD_SECONDS,          # 压制后保持
    "release_db_per_s": DEFAULT_RELEASE_DB_PER_S,  # 回升速率(慢,防泵动)
    # 对下发音量做低通(非对称:压制方向不受影响),消除音量细碎抖动
    "volume_filter_seconds": 0.05,
    # 用户期望的音量(压制的起点),百分比形式,与 Windows 滑块一致
    "base_volume": 50,
    # ── 音量锁定(旧行为) ──
    "locked": False,
    "target_volume": 50,
    # ── 兼容旧的 v3 字段(读到就迁移到 ceiling_dbfs) ──
    "limiter_enabled": False,
    "limiter_db": 0.0,
    "last_seen": "",
}


# ══════════════════════════════════════════════════════════════════
# DeviceLimiter — 单设备控制环(COM 指针不得跨线程,故由控制线程独占创建)
# ══════════════════════════════════════════════════════════════════
# 两种互斥模式(它们抢同一个音量标量,同时开必然互相打架,所以只能二选一):
#   MODE_LIMIT  响度限幅 —— 盯住输出响度,超上限才压,安静时不动(仿 Sound Lock)
#   MODE_LOCK   音量锁定 —— 把音量钉在某个值上,谁来改都顶回去(旧行为)
MODE_LIMIT = "limit"
MODE_LOCK = "lock"


class DeviceLimiter:
    """为一个端点维护"峰值表 -> 控制律 -> 按 dB 写音量"的控制环。

    实测得到的硬约束(全部来自本机验证,不是推测):

    1. 必须用 IMMDevice::Activate 单独取 IAudioMeterInformation。
       pycaw 新版 AudioDevice 没有 AudioMeterInformation 属性;
       自带的接口声明也缺方法。
    2. 峰值表读的是**音量衰减之前**的信号。所以压完音量后表值不变,
       绝不能靠回读表值来判断"我有没有生效"——那正是 Sound Lock
       状态机跑飞、超阈值自动解锁的成因。
    3. 音量写入是异步的(蓝牙 AVRCP):写完立刻读会拿到旧值,连发写入
       还会出现非单调读数。所以只写不验,并且写入必须节流。
    4. COM 指针**不能跨线程使用**(实测跨线程调用直接 access violation),
       所以本对象的 meter/volume 指针必须在同一个线程里创建和使用。

    轻量化:每拍只做一次 GetPeakValue + 少量算术,静音时直接返回不写;
    写入按"变化 >=0.1 dB 且间隔 >=50ms"节流,减少无谓的 COM 调用。
    """

    POLL_SECONDS = 0.008       # 控制环节拍
    MIN_WRITE_DELTA_DB = 0.10  # 变化小于这个 dB 不写
    # 两次写入的最小间隔。这是攻击端延迟里最大的一段:
    #   真实声音骤起 -> 峰值表刷新(~10ms)-> 节拍(0~8ms)-> 节流(0~N ms)-> 设备生效
    # 原来取 50ms(当初为了避开蓝牙 AVRCP 写爆),实测单次写入仅约 198µs
    # (理论 5000 次/秒),收紧到 10ms 只用到 2% 容量。
    MIN_WRITE_INTERVAL = 0.010
    # 输出音量的一阶低通时间常数(秒)。
    # 限幅是"拉低基础音量"实现的,音量本身一直在动。若让控制值原样下发,
    # 单拍就会跳 0.1 dB 量级、峰峰摆动 2.08 dB(1Hz 起伏素材,默认释放),
    # 听感是"一炸一炸"。加了低通之后摆动降到 0.55 dB(实测),而
    # **压制反应时间不变** —— 因为滤波是**非对称**的:向下(压制)不过滤,
    # 只过滤向上(回升),所以瞬态仍能一拍内压住,而回升不会跳着往上蹦。
    VOLUME_FILTER_SECONDS = 0.05
    # 界面滑条范围与步进。上限为什么是 0.5:
    #   泵动(tau=0)2.08 -> 0.90(0.4) -> 0.55(0.8),收益递减;
    #   而恢复时间从 1.0s(0)涨到 1.7s(0.4)、2.6s(0.8)。
    #   0..0.5 覆盖了"有用且几乎不付代价"的那一段,再大只是在磨最后一点抖动。
    # ⚠️ 滤波**不再**影响释放速率(见 step() 里的长注释):它只磨平"写出去的值"。
    FILTER_MIN_S = 0.0
    FILTER_MAX_S = 0.5
    FILTER_STEP_S = 0.01
    SILENCE_PEAK = 1e-5        # 低于此值视为静音,跳过所有写入

    @classmethod
    def clamp_filter_seconds(cls, seconds) -> float:
        """把任意来源的滤波常数夹进滑条范围,并归到步进上。

        归整是为了不再往配置里写 0.011037593818985 这种拖拽残渣
        (旧版滑条没有分辨率,拖出来的就是这么长的浮点)。
        """
        try:
            v = float(seconds)
        except (TypeError, ValueError):
            return cls.VOLUME_FILTER_SECONDS
        if v <= cls.FILTER_MIN_S:
            return cls.FILTER_MIN_S
        if v >= cls.FILTER_MAX_S:
            return cls.FILTER_MAX_S
        step = cls.FILTER_STEP_S
        return round(round(v / step) * step, 4)

    def __init__(self, comtypes_module, meter_cls, limiter_cls, limiter_cfg):
        self._comtypes = comtypes_module
        self._meter_cls = meter_cls
        self._limiter_cls = limiter_cls
        self._limiter_cfg = limiter_cfg          # LoudnessConfig

        self.device_id: Optional[str] = None
        self.mode = MODE_LIMIT
        self.scale = VolumeScale()

        self._volume = None
        self._meter = None
        self._lim = None
        self._last_written = None
        self._commanded_db = None      # 限幅器原始请求
        self._sent_db = None           # 滤波后实际下发的音量(控制环的反馈量)
        self.volume_filter_seconds = self.VOLUME_FILTER_SECONDS
        self._last_write_at = 0.0
        # 内部单调时钟基准:所有时间戳都从这里派生,保证只有一套基准
        self._t0 = time.perf_counter()

        # 配置(由主轮询线程按 GUI 写入)
        self.base_volume_db = 0.0                # 用户期望的音量(压制的起点)
        self.lock_target_db = 0.0                # MODE_LOCK 的目标
        self._lock_target_pending = None         # GUI 改过目标后待应用一次

        # 仅供 UI 读取(写入者=控制线程,读取者=GUI;标量读写原子)
        # ⚠️ 这几个**必须在 __init__ 里就建好**:界面刷新是无条件读它们的,
        #    而只有"限幅分支"会更新它们 —— 锁定模式下永远不更新。
        #    少一个就是 AttributeError,而界面刷新一旦抛异常,
        #    旧代码会把 polling_active 置 False → 轮询线程与控制环线程双双退出。
        self.signal_dbfs = -120.0
        self.output_dbfs = -120.0
        self.attenuation_db = 0.0
        self.volume_db = 0.0
        self.limiting = False
        self.error: Optional[str] = None

    def _clock(self) -> float:
        """本对象内部的单调时钟(所有时间戳都必须从这里派生,只有一套基准)。

        ⚠️ **必须放在 __init__ 之外。** 它曾经被插在 __init__ 中间,`return`
        之后那一整段初始化(base_volume_db / output_dbfs / attenuation_db …)
        全成了**死代码**。后果不是立刻崩,而是:
        启动即"音量锁定"时没跑过限幅分支 → output_dbfs/attenuation_db 从未被
        创建 → 界面第一次刷新读它就抛异常 → 整个音频控制停摆。
        """
        return time.perf_counter() - self._t0

    # ── 必须在控制线程内调用 ──
    def attach(self, device_obj, device_id: str) -> bool:
        """在**控制线程内**绑定设备接口。每次换设备都要重新绑定。"""
        self.device_id = device_id
        self.error = None
        try:
            ep = device_obj.EndpointVolume
            vmin, vmax, vinc = ep.GetVolumeRange()
            self.scale = VolumeScale(min_db=vmin, max_db=vmax, increment_db=vinc)
            self._volume = ep
            if self.base_volume_db < vmin:
                self.base_volume_db = vmin
            if self.base_volume_db > vmax:
                self.base_volume_db = vmax

            raw = device_obj._dev.Activate(self._meter_cls._iid_, CLSCTX_ALL, None)
            self._meter = raw.QueryInterface(self._meter_cls)

            self._lim = self._limiter_cls(self._limiter_cfg,
                                          base_volume_db=self.base_volume_db)
            self._last_written = None
            return True
        except Exception as e:  # noqa: BLE001
            self.error = f"绑定失败: {e}"
            self._volume = None
            self._meter = None
            self._lim = None
            return False

    @property
    def ready(self) -> bool:
        return self._meter is not None and self._volume is not None

    # ── 配置(setter 由主轮询线程调用) ──
    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def set_ceiling_dbfs(self, dbfs: float) -> None:
        if self._lim is not None:
            self._lim.set_ceiling_dbfs(dbfs)

    def set_base_volume_db(self, db: float) -> None:
        self.base_volume_db = db
        if self._lim is not None:
            self._lim.set_base_volume_db(db)

    def set_lock_target_db(self, db: float) -> None:
        self.lock_target_db = db
        self._lock_target_pending = db

    # ── 控制环 ──
    def _write(self, target_db: float, now: float, force: bool = False) -> None:
        """按 dB 写音量(节流)。**只写不验** —— 蓝牙写完立刻读会拿到旧值。

        目标值先夹到**端点自己的音量范围**内:写超出范围的值,设备是**拒绝**
        (实测 COMError E_INVALIDARG)而不是夹住 —— 那样这一拍就等于没写。
        上限滑条最深只能到 -60,正常情况下到不了这里;这是最后一层保险。
        """
        lo, hi = self.scale.min_db, self.scale.max_db
        if target_db < lo:
            target_db = lo
        elif target_db > hi:
            target_db = hi
        last = self._last_written
        if not force and last is not None:
            if abs(target_db - last) < self.MIN_WRITE_DELTA_DB:
                return
            if (now - self._last_write_at) < self.MIN_WRITE_INTERVAL:
                return
        try:
            self._volume.SetMasterVolumeLevel(target_db, None)
            self._last_written = target_db
            self._last_write_at = now
        except Exception as e:  # noqa: BLE001
            self.error = f"音量写入失败: {e}"

    def _read_peak(self) -> float:
        """读一次端点峰值表(音量衰减**之前**的信号)。

        单独抽成一个方法是为了让离线测试能替换掉硬件访问 ——
        生产路径就是一次 COM 调用。
        """
        return self._meter.GetPeakValue()

    def step(self, now: float = None) -> None:
        """跑一拍控制环。必须由绑定时所在的同一线程调用。

        now 省略时用本对象内部的单调时钟 —— 时间基准必须统一。
        踩过的坑:apply_now() 曾传 perf_counter() 的绝对值(几万秒),
        而控制环传从 0 起算的相对值,导致 hold_until 被设成一个大数,
        控制环的时间永远追不上它,衰减**永不释放**。
        """
        if now is None:
            now = self._clock()
        if not self.ready:
            return
        try:
            peak = self._read_peak()
        except Exception as e:  # noqa: BLE001
            self.error = f"峰值读取失败: {e}"
            return

        if self.mode == MODE_LOCK:
            self._write(self.lock_target_db, now)
            self.signal_dbfs = peak_to_dbfs(peak)
            return

        # ── 响度限幅 ──
        # 静音时也要走同一段逻辑(把峰值当 0 喂进去),否则保持期与释放
        # 根本走不到 —— 踩过的坑:之前在静音分支直接 return 并清零衰减,
        # 素材一停就"秒放",完全失去 hold 的意义。
        if peak is None or peak <= self.SILENCE_PEAK:
            peak = 0.0

        if self._lim is None:
            return
        # 喂给限幅器的是"**实际下发**的音量",不是"上次真正写出去的值",
        # 也不是限幅器的原始请求 —— 滤波发生在控制环之外,所以控制环必须
        # 用它自己下发的值来做反馈。踩过的坑:用"上次真正写出去的值"时,
        # 写入被节流限住,控制环会把同一个陈旧值反复喂回去,释放量每拍都被
        # 重新算成同一个数,音量永远爬不回来(实测衰减卡在 2.46 再也不动)。
        # 这里有两个**必须分开**的量(踩过的坑,见下面的长注释):
        #   反馈量(喂给控制律)= 限幅器上一拍的**命令值**;
        #   滤波基准(平滑的对象)= 上一次**真正下发**的值。
        cur_volume = self._commanded_db
        if cur_volume is None:
            cur_volume = self._sent_db
        if cur_volume is None:
            cur_volume = self.base_volume_db
        last_sent = self._sent_db
        if last_sent is None:
            last_sent = cur_volume
        target = self._lim.update(peak, cur_volume, now)

        # ── 输出音量滤波(非对称:压制不过滤,只过滤回升) ──
        # 限幅是"拉低基础音量"实现的,音量本身一直在动;原样下发时单拍会跳
        # 0.1 dB 量级、峰峰摆动 1.29 dB,听感"一炸一炸"。
        # 滤波后摆动降到 0.06 dB 量级,而**瞬态反应不变** —— 因为向下的路径
        # 仍然直接放行,只有回升被磨平。
        #
        # ⚠️ 反馈量**不能**用滤波后的下发值。释放是"在当前值上加 release*dt",
        #    若当前值本身就是被滤波压着的值,滤波又只放行其中 a = dt/(tau+dt),
        #    等效释放速率就被乘了 a:
        #        tau=0.00 -> 1.5 dB/s(恢复 3.5s)
        #        tau=0.02 -> 0.43 dB/s(恢复 12s)
        #        tau=0.05 -> 0.21 dB/s(恢复 25s)  ← 这就是滑块**默认值**
        #        tau=0.10 -> 0.11 dB/s(30s 后还差 2.6 dB,听感"爆炸之后回不来")
        #    改用命令值后,释放速率不再受滤波影响(各 tau 恢复时间都回到 ~4s),
        #    滤波只负责把"写出去的东西"磨平 —— 这才是这个滑块该有的语义。
        #    也不能退回用"上次真正写出去的值":那会被写入节流卡住变陈旧,
        #    释放量每拍算成同一个数,音量永远爬不回来。
        if target >= last_sent:
            # 向上:一阶低通
            a = self.POLL_SECONDS / (self.volume_filter_seconds + self.POLL_SECONDS) \
                if self.volume_filter_seconds > 0 else 1.0
            sent = last_sent + (target - last_sent) * a
            if sent > target:
                sent = target
        else:
            sent = target            # 向下(压制):立刻生效,绝不延迟
        # 不变量:sent <= target 恒成立(向上朝 target 靠近并夹住,向下等于 target)。
        # "写出去的值"永不高于控制律允许的上限 => 输出不可能超过 ceiling,
        # 滤波只会让声音更安静、不会更响。

        self._sent_db = sent
        self._commanded_db = target
        r = self._lim.reading
        self.signal_dbfs = r.signal_dbfs
        self.output_dbfs = r.output_dbfs
        self.attenuation_db = r.attenuation_db
        self.volume_db = sent
        self.limiting = r.limiting
        self._write(sent, now)

    def apply_now(self) -> None:
        """启用瞬间立即生效一次(不等轮询)。"""
        if not self.ready:
            return
        now = self._clock()
        if self.mode == MODE_LOCK:
            self._lock_target_pending = None
            self._write(self.lock_target_db, now, force=True)
            return
        # 限幅:先按当前信号跑一拍,再强制写一次,
        # 避免"刚开始那几拍声音还很大"
        self.step(now)
        if self._sent_db is not None:
            self._write(self._sent_db, now, force=True)

    def detach(self) -> None:
        self._meter = None
        self._volume = None
        self._lim = None
        self._last_written = None
        self._commanded_db = None
        self._sent_db = None

# ══════════════════════════════════════════════════════════════════
# AudioController — 多设备音频管理
# ══════════════════════════════════════════════════════════════════
class AudioController:
    """封装 Windows Core Audio API 的多设备操作，线程安全。
    v2.0.2: 增加设备缓存层 + COM 自动恢复。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._com_init = False
        self._enumerator = None
        self._device_cache: Dict[str, any] = {}
        self._cache_time = 0.0
        self._com_fail_count = 0

    def _ensure_init(self):
        if self._com_init:
            return True
        try:
            comtypes.CoInitializeEx(0)
            self._com_init = True
            self._enumerator = AudioUtilities.GetDeviceEnumerator()
            self._com_fail_count = 0
            return True
        except Exception as e:
            print(f"[Audio] COM 初始化失败: {e}")
            return False

    def _handle_com_error(self):
        """COM 调用失败时调用：标记 COM 为过期，下次自动重新初始化。"""
        self._com_fail_count += 1
        if self._com_fail_count >= 2:
            # 连续失败，强制重置 COM 状态
            self._com_init = False
            self._enumerator = None
            self._device_cache.clear()
            self._cache_time = 0.0

    # ── 缓存管理 ──
    def _is_cache_fresh(self) -> bool:
        return (time.time() - self._cache_time) < CACHE_TTL

    def invalidate_cache(self):
        """强制刷新缓存（设备变更时调用）。"""
        with self._lock:
            # 清除端点缓存
            for d in self._device_cache.values():
                if hasattr(d, '_cached_ep'):
                    delattr(d, '_cached_ep')
            self._cache_time = 0.0

    def _refresh_cache(self):
        """从系统枚举所有活跃设备并更新缓存。COM 异常时自动重试。"""
        with self._lock:
            if self._is_cache_fresh():
                return
            if not self._ensure_init():
                return
            try:
                raw_list = AudioUtilities.GetAllDevices(
                    EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value
                )
                new_cache = {}
                for d in raw_list:
                    try:
                        _ = d.EndpointVolume.GetMasterVolumeLevelScalar()
                        new_cache[d.id] = d
                    except Exception:
                        continue
                self._device_cache = new_cache
                self._cache_time = time.time()
                self._com_fail_count = 0
            except Exception as e:
                print(f"[Audio] 缓存刷新失败: {e}")
                self._handle_com_error()

    # ── 设备枚举 ──
    def get_all_devices(self, active_only: bool = True) -> List[DeviceInfo]:
        """返回所有活跃渲染设备的 DeviceInfo 列表 (从缓存读取)。"""
        if not self._is_cache_fresh():
            self._refresh_cache()
        with self._lock:
            return [
                DeviceInfo(id=d.id, friendly_name=d.FriendlyName, state=d.state)
                for d in self._device_cache.values()
            ]

    def get_default_device_id(self) -> Optional[str]:
        """获取当前 Windows 默认播放设备 ID。COM 异常时自动恢复。"""
        with self._lock:
            if not self._ensure_init():
                return None
            try:
                device = AudioUtilities.GetSpeakers()
                self._com_fail_count = 0  # 成功则清零
                return device.id if device else None
            except Exception as e:
                print(f"[Audio] 获取默认设备失败: {e}")
                self._handle_com_error()
                return None

    # ── 单设备音量读写 ──
    def _get_active_device_obj(self, device_id: str):
        """从缓存中按 ID 查找 AudioDevice 对象。"""
        if not self._is_cache_fresh():
            self._refresh_cache()
        return self._device_cache.get(device_id)

    def get_device_volume(self, device_id: str) -> int:
        """获取指定设备的音量 (0-100)。不活跃设备返回 0。"""
        try:
            device = self._get_active_device_obj(device_id)
            if device is None:
                return 0
            scalar = device.EndpointVolume.GetMasterVolumeLevelScalar()
            return int(round(scalar * 100))
        except Exception:
            return 0

    def set_device_volume(self, device_id: str, percentage: int):
        """设置指定设备的音量 (0-100)。仅对活跃设备生效。"""
        try:
            device = self._get_active_device_obj(device_id)
            if device is None:
                return
            scalar = max(0.0, min(1.0, percentage / 100.0))
            device.EndpointVolume.SetMasterVolumeLevelScalar(scalar, None)
        except Exception as e:
            print(f"[Audio] 设置音量失败 ({device_id[:30]}): {e}")

    def get_device_endpoint(self, device_id: str):
        """获取指定设备的 IAudioEndpointVolume COM 指针（缓存版）。
        用于轮询线程的热路径，避免每次都重新激活 COM 接口。"""
        device = self._get_active_device_obj(device_id)
        if device is None:
            return None
        # 在 AudioDevice 对象上缓存端点指针
        if not hasattr(device, '_cached_ep'):
            try:
                device._cached_ep = device.EndpointVolume
            except Exception:
                return None
        return device._cached_ep

    def is_device_present(self, device_id: str) -> bool:
        """检查设备是否仍在系统中。"""
        with self._lock:
            if not self._ensure_init():
                return False
            try:
                return self._enumerator.GetDevice(device_id) is not None
            except Exception:
                return False

    def get_enumerator(self):
        """获取 COM 设备枚举器 (供 DeviceWatcher 使用)。"""
        if not self._ensure_init():
            return None
        return self._enumerator

    def cleanup(self):
        with self._lock:
            try:
                if self._com_init:
                    comtypes.CoUninitialize()
                    self._com_init = False
                    self._enumerator = None
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════
# ConfigManager — 配置管理 (v2 多设备格式)
# ══════════════════════════════════════════════════════════════════
class ConfigManager:

    @staticmethod
    def load() -> dict:
        """加载配置，必要时自动迁移 v1 格式。"""
        default = {
            "version": APP_VERSION,
            "auto_start": False,
            "minimize_to_tray": True,
            "appearance": APPEARANCE_SYSTEM,   # system / light / dark
            # 模式是**全局偏好**,不是每设备一份。
            # 旧版把 mode 存在 devices[<id>] 里,后果是:换设备、或原设备掉线
            # (蓝牙耳机一断)就"忘记了"用户上次选的模式,又默认回响度限幅。
            # 现在这里存一份全局的,设备级 mode 只作为一次性迁移来源。
            "mode": MODE_LIMIT,
            "selected_device_id": "",
            "devices": {},
        }
        if not os.path.exists(CONFIG_FILE):
            return default
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "version" not in data:
                # v1 -> v2 迁移
                data = ConfigManager._migrate_v1(data)
            # 全局 mode 的迁移:**必须在下面"补默认值"之前做**,否则会被默认值
            # (响度限幅)先填上,老用户的"上次模式"就丢了。
            # 从"上次选中的设备"继承一次。
            if "mode" not in data:
                devs = data.get("devices", {}) or {}
                selected = devs.get(data.get("selected_device_id", ""), {}) or {}
                data["mode"] = selected.get("mode", MODE_LIMIT)
                if data["mode"] != MODE_LIMIT:
                    print(f"[Config] 继承上次的模式: {data['mode']}")
            # 确保所有必需字段存在
            for k, v in default.items():
                if k not in data:
                    data[k] = v
            # 旧格式设备配置 -> 当前格式(避免用户开关被静默重置 / 单位混淆)
            if ConfigManager.migrate_all_devices(data):
                ConfigManager.save(data)
                print("[Config] 已把设备配置升级为当前格式")
            return data
        except (json.JSONDecodeError, IOError) as e:
            print(f"[Config] 加载失败: {e}")
            # 备份损坏文件
            try:
                bak = CONFIG_FILE + ".bak"
                os.replace(CONFIG_FILE, bak)
            except Exception:
                pass
            return default

    @staticmethod
    def save(config: dict):
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            config["version"] = APP_VERSION
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] 保存失败: {e}")

    @staticmethod
    def get_device_config(device_id: str, config: dict) -> dict:
        """获取特定设备的配置 (自动填充默认值)。"""
        devs = config.get("devices", {})
        if device_id in devs:
            cfg = dict(DEFAULT_DEVICE_CONFIG)
            cfg.update(devs[device_id])
            return cfg
        return dict(DEFAULT_DEVICE_CONFIG)

    @staticmethod
    def set_device_config(device_id: str, field: str, value, config: dict):
        """更新设备配置的单个字段。"""
        devs = config.setdefault("devices", {})
        if device_id not in devs:
            devs[device_id] = dict(DEFAULT_DEVICE_CONFIG)
        devs[device_id][field] = value
        devs[device_id]["last_seen"] = datetime.now().isoformat()

    @staticmethod
    def cleanup_stale_devices(config: dict):
        """清理 7 天以上未见的设备条目。"""
        devs = config.get("devices", {})
        cutoff = datetime.now() - timedelta(days=7)
        stale = []
        for did, dconf in devs.items():
            try:
                ls = datetime.fromisoformat(dconf.get("last_seen", ""))
                if ls < cutoff:
                    stale.append(did)
            except (ValueError, TypeError):
                pass
        for did in stale:
            del devs[did]
            print(f"[Config] 清理陈旧设备: {did}")

    @staticmethod
    def _migrate_v1(old: dict) -> dict:
        """v1 {target_volume, auto_start} -> v2 格式。"""
        vol = old.get("target_volume", 50)
        auto = old.get("auto_start", False)
        return {
            "version": APP_VERSION,
            "auto_start": auto,
            "minimize_to_tray": True,
            "selected_device_id": "",
            "devices": {
                "__legacy__": {
                    "friendly_name": "默认设备 (迁移)",
                    "locked": False,
                    "target_volume": vol,
                    "last_seen": datetime.now().isoformat(),
                }
            },
        }

    @staticmethod
    def migrate_device_config(device_id: str, config: dict) -> bool:
        """把单个设备的旧格式配置就地升级为当前格式。返回是否发生了改动。

        要点:
          - 旧字段 limiter_enabled(布尔,表示"限幅开着")要搬到新的 enabled,
            否则升级后用户的开关会被静默重置为关。
          - 旧字段 limiter_db 的单位是**该端点的音量标尺 dB**(0 dB = 满刻度),
            与新字段 ceiling_dbfs(**dBFS 输出响度上限**)含义完全不同,
            绝不能直接搬。旧的丢弃,用新的默认上限。
          - 搬完把旧键删掉,免得下次读又混淆。
        """
        devs = config.get("devices", {})
        if device_id not in devs:
            return False
        dc = devs[device_id]
        changed = False

        if "enabled" not in dc:
            # 旧 limiter_enabled -> 新 enabled
            dc["enabled"] = bool(dc.get("limiter_enabled", False))
            changed = True
        if "mode" not in dc:
            # 旧行为只有"音量锁定";若旧 locked 为真就沿用锁定模式
            dc["mode"] = MODE_LOCK if dc.get("locked", False) else MODE_LIMIT
            changed = True
        if "base_volume" not in dc:
            dc["base_volume"] = int(dc.get("target_volume", 50))
            changed = True
        if "ceiling_dbfs" not in dc:
            dc["ceiling_dbfs"] = DEFAULT_CEILING_DBFS
            changed = True
        if "hold_seconds" not in dc:
            dc["hold_seconds"] = DEFAULT_HOLD_SECONDS
            changed = True
        if "release_db_per_s" not in dc:
            dc["release_db_per_s"] = DEFAULT_RELEASE_DB_PER_S
            changed = True
        if "volume_filter_seconds" not in dc:
            dc["volume_filter_seconds"] = DeviceLimiter.VOLUME_FILTER_SECONDS
            changed = True

        # 清掉含义不同、容易混淆的旧键
        for stale in ("limiter_db", "limiter_enabled"):
            if stale in dc:
                del dc[stale]
                changed = True
        return changed

    @staticmethod
    def migrate_all_devices(config: dict) -> bool:
        changed = False
        for did in list(config.get("devices", {}).keys()):
            if ConfigManager.migrate_device_config(did, config):
                changed = True
        return changed

    @staticmethod
    def _autostart_command() -> str:
        """开机自启要执行的命令行。

        **必须带 `--tray`**:开机自启时不能弹界面(用户明确要求"自动在后台
        开始工作"),而用户双击 exe / 双击 bat 时**没有**这个参数,所以会正常
        显示窗口 —— 一个标志位就把两种启动方式分开了。
        """
        if getattr(sys, "frozen", False):
            # 打包版: exe 自带完整环境
            return f'"{sys.executable}" {AUTOSTART_FLAG}'
        # 源码运行: 必须把「解释器 + 脚本」都写死。
        # 只写 .py 路径的话, Windows 会交给 py.exe / 文件关联去猜解释器,
        # 猜错就是弹「缺少必需的 Python 库」——本机已经踩过这个坑。
        # 用 __file__ 而不是 sys.argv[0]: 后者在 -c / stdin / 被别的
        # 脚本 import 时会变成 "-" 之类, 写进自启项就废了。
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pyw):
            pyw = sys.executable
        return f'"{pyw}" "{os.path.abspath(__file__)}" {AUTOSTART_FLAG}'

    @staticmethod
    def set_auto_start(enabled: bool):
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0,
                winreg.KEY_SET_VALUE | winreg.KEY_READ,
            )
            if enabled:
                cmd = ConfigManager._autostart_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                print(f"[AutoStart] 已写入自启命令: {cmd}")
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except WindowsError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[AutoStart] 失败: {e}")

    @staticmethod
    def ensure_auto_start_flag() -> bool:
        """给**旧版本写下的**自启项补上 `--tray`(就地自愈)。

        老版本写的是不带参数的 exe 路径,开机就会弹界面。用户不一定想到要
        重新勾一次复选框,所以启动时自己修一次。返回是否改动过。
        """
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                 winreg.KEY_READ)
            try:
                cmd, _ = winreg.QueryValueEx(key, APP_NAME)
            except WindowsError:
                winreg.CloseKey(key)
                return False            # 本来就没开自启
            winreg.CloseKey(key)
            if AUTOSTART_FLAG in (cmd or ""):
                return False
            old = cmd
            ConfigManager.set_auto_start(True)
            print(f"[AutoStart] 已给旧自启项补上后台标志: {old!r} -> "
                  f"{ConfigManager._autostart_command()!r}")
            return True
        except Exception:
            return False

    @staticmethod
    def is_auto_start_enabled() -> bool:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, APP_NAME)
                winreg.CloseKey(key)
                return True
            except WindowsError:
                winreg.CloseKey(key)
                return False
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════
# DeviceWatcher — 设备变更监听
# ══════════════════════════════════════════════════════════════════
class DeviceWatcher(MMNotificationClient):
    """监听音频设备变更事件并通过 queue 通知 GUI 线程。"""

    def __init__(self, event_queue: queue.Queue):
        super().__init__()
        self._q = event_queue
        self._registered = False

    def on_device_added(self, device_id, flow, role):
        self._q.put(("added", device_id))

    def on_device_removed(self, device_id, flow, role):
        self._q.put(("removed", device_id))

    def on_device_state_changed(self, device_id, new_state, new_device_id):
        self._q.put(("state_changed", device_id, new_state))

    def on_default_device_changed(self, flow, role, default_device_id):
        if flow == EDataFlow.eRender.value or flow == EDataFlow.eRender:
            self._q.put(("default_changed", default_device_id))

    def register(self, audio: AudioController):
        enumerator = audio.get_enumerator()
        if enumerator:
            # 先注销旧的回调（安全幂等操作）
            if self._registered:
                try:
                    enumerator.UnregisterEndpointNotificationCallback(self)
                except Exception:
                    pass
            enumerator.RegisterEndpointNotificationCallback(self)
            self._registered = True
            print("[DevWatch] 已注册设备通知")

    def health_check(self, audio: AudioController) -> bool:
        """定期健康检查：超时后强制重新注册。返回 True 表示回调可能失效。"""
        # 每 30 秒重新注册一次（COM 在睡眠后可能失效）
        enumerator = audio.get_enumerator()
        if enumerator and self._registered:
            try:
                enumerator.UnregisterEndpointNotificationCallback(self)
                enumerator.RegisterEndpointNotificationCallback(self)
                return False  # 健康
            except Exception:
                self._registered = False
                return True  # 需要恢复
        return not self._registered

    def unregister(self, audio: AudioController):
        if not self._registered:
            return
        enumerator = audio.get_enumerator()
        if enumerator:
            try:
                enumerator.UnregisterEndpointNotificationCallback(self)
            except Exception:
                pass
        self._registered = False


# ══════════════════════════════════════════════════════════════════
# SystemTrayManager — 系统托盘
# ══════════════════════════════════════════════════════════════════
class SystemTrayManager:
    def __init__(self, app):
        self.app = app
        self.icon = None
        self._tray_thread = None
        self._running = False

    def start(self):
        if not PYSTRAY_AVAILABLE:
            print("[Tray] 不可用，跳过")
            return
        self._running = True
        self._tray_thread = threading.Thread(target=self._run, daemon=True)
        self._tray_thread.start()

    def _run(self):
        image = self._load_icon()
        menu = pystray.Menu(
            pystray.MenuItem("显示设置", self._on_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._on_exit),
        )
        self.icon = pystray.Icon(APP_NAME, image, APP_NAME, menu)
        self.icon.run()

    def _load_icon(self):
        if os.path.exists(ICO_PATH):
            return Image.open(ICO_PATH)
        # 回退：创建一个简单的彩色方形图标
        img = Image.new("RGBA", (64, 64), (33, 150, 243, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([16, 20, 32, 44], fill=(255, 255, 255, 255))
        draw.polygon([(32, 20), (48, 14), (48, 50), (32, 44)], fill=(255, 255, 255, 255))
        return img

    def _on_show(self, icon, item):
        self.app.root.after(0, self.app._restore_window)

    def _on_exit(self, icon, item):
        self.app.root.after(0, self.app._full_exit)

    def stop(self):
        self._running = False
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════
# VolumeLockerApp — 主应用 (v2 多设备版)
# ══════════════════════════════════════════════════════════════════
class VolumeLockerApp:
    def __init__(self, start_hidden: bool = False):
        """start_hidden=True:只进托盘、不显示窗口(开机自启走这条路)。

        用户的要求是"开机自启时在后台自动开始工作、别弹界面",但"双击图标"
        时必须弹出界面 —— 两者靠命令行里的 `--tray` 区分(见 AUTOSTART_FLAG)。
        """
        # 托盘不可用时**绝对不能**隐藏:否则用户没有任何入口能把窗口叫出来。
        if start_hidden and not PYSTRAY_AVAILABLE:
            print("[Start] 托盘不可用,忽略 --tray,改为显示窗口")
            start_hidden = False
        self.start_hidden = start_hidden

        self.audio = AudioController()
        self.config = ConfigManager.load()

        # ── 状态变量 ──
        self.mode = self.config.get("mode", MODE_LIMIT)   # 当前模式(全局偏好)
        self.limiter_enabled = False      # 是否启用
        self.ceiling_dbfs = DEFAULT_CEILING_DBFS
        self.release_db_per_s = DEFAULT_RELEASE_DB_PER_S
        self.hold_seconds = DEFAULT_HOLD_SECONDS
        self.volume_filter_seconds = DeviceLimiter.VOLUME_FILTER_SECONDS
        self.base_volume = 50             # 基础音量(百分比)
        # 兼容旧字段
        self.locked = False
        self.target_volume = 50
        self.polling_active = True
        self._suppress_slider = False
        self._suppress_ceiling = False
        self._suppress_release = False
        self._suppress_hold = False
        self._suppress_smooth = False
        self._suppress_combo = False
        self._exit_event = threading.Event()

        # ── 设备状态 ──
        self._device_list: List[DeviceInfo] = []
        self._device_map: Dict[str, DeviceInfo] = {}  # id -> DeviceInfo
        self._current_default_id: Optional[str] = None
        self._selected_device_id: Optional[str] = None

        # ── 设备事件队列 ──
        self._device_events = queue.Queue()
        self._last_refresh_time = 0.0  # 防抖时间戳
        self._topmost_until = 0.0      # 窗口临时置顶截止时间

        # ── 限幅器(控制环由 _poll_loop 里的独立线程以 8ms 节拍驱动) ──
        self._limiter = None
        self._limiter_device_id = None

        # ── 单实例锁 ──
        self._instance_lock = None
        if not self._acquire_single_instance():
            # 已有实例在运行，尝试恢复并退出
            self.audio = None
            self._notify_existing_instance()
            sys.exit(0)

        # ── GUI ──
        self.root = tk.Tk()
        # 自启模式:必须在**建控件之前**就藏起来,否则窗口会先闪一下再消失。
        # 之后由托盘菜单"显示设置"或第二个实例的信号把它叫出来。
        if self.start_hidden:
            self.root.withdraw()
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.resizable(True, True)

        # 外观必须在建控件之前建好:控件创建时就要从调色板取色、按 DPI 取尺寸
        self.theme = ThemeManager(
            self.root, appearance=self.config.get("appearance", APPEARANCE_SYSTEM))
        self.root.minsize(self.theme.px(430), self.theme.px(430))
        self._center_window(self.theme.px(600), self.theme.px(640))

        if os.path.exists(ICO_PATH):
            try:
                self.root.iconbitmap(ICO_PATH)
                # 打出来:冻结版没有控制台,这行日志是"图标到底用没用上"的
                # 唯一客观证据(用户报"图标不对"时也靠它定位)。
                print(f"[Icon] 窗口图标与托盘图标共用: {ICO_PATH}")
            except Exception as e:
                print(f"[Icon] 窗口图标设置失败({e}),托盘将用内置兜底图标")
        else:
            print(f"[Icon] 找不到图标文件: {ICO_PATH}(托盘将用内置兜底图标)")

        self._build_gui()
        self._init_devices()

        # ── 恢复设置 ──
        self.auto_start_var.set(ConfigManager.is_auto_start_enabled())
        self.minimize_tray_var.set(self.config.get("minimize_to_tray", True))
        self.appearance_var.set(APPEARANCE_LABELS.get(
            self.theme.appearance, APPEARANCE_LABELS[APPEARANCE_SYSTEM]))

        # ── 系统托盘 ──
        self.tray = SystemTrayManager(self)
        self.tray.start()

        # ── 设备变更监听 ──
        self._device_watcher = DeviceWatcher(self._device_events)

        # ── 后台线程 ──
        self._start_polling()

        # ── 定时刷新 ──
        self.root.after(1000, self._update_ui)
        self.root.after(DEVICE_REFRESH_MS, self._refresh_devices)
        self.root.after(200, self._process_device_events)
        self.root.after(30000, self._device_watcher_health_check)  # 每30秒重新注册

        # ── 关闭 ──
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        # 启动时临时置顶，确保用户能看到窗口
        self.root.attributes('-topmost', True)
        self._topmost_until = time.time() + 3.0
        self.root.after(3000, self._release_topmost)

    # ── DeviceWatcher 健康检查 ──
    def _device_watcher_health_check(self):
        """每 30 秒重新注册 DeviceWatcher（睡眠唤醒后 COM 可能过期）。"""
        if not self.polling_active:
            return
        try:
            if self._device_watcher and self.audio:
                self._device_watcher.health_check(self.audio)
                # 同时触发一次设备列表刷新（确保睡眠后 UI 不卡在旧状态）
                self._refresh_devices()
        except Exception:
            pass
        self.root.after(30000, self._device_watcher_health_check)

    # ── 单实例检测 ──
    def _acquire_single_instance(self) -> bool:
        os.makedirs(APP_DIR, exist_ok=True)
        lock_path = os.path.join(APP_DIR, ".instance.lock")
        try:
            self._instance_lock = open(lock_path, "w")
            msvcrt.locking(self._instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (IOError, OSError):
            return False

    def _notify_existing_instance(self):
        """通知已有实例恢复窗口。"""
        signal_path = os.path.join(APP_DIR, ".restore_signal")
        try:
            with open(signal_path, "w") as f:
                f.write("restore")
        except Exception:
            pass

    # ── GUI 构建 ──
    def _center_window(self, w, h):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _build_gui(self):
        th = self.theme
        px = th.px

        container = ui.Frame(self.root)
        container.pack(fill=tk.BOTH, expand=True)

        self.scrollbar = ui.Scrollbar(container, orient=tk.VERTICAL)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(
            container, highlightthickness=0, bd=0, relief=tk.FLAT,
            background=th.color("window_bg"),
            yscrollcommand=self.scrollbar.set,
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.canvas.yview)

        self.inner = ui.Frame(self.canvas, padding=px(16))
        self.inner_window = self.canvas.create_window(
            (0, 0), window=self.inner, anchor=tk.NW, tags="inner"
        )

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

        # ========== 内容区 ==========

        # ── 页眉:标题 + 副标题 + 状态药丸 ──
        header = ui.Frame(self.inner)
        header.pack(fill=tk.X, pady=(0, px(12)))

        titles = ui.Frame(header)
        titles.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ui.Label(titles, text=APP_NAME, style="Title.TLabel").pack(anchor=tk.W)
        ui.Label(titles, text=f"v{APP_VERSION} · 响度限幅 / 音量锁定,按设备独立配置",
                 style="Sub.TLabel").pack(anchor=tk.W, pady=(px(1), 0))

        self.status_pill = StatusPill(header, th, "未启用", "muted")
        self.status_pill.pack(side=tk.RIGHT, anchor=tk.N)

        # ── 设备选择(卡片) ──
        dev_card = ui.Frame(self.inner, style="Card.TFrame", padding=px(12))
        dev_card.pack(fill=tk.X, pady=(0, px(10)))
        ui.Label(dev_card, text="输出设备", style="Card.TLabel",
                 font=th.font(9, "bold")).pack(anchor=tk.W)

        dev_row = ui.Frame(dev_card, style="Card.TFrame")
        dev_row.pack(fill=tk.X, pady=(px(6), 0))

        self.device_combo_var = tk.StringVar()
        self.device_combo = ui.Combobox(
            dev_row, textvariable=self.device_combo_var, state="readonly",
        )
        self.device_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.device_combo.bind("<<ComboboxSelected>>", self._on_device_select)

        self.device_status_label = ui.Label(
            dev_row, text="", style="CardHint.TLabel",
        )
        self.device_status_label.pack(side=tk.LEFT, padx=(px(8), 0))

        # ── 模式与启用(卡片) ──
        # 两种模式互斥:都抢同一个音量标量,同时开必然打架
        mode_card = ui.Frame(self.inner, style="Card.TFrame", padding=px(12))
        mode_card.pack(fill=tk.X, pady=(0, px(10)))

        mode_head = ui.Frame(mode_card, style="Card.TFrame")
        mode_head.pack(fill=tk.X)
        ui.Label(mode_head, text="模式", style="Card.TLabel",
                 font=th.font(9, "bold")).pack(side=tk.LEFT)

        self.enable_var = tk.BooleanVar(value=False)
        self.enable_cb = ui.Checkbutton(
            mode_head, text="启用", variable=self.enable_var,
            command=self._on_enable_toggle, style="Card.TCheckbutton",
        )
        self.enable_cb.pack(side=tk.RIGHT)

        mode_row = ui.Frame(mode_card, style="Card.TFrame")
        mode_row.pack(fill=tk.X, pady=(px(6), 0))

        self.mode_var = tk.StringVar(value=getattr(self, "mode", MODE_LIMIT))
        ui.Radiobutton(
            mode_row, text="响度限幅", value=MODE_LIMIT,
            variable=self.mode_var, command=self._on_mode_change,
            bootstyle="@card",
        ).pack(side=tk.LEFT)
        ui.Radiobutton(
            mode_row, text="音量锁定", value=MODE_LOCK,
            variable=self.mode_var, command=self._on_mode_change,
            bootstyle="@card",
        ).pack(side=tk.LEFT, padx=(px(14), 0))

        # ── 响度上限(dBFS) —— 限幅模式的核心旋钮 ──
        # 0 dBFS = 数字满刻度。信号越响越接近 0。
        #   对白通常在 -20 ~ -30 dBFS,电影爆炸/高潮接近 0 dBFS。
        self.ceiling_frame = ui.Frame(self.inner, style="Card.TFrame", padding=px(12))
        self.ceiling_frame.pack(fill=tk.X, pady=(0, px(10)))

        ceil_head = ui.Frame(self.ceiling_frame, style="Card.TFrame")
        ceil_head.pack(fill=tk.X)
        ui.Label(ceil_head, text="响度上限", style="Card.TLabel",
                 font=th.font(9, "bold")).pack(side=tk.LEFT)

        self.ceiling_label = ui.Label(
            ceil_head, text=f"{int(DEFAULT_CEILING_DBFS)} dBFS",
            style="CardAccent.TLabel", font=th.font(12, "bold"),
        )
        self.ceiling_label.pack(side=tk.RIGHT)

        self.ceiling_var = tk.IntVar(value=int(DEFAULT_CEILING_DBFS))
        self.ceiling_scale = ui.Scale(
            self.ceiling_frame, from_=int(CEILING_MIN_DBFS), to=int(CEILING_MAX_DBFS),
            orient=tk.HORIZONTAL, variable=self.ceiling_var,
            command=self._on_ceiling_change, bootstyle="@card",
        )
        self.ceiling_scale.pack(fill=tk.X, pady=(px(4), 0))

        self.ceiling_hint = ui.Label(
            self.ceiling_frame, style="CardHint.TLabel", justify=tk.LEFT,
            text="输出响度(= 信号 + 当前音量)超过它才压低。\n"
                 "它是「输出」上限(不是素材峰值),大约比素材峰值低一个基础音量的量。",
        )
        self.ceiling_hint.pack(anchor=tk.W, pady=(px(2), 0))

        # 上限高于"基础音量对应的 dB"时永远不会触发(输出根本到不了那么高)。
        # 修好上限公式之后这个坑变得容易踩,所以直接提示出来。
        self.ceiling_warn = ui.Label(self.ceiling_frame, style="CardWarn.TLabel",
                                     justify=tk.LEFT)

        # ── 基础音量(音量锁定模式的目标 / 限幅模式压制的起点) ──
        # 释放速率 / 保持时间 / 音量平滑 三个滑条已移到底部的「高级设置」折叠面板。
        bv_f = ui.Frame(self.inner, style="Card.TFrame", padding=px(12))
        bv_f.pack(fill=tk.X, pady=(0, px(10)))
        self._bv_card = bv_f          # 重新显示"响度上限"卡片时要插回它前面

        bv_head = ui.Frame(bv_f, style="Card.TFrame")
        bv_head.pack(fill=tk.X)
        self.base_label = ui.Label(bv_head, text="基础音量", style="Card.TLabel",
                                   font=th.font(9, "bold"))
        self.base_label.pack(side=tk.LEFT)

        self.vol_pct_label = ui.Label(
            bv_head, text="50%", style="CardValue.TLabel", font=th.font(12, "bold"),
        )
        self.vol_pct_label.pack(side=tk.RIGHT)

        # 基础音量对应的端点 dB(仅显示)。属性名是历史遗留,别被名字骗了。
        self.ceiling_db_label = ui.Label(
            bv_head, text="-- dB", style="CardAccent.TLabel",
        )
        self.ceiling_db_label.pack(side=tk.RIGHT, padx=(0, px(10)))

        self.volume_var = tk.IntVar(value=50)
        self.slider = ui.Scale(
            bv_f, from_=0, to=100, orient=tk.HORIZONTAL,
            variable=self.volume_var, command=self._on_slider_change,
            bootstyle="@card",
        )
        self.slider.pack(fill=tk.X, pady=(px(4), 0))

        self.base_hint = ui.Label(
            bv_f, style="CardHint.TLabel",
            text="音量锁定:把音量钉在这个值。响度限幅:不超上限时的音量(压制从这里往下走)。",
        )
        self.base_hint.pack(anchor=tk.W, pady=(px(2), 0))

        # ── 当前设备音量(系统实际值,只读) ──
        cur_f = ui.Frame(bv_f, style="Card.TFrame")
        cur_f.pack(fill=tk.X, pady=(px(10), 0))

        self.current_vol_label = ui.Label(
            cur_f, text="当前设备音量 --%", style="CardMono.TLabel",
        )
        self.current_vol_label.pack(side=tk.LEFT)

        self.sys_vol_bar = MiniBar(cur_f, th, maximum=100)
        self.sys_vol_bar.pack(side=tk.LEFT, padx=(px(10), px(6)),
                              fill=tk.X, expand=True)
        self.sys_vol_pct_label = ui.Label(
            cur_f, text="--%", style="CardHint.TLabel",
        )
        self.sys_vol_pct_label.pack(side=tk.LEFT)

        # ── 电平表(Canvas 自绘的英雄控件) ──
        # 只对响度限幅有意义 —— 整张卡片由 _sync_mode_visibility() 按模式显隐。
        self.meter_card = ui.Frame(self.inner, style="Card.TFrame", padding=px(12))
        self.meter_card.pack(fill=tk.X, pady=(0, px(10)))
        self._mode_visible = True

        self.level_meter = LevelMeter(self.meter_card, th)
        self.level_meter.pack(fill=tk.X)

        readout = ui.Frame(self.meter_card, style="Card.TFrame")
        readout.pack(fill=tk.X, pady=(px(8), 0))
        for col in range(3):
            readout.columnconfigure(col, weight=1, uniform="readout")

        def _readout_cell(col, caption):
            cell = ui.Frame(readout, style="Card.TFrame")
            cell.grid(row=0, column=col, sticky="w")
            ui.Label(cell, text=caption, style="CardHint.TLabel").pack(anchor=tk.W)
            value = ui.Label(cell, text="--", style="CardBigMono.TLabel")
            value.pack(anchor=tk.W)
            return value

        self.signal_value = _readout_cell(0, "信号峰值")
        self.output_value = _readout_cell(1, "输出响度")
        self.atten_value = _readout_cell(2, "衰减")

        if not (LIMITER_AVAILABLE and METER_AVAILABLE):
            self.enable_cb.state(["disabled"])
            self.enable_var.set(False)
            self.status_pill.set("不可用", "danger")

        # 展开折叠面板时要把电平表卡片插回这条分隔线之前,所以留住引用
        self._bottom_sep = ui.Separator(self.inner, orient=tk.HORIZONTAL)
        self._bottom_sep.pack(fill=tk.X, pady=(px(4), px(6)))

        # ── 底部:两个可折叠面板 ──
        self._advanced_open = False
        self._advanced_header = SectionHeader(
            self.inner, th, "高级设置", "释放速率 / 保持时间 / 音量平滑",
            command=self._toggle_advanced,
        )
        self._advanced_header.pack(fill=tk.X, pady=(px(2), px(4)))

        self._advanced_frame = ui.Frame(self.inner, style="Card.TFrame",
                                        padding=(px(12), px(10), px(12), px(10)))

        # 释放速率 / 保持时间(怕泵动就调慢释放)
        arf = ui.Frame(self._advanced_frame, style="Card.TFrame")
        arf.pack(fill=tk.X, pady=(0, 2))

        self.release_var = tk.DoubleVar(value=DEFAULT_RELEASE_DB_PER_S)
        self.release_scale = ui.Scale(
            arf, from_=0.2, to=10.0, orient=tk.HORIZONTAL,
            variable=self.release_var, command=self._on_release_change,
            bootstyle="@card",
        )
        ui.Label(arf, text="释放速率", style="Card.TLabel",
                 font=th.font(9)).pack(side=tk.LEFT)
        self.release_scale.pack(side=tk.LEFT, padx=(px(8), px(6)),
                                fill=tk.X, expand=True)
        self.release_label = ui.Label(
            arf, text=f"{DEFAULT_RELEASE_DB_PER_S:.1f} dB/s",
            style="CardValue.TLabel", font=th.font(9, "bold"), width=9,
            anchor=tk.E,
        )
        self.release_label.pack(side=tk.LEFT)

        ahf = ui.Frame(self._advanced_frame, style="Card.TFrame")
        ahf.pack(fill=tk.X, pady=(0, 2))

        ui.Label(ahf, text="保持时间", style="Card.TLabel",
                 font=th.font(9)).pack(side=tk.LEFT)
        self.hold_var = tk.DoubleVar(value=DEFAULT_HOLD_SECONDS)
        self.hold_scale = ui.Scale(
            ahf, from_=0.0, to=10.0, orient=tk.HORIZONTAL,
            variable=self.hold_var, command=self._on_hold_change,
            bootstyle="@card",
        )
        self.hold_scale.pack(side=tk.LEFT, padx=(px(8), px(6)), fill=tk.X,
                             expand=True)
        self.hold_label = ui.Label(
            ahf, text=f"{DEFAULT_HOLD_SECONDS:.1f} s",
            style="CardValue.TLabel", font=th.font(9, "bold"), width=9,
            anchor=tk.E,
        )
        self.hold_label.pack(side=tk.LEFT)

        # 音量平滑(对下发音量做非对称低通)
        asf = ui.Frame(self._advanced_frame, style="Card.TFrame")
        asf.pack(fill=tk.X, pady=(0, 2))

        ui.Label(asf, text="音量平滑", style="Card.TLabel",
                 font=th.font(9)).pack(side=tk.LEFT)
        self.smooth_var = tk.DoubleVar(value=DeviceLimiter.VOLUME_FILTER_SECONDS)
        self.smooth_scale = ui.Scale(
            asf, from_=DeviceLimiter.FILTER_MIN_S, to=DeviceLimiter.FILTER_MAX_S,
            orient=tk.HORIZONTAL,
            variable=self.smooth_var, command=self._on_smooth_change,
            bootstyle="@card",
        )
        self.smooth_scale.pack(side=tk.LEFT, padx=(px(8), px(6)), fill=tk.X,
                               expand=True)
        self.smooth_label = ui.Label(
            asf, text=f"{DeviceLimiter.VOLUME_FILTER_SECONDS:.2f} s",
            style="CardValue.TLabel", font=th.font(9, "bold"), width=9,
            anchor=tk.E,
        )
        self.smooth_label.pack(side=tk.LEFT)

        ui.Label(
            self._advanced_frame, style="CardHint.TLabel", justify=tk.LEFT,
            text="出现\"压一会松一会\"(泵动)时把释放速率调小;想让压制多撑一会儿就加大保持时间。\n"
                 "音量平滑:对下发的音量做低通,消除细碎抖动(压制方向不受影响,瞬态仍能立刻压住)。"
                 "越大越稳,但恢复越慢。",
        ).pack(anchor=tk.W, pady=(px(6), 0))

        # ── 设置面板 ──
        self._settings_open = False
        self._settings_header = SectionHeader(
            self.inner, th, "设置", "外观 / 开机启动 / 关闭行为",
            command=self._toggle_settings,
        )
        self._settings_header.pack(fill=tk.X, pady=(px(6), px(4)))

        self._settings_frame = ui.Frame(self.inner, style="Card.TFrame",
                                        padding=(px(12), px(10), px(12), px(10)))

        # 外观:跟随系统 / 浅色 / 深色
        appearance_row = ui.Frame(self._settings_frame, style="Card.TFrame")
        appearance_row.pack(fill=tk.X, pady=(0, px(8)))
        ui.Label(appearance_row, text="外观", style="Card.TLabel",
                 font=th.font(9)).pack(side=tk.LEFT)
        self.appearance_var = tk.StringVar()
        self.appearance_combo = ui.Combobox(
            appearance_row, textvariable=self.appearance_var, state="readonly",
            values=[APPEARANCE_LABELS[c] for c in APPEARANCE_CHOICES],
            width=10,
        )
        self.appearance_combo.pack(side=tk.RIGHT)
        self.appearance_combo.bind("<<ComboboxSelected>>", self._on_appearance_change)

        self.auto_start_var = tk.BooleanVar(value=False)
        ui.Checkbutton(
            self._settings_frame, text="开机自动启动",
            variable=self.auto_start_var, command=self._on_auto_start_change,
            style="Card.TCheckbutton",
        ).pack(anchor=tk.W)

        self.minimize_tray_var = tk.BooleanVar(value=True)
        ui.Checkbutton(
            self._settings_frame, text="关闭时最小化到系统托盘",
            variable=self.minimize_tray_var, style="Card.TCheckbutton",
        ).pack(anchor=tk.W, pady=(px(4), 0))

        # 底部填充(退出方式不再在界面上写一行提示 —— 用户要求去掉)
        ui.Frame(self.inner, height=px(12)).pack()

        # ── 恢复信号轮询 ──
        self._check_restore_signal()

    # ── 滚动 ──
    def _on_canvas_configure(self, event=None):
        self.canvas.itemconfig(self.inner_window, width=event.width)

    def _bind_mousewheel(self, event=None):
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, event=None):
        self.root.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _refresh_scrollregion(self):
        """折叠/展开面板后重算滚动区域,否则会出现滚不到底或底部空白。"""
        try:
            self.inner.update_idletasks()
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except tk.TclError:
            pass

    # ── 折叠面板(高级设置 / 设置) ──
    def _set_panel_open(self, frame, header, opened, mode_gated=False):
        """展开/收起一个折叠面板,标题条的箭头跟着状态变。

        `mode_gated=True` 只给**高级设置**用:那一块只在响度限幅模式下存在,
        锁定模式下即使被程序调用也不许放出来。
        ⚠️ 别把它套到"设置"面板上 —— 设置里的外观/开机启动/关闭行为与模式无关。
        这个闸门一开始写在了这个公共函数里,结果锁定模式下点"设置"什么都不出来
        (面板没被 pack),用户直接报"设置界面是空的"。
        """
        if opened and not (mode_gated and not getattr(self, "_mode_visible", True)):
            # after= 让面板紧贴自己的标题条,而不是排到所有控件末尾
            frame.pack(fill=tk.X, after=header)
        else:
            frame.pack_forget()
        header.set_open(opened)
        self._refresh_scrollregion()

    def _toggle_advanced(self):
        self._advanced_open = not self._advanced_open
        self._set_panel_open(self._advanced_frame, self._advanced_header,
                             self._advanced_open, mode_gated=True)

    def _toggle_settings(self):
        self._settings_open = not self._settings_open
        self._set_panel_open(self._settings_frame, self._settings_header,
                             self._settings_open)

    def _sync_mode_visibility(self):
        """按模式显示/隐藏**只对响度限幅有意义**的控件。

        锁定模式下,"响度上限"、电平表、以及高级设置里的三个参数
        (释放速率/保持时间/音量平滑)全都**不起作用**。

        为什么选择"隐藏"而不是"置灰"(用户提的两个方案):
          * 高级设置默认是**收起**的 —— 把里面的滑条置灰,收起状态下根本看不见,
            用户仍然能展开、能拖,只是拖了没用。置灰在这里是无效提示。
          * 与既有行为统一:电平表卡片在锁定模式下本来就是整卡隐藏。
            统一成一条规则("只显示当前模式用得上的东西")比
            "有的隐藏、有的置灰、有的还开着"好理解。
          * 锁定的界面因此只剩:设备 / 模式 / 基础音量 / 设置 —— 干净且不误导。
        """
        want = (getattr(self, "mode", MODE_LIMIT) == MODE_LIMIT)
        if want == getattr(self, "_mode_visible", None):
            return
        self._mode_visible = want
        px = self.theme.px
        if want:
            # 三个都必须用 before=/after= 插回去:pack 默认会排到所有控件末尾
            self.ceiling_frame.pack(fill=tk.X, pady=(0, px(10)),
                                    before=self._bv_card)
            self.meter_card.pack(fill=tk.X, pady=(0, px(10)),
                                 before=self._bottom_sep)
            self._advanced_header.pack(fill=tk.X, pady=(px(2), px(4)),
                                       before=self._settings_header)
            if self._advanced_open:
                self._advanced_frame.pack(fill=tk.X, after=self._advanced_header)
        else:
            self.ceiling_frame.pack_forget()
            self.meter_card.pack_forget()
            self._advanced_header.pack_forget()
            self._advanced_frame.pack_forget()
        self._refresh_scrollregion()

    # ── 外观 ──
    def _on_appearance_change(self, event=None):
        """「设置 → 外观」改变时:存配置 + 立即重刷。"""
        label = self.appearance_var.get()
        mode = APPEARANCE_SYSTEM
        for key, text in APPEARANCE_LABELS.items():
            if text == label:
                mode = key
                break
        self.config["appearance"] = mode
        ConfigManager.save(self.config)
        self.theme.set_appearance(mode)
        self._apply_theme_to_widgets()
        print(f"[Theme] 外观切换为 {mode} (深色={self.theme.dark})")

    def _apply_theme_to_widgets(self):
        """把新主题推到"自己管颜色"的控件上。

        ttk 控件由样式数据库自动更新,不用管;需要手动刷的是三类:
          * tk.Canvas(它的背景是显式设的)
          * 自绘控件(电平表 / 状态药丸 / 折叠标题条)
          * 带状态色的文字(由 _update_limiter_* 重新算)
        """
        th = self.theme
        try:
            self.canvas.configure(background=th.color("window_bg"))
        except tk.TclError:
            pass
        for name in ("level_meter", "status_pill", "sys_vol_bar",
                     "_advanced_header", "_settings_header"):
            w = getattr(self, name, None)
            if w is not None:
                try:
                    w.apply_theme(th)
                except Exception as e:
                    print(f"[Theme] {name} 重刷失败: {e}")
        self._refresh_scrollregion()
        self._update_limiter_labels()
        self._update_limiter_meter(bool(getattr(self, "limiter_enabled", False)))

    # ── 设备管理 ──
    def _init_devices(self):
        """初始化设备列表和选中设备。"""
        self._refresh_devices(init=True)
        # 如果有上次记住的选中设备，尝试恢复
        saved = self.config.get("selected_device_id", "")
        if saved and saved in self._device_map:
            self._select_device(saved)
        elif self._current_default_id:
            self._select_device(self._current_default_id)
        elif self._device_list:
            self._select_device(self._device_list[0].id)

    def _refresh_devices(self, init=False):
        """刷新设备列表。只显示当前活跃的音频输出设备。"""
        if not self.polling_active:
            return
        # 防抖：非初始化时至少间隔 1 秒
        now = time.time()
        if not init and (now - self._last_refresh_time) < 1.0:
            return
        self._last_refresh_time = now

        try:
            # 使缓存失效以获取最新设备列表
            self.audio.invalidate_cache()
            # 1. 获取当前活跃设备
            active_devices = self.audio.get_all_devices(active_only=True)
            self._current_default_id = self.audio.get_default_device_id()
            self._device_list = active_devices
            self._device_map = {d.id: d for d in active_devices}

            # 2. 更新下拉框 — 只显示设备名称，无标记/后缀
            self._suppress_combo = True
            display_names = [d.friendly_name for d in active_devices]
            self.device_combo["values"] = display_names

            # 3. 恢复/自动选择一个设备
            selected_idx = None
            if self._selected_device_id and self._selected_device_id in self._device_map:
                selected_idx = next(
                    (i for i, d in enumerate(active_devices) if d.id == self._selected_device_id), None
                )
            if selected_idx is None and self._current_default_id and self._current_default_id in self._device_map:
                self._selected_device_id = self._current_default_id
                selected_idx = next(
                    (i for i, d in enumerate(active_devices) if d.id == self._current_default_id), None
                )
            if selected_idx is None and active_devices:
                self._selected_device_id = active_devices[0].id
                selected_idx = 0

            # 只在选中设备真正变化时才重新加载 (避免闪烁)
            old_selected = self.device_combo_var.get()
            new_name = ""
            if selected_idx is not None:
                new_name = active_devices[selected_idx].friendly_name
            if old_selected != new_name:
                if selected_idx is not None:
                    self.device_combo.current(selected_idx)
                self._select_device(self._selected_device_id)

            self._suppress_combo = False

            # 4. 蓝牙回退匹配
            active_map = {d.id: d for d in active_devices}
            config_devs = self.config.get("devices", {})
            for d in active_devices:
                if d.id not in config_devs:
                    for known_id, kconf in list(config_devs.items()):
                        if kconf.get("friendly_name") == d.friendly_name and known_id not in active_map:
                            print(f"[Device] 蓝牙 ID 变更: {known_id} -> {d.id}")
                            config_devs[d.id] = dict(kconf)
                            config_devs[d.id]["last_seen"] = datetime.now().isoformat()
                            del config_devs[known_id]
                            ConfigManager.save(self.config)
                            break

            # 5. 清理陈旧设备
            ConfigManager.cleanup_stale_devices(self.config)

            # 6. 更新状态标签
            self._update_device_status()

        except Exception as e:
            print(f"[Device] 刷新失败: {e}")

        if not init:
            self.root.after(DEVICE_REFRESH_MS, self._refresh_devices)

    def _select_device(self, device_id: str):
        """选中指定设备，更新滑条/锁定状态。"""
        self._selected_device_id = device_id
        self.config["selected_device_id"] = device_id

        # 读取设备配置
        dev_cfg = ConfigManager.get_device_config(device_id, self.config)
        self._update_device_status()

        # 更新 UI
        # ── 模式与启用状态 ──
        # 模式读**全局偏好**(见 ConfigManager.load 的说明):以前按设备读,
        # 换个设备或原设备掉线就会"忘记"用户上次选的是什么。
        # 设备级 mode 只作为老配置的兜底。
        mode = self.config.get("mode", dev_cfg.get("mode", MODE_LIMIT))
        self.mode = mode
        self.limiter_enabled = bool(dev_cfg.get("enabled", dev_cfg.get("limiter_enabled", False)))
        self.ceiling_dbfs = float(dev_cfg.get("ceiling_dbfs", DEFAULT_CEILING_DBFS))
        self.base_volume = int(dev_cfg.get("base_volume", dev_cfg.get("target_volume", 50)))
        self.release_db_per_s = float(dev_cfg.get("release_db_per_s",
                                                  DEFAULT_RELEASE_DB_PER_S))
        self.hold_seconds = float(dev_cfg.get("hold_seconds", DEFAULT_HOLD_SECONDS))
        self.volume_filter_seconds = DeviceLimiter.clamp_filter_seconds(
            dev_cfg.get("volume_filter_seconds",
                        DeviceLimiter.VOLUME_FILTER_SECONDS))
        # 顺手把配置里的拖拽残渣(旧滑条没有分辨率)归整成 0.01 的倍数;
        # _select_device 结尾会 save,所以这份修正会落盘。
        dev_cfg["volume_filter_seconds"] = self.volume_filter_seconds

        self._suppress_slider = True
        self._suppress_ceiling = True
        self._suppress_release = True
        self._suppress_hold = True
        self._suppress_smooth = True
        self.mode_var.set(mode)
        self.enable_var.set(self.limiter_enabled)
        self.volume_var.set(self.base_volume)
        self.vol_pct_label.config(text=f"{self.base_volume}%")
        self.ceiling_var.set(int(round(self.ceiling_dbfs)))
        self.ceiling_label.config(text=f"{self.ceiling_dbfs:.0f} dBFS")
        self.release_var.set(self.release_db_per_s)
        self.release_label.config(text=f"{self.release_db_per_s:.1f} dB/s")
        self.hold_var.set(self.hold_seconds)
        self.hold_label.config(text=f"{self.hold_seconds:.1f} s")
        self.smooth_var.set(self.volume_filter_seconds)
        self.smooth_label.config(text=f"{self.volume_filter_seconds:.2f} s")
        self._suppress_slider = False
        self._suppress_ceiling = False
        self._suppress_release = False
        self._suppress_hold = False
        self._suppress_smooth = False

        # 锁定模式的旧字段同步(兼容读旧配置)
        self.locked = bool(dev_cfg.get("locked", False))
        self.target_volume = self.base_volume

        self._update_limiter_labels()
        self._sync_mode_visibility()

        # 更新当前音量显示（活跃设备必有音量值）
        vol = self.audio.get_device_volume(device_id)
        self.current_vol_label.config(text=f"当前设备音量 {vol}%")
        self.sys_vol_bar.set(vol)
        self.sys_vol_pct_label.config(text=f"{vol}%")

        ConfigManager.save(self.config)

    def _endpoint_scale(self, device_id=None) -> VolumeScale:
        """取端点的音量标尺(用于百分比<->dB 换算)。取不到就退回默认范围。"""
        device_id = device_id or self._selected_device_id
        try:
            obj = self.audio._get_active_device_obj(device_id) if device_id else None
            if obj is not None:
                vmin, vmax, vinc = obj.EndpointVolume.GetVolumeRange()
                return VolumeScale(min_db=vmin, max_db=vmax, increment_db=vinc)
        except Exception:
            pass
        return VolumeScale()

    def _ceiling_db_for_percent(self, percent: int, device_id=None) -> float:
        """百分比(Windows 音量位置)-> 端点 dB。"""
        return self._endpoint_scale(device_id).scalar_to_db(max(0, min(100, percent)) / 100.0)

    def _update_limiter_labels(self):
        """刷新 dB 显示与状态药丸。"""
        # 基础音量对应的端点 dB(仅显示)
        base_db = self._ceiling_db_for_percent(self.base_volume)
        self.ceiling_db_label.config(text=f"{base_db:.2f} dB")

        # 上限高于"基础音量对应的 dB"时,输出**根本到不了那么高**,永远不触发。
        # 上限公式修好(改成绝对 dBFS 上限)之后这个坑变得容易踩,所以直接提示。
        try:
            px = self.theme.px
            if self.ceiling_dbfs >= base_db - 0.5:
                self.ceiling_warn.config(
                    text=f"注意:上限 {self.ceiling_dbfs:.0f} dBFS 高于基础音量对应的 "
                         f"{base_db:.1f} dB\n"
                         f"输出最高只到 {base_db:.1f} dBFS,限幅不会触发 —— 把上限拖到它下面。")
                if not self.ceiling_warn.winfo_manager():
                    self.ceiling_warn.pack(anchor=tk.W, pady=(px(2), 0))
            elif self.ceiling_warn.winfo_manager():
                self.ceiling_warn.pack_forget()
        except (tk.TclError, AttributeError):
            pass

        # 让当前模式的关键旋钮可操作,另一个置灰以示互斥。
        # **这段必须在下面的 early return 之前**:旧版把它放在最后,而未启用时会
        # 提前 return —— 于是"锁定模式下停用 → 切回限幅"之后,上限滑条一直是灰的。
        try:
            if getattr(self, "mode", MODE_LIMIT) == MODE_LIMIT:
                self.ceiling_scale.state(["!disabled"])
            else:
                self.ceiling_scale.state(["disabled"])
        except Exception:
            pass

        if not (LIMITER_AVAILABLE and METER_AVAILABLE):
            self.status_pill.set("不可用", "danger")
            return
        if not getattr(self, "limiter_enabled", False):
            self.status_pill.set("未启用", "muted")
            return
        # 运行中的具体状态由 _update_limiter_meter 按实时数据覆盖
        if getattr(self, "mode", MODE_LIMIT) == MODE_LIMIT:
            self.status_pill.set("限幅运行中", "ok")
        else:
            self.status_pill.set("音量锁定", "warn")

    def _save_device_field(self, field, value):
        if self._selected_device_id:
            ConfigManager.set_device_config(self._selected_device_id, field, value, self.config)
            ConfigManager.save(self.config)

    def _on_mode_change(self):
        """切换 响度限幅 / 音量锁定。"""
        self.mode = self.mode_var.get()
        self.locked = (self.mode == MODE_LOCK and self.limiter_enabled)
        # 全局持久化:退出时是什么模式,下次启动就是什么模式
        self.config["mode"] = self.mode
        self._save_device_field("mode", self.mode)
        self._save_device_field("locked", self.locked)
        self._update_limiter_labels()
        self._sync_mode_visibility()
        print(f"[Mode] 切换到 {'响度限幅' if self.mode == MODE_LIMIT else '音量锁定'}"
              f" (启用={self.limiter_enabled})")

    def _on_enable_toggle(self):
        """启用/停用当前模式。"""
        self.limiter_enabled = self.enable_var.get()
        self.locked = (self.mode == MODE_LOCK and self.limiter_enabled)
        self._save_device_field("enabled", self.limiter_enabled)
        self._save_device_field("locked", self.locked)
        self._save_device_field("mode", self.mode)
        self._update_limiter_labels()
        if not self.limiter_enabled and self._selected_device_id:
            # 停用后把音量还原到基础音量,否则会一直停在被压低的状态
            self.audio.set_device_volume(self._selected_device_id, self.base_volume)
        print(f"[Mode] {'启用' if self.limiter_enabled else '停用'} "
              f"{'响度限幅' if self.mode == MODE_LIMIT else '音量锁定'}")

    def _on_ceiling_change(self, value):
        """上限滑条(dBFS)。"""
        if getattr(self, "_suppress_ceiling", False):
            return
        val = int(round(float(value)))
        self.ceiling_var.set(val)
        self.ceiling_dbfs = float(val)
        self.ceiling_label.config(text=f"{val} dBFS")
        self._save_device_field("ceiling_dbfs", float(val))
        self._update_limiter_labels()      # 上限越界提示要跟着动

    def _on_release_change(self, value):
        """释放速率滑条(dB/s)。调小可消除"压一会松一会"的泵动。"""
        if getattr(self, "_suppress_release", False):
            return
        val = float(value)
        self.release_var.set(val)
        self.release_db_per_s = val
        self.release_label.config(text=f"{val:.1f} dB/s")
        self._save_device_field("release_db_per_s", val)

    def _on_smooth_change(self, value):
        """音量平滑滑条(低通时间常数,秒)。"""
        if getattr(self, "_suppress_smooth", False):
            return
        val = float(value)
        # ttk.Scale 没有 resolution 选项,所以步进在这里做:归到 0.01
        val = DeviceLimiter.clamp_filter_seconds(val)
        self.smooth_var.set(val)
        self.volume_filter_seconds = val
        self.smooth_label.config(text=f"{val:.2f} s")
        self._save_device_field("volume_filter_seconds", val)

    def _on_hold_change(self, value):
        """保持时间滑条(秒)。"""
        if getattr(self, "_suppress_hold", False):
            return
        val = float(value)
        self.hold_var.set(val)
        self.hold_seconds = val
        self.hold_label.config(text=f"{val:.1f} s")
        self._save_device_field("hold_seconds", val)

    def _update_device_status(self):
        """更新设备状态标签:当前输出设备(绿) / 不活跃设备(红)。

        颜色从主题调色板取 —— 曾经是硬编码的 #2E7D32/#C62828,
        深色模式下这俩在卡片上几乎看不清(而且扫描只查了 _build_gui,漏了这里)。
        """
        if not self._selected_device_id:
            self.device_status_label.config(text="")
            return
        if self._current_default_id and self._selected_device_id == self._current_default_id:
            self.device_status_label.config(text="当前输出设备",
                                            foreground=self.theme.color("ok"))
        else:
            self.device_status_label.config(text="不活跃设备",
                                            foreground=self.theme.color("danger"))

    # ── 事件处理 ──
    def _on_device_select(self, event=None):
        if self._suppress_combo:
            return
        idx = self.device_combo.current()
        if 0 <= idx < len(self._device_list):
            self._select_device(self._device_list[idx].id)

    def _on_slider_change(self, value):
        """基础音量滑条。"""
        if self._suppress_slider:
            return
        val = int(round(float(value)))
        self.volume_var.set(val)
        self.vol_pct_label.config(text=f"{val}%")
        self.base_volume = val
        self.target_volume = val
        self._save_device_field("base_volume", val)
        self._save_device_field("target_volume", val)
        if self._selected_device_id:
            # 未启用任何模式时才直接改系统音量;启用后由控制环负责
            if not getattr(self, "limiter_enabled", False):
                self.audio.set_device_volume(self._selected_device_id, val)
        self._update_limiter_labels()

    def _on_auto_start_change(self):
        ConfigManager.set_auto_start(self.auto_start_var.get())

    # ── 设备事件处理 ──
    def _process_device_events(self):
        """定时消费设备变更事件队列。"""
        if not self.polling_active:
            return
        try:
            while True:
                event = self._device_events.get_nowait()
                event_type = event[0]
                if event_type == "default_changed":
                    new_default = event[1]
                    if new_default != self._current_default_id:
                        print(f"[DevWatch] 默认设备变更: {new_default}")
                        self._on_default_device_changed(new_default)
                elif event_type == "added":
                    print(f"[DevWatch] 设备接入: {event[1]}")
                    self._refresh_devices()
                elif event_type == "removed":
                    print(f"[DevWatch] 设备移除: {event[1]}")
                    self._refresh_devices()
                elif event_type == "state_changed":
                    print(f"[DevWatch] 设备状态变更: {event[1]} -> {event[2]}")
                    self._refresh_devices()
        except queue.Empty:
            pass
        except Exception as e:
            print(f"[DevWatch] 事件处理异常: {e}")
        self.root.after(200, self._process_device_events)

    def _on_default_device_changed(self, new_default_id: str):
        """默认设备变更时，刷新列表 + 应用新默认设备的锁定配置。"""
        # 先刷新设备列表确保数据最新
        self._refresh_devices()
        self._current_default_id = new_default_id

        dev_cfg = ConfigManager.get_device_config(new_default_id, self.config)
        if dev_cfg.get("locked", False):
            target = dev_cfg.get("target_volume", 50)
            print(f"[Lock] 默认设备切换，自动锁定: {new_default_id[:30]} -> {target}%")
            self.audio.set_device_volume(new_default_id, target)

        # 自动切换到新默认设备
        if self._selected_device_id != new_default_id:
            self._select_device(new_default_id)
            idx = next((i for i, d in enumerate(self._device_list) if d.id == new_default_id), None)
            if idx is not None:
                self._suppress_combo = True
                self.device_combo.current(idx)
                self._suppress_combo = False

    # ── 轮询 ──
    def _start_polling(self):
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

    def _update_limiter_target(self, default_id) -> None:
        """让控制环跟随当前默认设备与配置。由主轮询线程调用(200ms 粒度)。

        控制环本身跑在独立线程上(8ms 节拍)——主轮询 200ms 的粒度
        对限幅来说太慢,瞬态会被放过去。
        """
        if not (LIMITER_AVAILABLE and METER_AVAILABLE):
            return
        cfg = ConfigManager.get_device_config(default_id, self.config)
        want = bool(cfg.get("enabled", cfg.get("limiter_enabled", False)))
        lim = self._limiter

        if not want:
            if lim is not None:
                lim.detach()
                self._limiter = None
                self._limiter_device_id = None
            return

        # 模式是全局偏好,不是每设备一份 —— 控制环必须跟界面读同一个来源,
        # 否则会出现"界面显示音量锁定,后台却按限幅处理"(音量根本没人钉)。
        mode = self.config.get("mode", cfg.get("mode", MODE_LIMIT))
        ceiling = float(cfg.get("ceiling_dbfs", DEFAULT_CEILING_DBFS))
        base_pct = int(cfg.get("base_volume", cfg.get("target_volume", 50)))
        base_db = self._ceiling_db_for_percent(base_pct, default_id)
        hold = float(cfg.get("hold_seconds", DEFAULT_HOLD_SECONDS))
        release = float(cfg.get("release_db_per_s", DEFAULT_RELEASE_DB_PER_S))
        smooth = DeviceLimiter.clamp_filter_seconds(
            cfg.get("volume_filter_seconds",
                    DeviceLimiter.VOLUME_FILTER_SECONDS))

        if lim is None:
            # COM 指针必须在本线程创建与使用 —— 控制环也在这条线程上跑
            lim = DeviceLimiter(comtypes, IAudioMeterInformationFull,
                                LoudnessLimiter,
                                LoudnessConfig(ceiling_dbfs=ceiling,
                                               hold_seconds=hold,
                                               release_db_per_s=release))
            lim.set_mode(mode)
            lim.set_ceiling_dbfs(ceiling)
            lim.set_base_volume_db(base_db)
            lim.set_lock_target_db(base_db)
            lim.volume_filter_seconds = smooth
            device_obj = self._get_device_obj_cached(default_id)
            if device_obj is None or not lim.attach(device_obj, default_id):
                return
            self._limiter = lim
            self._limiter_device_id = default_id
            lim.apply_now()
            return

        # 设备换了 -> 重新绑定
        if self._limiter_device_id != default_id:
            lim.set_mode(mode)
            lim.set_ceiling_dbfs(ceiling)
            lim.set_base_volume_db(base_db)
            lim.set_lock_target_db(base_db)
            lim.volume_filter_seconds = smooth
            if lim.attach(self._get_device_obj_cached(default_id), default_id):
                self._limiter_device_id = default_id
                lim.apply_now()
            return

        # 参数变化 -> 就地更新(不重新绑定,避免打断控制环)
        if lim.mode != mode:
            lim.set_mode(mode)
            lim.apply_now()
        if lim._lim is not None:
            if abs(ceiling - lim._lim.ceiling_dbfs) > 1e-6:
                lim.set_ceiling_dbfs(ceiling)
            lim._lim.config.hold_seconds = hold
            lim._lim.config.release_db_per_s = release
        lim.volume_filter_seconds = smooth
        if abs(base_db - lim.base_volume_db) > 1e-6:
            lim.set_base_volume_db(base_db)
            if mode == MODE_LOCK:
                lim.set_lock_target_db(base_db)
        if lim._lock_target_pending is not None and mode == MODE_LOCK:
            lim._lock_target_pending = None

    def _get_device_obj_cached(self, device_id):
        """取 pycaw 的 AudioDevice 对象(只读,拿接口用)。"""
        try:
            return self.audio._get_active_device_obj(device_id)
        except Exception:
            return None

    def _poll_loop(self):
        """主轮询热路径:设备/配置监控 + 限幅器生命周期(200ms 粒度)。

        限幅控制环(_limiter_step)在另一条线程上以 8ms 节拍跑。
        """
        last_default_id = None
        default_ep = None
        fail_streak = 0

        def limiter_step_loop():
            """8ms 节拍跑控制环。绝不在本线程之外创建/使用 COM 指针。"""
            while self.polling_active:
                lim = self._limiter
                if lim is not None and lim.ready:
                    lim.step()          # 时间基准由 DeviceLimiter 内部统一提供
                time.sleep(DeviceLimiter.POLL_SECONDS)

        threading.Thread(target=limiter_step_loop, daemon=True).start()

        while self.polling_active:
            try:
                # 1. 获取当前默认设备
                default_id = self.audio.get_default_device_id()
                if default_id is None:
                    fail_streak += 1
                    if fail_streak >= 3:
                        last_default_id = None
                        default_ep = None
                        self.audio.invalidate_cache()
                        self.audio._handle_com_error()
                        fail_streak = 0
                    time.sleep(POLL_INTERVAL)
                    continue
                fail_streak = 0

                dev_cfg = ConfigManager.get_device_config(default_id, self.config)
                limiter_on = bool(dev_cfg.get("enabled", dev_cfg.get("limiter_enabled", False)))

                # 2. 控制环生命周期跟随当前默认设备
                self._update_limiter_target(default_id)

                # 3. 没有端点指针 → 立即尝试获取（每轮都重试，不依赖 ID 变更）
                if default_ep is None:
                    new_ep = self.audio.get_device_endpoint(default_id)
                    if new_ep is not None:
                        default_ep = new_ep
                        # 第一次拿到端点 + 设备确实变了 → 通知 GUI
                        if last_default_id is not None and default_id != last_default_id:
                            self._device_events.put(("default_changed", default_id))
                        last_default_id = default_id

                # 4. 音量锁定
                #    只在"音量锁定模式且已启用"时才由这里钉音量。
                #    响度限幅模式下音量由控制环负责 —— 两边同时写必然打架
                #    (锁模式每 200ms 把音量钉回目标,限幅刚压下去就被顶回来)。
                # 模式跟界面读同一个来源(全局偏好),别读设备级的旧字段
                lock_mode = (self.config.get("mode", MODE_LIMIT) == MODE_LOCK)
                if limiter_on and lock_mode and default_ep is not None:
                    target = int(dev_cfg.get("base_volume",
                                             dev_cfg.get("target_volume", 50)))
                    try:
                        scalar = default_ep.GetMasterVolumeLevelScalar()
                        current = int(round(scalar * 100))
                        if current != target:
                            default_ep.SetMasterVolumeLevelScalar(
                                max(0.0, min(1.0, target / 100.0)), None
                            )
                    except Exception:
                        # COM 端点过期 → 强制重置，下轮重试
                        last_default_id = None
                        default_ep = None

                # 5. 有端点但默认设备变了 → 通知 GUI + 重置端点下轮重取
                if default_ep is not None and default_id != last_default_id:
                    if last_default_id is not None:
                        self._device_events.put(("default_changed", default_id))
                    last_default_id = None
                    default_ep = None

            except Exception:
                pass
            time.sleep(POLL_INTERVAL)

    # ── UI 更新 ──
    def _update_ui(self):
        """定时刷新界面:设备音量、dB 显示、限幅实时读数。

        限幅开启时以 100ms 刷新实时表头;否则 1s 一次省 CPU。

        ⚠️ **界面刷新失败绝不能连音频控制一起带走。** 这里原来的写法是
        `except: self.polling_active = False`,而 polling_active 同时是
        **轮询线程与控制环线程的循环条件** —— 于是"界面上某个属性读不到"
        会直接让整个限幅/锁定停止工作(用户报的"切到限幅但整个软件不工作"
        就是这么来的:锁模式下 DeviceLimiter 没有 attenuation_db)。
        现在：出错只记日志、继续刷新;只有窗口真的没了才停。
        """
        if not self.polling_active:
            return
        interval = 1000
        try:
            if not self.root.winfo_exists():
                self.polling_active = False
                return

            # 跟随系统外观:系统切深浅色时自动重刷。
            # 每 2 秒查一次注册表就够了 —— 每拍(100ms)查是白耗 IO。
            now = time.time()
            if now - getattr(self, "_appearance_checked_at", 0.0) >= 2.0:
                self._appearance_checked_at = now
                if self.theme.refresh_system_mode():
                    self.appearance_var.set(
                        APPEARANCE_LABELS[self.theme.appearance])
                    self._apply_theme_to_widgets()

            limiter_on = bool(getattr(self, "limiter_enabled", False))
            interval = 100 if limiter_on else 1000

            if self._selected_device_id:
                vol = self.audio.get_device_volume(self._selected_device_id)
                self.current_vol_label.config(text=f"当前设备音量 {vol}%")
                self.sys_vol_bar.set(vol)
                self.sys_vol_pct_label.config(text=f"{vol}%")

                # 基础音量滑条跟随系统音量的条件:未启用任何模式。
                # 启用后系统音量是**控制环写入的结果**(锁定值或被压低的音量),
                # 让滑条跟着它跑会把用户设的基础音量一起拖下去。
                if (self._selected_device_id in self._device_map
                        and not limiter_on):
                    self._suppress_slider = True
                    self.volume_var.set(vol)
                    self.vol_pct_label.config(text=f"{vol}%")
                    self.base_volume = vol
                    self.target_volume = vol
                    self._suppress_slider = False

            self._update_limiter_meter(limiter_on)
        except Exception as e:
            # 限流打印:不然 100ms 一拍会把控制台刷爆
            self._ui_error_count = getattr(self, "_ui_error_count", 0) + 1
            if self._ui_error_count <= 3 or self._ui_error_count % 50 == 0:
                print(f"[UI] 第 {self._ui_error_count} 次刷新失败"
                      f"(不影响音频控制): {type(e).__name__}: {e}")
        finally:
            try:
                self.root.after(interval, self._update_ui)
            except tk.TclError:
                # 窗口已经销毁 -> 这才是真正该停的时候
                self.polling_active = False

    def _update_limiter_meter(self, limiter_on: bool):
        """把控制环的实时状态画到界面上(数值 + 电平表 + 状态药丸)。"""
        self._sync_mode_visibility()
        th = self.theme
        lim = self._limiter
        ceiling = (lim._lim.ceiling_dbfs
                   if (lim is not None and lim._lim is not None)
                   else getattr(self, "ceiling_dbfs", DEFAULT_CEILING_DBFS))

        if not limiter_on or lim is None or not lim.ready:
            if limiter_on:
                self.status_pill.set("等待设备", "warn")
            for lbl in (self.signal_value, self.output_value, self.atten_value):
                lbl.config(text="--", foreground=th.color("text"))
            self.level_meter.set_level(None, ceiling, None, False)
            return

        mode = getattr(lim, "mode", MODE_LIMIT)
        sig_db = getattr(lim, "signal_dbfs", -120.0)
        # 用 getattr 兜底:锁定模式下"输出响度/衰减"这两个量根本不存在
        # (限幅分支才会更新它们)。踩过:直接点属性 -> AttributeError ->
        # 界面刷新抛异常 -> 整个音频控制停摆。
        att_db = getattr(lim, "attenuation_db", 0.0)
        silent = sig_db <= -119.0

        if mode == MODE_LOCK:
            # 锁定模式没有响度概念,只显示信号峰值 + "已锁定"
            self.signal_value.config(
                text="静音" if silent else f"{sig_db:.1f} dBFS",
                foreground=th.color("muted"))
            self.output_value.config(text="--", foreground=th.color("text"))
            self.atten_value.config(text="--", foreground=th.color("text"))
            self.level_meter.set_level(None, ceiling, None, False)
            self.status_pill.set("音量锁定", "warn")
            return

        out_db = getattr(lim, "output_dbfs", -120.0)
        holding = att_db > 0.01

        self.signal_value.config(
            text="静音" if silent else f"{sig_db:.1f} dBFS",
            foreground=th.color("text"))
        self.output_value.config(
            text="静音" if out_db <= -119.0 else f"{out_db:.1f} dBFS",
            foreground=th.color("danger") if holding else th.color("ok"))
        self.atten_value.config(
            text=f"-{att_db:.1f} dB" if holding else "0.0 dB",
            foreground=th.color("danger") if holding else th.color("ok"))

        # 电平表:一把好尺子,把"信号 → 压到哪 → 离上限多远"一次讲清
        self.level_meter.set_level(
            out_db, ceiling, None if silent else sig_db, holding)

        if holding:
            self.status_pill.set("限幅中", "danger")
        else:
            self.status_pill.set("限幅运行中", "ok")

    # ── 恢复信号 ──
    def _check_restore_signal(self):
        """检测是否有来自另一个实例的恢复窗口信号。"""
        if not self.root.winfo_exists():
            return
        signal_path = os.path.join(APP_DIR, ".restore_signal")
        if os.path.exists(signal_path):
            try:
                os.remove(signal_path)
                self._restore_window()
            except Exception:
                pass
        self.root.after(2000, self._check_restore_signal)

    # ── 窗口生命周期 ──
    def _on_closing(self):
        """窗口关闭事件。"""
        if self.minimize_tray_var.get() and PYSTRAY_AVAILABLE:
            self.root.withdraw()
        else:
            self._full_exit()

    def _restore_window(self):
        """从托盘恢复窗口，临时置顶防止意外消失。"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        # 恢复后临时置顶 3 秒，防止点击外部时窗口跑到其他窗口后面
        self.root.attributes('-topmost', True)
        self._topmost_until = time.time() + 3.0
        # 3 秒后取消置顶
        self.root.after(3000, self._release_topmost)

    def _release_topmost(self):
        """取消窗口置顶（3 秒定时器到期后调用）。"""
        if time.time() >= getattr(self, '_topmost_until', 0):
            try:
                self.root.attributes('-topmost', False)
            except Exception:
                pass

    def _full_exit(self):
        """完全退出应用。"""
        self.polling_active = False
        self.config["minimize_to_tray"] = self.minimize_tray_var.get()
        self.config["auto_start"] = self.auto_start_var.get()
        self.config["appearance"] = self.theme.appearance
        ConfigManager.save(self.config)
        self.tray.stop()
        if self._device_watcher:
            self._device_watcher.unregister(self.audio)
        self.audio.cleanup()
        if self._instance_lock:
            try:
                self._instance_lock.close()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        # 注册设备监听
        self._device_watcher.register(self.audio)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self._full_exit()


# ══════════════════════════════════════════════════════════════════
# 程序入口
# ══════════════════════════════════════════════════════════════════

# 打包成 exe(--windowed)之后 **stdout 是个 NullWriter**(实测:不是 None,
# 但也写不出去),`print()` 全部静默丢弃 —— 于是"托盘程序出问题"就变成纯黑盒
# (双击没反应、连一句线索都没有)。所以**冻结版一律**把 print 接到
# APP_DIR\app.log:源码运行照旧打控制台,打包版留一份可以发我的日志。
# 上限 1MB 后自动轮转成 .1,不会长胖。
LOG_FILE = os.path.join(APP_DIR, "app.log")
LOG_MAX_BYTES = 1024 * 1024


def _setup_logging():
    if not getattr(sys, "frozen", False):
        return                      # 源码运行:控制台就是日志
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > LOG_MAX_BYTES:
            os.replace(LOG_FILE, LOG_FILE + ".1")
        # buffering=1 = 行缓冲:托盘程序随时可能被任务管理器结束,
        # 块缓冲会把最后几行(往往正是报错那几行)一起丢掉。
        f = open(LOG_FILE, "a", encoding="utf-8", errors="replace", buffering=1)
        f.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} "
                f"启动 v{APP_VERSION} (frozen) =====\n")
        f.flush()
        sys.stdout = f
        sys.stderr = f
    except Exception:
        pass


if __name__ == "__main__":
    _setup_logging()
    os.makedirs(APP_DIR, exist_ok=True)
    # 旧版本写下的自启项没有 --tray,开机还会弹窗 —— 启动时自己修一次
    ConfigManager.ensure_auto_start_flag()
    # 自启(带 --tray)只进托盘;双击 exe / bat(无参数)照常显示界面
    start_hidden = AUTOSTART_FLAG in sys.argv[1:]
    print(f"[Start] v{APP_VERSION} "
          f"{'开机自启 → 只进托盘' if start_hidden else '用户启动 → 显示窗口'}"
          f"  argv={sys.argv[1:]}")
    app = VolumeLockerApp(start_hidden=start_hidden)
    app.run()





