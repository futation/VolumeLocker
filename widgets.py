# widgets.py — 自绘控件(Canvas):电平表、状态药丸
#
# 为什么不用 ttk.Progressbar:它由系统主题绘制,颜色/刻度/阈值线全都改不动。
# 而"电平表"是这个软件唯一真正有信息量的视觉元素 —— 信号进了多少、
# 被压到多少、离上限还有多远,全在这张表上。所以它值得用 Canvas 自己画。
#
# 两个约定:
#   * 所有像素尺寸走 `theme.px()` —— 字号是"点"会自动随 DPI 缩放,**像素不会**。
#   * 所有颜色走 `theme.palette` —— 深色/浅色切换时只需 `apply_theme()` 重画。

from __future__ import annotations

import time
import tkinter as tk
from tkinter import font as tkfont

from theme import blend


def rounded_rect(cv: tk.Canvas, x0, y0, x1, y1, r, fill="", outline="",
                 width=1, tags=()):
    """在 Canvas 上画圆角矩形(tkinter 没有现成的)。

    用"两个矩形 + 四个扇形"拼,而不是 smooth 多边形 —— 后者在小圆角上会发虚。
    """
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    d = 2 * r
    items = []
    if fill:
        items.append(cv.create_rectangle(x0 + r, y0, x1 - r, y1,
                                         fill=fill, outline="", tags=tags))
        items.append(cv.create_rectangle(x0, y0 + r, x1, y1 - r,
                                         fill=fill, outline="", tags=tags))
        for box, start in (((x0, y0, x0 + d, y0 + d), 90),
                           ((x1 - d, y0, x1, y0 + d), 0),
                           ((x1 - d, y1 - d, x1, y1), 270),
                           ((x0, y1 - d, x0 + d, y1), 180)):
            items.append(cv.create_arc(*box, start=start, extent=90,
                                       fill=fill, outline="", style="pieslice",
                                       tags=tags))
    if outline and width > 0:
        items.append(cv.create_line(x0 + r, y0, x1 - r, y0, fill=outline,
                                    width=width, tags=tags))
        items.append(cv.create_line(x0 + r, y1, x1 - r, y1, fill=outline,
                                    width=width, tags=tags))
        items.append(cv.create_line(x0, y0 + r, x0, y1 - r, fill=outline,
                                    width=width, tags=tags))
        items.append(cv.create_line(x1, y0 + r, x1, y1 - r, fill=outline,
                                    width=width, tags=tags))
        for box, start in (((x0, y0, x0 + d, y0 + d), 90),
                           ((x1 - d, y0, x1, y0 + d), 0),
                           ((x1 - d, y1 - d, x1, y1), 270),
                           ((x0, y1 - d, x0 + d, y1), 180)):
            items.append(cv.create_arc(*box, start=start, extent=90,
                                       outline=outline, width=width,
                                       style="arc", tags=tags))
    return items


