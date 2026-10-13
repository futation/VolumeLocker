# theme.py — 外观层:DPI 感知、配色、字体阶梯、ttk 样式、深浅主题、Win11 深色标题栏
#
# 三条设计约束(踩过才知道为什么必须这样)
# ────────────────────────────────────────────────────────────────────
# 1. **颜色只有一个来源。** 界面代码里不允许出现字面色值(如 "#999"),一律从
#    `ThemeManager.palette` 取。否则切深色时必然出现"白底白字"或"灰字看不见",
#    而且是逐个控件去发现、去修 —— 那种 bug 只能靠眼睛找。
# 2. **ttkbootstrap 是可选依赖,缺了不能崩。** 这个程序是托盘常驻的:导入期抛异常
#    的话,用户只会看到一个"双击了没反应"的图标,连报错窗口都没有。
#    所以:装了就用它做扁平化外观,并把它的调色板当唯一色源(自绘的电平表和
#    ttk 控件天然同色);没装就退回 clam + 内置调色板,功能不降级,只是没它精致。
# 3. 本模块 **不 import pycaw/comtypes**,可以离线跑测试。

from __future__ import annotations

import ctypes
import os
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ── 可选的 ttkbootstrap ──────────────────────────────────────────────
# 设 VOLUMELOCKER_LITE=1 可以强制走"轻量模式"(不加 ttkbootstrap,退回 clam +
# 内置调色板)。实测差别:现代模式常驻 ~58MB,轻量模式 ~46MB —— 省下的 12MB
# 全是 ttkbootstrap 的主题系统本身,不是我们的布局/电平表。
# 布局、卡片、电平表、深浅主题在两种模式下都工作,只是控件质感朴素一些。
_FORCE_LITE = os.environ.get("VOLUMELOCKER_LITE", "").strip().lower() not in (
    "", "0", "false", "no")

try:
    if _FORCE_LITE:
        raise ImportError("VOLUMELOCKER_LITE=1,强制轻量模式")
    import ttkbootstrap as _tb

    TTKBOOTSTRAP = True
    TTKBOOTSTRAP_VERSION = getattr(_tb, "__version__", "?")
except Exception as _e:                      # pragma: no cover - 取决于环境
    _tb = None
    TTKBOOTSTRAP = False
    TTKBOOTSTRAP_VERSION = None
    print(f"[Theme] 未启用 ttkbootstrap,用内置主题(轻量模式): {_e}")

# 主题名(ttkbootstrap 的浅/深一对)
LIGHT_THEME = "bootstrap-light"
DARK_THEME = "bootstrap-dark"

# 外观模式(存进 config.json)
APPEARANCE_SYSTEM = "system"
APPEARANCE_LIGHT = "light"
APPEARANCE_DARK = "dark"
APPEARANCE_CHOICES = (APPEARANCE_SYSTEM, APPEARANCE_LIGHT, APPEARANCE_DARK)
APPEARANCE_LABELS = {
    APPEARANCE_SYSTEM: "跟随系统",
    APPEARANCE_LIGHT: "浅色",
    APPEARANCE_DARK: "深色",
}


