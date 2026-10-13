#!/usr/bin/env python3
"""验证**冻结版** dist\\VolumeLocker.exe 真的能用。

为什么需要它
====================================================================
打包最常见的失败不是"构建报错",而是"构建成功、双击没反应":漏了某个隐式
依赖、comtypes 在只读目录里生成不了模块、图标没进包、界面库资源缺失……
这些在构建日志里全都看不出来。而它偏偏是个**托盘程序**:没有控制台,
崩了连痕迹都没有。所以必须由外部驱动 + 客观断言。

做法(每条都有断言,不靠眼睛)
====================================================================
1. **隔离**:把子进程的 `LOCALAPPDATA` 指到临时目录再启动 —— 于是它既不读
   也不写用户的 config.json,也不会撞上用户正在运行的那个实例的
   `msvcrt` 文件锁(那是 OS 级锁,进程一死就释放,所以能连测两次)。
2. **两次启动**:
   A. 冷启动(无配置):量冷启动耗时、等窗口出现、查窗口标题 / 托盘窗口类 /
      日志里的图标与设备注册行、查配置是否落盘(证明 pycaw/COM 枚举活了)。
   B. 热启动(写好配置 enabled=true + 基础音量):**先把真实音量挪开 20%**,
      再让应用把它写回基础音量 —— 这一步同时证明 COM 枚举、接口 Activate、
      控制环、音量写入四件事都活着(任何一件坏了,exe 就只是"能开窗但没用")。
3. **安全**:退出前把真实音量恢复原值,并比对用户 config.json 的 mtime+大小,
   确认整个验证过程没碰过它。

用法
====================================================================
    .\\.venv\\Scripts\\python.exe tools\\verify_exe.py [--shot 路径]
"""

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXE = ROOT / "dist" / "VolumeLocker.exe"
WINDOW_TITLE_PREFIX = "VolumeLocker v"
WM_GETICON, ICON_BIG, ICON_SMALL = 0x007F, 1, 0
POLL_S = 0.25
WINDOW_TIMEOUT_S = 60.0        # onefile 冷启动要解包,给足时间
SETTLE_S = 6.0                 # 等控制环跑几拍

user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f"   [{detail}]" if detail else ""))
    return bool(ok)


def pids_of_tree(pid):
    """onefile 的 exe 是**父子两个进程**(引导进程解包后再起一个跑 Python),
    窗口/托盘都属于子进程 —— 只按启动时那个 PID 找窗口会永远找不到。"""
    import psutil
    pids = {pid}
    try:
        pids |= {c.pid for c in psutil.Process(pid).children(recursive=True)}
    except Exception:
        pass
    # 再兜一次:同名的所有进程(父子都可能改了名字查询的时机)
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["name"] and p.info["name"].lower() == EXE.name.lower():
                pids.add(p.info["pid"])
        except Exception:
            pass
    return pids


def windows_of_tree(pid):
    out = []
    for p in pids_of_tree(pid):
        out += windows_of_pid(p)
    return out


def exe_version_and_icons(path):
    """用 pefile 读版本资源与图标条目(不调 PowerShell:它的输出编码会炸)。"""
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    icons, version = 0, {}
    try:
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        for entry in getattr(pe, "DIRECTORY_ENTRY_RESOURCE", []).entries:
            if entry.id == 3:                       # RT_ICON
                for sub in entry.directory.entries:
                    for lang in sub.directory.entries:
                        icons += 1
            elif entry.id == 16:                    # RT_VERSION
                for sub in entry.directory.entries:
                    for lang in sub.directory.entries:
                        d = lang.data.struct
                        data = pe.get_data(d.OffsetToData, d.Size)
                        # 从 VS_VERSIONINFO 里粗暴捞 UTF-16 字符串
                        txt = data.decode("utf-16-le", errors="ignore")
                        for key in ("FileVersion", "ProductName", "FileDescription"):
                            i = txt.find(key)
                            if i >= 0:
                                version[key] = txt[i + len(key):i + len(key) + 24] \
                                    .strip("\x00 ").split("\x00")[0]
    finally:
        pe.close()
    return icons, version