class LevelMeter(tk.Canvas):
    """手绘电平表。

    同一根 -60..0 dBFS 标尺上画三样东西:

      * **输出响度**(渐变填充条):被限幅约束的量,也就是你实际听到的响度
      * **信号峰值**(细游标):进入限幅器之前的原始信号
      * **响度上限**(竖直标线 + 三角):阈值

    这样一来,"衰减"就是那两个量之间的空隙 —— 一眼看懂,
    比并排三行数字直观得多。

    数据由 `set_level()` 推入(界面每 100ms 推一次),不自己起定时器。
    """

    MIN_DB = -60.0
    MAX_DB = 0.0
    SILENCE_DB = -119.0
    PEAK_DECAY_DB_PER_S = 18.0     # 峰值保持游标的回落速度
    GRADIENT_STEPS = 48
    DESIGN_HEIGHT = 52             # 设计稿高度(像素,再乘 DPI 系数)

    def __init__(self, master, theme, **kwargs):
        self.theme = theme
        kwargs.setdefault("height", theme.px(self.DESIGN_HEIGHT))
        super().__init__(master, highlightthickness=0, bd=0,
                         background=theme.color("card_bg"), **kwargs)

        self._out_db = None
        self._signal_db = None
        self._ceiling_db = -6.0
        self._holding = False
        self._peak_db = None
        self._peak_time = 0.0
        self._last_draw = 0.0

        self.bind("<Configure>", lambda e: self._redraw())

    # ── 外观 ──
    def apply_theme(self, theme=None):
        if theme is not None:
            self.theme = theme
        self.configure(background=self.theme.color("card_bg"),
                       height=self.theme.px(self.DESIGN_HEIGHT))
        self._redraw()

    # ── 数据 ──
    def set_level(self, out_db, ceiling_db, signal_db=None, holding=False,
                  force=False):
        """推入一帧数据。out_db/signal_db 为 None 或低于 -119 表示静音。

        `force=True` 跳过下面的合帧节流 —— 截图/测试这类"要立刻看到画面"的
        场合必须用它,否则最后一帧会被静默丢掉(实测踩过:工具灌了数据却截到
        一张空表)。
        """
        now = time.perf_counter()
        self._out_db = out_db
        self._signal_db = signal_db
        self._ceiling_db = ceiling_db
        self._holding = bool(holding)

        live = None if out_db is None or out_db <= self.SILENCE_DB else out_db
        if live is None:
            self._peak_db = None
        elif self._peak_db is None or live > self._peak_db:
            self._peak_db = live
            self._peak_time = now
        else:
            dt = max(0.0, now - self._peak_time)
            self._peak_db = max(live, self._peak_db - self.PEAK_DECAY_DB_PER_S * dt)
            self._peak_time = now

        if force or now - self._last_draw >= 0.025:   # 同一拍内的重复调用合并掉
            self._redraw()

    # ── 坐标换算 ──
    def _x_of(self, db, x0, x1) -> float:
        db = max(self.MIN_DB, min(self.MAX_DB, db))
        return x0 + (db - self.MIN_DB) / (self.MAX_DB - self.MIN_DB) * (x1 - x0)

    def _gradient_color(self, frac: float) -> str:
        """0=低电平(绿) → 1=贴住上限(琥珀)。"""
        frac = max(0.0, min(1.0, frac))
        return blend(self.theme.color("meter_low"),
                     self.theme.color("meter_mid"), frac)

    def _color_at_db(self, db: float) -> str:
        """某一 dB 处该用什么颜色 —— **以"响度上限"为基准**,不是以满刻度为基准。

        第一版按整根 -60..0 的尺子配色,结果 -6 dBFS 的正常输出也把大半条染成
        黄红,看着像一直在报警。现在:下限→上限走完绿→琥珀,**一越线就是纯红**。
        于是"颜色"表达的是"离你设的上限还有多远",和刻度文字各管一件事。
        越线用纯红而不是渐变,是为了不留模糊地带 —— 红 = 没压住。
        """
        ceil_db = max(self.MIN_DB + 1.0, min(self.MAX_DB, self._ceiling_db))
        if db > ceil_db:
            return self.theme.color("meter_high")
        return self._gradient_color((db - self.MIN_DB) / (ceil_db - self.MIN_DB))

    @staticmethod
    def _live(db):
        return None if db is None or db <= LevelMeter.SILENCE_DB else db

    # ── 绘制 ──
    def _redraw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            return
        self._last_draw = time.perf_counter()
        cv = self
        cv.delete("all")

        px = self.theme.px
        p = self.theme.palette
        f_tick = self.theme.font(7)

        x0, x1 = px(2), w - px(2)
        r = px(3)
        bar_top = px(20)
        bar_bot = bar_top + px(16)

        # ── 刻度:文字 + 短刻度线 ──
        for db in range(int(self.MIN_DB), int(self.MAX_DB), 12):
            x = self._x_of(db, x0, x1)
            cv.create_line(x, bar_top - px(6), x, bar_top - px(2),
                           fill=p["tick"], width=1)
            cv.create_text(x, px(5), text=f"{db}", fill=p["tick"],
                           font=f_tick, anchor="n")
        cv.create_text(x1, px(5), text="0 dBFS", fill=p["tick"], font=f_tick,
                       anchor="ne")

        # ── 底轨 ──
        rounded_rect(cv, x0, bar_top, x1, bar_bot, r, fill=p["track"])

        live = self._live(self._out_db)
        sig = self._live(self._signal_db)

        # ── 输出响度:渐变填充(左端用半圆头补齐圆角) ──
        if live is not None:
            xf = self._x_of(live, x0, x1)
            cv.create_arc(x0, bar_top, x0 + 2 * r, bar_bot, start=90, extent=180,
                          fill=self._color_at_db(self.MIN_DB),
                          outline="", style="pieslice")
            body_x0 = x0 + r
            span = xf - body_x0
            if span > 0.5:
                steps = max(1, min(self.GRADIENT_STEPS, int(span / 2) + 1))
                for i in range(steps):
                    sx = body_x0 + span * i / steps
                    ex = body_x0 + span * (i + 1) / steps
                    mid_x = (sx + ex) / 2
                    db_mid = self.MIN_DB + (mid_x - x0) / max(1.0, (x1 - x0)) * (
                        self.MAX_DB - self.MIN_DB)
                    cv.create_rectangle(sx, bar_top, ex + 1, bar_bot,
                                        fill=self._color_at_db(db_mid), outline="")

        # ── 峰值保持游标(细、在条内,只在确实回落过时才画) ──
        if self._peak_db is not None and live is not None and self._peak_db > live + 0.4:
            xp = self._x_of(self._peak_db, x0, x1)
            cv.create_line(xp, bar_top, xp, bar_bot, fill=p["muted"], width=1)

        # ── 信号峰值游标:高对比竖线 + 条下方的小三角 ──
        # 用 text 色(深色模式近白、浅色模式近黑),在整条渐变上都看得清;
        # 三角放在条外,和"上限"的三角方向相反,一眼能分清哪个是哪个。
        if sig is not None:
            xs = self._x_of(sig, x0, x1)
            cv.create_line(xs, bar_top - px(2), xs, bar_bot + px(1),
                           fill=p["text"], width=max(1, px(2)))
            cv.create_polygon(xs, bar_bot + px(6),
                              xs - px(3), bar_bot + px(2),
                              xs + px(3), bar_bot + px(2),
                              fill=p["muted"], outline="")

        # ── 响度上限标线 + 向下的小三角 ──
        xc = self._x_of(self._ceiling_db, x0, x1)
        cv.create_line(xc, bar_top - px(2), xc, bar_bot + px(3),
                       fill=p["accent"], width=max(1, px(2)))
        cv.create_polygon(xc, bar_top - px(2),
                          xc - px(3), bar_top - px(8),
                          xc + px(3), bar_top - px(8),
                          fill=p["accent"], outline="")

        # ── 超限:整条描红。不再画 "OVER" 文字 —— 一来会压在填充条上读不清,
        #    二来红色填充 + 下面变红的"输出响度"数字已经说了两遍,够了。 ──
        if live is not None and live > self._ceiling_db:
            rounded_rect(cv, x0, bar_top, x1, bar_bot, r,
                         outline=p["danger"], width=max(1, px(1)))