# ══════════════════════════════════════════════════════════════════
# 颜色工具
# ══════════════════════════════════════════════════════════════════
def hex_to_rgb(color: str):
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def blend(c1: str, c2: str, t: float) -> str:
    """把 c1 向 c2 混合 t(0=全 c1,1=全 c2)。用来从主题色派生卡片/次要文字色。"""
    a, b = hex_to_rgb(c1), hex_to_rgb(c2)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def luminance(color: str) -> float:
    r, g, b = (c / 255.0 for c in hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ══════════════════════════════════════════════════════════════════
# DPI 感知
# ══════════════════════════════════════════════════════════════════
_dpi_state = {"done": False, "ok": False}


def enable_dpi_awareness() -> bool:
    """声明本进程 DPI 感知。**必须在创建 Tk 根窗口之前调用。**

    实测(本机屏幕 125% 缩放):不调用时 `GetDpiForSystem()` 返回 96、Tk 的
    `tk scaling`=1.335 —— 也就是 Windows 把整个窗口**按 125% 位图拉伸**,
    字和线条全是糊的。调用之后同样两个值变成 120 / 1.668,渲染才是原生清晰的。

    窗口已经创建之后再调用会失败(E_ACCESSDENIED),这里静默接受:那样只是
    退回到"糊一点",不该因此崩。
    """
    if _dpi_state["done"]:
        return _dpi_state["ok"]
    _dpi_state["done"] = True
    u32 = ctypes.windll.user32
    try:
        # PER_MONITOR_AWARE_V2 = -4(需要 Win10 1703+)
        if u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            _dpi_state["ok"] = True
            return True
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
        _dpi_state["ok"] = True
        return True
    except Exception:
        pass
    try:
        _dpi_state["ok"] = bool(u32.SetProcessDPIAware())
    except Exception:
        _dpi_state["ok"] = False
    return _dpi_state["ok"]


def system_is_dark() -> bool:
    """Windows 的"应用模式"是不是深色。读注册表,不需要额外依赖。"""
    try:
        import winreg
        key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            value, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return int(value) == 0
    except Exception:
        return False


def apply_dark_titlebar(root: tk.Misc, dark: bool) -> bool:
    """把 Win11 的标题栏切成深色(DWMWA_USE_IMMERSIVE_DARK_MODE=20)。

    不做这一步的话,深色界面会顶着一个亮白标题栏,比不改还难看。
    """
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        if not hwnd:
            hwnd = root.winfo_id()
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):        # 20 = 正式;19 = 旧版 Win10 的同一个开关
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd), attr,
                    ctypes.byref(value), ctypes.sizeof(value)) == 0:
                return True
    except Exception:
        pass
    return False


# ══════════════════════════════════════════════════════════════════
# 控件命名空间(ttkbootstrap 可选)
# ══════════════════════════════════════════════════════════════════
class _TtkFallback:
    """没装 ttkbootstrap 时的替身:转发给 tkinter.ttk,并吞掉 bootstyle 关键字。"""

    def __getattr__(self, name):
        target = getattr(ttk, name)

        def factory(*args, **kwargs):
            kwargs.pop("bootstyle", None)
            return target(*args, **kwargs)

        factory.__name__ = name
        return factory


ui = _tb if TTKBOOTSTRAP else _TtkFallback()


# ══════════════════════════════════════════════════════════════════
# 内置调色板(没有 ttkbootstrap 时用)
# ══════════════════════════════════════════════════════════════════
_FALLBACK_PALETTES = {
    False: {   # 浅色
        "window_bg": "#f3f3f3", "card_bg": "#ffffff", "border": "#e2e2e2",
        "text": "#1a1a1a", "muted": "#5a5a5a", "hint": "#8a8a8a",
        "accent": "#0067c0", "accent_fg": "#ffffff",
        "ok": "#0f7b0f", "warn": "#9d5d00", "danger": "#c42b1c",
        "track": "#dcdcdc", "meter_low": "#2e9e4f", "meter_mid": "#e0a92a",
        "meter_high": "#d13438", "tick": "#9a9a9a",
    },
    True: {    # 深色
        "window_bg": "#202020", "card_bg": "#2b2b2b", "border": "#3d3d3d",
        "text": "#f2f2f2", "muted": "#c8c8c8", "hint": "#9a9a9a",
        "accent": "#60cdff", "accent_fg": "#003350",
        "ok": "#6ccb5f", "warn": "#fce100", "danger": "#ff99a4",
        "track": "#3a3a3a", "meter_low": "#4cc38a", "meter_mid": "#e5c07b",
        "meter_high": "#e5484d", "tick": "#8a8a8a",
    },
}


class _StyleRecorder:
    """代理 `style.configure/map`,顺手把样式名记下来。

    为什么要记:ttkbootstrap 的控件类会**静默丢掉**没注册过的 `style=` 名字
    (实测 `tb.Radiobutton(style="Card.TRadiobutton")` 会退回 `TRadiobutton`,
    不报任何错)。于是"样式名写错/漏注册"的表现是**颜色悄悄不对**而不是崩。
    记下来之后,`gui_smoke_test.py` 能拿这份名单核对 `_build_gui` 里的每个
    `style=`,把静默降级变成测试失败。
    """

    def __init__(self, style, names: set):
        self._style = style
        self._names = names

    def configure(self, name, **kw):
        self._names.add(name)
        return self._style.configure(name, **kw)

    def map(self, name, **kw):
        self._names.add(name)
        return self._style.map(name, **kw)

    def __getattr__(self, item):
        return getattr(self._style, item)