def windows_of_pid(pid):
    """列出该进程的所有顶层窗口(标题 / 类名 / 是否可见)。"""
    found = []

    def cb(hwnd, _lparam):
        wpid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, title, n + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        found.append({"hwnd": hwnd, "title": title.value, "cls": cls.value,
                      "visible": bool(user32.IsWindowVisible(hwnd))})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", default="", help="把冻结版窗口截图存到这里")
    ap.add_argument("--keep", action="store_true", help="保留临时目录(排查用)")
    args = ap.parse_args()

    print("=" * 76)
    print("冻结版 exe 验证")
    print("=" * 76)

    # ── 0. 文件本身 ──
    print("\n[0] exe 本体")
    if not EXE.exists():
        print(f"  ✗ 找不到 {EXE},先打包:打包VolumeLocker.bat")
        return 1
    size_mb = EXE.stat().st_size / 1024 / 1024
    check("exe 存在", True, f"{size_mb:.2f} MB")

    # exe 里的图标资源必须是多尺寸(托盘 16 → 资源管理器 256),否则会糊
    try:
        icons, ver = exe_version_and_icons(EXE)
        check("exe 内嵌了多尺寸图标", icons >= 4, f"{icons} 个 RT_ICON 条目")
        check("版本资源可用", bool(ver.get("FileVersion")),
              f"FileVersion={ver.get('FileVersion', '?')} / "
              f"{ver.get('FileDescription', '?')}")
    except Exception as e:
        check("exe 资源检查", False, f"{type(e).__name__}: {e}")

    # ── 1. 记录真实环境(末尾必须原样恢复) ──
    import volume_locker as vl

    audio = vl.AudioController()
    dev = audio.get_default_device_id()
    orig_vol = audio.get_device_volume(dev)
    real_cfg = Path(os.environ["LOCALAPPDATA"]) / "VolumeLocker" / "config.json"
    real_before = (real_cfg.stat().st_mtime_ns, real_cfg.stat().st_size) if real_cfg.exists() else None
    print(f"\n[1] 真实环境基线: 默认设备音量 {orig_vol}%, 配置 "
          f"{'存在' if real_before else '不存在'}")

    tmp = Path(tempfile.mkdtemp(prefix="vl_exe_verify_"))
    # 记录启动前已有的 onefile 解包目录,收尾时只删**本次新增**的
    import glob
    mei_before = set(glob.glob(os.path.join(tempfile.gettempdir(), "_MEI*")))
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(tmp)          # ★ 隔离:配置/锁都落在临时目录
    cfg = tmp / "VolumeLocker" / "config.json"
    procs = []

    def launch(tag, extra_args=(), wait_window=True):
        """启动 exe 并(可选)等主窗口出现。返回 (进程, 重定向日志, 应用日志, 窗口句柄, 毫秒)。

        注意:windowed 模式下 `sys.stdout` 是 NullWriter,重定向日志永远是空的
        —— 真正能看的是程序自己写的 `APP_DIR\\app.log`(见 _setup_logging)。
        `wait_window=False` 用于 --tray(自启)场景:那时**不该**有窗口出现。
        """
        log = tmp / f"{tag}.stdout.log"
        f = open(log, "w", encoding="utf-8", errors="replace")
        applog = tmp / "VolumeLocker" / "app.log"
        t0 = time.perf_counter()
        p = subprocess.Popen([str(EXE), *extra_args], env=env, cwd=str(EXE.parent),
                             stdout=f, stderr=subprocess.STDOUT,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        procs.append((p, f, log))
        hwnd = None
        if wait_window:
            while time.perf_counter() - t0 < WINDOW_TIMEOUT_S:
                if p.poll() is not None:
                    break
                for w in windows_of_tree(p.pid):      # ★ 含 onefile 的子进程
                    if w["visible"] and w["title"].startswith(WINDOW_TITLE_PREFIX):
                        hwnd = w["hwnd"]
                        break
                if hwnd:
                    break
                time.sleep(POLL_S)
        else:
            time.sleep(5.0)                           # 给托盘与控制环一点时间
        dt = (time.perf_counter() - t0) * 1000
        return p, log, applog, hwnd, dt

    def app_log_text(applog, limit=4000):
        try:
            return applog.read_text(encoding="utf-8", errors="replace")[-limit:]
        except Exception:
            return ""

    def kill_all():
        """注意要杀**整棵进程树**:onefile 的 exe 是父子两个进程,
        只杀启动时那个 PID,真正跑 Python 的子进程会留在后台继续锁音量。"""
        import psutil
        for p, f, _log in procs:
            for q in pids_of_tree(p.pid):
                try:
                    pr = psutil.Process(q)
                    pr.terminate()
                    try:
                        pr.wait(timeout=6)
                    except psutil.TimeoutExpired:
                        pr.kill()
                except Exception:
                    pass
            try:
                f.close()
            except Exception:
                pass

    ok_all = True
    try:
        # ── A. 冷启动 ──
        print("\n[A] 冷启动(无配置)")
        p, log, applog, hwnd, dt = launch("cold")
        check("进程没崩", p.poll() is None, f"冷启动到窗口 {dt:.0f} ms")
        check("主窗口出现", hwnd is not None,
              f"标题 '{WINDOW_TITLE_PREFIX}…'")
        wins = windows_of_tree(p.pid)
        # 托盘窗口建得比主窗口晚一点(pystray 在子线程里注册窗口类),
        # 所以这里要轮询,不能只查一次。
        tray = []
        for _ in range(int(15 / POLL_S)):
            wins = windows_of_tree(p.pid)
            tray = [w for w in wins if "SystemTrayIcon" in w["cls"]]
            if tray:
                break
            time.sleep(POLL_S)
        check("托盘图标已创建(pystray 窗口类)", bool(tray),
              tray[0]["cls"] if tray else "未找到 SystemTrayIcon 类")
        if hwnd:
            big = user32.SendMessageW(hwnd, WM_GETICON, ICON_BIG, 0)
            small = user32.SendMessageW(hwnd, WM_GETICON, ICON_SMALL, 0)
            # 注意:句柄非空**不能**证明用的是我们的图标(Tk 默认也有图标),
            # 所以这里只作为信息打印;"图标有没有进包"由下面日志那行证明。
            print(f"      窗口图标句柄 big={big} small={small}(非空不等于就是我们的图)")

        time.sleep(SETTLE_S)
        atxt = app_log_text(applog)
        check("应用日志已写入(app.log)", bool(atxt.strip()),
              f"{len(atxt)} 字节" if atxt else "空 —— 冻结版没有日志就没法排查")
        icon_line = [ln for ln in atxt.splitlines() if ln.startswith("[Icon]")]
        check("运行时找到并应用了包内图标",
              bool(icon_line) and "icon.ico" in icon_line[0],
              icon_line[0] if icon_line else "无 [Icon] 行")
        check("设备通知已注册(COM/DeviceWatcher 活着)",
              "[DevWatch] 已注册设备通知" in atxt)
        check("日志里没有 Python 异常/Traceback",
              "Traceback" not in atxt, "")
        if atxt and (hwnd is None):
            print("      ---- app.log 末尾 ----")
            for ln in atxt.splitlines()[-12:]:
                print("      " + ln)

        cfg_ok = False
        sel = ""
        if cfg.exists():
            data = json.loads(cfg.read_text(encoding="utf-8"))
            sel = data.get("selected_device_id") or ""
            # 注意:启动时 `devices` 本来就是空的(只有用户动过设置才会写条目),
            # 所以"枚举成功"的证据是 selected_device_id 变成了真实设备 GUID。
            cfg_ok = sel.startswith("{0.0.0.00")
        check("配置已写到隔离目录", cfg.exists())
        check("枚举到了真实设备(pycaw/COM 在冻结环境可用)", cfg_ok,
              f"selected_device_id={sel[:46]}" if sel else "配置里没有 selected_device_id")
        check("枚举到的默认设备与外部读到的一致", sel == dev,
              f"exe: {sel[:46]} / 验证器: {str(dev)[:46]}")
        kill_all()

        # ── B. 热启动 + 真的写音量 ──
        print("\n[B] 热启动 + 限幅器写音量(把音量挪开后看它能否写回)")
        if not cfg_ok or not dev:
            check("跳过写音量测试", False, "缺少设备信息")
            ok_all = False
        else:
            # 先把真实音量挪开 20%,再让 exe 把它写回基础音量。
            # 注意要写在**默认设备**那一项上(exe 的控制环只跟默认设备走)。
            audio.set_device_volume(dev, max(0, orig_vol - 20))
            moved = audio.get_device_volume(dev)
            data = json.loads(cfg.read_text(encoding="utf-8"))
            entry = data.setdefault("devices", {}).setdefault(dev, {})
            entry.update({"enabled": True, "base_volume": orig_vol,
                          "target_volume": orig_vol, "ceiling_dbfs": -6.0,
                          "mode": "limit"})
            data["mode"] = "limit"
            data["selected_device_id"] = dev
            cfg.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            p, log, applog, hwnd, dt = launch("warm")
            check("进程没崩", p.poll() is None, f"热启动到窗口 {dt:.0f} ms")
            check("主窗口出现", hwnd is not None)
            time.sleep(SETTLE_S)
            after = audio.get_device_volume(dev)
            check("限幅器把音量写回基础音量(COM 写入 + 控制环可用)",
                  abs(after - orig_vol) <= 2,
                  f"挪到 {moved}% → 现在 {after}%(期望 {orig_vol}%)")
            atxt2 = app_log_text(applog)
            check("热启动无 Python 异常", "Traceback" not in atxt2,
                  "" if "Traceback" not in atxt2 else "日志里有 Traceback")
            if args.shot:
                try:
                    import ctypes.wintypes as wt
                    from PIL import ImageGrab
                    user32.SetForegroundWindow(hwnd)
                    time.sleep(0.6)
                    r = wt.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(r))
                    img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
                    img.save(args.shot)
                    check("窗口截图已保存", True, f"{args.shot} {img.size}")
                except Exception as e:
                    check("窗口截图", False, f"{type(e).__name__}: {e}")
            # 内存:onefile 是父子两个进程,必须**加起来**才是这个软件的实际占用
            try:
                import psutil
                rss = uss = 0.0
                for q in pids_of_tree(p.pid):
                    try:
                        pr = psutil.Process(q)
                        rss += pr.memory_info().rss / 1024 / 1024
                        uss += pr.memory_full_info().uss / 1024 / 1024
                    except Exception:
                        pass
                print(f"      内存(含 onefile 引导进程): RSS {rss:.1f} MB / "
                      f"USS {uss:.1f} MB  —— 源码版见 AGENTS.md 的对照表")
            except Exception as e:
                print(f"      内存读不到: {e}")
            kill_all()

        # ── C. 开机自启(--tray):只进托盘、不弹窗口,但仍在后台干活 ──
        # 用户的要求:勾了开机自启后,开机时不弹界面、自动在后台开始工作;
        # 而双击 exe 时必须弹界面(那就是 A/B 两段测的)。
        print("\n[C] 开机自启模式(--tray):不许弹窗口,但后台要照常工作")
        if not cfg_ok or not dev:
            check("跳过自启模式测试", False, "缺少设备信息")
        else:
            audio.set_device_volume(dev, max(0, orig_vol - 20))   # 再挪开一次
            moved2 = audio.get_device_volume(dev)
            p, log, applog, hwnd, dt = launch("tray", extra_args=(vl.AUTOSTART_FLAG,),
                                              wait_window=False)
            check("进程没崩", p.poll() is None, f"{dt:.0f} ms 后仍在运行")
            check("**没有**可见的主窗口(自启不弹界面)", hwnd is None,
                  "" if hwnd is None else "窗口却弹出来了!")
            wins = windows_of_tree(p.pid)
            check("托盘图标仍在(能从这里把窗口叫出来)",
                  any("SystemTrayIcon" in w["cls"] for w in wins))
            # 主窗口"存在但不可见"也说明是同一个进程做完了初始化(而不是没起来)
            hidden_main = [w for w in wins if w["title"].startswith(WINDOW_TITLE_PREFIX)]
            check("主窗口已创建但处于隐藏状态",
                  bool(hidden_main) and not any(w["visible"] for w in hidden_main),
                  f"{len(hidden_main)} 个隐藏窗口")
            time.sleep(SETTLE_S)
            atxt = app_log_text(applog)
            # app.log 是**跨启动累积**的(A/B/C 三段都在里面),
            # 所以要看**最后一条** [Start],而不是第一条(那是冷启动写的)。
            starts = [ln for ln in atxt.splitlines() if ln.startswith("[Start]")]
            last_start = starts[-1] if starts else ""
            check("日志确认走的是自启分支",
                  "开机自启" in last_start and vl.AUTOSTART_FLAG in last_start,
                  last_start or "无 [Start] 行")
            after2 = audio.get_device_volume(dev)
            check("隐藏状态下后台仍在工作(限幅器写回基础音量)",
                  abs(after2 - orig_vol) <= 2,
                  f"挪到 {moved2}% → 现在 {after2}%(期望 {orig_vol}%)")
            kill_all()

    finally:
        kill_all()
        # 恢复真实音量 + 确认用户配置没被动过
        try:
            audio.set_device_volume(dev, orig_vol)
            back = audio.get_device_volume(dev)
            check("真实音量已恢复原值", abs(back - orig_vol) <= 2,
                  f"{back}%(原 {orig_vol}%)")
        except Exception as e:
            check("真实音量已恢复原值", False, str(e))
        try:
            audio.cleanup()
        except Exception:
            pass
        if real_before is not None and real_cfg.exists():
            now = (real_cfg.stat().st_mtime_ns, real_cfg.stat().st_size)
            check("用户的 config.json 未被本次验证触碰", now == real_before,
                  f"{now} vs {real_before}")
        else:
            check("用户的 config.json 未被本次验证触碰", True, "原本不存在")

        left = [p for p, _f, _l in procs if p.poll() is None]
        check("测试进程都已退出", not left, f"{len(left)} 个残留")
        # onefile 的解包目录在 %TEMP%\_MEIxxxxx:优雅退出时由引导进程自己删,
        # 而我们是强杀,所以会留下 ~37MB。本工具自己造的垃圾自己扫。
        try:
            import glob
            now = set(glob.glob(os.path.join(tempfile.gettempdir(), "_MEI*")))
            for d in now - mei_before:
                shutil.rmtree(d, ignore_errors=True)
            if now - mei_before:
                print(f"      (已清理本次解包残留 {len(now - mei_before)} 个 _MEI 目录)")
        except Exception:
            pass
        if any(not ok for _n, ok, _d in results) and not args.keep:
            print(f"\n  (失败,保留临时目录: {tmp})")
        elif not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 76)
    bad = [(n, d) for n, ok, d in results if not ok]
    print(f"结果: {'✓ 全部通过' if not bad else f'✗ {len(bad)} 项失败'}"
          f"  ({len(results) - len(bad)}/{len(results)})")
    for n, d in bad:
        print(f"   - {n}  {d}")
    print("=" * 76)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