class MiniBar(tk.Canvas):
    """细长的**只读**进度条(替代 ttk.Progressbar)。

    为什么不用 ttk.Progressbar:它的槽(trough)也是**图片**,实测 `background`、
    `troughcolor`、`bordercolor` 全改不动 —— 在深色卡片上就是一条突兀的灰条。
    这跟滑条轨道是同一类问题,自己画最省事,还能和主题完全一致。
    """

    DESIGN_HEIGHT = 10

    def __init__(self, master, theme, maximum=100, background_key="card_bg", **kw):
        self.theme = theme
        self.maximum = max(1, int(maximum))
        self._value = 0
        self._bg_key = background_key
        kw.setdefault("height", theme.px(self.DESIGN_HEIGHT))
        super().__init__(master, highlightthickness=0, bd=0,
                         background=theme.color(background_key), **kw)
        self.bind("<Configure>", lambda e: self._redraw())

    def set(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        self._value = max(0.0, min(float(self.maximum), value))
        self._redraw()

    def apply_theme(self, theme=None, background_key=None):
        if theme is not None:
            self.theme = theme
        if background_key:
            self._bg_key = background_key
        self.configure(background=self.theme.color(self._bg_key),
                       height=self.theme.px(self.DESIGN_HEIGHT))
        self._redraw()

    def _redraw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            return
        px = self.theme.px
        self.delete("all")
        r = h / 2
        rounded_rect(self, px(1), px(1), w - px(1), h - px(1), r,
                     fill=self.theme.color("track"))
        frac = self._value / self.maximum
        if frac <= 0:
            return
        fill_w = px(1) + (w - 2 * px(1)) * frac
        rounded_rect(self, px(1), px(1), max(fill_w, px(1) + h), h - px(1), r,
                     fill=self.theme.color("accent"))


class SectionHeader(tk.Frame):
    """可点击的折叠面板标题条:整条可点、有 hover 反馈、箭头跟着开合状态变。

    不用 ttk.Button:那样做不出"整条 + 右侧副标题"的排版,箭头状态也没法跟着变。
    tk.Frame + tk.Label 完全可控(颜色自己管,深色模式下不会露白底)。
    """

    def __init__(self, master, theme, title, subtitle, command,
                 background_key="window_bg"):
        self.theme = theme
        self._bg_key = background_key
        super().__init__(master, background=theme.color(background_key))
        self.title = title
        self.command = command
        self._open = False

        bg = theme.color(background_key)
        # ▼/▲ 是实测在 Microsoft YaHei UI 里有字形的(▶ 没有,会显示成方框)
        self.chevron = tk.Label(self, text="▼", background=bg,
                                foreground=theme.color("hint"),
                                font=theme.font(8))
        self.chevron.pack(side=tk.LEFT, padx=(theme.px(2), theme.px(8)))
        self.title_label = tk.Label(self, text=title, background=bg,
                                    foreground=theme.color("text"),
                                    font=theme.font(10, "bold"))
        self.title_label.pack(side=tk.LEFT)
        self.sub_label = tk.Label(self, text=subtitle or "", background=bg,
                                  foreground=theme.color("hint"),
                                  font=theme.font(8))
        self.sub_label.pack(side=tk.LEFT, padx=(theme.px(10), 0))

        self._parts = (self, self.chevron, self.title_label, self.sub_label)
        for w in self._parts:
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
            w.bind("<Button-1>", self._on_click)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

    # ── 事件 ──
    def _on_click(self, _e=None):
        if self.command:
            self.command()

    def _on_enter(self, _e=None):
        self._paint(blend(self.theme.color(self._bg_key),
                          self.theme.color("accent"), 0.10))

    def _on_leave(self, _e=None):
        # 指针在子控件之间移动也会触发 <Leave>;延后再确认一次,避免闪烁
        self.after(40, self._confirm_leave)

    def _confirm_leave(self):
        try:
            x, y = self.winfo_pointerxy()
            if self.winfo_containing(x, y) in self._parts:
                return
        except Exception:
            pass
        self._paint(self.theme.color(self._bg_key))

    def _paint(self, bg):
        for w in self._parts:
            try:
                w.configure(background=bg)
            except Exception:
                pass

    # ── 状态/外观 ──
    def set_open(self, opened: bool):
        self._open = bool(opened)
        self.chevron.configure(text="▲" if self._open else "▼")

    def apply_theme(self, theme=None, background_key=None):
        if theme is not None:
            self.theme = theme
        if background_key:
            self._bg_key = background_key
        bg = self.theme.color(self._bg_key)
        self._paint(bg)
        self.chevron.configure(foreground=self.theme.color("hint"))
        self.title_label.configure(foreground=self.theme.color("text"))
        self.sub_label.configure(foreground=self.theme.color("hint"))


class StatusPill(tk.Canvas):
    """圆角状态药丸(例如"限幅中""运行中""未启用")。

    比一行灰色斜体字醒目得多,而且颜色本身就能表达状态。
    """

    DESIGN_HEIGHT = 22
    KINDS = ("muted", "ok", "warn", "danger", "accent")
    _KEY = {"muted": "hint", "ok": "ok", "warn": "warn",
            "danger": "danger", "accent": "accent"}

    def __init__(self, master, theme, text="", kind="muted",
                 background_key="window_bg", **kwargs):
        self.theme = theme
        self._bg_key = background_key
        kwargs.setdefault("height", theme.px(self.DESIGN_HEIGHT))
        kwargs.setdefault("width", theme.px(80))
        super().__init__(master, highlightthickness=0, bd=0,
                         background=theme.color(background_key), **kwargs)
        self._text = text
        self._kind = kind
        self._font = None
        self.bind("<Configure>", lambda e: self._redraw())
        self._fit()

    # ── 外观 ──
    def apply_theme(self, theme=None, background_key=None):
        if theme is not None:
            self.theme = theme
            self._font = None
        if background_key:
            self._bg_key = background_key
        self.configure(background=self.theme.color(self._bg_key),
                       height=self.theme.px(self.DESIGN_HEIGHT))
        self._fit()
        self._redraw()

    def set(self, text=None, kind=None):
        if text is not None:
            self._text = text
        if kind is not None and kind in self.KINDS:
            self._kind = kind
        self._fit()
        self._redraw()

    def _font_obj(self):
        if self._font is None:
            self._font = tkfont.Font(font=self.theme.font(8, "bold"))
        return self._font

    def _fit(self):
        """按文字宽度调整画布宽度(药丸要"刚好裹住"文字才有质感)。"""
        want = self._font_obj().measure(self._text or "") + 2 * self.theme.px(10)
        if abs(int(self.cget("width")) - want) > 1:
            self.configure(width=want)

    def _redraw(self):
        cv = self
        cv.delete("all")
        if not self._text:
            return
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            return
        px = self.theme.px
        fg = self.theme.color(self._KEY[self._kind])
        bg = blend(self.theme.color(self._bg_key), fg, 0.16)
        rounded_rect(cv, px(1), px(1), w - px(1), h - px(1),
                     (h - px(2)) / 2, fill=bg, outline=fg, width=1)
        cv.create_text(w / 2, h / 2, text=self._text, fill=fg,
                       font=self.theme.font(8, "bold"), anchor="center")