class ThemeManager:
    """一个实例管一个 Tk 根窗口的外观。

    用法::
        enable_dpi_awareness()          # 必须在 tk.Tk() 之前
        root = tk.Tk()
        theme = ThemeManager(root, appearance="system")
        ...
        ttk.Label(parent, style="Hint.TLabel")     # 颜色/字体全部来自主题
    """

    def __init__(self, root: tk.Misc, appearance: str = APPEARANCE_SYSTEM):
        self.root = root
        self.appearance = appearance if appearance in APPEARANCE_CHOICES else APPEARANCE_SYSTEM
        self.dark = self._resolve_dark()
        self.scale = self._detect_scale()
        self.base_family, self.mono_family = self._pick_families()
        self.style = self._make_style()
        self.palette = dict(_FALLBACK_PALETTES[self.dark])
        self.apply()

    # ── 基础信息 ──
    def _resolve_dark(self) -> bool:
        if self.appearance == APPEARANCE_DARK:
            return True
        if self.appearance == APPEARANCE_LIGHT:
            return False
        return system_is_dark()

    def _detect_scale(self) -> float:
        """像素缩放系数(96dpi = 1.0)。字号是"点"会自动缩放,**像素不会**,
        所以 padx/pady/Canvas 尺寸都要过一遍 `px()`。"""
        try:
            return max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except Exception:
            return 1.0

    def _pick_families(self):
        try:
            families = set(tkfont.families(self.root))
        except Exception:
            families = set()
        base = "Microsoft YaHei UI" if "Microsoft YaHei UI" in families else "Segoe UI"
        mono = "Consolas" if "Consolas" in families else base
        return base, mono

    def px(self, n: float) -> int:
        """把设计稿里的像素值换算成当前 DPI 下的像素。"""
        return int(round(n * self.scale))

    def font(self, size: int = 9, weight: str = None, mono: bool = False):
        family = self.mono_family if mono else self.base_family
        return (family, size) if weight is None else (family, size, weight)

    # ── 主题应用 ──
    def _make_style(self):
        if TTKBOOTSTRAP:
            # 必须在 Tk 根窗口之后创建;它会把主题写进全局 style 数据库,
            # 所以普通 tkinter.ttk 控件也会一起被主题化。
            return _tb.Style(theme=DARK_THEME if self.dark else LIGHT_THEME)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        return style

    def _theme_based_palette(self) -> dict:
        c = self.style.colors
        dark = self.dark
        toward = "#ffffff" if dark else "#000000"
        p = {
            "window_bg": c.bg,
            "card_bg": blend(c.bg, toward, 0.06),
            "border": c.border,
            "text": c.fg,
            "muted": blend(c.fg, c.bg, 0.30),
            "hint": blend(c.fg, c.bg, 0.50),
            "accent": c.primary,
            "accent_fg": getattr(c, "selectfg", "#ffffff") or "#ffffff",
            "ok": c.success,
            "warn": c.warning,
            "danger": c.danger,
            "track": blend(c.bg, toward, 0.14),
            "meter_low": c.success,
            "meter_mid": c.warning,
            "meter_high": c.danger,
            "tick": blend(c.fg, c.bg, 0.55),
        }
        return p

    def _resolve_card_bg(self) -> str:
        """问主题要 `card` 表面色,而不是自己拍一个。

        为什么必须问:ttkbootstrap 的**滑条轨道、单选圆点、进度条槽都是图片**,
        颜色由"这个控件坐在哪个表面上"决定 —— 给控件加 `bootstyle="@card"` 之后,
        它会把轨道按 card 表面重画一遍。所以卡片底色必须和主题认定的 card
        **完全一致**,否则只是把"差一层色"换个位置。

        做法:造一个隐藏的 `@card` 帧,把它的 background 读回来(`resolve_surface`
        挂在 StyleBuilder 上,Style 没暴露,这是公开可用的等效推断)。
        """
        if TTKBOOTSTRAP:
            try:
                probe = _tb.Frame(self.root, bootstyle="@card")
                color = self.style.lookup(probe.cget("style"), "background")
                probe.destroy()
                if color:
                    return color
            except Exception as e:
                print(f"[Theme] 读取 card 表面色失败,退回内置推算: {e}")
        # 内置推算:深色往白推、浅色往黑推(与主题的 elevation 方向一致)
        return blend(self.palette["window_bg"],
                     "#ffffff" if self.dark else "#000000", 0.06)

    def apply(self):
        """把主题和样式刷上去。

        顺序有讲究:`theme_use` 会**重置** ttkbootstrap 的全部样式定义,所以自定义
        样式必须在切主题**之后**再配一遍,否则切一次深浅色就全丢了。
        """
        if TTKBOOTSTRAP:
            try:
                self.style.theme_use(DARK_THEME if self.dark else LIGHT_THEME)
            except Exception as e:
                print(f"[Theme] 切换主题失败({e}),保持当前主题")
            self.palette = self._theme_based_palette()
            self.palette["card_bg"] = self._resolve_card_bg()
        else:
            self.palette = dict(_FALLBACK_PALETTES[self.dark])

        self._configure_styles()
        try:
            self.root.configure(background=self.palette["window_bg"])
        except Exception:
            pass
        apply_dark_titlebar(self.root, self.dark)

    def set_appearance(self, appearance: str) -> bool:
        """切换外观模式,返回"深色状态是否真的变了"。"""
        if appearance not in APPEARANCE_CHOICES:
            appearance = APPEARANCE_SYSTEM
        was_dark = self.dark
        self.appearance = appearance
        self.dark = self._resolve_dark()
        if self.dark == was_dark and appearance == getattr(self, "_applied_appearance", None):
            return False
        self._applied_appearance = appearance
        self.apply()
        return self.dark != was_dark

    def refresh_system_mode(self):
        """跟随系统模式下,系统配色变了就重刷一遍。返回是否真的变了。"""
        if self.appearance != APPEARANCE_SYSTEM:
            return False
        dark = system_is_dark()
        if dark == self.dark:
            return False
        self.dark = dark
        self.apply()
        return True

    # ── ttk 样式 ──
    def _configure_styles(self):
        p = self.palette
        self.style_names = set()
        st = _StyleRecorder(self.style, self.style_names)
        f = self.font

        try:
            st.configure(".", background=p["window_bg"], foreground=p["text"],
                         font=f(9))
        except Exception:
            pass

        # 容器
        st.configure("TFrame", background=p["window_bg"])
        st.configure("Card.TFrame", background=p["card_bg"])
        st.configure("Header.TFrame", background=p["window_bg"])

        # 文字层级:标题 / 副标题 / 正文 / 说明 / 数值
        st.configure("TLabel", background=p["window_bg"], foreground=p["text"],
                     font=f(9))
        st.configure("Card.TLabel", background=p["card_bg"], foreground=p["text"])
        st.configure("Title.TLabel", background=p["window_bg"], foreground=p["text"],
                     font=f(17, "bold"))
        st.configure("Sub.TLabel", background=p["window_bg"], foreground=p["muted"],
                     font=f(9))
        st.configure("Section.TLabel", background=p["window_bg"],
                     foreground=p["text"], font=f(10, "bold"))
        st.configure("Hint.TLabel", background=p["window_bg"], foreground=p["hint"],
                     font=f(8))
        st.configure("CardHint.TLabel", background=p["card_bg"],
                     foreground=p["hint"], font=f(8))
        st.configure("Muted.TLabel", background=p["window_bg"],
                     foreground=p["muted"], font=f(9))
        st.configure("Value.TLabel", background=p["window_bg"], foreground=p["text"],
                     font=f(11, "bold"))
        st.configure("CardValue.TLabel", background=p["card_bg"],
                     foreground=p["text"], font=f(11, "bold"))
        st.configure("Mono.TLabel", background=p["window_bg"], foreground=p["text"],
                     font=f(10, mono=True))
        st.configure("CardMono.TLabel", background=p["card_bg"], foreground=p["text"],
                     font=f(10, mono=True))
        st.configure("BigMono.TLabel", background=p["window_bg"], foreground=p["text"],
                     font=f(12, "bold", mono=True))
        st.configure("CardBigMono.TLabel", background=p["card_bg"],
                     foreground=p["text"], font=f(12, "bold", mono=True))
        st.configure("Accent.TLabel", background=p["window_bg"],
                     foreground=p["accent"], font=f(10, "bold"))
        st.configure("CardAccent.TLabel", background=p["card_bg"],
                     foreground=p["accent"], font=f(10, "bold"))
        for name, key in (("Ok.TLabel", "ok"), ("Warn.TLabel", "warn"),
                          ("Danger.TLabel", "danger")):
            st.configure(name, background=p["window_bg"], foreground=p[key],
                         font=f(9, "bold"))
            st.configure("Card" + name, background=p["card_bg"], foreground=p[key],
                         font=f(9, "bold"))

        # 勾选/单选:背景必须跟着容器走,否则深色下会露白底
        for style_name, bg in (("TCheckbutton", p["window_bg"]),
                               ("Card.TCheckbutton", p["card_bg"]),
                               ("TRadiobutton", p["window_bg"])):
            st.configure(style_name, background=bg, foreground=p["text"],
                         font=f(9), focuscolor=bg)
            st.map(style_name,
                   background=[("active", bg)],
                   foreground=[("disabled", p["hint"])],
                   indicatorcolor=[("selected", p["accent"]),
                                   ("!selected", p["card_bg"])])

        # 按钮:扁平 + 内边距。需要更精确配色的地方用 ttkbootstrap 的 bootstyle。
        # 注意:ttkbootstrap 的 `round-toggle`(开关样式)**在这个版本不存在**
        # (实测 TclError: Layout Round.Toggle not found),别照文档抄。
        st.configure("TButton", font=f(9), padding=(self.px(12), self.px(5)),
                     relief="flat", borderwidth=0)
        # 下拉框:readonly 状态下 ttkbootstrap 用的是主题的 selectbg(#bdc4ca 浅灰),
        # **一聚焦就整块变亮**。实测必须把它 map 回卡片色才不留亮底。
        st.configure("TCombobox", padding=(self.px(6), self.px(3)),
                     fieldbackground=p["card_bg"], background=p["card_bg"],
                     foreground=p["text"], arrowcolor=p["text"],
                     bordercolor=p["border"], lightcolor=p["card_bg"],
                     darkcolor=p["card_bg"])
        st.map("TCombobox",
               fieldbackground=[("readonly", p["card_bg"])],
               selectbackground=[("readonly", p["card_bg"])],
               selectforeground=[("readonly", p["text"])],
               foreground=[("readonly", p["text"])])
        # 卡片表面上的控件:**必须连 background 一起配**。
        # ttkbootstrap 只按 `@card` 表面重烘"图片"(轨道/圆点),**不管控件自己的
        # background** —— 于是轨道上下会露出一条比卡片更深的窗口底色。
        # 实测(竖直剖面,滑条 720x28):
        #     y=0..9   #212529(窗口底色)← 就是这条看着"突兀地深"
        #     y=10..17 #4f5356(轨道图片,= border(card))
        #     y=18..27 #212529
        # 配上 background=card_bg 之后整块才和卡片齐平。
        for name in ("@card.Horizontal.TScale", "@card.Vertical.TScale"):
            st.configure(name, background=p["card_bg"], focuscolor=p["card_bg"],
                         troughcolor=p["card_bg"])
        for name in ("@card.TRadiobutton", "@card.TCheckbutton"):
            st.configure(name, background=p["card_bg"], focuscolor=p["card_bg"])
            st.map(name,
                   background=[("active", p["card_bg"])],
                   indicatorcolor=[("selected", p["accent"]),
                                   ("!selected", p["card_bg"])])
        st.configure("@card.TCombobox", fieldbackground=p["card_bg"],
                     background=p["card_bg"], foreground=p["text"],
                     arrowcolor=p["text"], bordercolor=p["border"])

        st.configure("TSeparator", background=p["border"])
        st.configure("Vertical.TScrollbar", background=p["window_bg"],
                     troughcolor=p["window_bg"], borderwidth=0, arrowsize=self.px(12))
        st.configure("TEntry", fieldbackground=p["card_bg"], foreground=p["text"])

    # ── 给自绘控件用的小工具 ──
    def color(self, key: str) -> str:
        return self.palette.get(key, "#ff00ff")   # 品红 = 明显是漏配了
