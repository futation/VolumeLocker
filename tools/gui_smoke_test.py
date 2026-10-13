#!/usr/bin/env python3
"""
gui_smoke_test.py — 启动 volume_locker 的 GUI 跑几秒,确认没崩、控件都在位。

不做任何音量改动(不勾选启用开关),只验证:
  - 模块导入、配置加载
  - GUI 构建(含限幅控件、两个折叠面板)
  - 折叠面板展开/收起、电平条随模式显示/隐藏
  - 主循环、设备枚举、托盘线程能正常起来
  - 退出路径干净

**配置被重定向到临时目录**(见 _isolate_config),所以:
  * 不会读也不会写用户的 %LOCALAPPDATA%\\VolumeLocker\\config.json
  * 不受"用户自己正在跑本程序"的单实例锁影响,随时可以跑
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
import threading
import time
import traceback

sys.coinit_flags = 0
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台/管道默认按 GBK 编码 stdout,打印 ✓✗ 会 UnicodeEncodeError。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

errors = []


def _isolate_config(vl, tmp_dir):
    """把 APP_DIR / CONFIG_FILE 指到临时目录。

    ConfigManager 与 VolumeLockerApp 都是在**调用时**读这两个模块级全局,
    所以在这里改掉就足够,不必动源代码。
    """
    vl.APP_DIR = tmp_dir
    vl.CONFIG_FILE = os.path.join(tmp_dir, "config.json")


def managed(widget) -> bool:
    """控件是否被 pack/grid 管理(不依赖窗口是否已映射,主循环前也能查)。"""
    return bool(widget.winfo_manager())


def pack_index(widget):
    """控件在父容器 pack 顺序里的位置,不在则返回 -1。"""
    try:
        return widget.master.pack_slaves().index(widget)
    except ValueError:
        return -1


def is_inside(widget, container) -> bool:
    """widget 是否(间接)挂在 container 里 —— 不依赖窗口是否已映射。"""
    w = widget
    while w is not None:
        if w is container:
            return True
        w = getattr(w, "master", None)
    return False


def collect_texts(widget, acc=None):
    """递归收集所有控件上的文字。"""
    if acc is None:
        acc = []
    try:
        t = widget.cget("text")
        if t:
            acc.append(str(t))
    except Exception:
        pass
    for child in widget.winfo_children():
        collect_texts(child, acc)
    return acc


def missing_glyphs(root, families=("Microsoft YaHei UI", "Segoe UI")):
    """找出界面文字里"字体根本没有字形"的符号。

    实测踩过:折叠面板的箭头一开始用的 ▶(U+25B6),在 Microsoft YaHei UI
    (Tk 在中文 Windows 上的默认字体)和 Segoe UI 里**都没有字形**,会渲染成方框。
    GDI 的 GetGlyphIndicesW 在缺字形时返回 0xFFFF,用它查最准。

    CJK 汉字与全角标点不查:它们靠 Windows 的字体链接(MLang)兜底,直接问
    字体本身会误报。
    """
    import ctypes as _ct

    gdi = _ct.WinDLL("gdi32")
    user = _ct.WinDLL("user32")
    hdc = user.GetDC(0)

    def absent_in(family, ch):
        hf = gdi.CreateFontW(20, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, family)
        old = gdi.SelectObject(hdc, hf)
        arr = (_ct.c_ushort * 1)()
        gdi.GetGlyphIndicesW(hdc, ch, 1, arr, 0x0001)   # GGI_MARK_NONEXISTING_GLYPHS
        gdi.SelectObject(hdc, old)
        gdi.DeleteObject(hf)
        return arr[0] == 0xFFFF

    symbols = set()
    for text in collect_texts(root):
        for ch in text:
            o = ord(ch)
            if o < 0x80:
                continue                                  # ASCII 必然有
            if (0x2000 <= o <= 0x206F or 0x3000 <= o <= 0x9FFF
                    or 0xFF00 <= o <= 0xFFEF):
                continue                                  # 标点 / CJK / 全角
            symbols.add(ch)

    bad = sorted(c for c in symbols if all(absent_in(f, c) for f in families))
    user.ReleaseDC(0, hdc)
    return symbols, bad


def main():
    tmp_dir = tempfile.mkdtemp(prefix="vl_smoke_")
    import volume_locker as vl

    _isolate_config(vl, tmp_dir)

    print(f"LIMITER_AVAILABLE = {vl.LIMITER_AVAILABLE}")
    print(f"METER_AVAILABLE   = {vl.METER_AVAILABLE}")
    print(f"APP_VERSION       = {vl.APP_VERSION}")
    print(f"CONFIG_FILE       = {vl.CONFIG_FILE}   (临时,用完删)")
    print()

    try:
        app = vl.VolumeLockerApp()
    except Exception:
        print("构造 VolumeLockerApp 失败:")
        traceback.print_exc()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return 1

    print("VolumeLockerApp 构造成功")
    print(f"  设备数量      : {len(app._device_list)}")
    print(f"  当前默认设备  : {app._current_default_id}")
    print(f"  选中设备      : {app._selected_device_id}")
    print(f"  模式          : {app.mode_var.get()}")
    print(f"  启用          : {app.enable_var.get()}")
    print(f"  基础音量      : {app.base_volume}%")
    print(f"  响度上限      : {app.ceiling_var.get()} dBFS")
    print(f"  释放速率      : {app.release_var.get():.1f} dB/s")
    print(f"  保持时间      : {app.hold_var.get():.1f} s")
    print(f"  音量平滑      : {app.smooth_var.get():.3f} s")
    print(f"  基础音量 dB   : {app.ceiling_db_label.cget('text')}")
    print(f"  外观          : mode={app.theme.appearance} 深色={app.theme.dark} "
          f"DPI系数={app.theme.scale:.2f}")
    print(f"  ttkbootstrap  : {vl.TTKBOOTSTRAP} v{vl.TTKBOOTSTRAP_VERSION}")
    print(f"  状态药丸      : {app.status_pill._text}")
    print()

    # ── 1. 控件存在性 ──
    needed = ["mode_var", "enable_var", "enable_cb", "ceiling_var", "ceiling_scale",
              "ceiling_label", "ceiling_frame", "status_pill",
              "signal_value", "output_value", "atten_value",
              "meter_card", "level_meter",
              "ceiling_db_label", "vol_pct_label", "sys_vol_bar",
              "release_var", "release_scale", "release_label",
              "hold_var", "hold_scale", "hold_label",
              "smooth_var", "smooth_scale", "smooth_label",
              "_advanced_header", "_advanced_frame",
              "_settings_header", "_settings_frame",
              "_bottom_sep", "auto_start_var", "minimize_tray_var",
              "appearance_var", "theme"]
    missing = [n for n in needed if not hasattr(app, n)]
    if missing:
        print(f"✗ 缺少控件: {missing}")
        errors.append(f"missing widgets: {missing}")
    else:
        print("✓ 所有控件均存在")

    # ── 1b. 主题层:调色板必须齐全,否则某处会取到"漏配色" ──
    required_keys = ["window_bg", "card_bg", "border", "text", "muted", "hint",
                     "accent", "accent_fg", "ok", "warn", "danger",
                     "track", "meter_low", "meter_mid", "meter_high", "tick"]
    missing_keys = [k for k in required_keys if k not in app.theme.palette]
    bad_colors = [k for k in required_keys
                  if k in app.theme.palette
                  and not str(app.theme.palette[k]).startswith("#")]
    if missing_keys or bad_colors:
        print(f"✗ 调色板缺项 {missing_keys} 或格式不对 {bad_colors}")
        errors.append(f"palette problems: {missing_keys} {bad_colors}")
    else:
        print(f"✓ 调色板 {len(required_keys)} 项齐全")

    # ── 1c. 界面代码里不许有字面色值(否则切深色必然花) ──
    # 早先只扫 _build_gui,结果 _update_device_status 里藏着 #2E7D32/#C62828
    # 一直没被发现(深色下几乎看不清)。现在扫**整个 volume_locker.py**。
    import inspect
    import re
    src = inspect.getsource(vl.VolumeLockerApp._build_gui)
    whole = Path(vl.__file__).read_text(encoding="utf-8")
    literals = sorted(set(re.findall(r'"#[0-9a-fA-F]{3,8}"', whole)))
    if literals:
        print(f"✗ volume_locker.py 里有硬编码颜色: {literals}")
        errors.append(f"hardcoded colors: {literals}")
    else:
        print("✓ volume_locker.py 全文没有硬编码颜色(全部走主题调色板)")

    # ── 1d. 每一处 style= 都必须是**注册过**的样式名 ──
    # ttkbootstrap 的控件类会静默丢掉未注册的 style=(实测:不报错,直接退回默认
    # 样式),于是"名字写错/漏注册"的表现是颜色悄悄不对。这里把它变成硬失败。
    used = set(re.findall(r'style="([A-Za-z0-9_.]+)"', src))
    unknown = sorted(s for s in used if s not in app.theme.style_names)
    if unknown:
        print(f"✗ 这些 style= 名字没被注册(会被静默丢弃,颜色会不对): {unknown}")
        print(f"   已注册的有: {sorted(app.theme.style_names)}")
        errors.append(f"unregistered styles: {unknown}")
    else:
        print(f"✓ _build_gui 里 {len(used)} 个 style= 名字全部已注册")

    # ── 1e. 声明了 @card 表面的控件,它自己的 background 也必须是卡片色 ──
    # 踩过两次的坑:`bootstyle="@card"` 只会**重烘图片**(轨道/圆点),
    # 不管控件自己的 background —— 于是轨道上下露出一条比卡片更深的窗口底色。
    # 用户两次都是靠眼睛发现的,所以这里把不变量写成断言。
    try:
        st = app.theme.style
        card = app.theme.color("card_bg").lower()
        found, bad = [], []

        def walk(w):
            for c in w.winfo_children():
                try:
                    sty = c.cget("style") or ""
                except Exception:
                    sty = ""
                if "@card" in str(sty):
                    found.append(sty)
                    bg = st.lookup(sty, "background")
                    if bg and str(bg).lower() != card:
                        bad.append(f"{c.winfo_class()} {sty}: background={bg} ≠ {card}")
                walk(c)

        walk(app.root)
        if not vl.TTKBOOTSTRAP:
            # 轻量模式下没有 ttkbootstrap,`bootstyle` 会被替身吃掉 —— 不适用
            print("- 轻量模式(无 ttkbootstrap),跳过 @card 表面检查")
        elif bad:
            print(f"✗ 声明了 @card 但 background 不是卡片色: {bad}")
            errors.append(f"@card background mismatch: {bad}")
        elif not found:
            print("✗ 界面上找不到任何 @card 控件(表面声明可能被丢掉了)")
            errors.append("no @card widgets")
        else:
            print(f"✓ {len(found)} 处 @card 表面声明,background 都等于卡片色 {card}")
    except Exception as e:
        print(f"✗ @card 表面检查异常: {e}")
        errors.append(f"@card surface check raised: {e}")

    # ── 1f. DeviceLimiter 必须从构造起就带齐"界面要读的字段" ──
    # 踩过:output_dbfs/attenuation_db 原本只在"限幅分支"里创建,而 __init__
    # 里那段初始化因为 _clock() 被插在中间而成了死代码。启动即锁定模式时
    # 界面读不到它们 -> AttributeError -> 整个音频控制停摆。
    try:
        probe_lim = vl.DeviceLimiter(None, None, vl.LoudnessLimiter,
                                     vl.LoudnessConfig())
        must_have = ["signal_dbfs", "output_dbfs", "attenuation_db",
                     "volume_db", "limiting", "base_volume_db",
                     "lock_target_db", "mode"]
        gone = [n for n in must_have if not hasattr(probe_lim, n)]
        if gone:
            print(f"✗ DeviceLimiter 构造后缺这些字段(界面会读它们): {gone}")
            errors.append(f"DeviceLimiter missing attrs: {gone}")
        else:
            print(f"✓ DeviceLimiter 构造后字段齐全({len(must_have)} 项,含界面要读的)")
    except Exception as e:
        print(f"✗ DeviceLimiter 字段检查异常: {e}")
        errors.append(f"DeviceLimiter attrs check raised: {e}")

    # ── 1g. 上限滑条下限必须与电平表刻度下限一致 ──
    # 不一致的话:要么上限线画不出来(超出表的量程),要么表上留一段永远用不到。
    try:
        from loudness_limiter import DEFAULT_MAX_ATTENUATION_DB
        lo = float(app.ceiling_scale.cget("from"))
        meter_min = vl.LevelMeter.MIN_DB
        max_att = DEFAULT_MAX_ATTENUATION_DB
        if abs(lo - meter_min) > 0.01:
            print(f"✗ 上限滑条下限 {lo} 与电平表刻度下限 {meter_min} 不一致")
            errors.append(f"ceiling min {lo} != meter min {meter_min}")
        elif max_att < abs(lo) - 0.01:
            print(f"✗ max_attenuation {max_att} < |滑条下限 {lo}|,最严那端压不到")
            errors.append(f"max_attenuation {max_att} < {abs(lo)}")
        else:
            print(f"✓ 上限范围 {lo:.0f}..{float(app.ceiling_scale.cget('to')):.0f} dBFS"
                  f" 与电平表刻度一致,且 max_attenuation={max_att:.0f} 够用")
    except Exception as e:
        print(f"✗ 上限范围一致性检查异常: {e}")
        errors.append(f"ceiling range check raised: {e}")

    # ── 1h. 音量平滑:范围 0..0.5、步进 0.01、越界与"拖拽残渣"会被归整 ──
    # 旧滑条是 0..1 且没有分辨率(ttk.Scale 没有 resolution 选项),
    # 所以配置里会留下 0.011037593818985 这种值。而且——在修掉"滤波偷乘
    # 释放速率"之前——大 tau 会让恢复慢到"爆炸之后声音回不来"。
    try:
        lo = float(app.smooth_scale.cget("from"))
        hi = float(app.smooth_scale.cget("to"))
        app._on_smooth_change(0.237)                    # 步进:应归到 0.24
        stepped = app.volume_filter_seconds
        snapped = vl.DeviceLimiter.clamp_filter_seconds(0.011037593818985)
        clamped = vl.DeviceLimiter.clamp_filter_seconds(99.0)
        row = [("范围下限", lo, 0.0), ("范围上限", hi, 0.5),
               ("步进归整 0.237", stepped, 0.24),
               ("残渣归整 0.0110375", snapped, 0.01),
               ("越界夹取 99", clamped, 0.5)]
        bad = [(n, v, w) for n, v, w in row if abs(v - w) > 1e-9]
        # 还原:后面还有一条断言在查三个高级滑条的默认值
        app._on_smooth_change(vl.DeviceLimiter.VOLUME_FILTER_SECONDS)
        if bad:
            print(f"✗ 音量平滑滑条不对: {bad}")
            errors.append(f"smooth slider: {bad}")
        else:
            print("✓ 音量平滑 0..0.5 / 步进 0.01 / 越界与残渣值都会归整")
    except Exception as e:
        print(f"✗ 音量平滑滑条检查异常: {e}")
        errors.append(f"smooth slider check raised: {e}")

    # ── 1i. 图标:窗口图标与托盘图标必须是**同一个文件**,而且得是真 ICO ──
    # 踩过(实测):
    #   * 用户给的 dist\VolumeControl.ico **其实是一张 PNG**(只改了扩展名);
    #   * `root.iconbitmap()` 对这种文件**不报错**(它只检查文件存在,
    #     缺失的文件才会抛 TclError)—— 所以"没报错"证明不了图标生效;
    #   * 托盘用 PIL 读同一个文件,转不成图标时会**静默**退回内置方块。
    # 因此断言只能落在"文件本身是真 ICO"+"两处读的是同一个常量"上。
    try:
        from PIL import Image as _Image
        ico = vl.ICO_PATH
        ok_exists = os.path.exists(ico)
        head = b""
        if ok_exists:
            with open(ico, "rb") as f:
                head = f.read(4)
        is_real_ico = head[:4] == b"\x00\x00\x01\x00"          # ICONDIR
        file_img = _Image.open(ico) if ok_exists else None
        sizes = sorted(file_img.ico.sizes()) if file_img else []
        multi_size = len(sizes) >= 4            # 托盘 16 到资源管理器 256
        # 正向:能被 Tk 接受
        apply_ok = True
        try:
            app.root.iconbitmap(ico)
        except Exception:
            apply_ok = False
        # 反向对照:缺失的文件**必须**报错 —— 证明"接受"这条不是空探针
        reject_missing = False
        try:
            app.root.iconbitmap(os.path.join(
                os.environ.get("TEMP", "."), "vl_no_such_icon_xyz.ico"))
        except Exception:
            reject_missing = True
        app.root.iconbitmap(ico)                # 复位
        # 托盘:比对它载入的图像与文件里的图像 —— 尺寸不同就说明走了兜底方块(64×64)
        tray = vl.SystemTrayManager(app)._load_icon()
        same_for_tray = bool(file_img) and tray.size == file_img.size
        checks = [("图标文件存在", ok_exists),
                  ("是真正的 ICO(不是改名的 PNG)", is_real_ico),
                  ("含多档尺寸(托盘 16 → 大图标 256)", multi_size),
                  ("Tk 能接受(缺失文件则会报错,已反向验证)", apply_ok and reject_missing),
                  ("托盘与窗口同源(同一个 ICO_PATH)", same_for_tray)]
        bad = [n for n, v in checks if not v]
        if bad:
            print(f"✗ 图标不合格: {bad}  (ICO_PATH={ico}, 尺寸={tray.size} vs 文件 "
                  f"{file_img.size if file_img else None}, 档位={sizes})")
            errors.append(f"icon: {bad}")
        else:
            print(f"✓ 窗口图标与托盘图标同源、是真 ICO、含 {len(sizes)} 档尺寸 "
                  f"(最大 {sizes[-1][0]}×{sizes[-1][1]})")
    except Exception as e:
        print(f"✗ 图标检查异常: {e}")
        errors.append(f"icon check raised: {e}")

    # ── 1j. 开机自启:命令必须带 --tray(只进托盘),普通启动要显示窗口 ──
    # 用户要求:自启时后台工作、不弹界面;双击 exe 时才弹。
    # 这里**不碰注册表**,只验证"命令里有没有那个标志"这条纯字符串事实。
    try:
        cmd = vl.ConfigManager._autostart_command()
        has_flag = vl.AUTOSTART_FLAG in cmd
        normal_visible = bool(app.root.winfo_viewable())
        hidden_default = (app.start_hidden is False)
        checks = [("自启命令含 --tray", has_flag),
                  ("默认启动不隐藏(双击 exe 要弹界面)", hidden_default),
                  ("默认启动窗口可见", normal_visible)]
        bad = [n for n, v in checks if not v]
        if bad:
            print(f"✗ 自启/启动方式不对: {bad}  (命令={cmd!r}, "
                  f"start_hidden={app.start_hidden}, viewable={normal_visible})")
            errors.append(f"autostart: {bad}")
        else:
            print(f"✓ 自启命令带 {vl.AUTOSTART_FLAG}(后台),普通启动显示窗口")
    except Exception as e:
        print(f"✗ 自启标志检查异常: {e}")
        errors.append(f"autostart check raised: {e}")

    # ── 2. "退出应用"按钮必须已被移除(改由托盘菜单退出) ──
    if hasattr(app, "exit_btn"):
        print("✗ 底部仍存在 exit_btn(退出按钮应已删除)")
        errors.append("exit_btn still present")
    elif not hasattr(app, "_full_exit"):
        print("✗ 退出路径 _full_exit 丢失")
        errors.append("_full_exit missing")
    else:
        print("✓ 退出按钮已移除,托盘退出路径 _full_exit 仍在")

    # ── 3. 两个折叠面板默认收起,展开后紧贴各自的按钮 ──
    if managed(app._advanced_frame) or managed(app._settings_frame):
        print("✗ 折叠面板默认应该是收起的")
        errors.append("panels not collapsed by default")
    else:
        print("✓ 高级设置 / 设置 两个面板默认收起")

    try:
        app._toggle_advanced()
        app._toggle_settings()
        ok = managed(app._advanced_frame) and managed(app._settings_frame)
        # 展开后必须紧跟自己的标题条(而不是被排到最末尾)
        order_ok = (pack_index(app._advanced_frame) == pack_index(app._advanced_header) + 1
                    and pack_index(app._settings_frame) == pack_index(app._settings_header) + 1)
        if not ok or not order_ok:
            print(f"✗ 展开异常: managed={ok} order={order_ok}")
            errors.append("panel expand failed")
        else:
            print("✓ 展开后面板紧跟按钮,顺序正确")
        # 三个滑条确实落在高级设置面板里
        sliders = [("释放速率", app.release_scale), ("保持时间", app.hold_scale),
                   ("音量平滑", app.smooth_scale)]
        stray = [n for n, w in sliders if not is_inside(w, app._advanced_frame)]
        if stray:
            print(f"✗ 这些滑条不在高级设置面板里: {stray}")
            errors.append(f"sliders outside advanced panel: {stray}")
        else:
            print("✓ 三个滑条都在高级设置面板内")

        # 设置面板里是那两条勾选栏
        texts = []
        for child in app._settings_frame.winfo_children():
            try:
                if child.winfo_class() == "TCheckbutton":
                    texts.append(child.cget("text"))
            except Exception:
                pass
        if len(texts) != 2 or "开机自动启动" not in texts[0]:
            print(f"✗ 设置面板勾选栏不对: {texts}")
            errors.append(f"settings checkboxes wrong: {texts}")
        else:
            print(f"✓ 设置面板两条勾选栏: {texts}")

        app._toggle_advanced()
        app._toggle_settings()
        if managed(app._advanced_frame) or managed(app._settings_frame):
            print("✗ 再次点击应收起")
            errors.append("panel collapse failed")
        else:
            print("✓ 再次点击可收起")
    except Exception as e:
        print(f"✗ 折叠面板回调异常: {e}")
        errors.append(f"panel toggle raised: {e}")

    # ── 4. 电平表卡片:限幅模式显示,锁定模式隐藏 ──
    try:
        app.mode_var.set(vl.MODE_LIMIT)
        app._on_mode_change()
        # 锁定模式下"只对限幅有意义"的三块都要隐藏,并且要能插回原位
        group = [("响度上限卡片", app.ceiling_frame, app._bv_card),
                 ("电平表卡片", app.meter_card, app._bottom_sep),
                 ("高级设置标题条", app._advanced_header, app._settings_header)]
        shown = all(managed(w) for _, w, _ in group)
        app.mode_var.set(vl.MODE_LOCK)
        app._on_mode_change()
        hidden = not any(managed(w) for _, w, _ in group)
        app.mode_var.set(vl.MODE_LIMIT)
        app._on_mode_change()
        back = all(managed(w) for _, w, _ in group)
        order_bad = [n for n, w, anchor in group
                     if pack_index(w) != pack_index(anchor) - 1]
        if not (shown and hidden and back):
            print(f"✗ 随模式显隐异常: limit={shown} lock={hidden} back={back}")
            errors.append("mode visibility wrong")
        elif order_bad:
            print(f"✗ 这些控件没插回原位: {order_bad}")
            errors.append(f"re-pack order wrong: {order_bad}")
        else:
            print("✓ 响度上限/电平表/高级设置:限幅显示 / 锁定隐藏 / 各自插回原位")
    except Exception as e:
        print(f"✗ 模式显隐异常: {e}")
        errors.append(f"mode visibility raised: {e}")

    # ── 4a2. 锁定时展开高级设置也不许把它放出来 ──
    try:
        app.mode_var.set(vl.MODE_LOCK)
        app._on_mode_change()
        if app._advanced_open:
            app._toggle_advanced()          # 先收起,保证起点确定
        app._toggle_advanced()              # 尝试展开
        leaked = managed(app._advanced_frame) or managed(app._advanced_header)
        if leaked:
            print("✗ 锁定模式下高级设置仍被放出来了")
            errors.append("advanced panel leaked in lock mode")
        else:
            print("✓ 锁定模式下展开高级设置也不会显示(隐藏优先)")
        app._toggle_advanced()              # 取消刚才的展开意图
        app.mode_var.set(vl.MODE_LIMIT)
        app._on_mode_change()
    except Exception as e:
        print(f"✗ 锁定模式高级设置检查异常: {e}")
        errors.append(f"lock-mode advanced check raised: {e}")

    # ── 4a3. 🔴 "设置"面板与模式无关:锁定模式下必须照样能打开 ──
    # 踩过:把"只在限幅下存在"的闸门写进了公共的 _set_panel_open(),
    # 结果锁定模式下点"设置"什么都不出来(面板没被 pack),用户报"设置界面是空的"。
    try:
        app.mode_var.set(vl.MODE_LOCK)
        app._on_mode_change()
        if app._settings_open:
            app._toggle_settings()
        app._toggle_settings()
        opened = managed(app._settings_frame)
        # 面板里必须真有东西(三条:外观行 + 两个勾选),而不是一个空壳
        kids = [c for c in app._settings_frame.winfo_children() if c.winfo_manager()]
        combo_ok = app.appearance_combo.cget("values") and app.appearance_combo.get()
        if not opened or len(kids) < 3 or not combo_ok:
            print(f"✗ 锁定模式下设置面板打不开或内容为空: opened={opened} "
                  f"子控件={len(kids)} 下拉值={combo_ok!r}")
            errors.append("settings panel unusable in lock mode")
        else:
            print(f"✓ 锁定模式下设置面板可正常展开({len(kids)} 个子控件,"
                  f"外观下拉有值)")
        app._toggle_settings()
        app.mode_var.set(vl.MODE_LIMIT)
        app._on_mode_change()
    except Exception as e:
        print(f"✗ 锁定模式设置面板检查异常: {e}")
        errors.append(f"settings-in-lock check raised: {e}")

    # ── 4a4. 🔴 模式必须能记住(全局偏好),不能被"换设备"重置 ──
    # 踩过:mode 存在 devices[<id>] 里,蓝牙耳机一掉线就换了设备,
    # 于是"上次退出前是音量锁定"变成默认的响度限幅。
    try:
        app.mode_var.set(vl.MODE_LOCK)
        app._on_mode_change()
        saved = app.config.get("mode")
        reloaded = vl.ConfigManager.load().get("mode")
        # 再选一次设备(模拟重启时选设备),模式不能被设备级的旧值覆盖
        if app._selected_device_id:
            app._select_device(app._selected_device_id)
        still_lock = (app.mode == vl.MODE_LOCK)
        if saved != vl.MODE_LOCK or reloaded != vl.MODE_LOCK:
            print(f"✗ 模式没被持久化: config={saved!r} 重新加载={reloaded!r}")
            errors.append(f"mode not persisted: {saved!r}/{reloaded!r}")
        elif not still_lock:
            print(f"✗ 选设备后模式被改回 {app.mode!r}(应该保持 lock)")
            errors.append("mode clobbered by device select")
        else:
            print("✓ 模式记住为 lock:已写入配置、重新加载仍是 lock、"
                  "换设备也不会被覆盖")
        app.mode_var.set(vl.MODE_LIMIT)
        app._on_mode_change()
    except Exception as e:
        print(f"✗ 模式持久化检查异常: {e}")
        errors.append(f"mode persistence check raised: {e}")

    # ── 4a5. 🔴 锁定模式下的限幅器"没有输出响度/衰减"字段,界面不许因此炸 ──
    # 这是用户报的"切到响度限幅但整个软件不工作"的直接原因。
    try:
        class _LockStub:
            """模拟真实的锁定态 DeviceLimiter:有 _lim,但**没有**
            output_dbfs / attenuation_db(它们只在限幅分支里产生)。"""
            mode = vl.MODE_LOCK
            ready = True
            _lim = None
            signal_dbfs = -25.0

        real_lim = app._limiter
        app._limiter = _LockStub()
        app.limiter_enabled = True
        app._update_limiter_meter(True)       # 不许抛异常
        app._limiter = real_lim
        print("✓ 锁定态限幅器缺 output_dbfs/attenuation_db 时,界面刷新不炸")
    except Exception as e:
        print(f"✗ 锁定态限幅器把界面刷新搞炸了: {type(e).__name__}: {e}")
        errors.append(f"lock-mode meter refresh raised: {e}")

    # ── 4a6. 🔴 界面刷新出错绝不能停掉音频控制 ──
    # 旧代码 `except: polling_active = False`,而 polling_active 同时是
    # 轮询线程与控制环线程的循环条件 —— 界面小错会变成"整个软件不工作"。
    try:
        class _BoomStub:
            ready = True
            _lim = None
            signal_dbfs = -25.0

            @property
            def mode(self):
                raise RuntimeError("模拟界面刷新时的任意错误")

        real_lim = app._limiter
        app._limiter = _BoomStub()
        app.polling_active = True
        app._update_ui()                       # 内部抛异常也会被吃掉并记日志
        survived = app.polling_active
        app._limiter = real_lim
        app.polling_active = True
        if not survived:
            print("✗ 界面刷新出错把 polling_active 打成 False(整个音频控制会停摆)")
            errors.append("UI error killed polling_active")
        else:
            print("✓ 界面刷新出错不停音频控制(polling_active 保持 True)")
    except Exception as e:
        app.polling_active = True
        print(f"✗ 界面刷新健壮性检查异常: {e}")
        errors.append(f"ui robustness check raised: {e}")

    # ── 4a7. 上限高于"基础音量对应的 dB"时必须提示 ──
    # 上限改成绝对 dBFS 之后的新坑:输出最高只到 base_db,上限比它高就永不触发。
    try:
        base_db = app._ceiling_db_for_percent(app.base_volume)
        app.ceiling_var.set(0)
        app._on_ceiling_change(0)                     # 0 dBFS 远高于 base_db
        warned = bool(app.ceiling_warn.winfo_manager())
        low = int(base_db) - 10
        app.ceiling_var.set(low)
        app._on_ceiling_change(low)                   # 低于 base_db -> 不该提示
        cleared = not app.ceiling_warn.winfo_manager()
        if not (warned and cleared):
            print(f"✗ 上限越界提示不对: 高于base时提示={warned} 低于base时消失={cleared} "
                  f"(base_db={base_db:.2f})")
            errors.append("ceiling warning wrong")
        else:
            print(f"✓ 上限高于基础音量({base_db:.1f} dB)会提示,拖到其下即消失")
    except Exception as e:
        print(f"✗ 上限越界提示检查异常: {e}")
        errors.append(f"ceiling warning check raised: {e}")

    # ── 4b. 电平表真的会画(给一帧数据,元素数量必须涨起来) ──
    try:
        meter = app.level_meter
        meter.set_level(None, -20.0, None, False, force=True)
        idle = len(meter.find_all())
        meter.set_level(-14.0, -20.0, -4.0, True, force=True)
        loud = len(meter.find_all())
        # 超限时应该出现"纯红"填充 + 红色描边
        red = app.theme.color("meter_high")
        fills = [meter.itemcget(i, "fill") for i in meter.find_all()
                 if meter.type(i) in ("rectangle", "arc")]
        if loud <= idle or red not in fills:
            print(f"✗ 电平表没画出来: 空={idle} 满={loud} 含纯红={red in fills}")
            errors.append("level meter not drawing")
        else:
            print(f"✓ 电平表绘制正常(空 {idle} 元素 → 满 {loud} 元素,超限有纯红)")
    except Exception as e:
        print(f"✗ 电平表绘制异常: {e}")
        errors.append(f"level meter draw raised: {e}")

    # ── 4c. 外观切换:浅↔深必须真的改到调色板和画布背景 ──
    try:
        app.theme.set_appearance("light")
        app._apply_theme_to_widgets()
        light_bg = app.canvas.cget("background")
        app.theme.set_appearance("dark")
        app._apply_theme_to_widgets()
        dark_bg = app.canvas.cget("background")
        app._on_appearance_change()          # 走一遍真实回调(含存配置)
        saved = app.config.get("appearance")
        if light_bg == dark_bg or saved not in vl.APPEARANCE_CHOICES:
            print(f"✗ 外观切换无效: light={light_bg} dark={dark_bg} saved={saved}")
            errors.append("appearance switch ineffective")
        else:
            print(f"✓ 外观切换有效(浅 {light_bg} / 深 {dark_bg},已存 config={saved})")
    except Exception as e:
        print(f"✗ 外观切换异常: {e}")
        errors.append(f"appearance switch raised: {e}")

    # ── 5. 三个滑条的默认值(临时配置 = 全新用户) ──
    if app._selected_device_id:
        wants = [("释放速率", app.release_db_per_s, vl.DEFAULT_RELEASE_DB_PER_S),
                 ("保持时间", app.hold_seconds, vl.DEFAULT_HOLD_SECONDS),
                 ("音量平滑", app.volume_filter_seconds,
                  vl.DeviceLimiter.VOLUME_FILTER_SECONDS)]
        bad = [f"{n}={got}" for n, got, want in wants if abs(got - want) > 1e-9]
        want_str = " / ".join(f"{w:.3f}" for _, _, w in wants)
        if bad:
            print(f"✗ 默认值不对: {bad} (应为 {want_str})")
            errors.append(f"defaults wrong: {bad}")
        else:
            print(f"✓ 三个滑条默认值 = {want_str} (dB/s, s, s)")
    else:
        print("- 没找到活跃设备,跳过默认值检查")

    # ── 6. dB 换算合理性:基础音量百分比应落在端点范围内 ──
    scale = app._endpoint_scale()
    pct = app.base_volume
    db = app._ceiling_db_for_percent(pct)
    print(f"  换算校验: {pct}% -> {db:.2f} dB  (端点范围 {scale.min_db}..{scale.max_db})")
    if not (scale.min_db - 0.01 <= db <= scale.max_db + 0.01):
        print(f"✗ dB 换算超出端点范围: {db}")
        errors.append(f"dB out of range: {db}")

    # 上限滑条范围应覆盖 dBFS 有效区间
    lo = float(app.ceiling_scale.cget("from"))
    hi = float(app.ceiling_scale.cget("to"))
    print(f"  上限滑条范围  : {lo:.0f} .. {hi:.0f} dBFS")
    if not (lo <= app.ceiling_dbfs <= hi):
        print(f"✗ 当前上限 {app.ceiling_dbfs} 不在滑条范围内")
        errors.append("ceiling out of slider range")

    # ── 7. 各回调不应抛异常 ──
    try:
        app.mode_var.set(vl.MODE_LOCK)
        app._on_mode_change()
        app.mode_var.set(vl.MODE_LIMIT)
        app._on_mode_change()
        print("✓ 模式切换回调正常")
    except Exception as e:
        print(f"✗ 模式切换回调异常: {e}")
        errors.append(f"mode switch raised: {e}")

    try:
        app._on_ceiling_change(-15)
        print(f"✓ 上限滑条回调正常 -> {app.ceiling_dbfs:.0f} dBFS")
    except Exception as e:
        print(f"✗ 上限滑条回调异常: {e}")
        errors.append(f"ceiling change raised: {e}")

    try:
        app._on_release_change(0.5)
        app._on_hold_change(5.0)
        app._on_smooth_change(0.10)
        print(f"✓ 释放/保持/平滑回调正常 -> {app.release_db_per_s:.1f} dB/s, "
              f"{app.hold_seconds:.1f} s, {app.volume_filter_seconds:.2f} s")
        if (abs(app.release_db_per_s - 0.5) > 1e-6
                or abs(app.hold_seconds - 5.0) > 1e-6
                or abs(app.volume_filter_seconds - 0.10) > 1e-6):
            errors.append("release/hold/smooth callback did not take effect")
    except Exception as e:
        print(f"✗ 释放/保持/平滑回调异常: {e}")
        errors.append(f"release/hold/smooth callback raised: {e}")

    # ── 8. 界面上的符号必须真的有字形(否则显示成方框) ──
    try:
        symbols, bad = set(), set()
        # 展开态 / 收起态各查一次:折叠按钮的箭头文字在这两个状态下不一样
        for _ in range(2):
            s, b = missing_glyphs(app.root)
            symbols |= s
            bad |= set(b)
            app._toggle_advanced()
            app._toggle_settings()
        print(f"  界面非 CJK 符号: {' '.join(sorted(symbols)) or '(无)'}")
        if bad:
            print(f"✗ 这些符号在 UI 字体里没有字形,会显示成方框: {sorted(bad)}")
            errors.append(f"missing glyphs: {sorted(bad)}")
        else:
            print("✓ 所有符号都有字形(不会出方框)")
    except Exception as e:
        print(f"✗ 字形检查异常: {e}")
        errors.append(f"glyph check raised: {e}")

    # ── 9. 死代码审计:函数里"return/raise/continue/break 之后还有语句" ──
    # 这类 bug 的杀伤力远超它看起来的样子:VolumeLocker 的 _clock() 曾经被插进
    # __init__ 中间,它 return 之后那一整段初始化全成了死代码(界面要读的
    # output_dbfs/attenuation_db 从未被创建),而症状是"整个音频控制停摆"。
    try:
        import ast

        TERMINAL = (ast.Return, ast.Raise, ast.Continue, ast.Break)

        def scan_unreachable(path):
            hits = []
            tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)

            def check(body, where):
                for i, node in enumerate(body):
                    if isinstance(node, TERMINAL):
                        rest = body[i + 1:]
                        # 后面只剩 docstring 不算
                        only_doc = rest and all(
                            isinstance(n, ast.Expr)
                            and isinstance(n.value, ast.Constant)
                            and isinstance(n.value.value, str) for n in rest)
                        if rest and not only_doc:
                            hits.append(f"{path}:{node.lineno} 在 {where} 里")
                        return

            class V(ast.NodeVisitor):
                def visit_FunctionDef(self, node):
                    check(node.body, node.name)
                    self.generic_visit(node)

                visit_AsyncFunctionDef = visit_FunctionDef

            V().visit(tree)
            return hits

        project = Path(__file__).resolve().parent.parent
        dead = []
        for rel in ("volume_locker.py", "theme.py", "widgets.py",
                    "loudness_limiter.py", "volume_limiter.py"):
            dead += scan_unreachable(str(project / rel))
        if dead:
            print(f"✗ 发现死代码(这些语句永远执行不到): {dead}")
            errors.append(f"dead code: {dead}")
        else:
            print("✓ 无死代码(5 个源文件里没有 return 之后还跟着语句的函数)")
    except Exception as e:
        print(f"✗ 死代码审计异常: {e}")
        errors.append(f"dead code audit raised: {e}")

    def shutdown():
        time.sleep(3.0)
        print()
        print("触发退出...")
        try:
            app.root.after(0, app._full_exit)
        except Exception as e:
            print(f"退出失败: {e}")
            errors.append(str(e))

    threading.Thread(target=shutdown, daemon=True).start()

    try:
        app.run()
        print("主循环已正常退出")
    except Exception:
        print("主循环异常:")
        traceback.print_exc()
        errors.append("mainloop raised")

    shutil.rmtree(tmp_dir, ignore_errors=True)

    print()
    print("=" * 56)
    if errors:
        print(f"✗ 冒烟测试失败: {errors}")
        return 1
    print("✓ GUI 冒烟测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
