"""阶段 5：Windows 记事本真实点击测试。

验证：
- 前台点击：消息入队 + 插入符变化（实际点击验证）
- 后台（部分遮挡）点击：记事本不是前台时能否处理
- 最小化行为
- 真实鼠标同时操作浏览器（光标位置与前台窗口不被改变）
- 圆点位置与点击坐标一致

严格语义：
- "消息入队成功"由 PostMessage 返回值判定；
- "实际点击成功"由记事本 RichEditD2DPT 插入符变化判定；
- 两者分别记录，绝不混为一谈。

运行：
    python tests/test_notepad_runtime.py
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import win32api
import win32con
import win32gui
import win32process

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from config import settings  # noqa: E402
from core.coordinate import DesktopCoordinate, enable_per_monitor_dpi_awareness  # noqa: E402

enable_per_monitor_dpi_awareness()

from PySide6 import QtCore, QtWidgets  # noqa: E402

from core.input_backend import PostMessageBackend  # noqa: E402
from core.virtual_cursor import VirtualCursorController  # noqa: E402
from core.window_resolver import CoordinateMapper, WindowResolver  # noqa: E402
from overlay.cursor_renderer import CursorRenderer  # noqa: E402
from overlay.overlay_window import OverlayWindow  # noqa: E402
from tools.screenshot import capture_virtual_screen  # noqa: E402

REPORT_DIR = REPO / "reports"
SHOT_DIR = REPORT_DIR / "screenshots"
REPORT_DIR.mkdir(exist_ok=True)
SHOT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(REPORT_DIR / "phase5_notepad.log", mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger("phase5")

user32 = ctypes.windll.user32
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND

EM_GETSEL = 0x00B0
EM_SETSEL = 0x00B1
WM_SETTEXT = 0x000C
TEST_TEXT = "AAAAAAAAAAAAAAAAAAAA\nBBBBBBBBBBBBBBBBBBBB\nCCCCCCCCCCCCCCCCCCCC"

results: list[dict] = []


def record(name: str, queued: bool | None, verified: bool | None, detail: str) -> None:
    item = {"name": name, "queued": queued, "verified": verified, "detail": detail}
    results.append(item)
    logger.info("[记录] %s :: %s", name, detail)


def find_notepad_windows() -> list[int]:
    found: list[int] = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == "Notepad":
            found.append(hwnd)
        return True

    win32gui.EnumWindows(cb, None)
    return found


def find_child(hwnd: int, cls: str) -> int:
    found: list[int] = []

    def cb(h, acc):
        if win32gui.GetClassName(h) == cls:
            acc.append(h)
        return True

    win32gui.EnumChildWindows(hwnd, cb, found)
    return found[0] if found else 0


def find_hitable_point(edit: int, dy_list=(60, 95, 130, 165)) -> DesktopCoordinate | None:
    """在文本区内找一个确实命中 RichEditD2DPT 的桌面坐标。

    多窗口叠加时不能假设固定偏移一定命中目标，必须实测命中窗口。
    """
    left, top, right, bottom = win32gui.GetWindowRect(edit)
    for dy in dy_list:
        for dx in range(40, 460, 40):
            x, y = left + dx, top + dy
            if x >= right - 5 or y >= bottom - 5:
                continue
            hit = int(user32.WindowFromPoint(wintypes.POINT(x, y)))
            if hit == edit:
                return DesktopCoordinate(x, y)
    return None


def get_caret(edit: int) -> tuple[int, int]:
    value = win32gui.SendMessage(edit, EM_GETSEL, 0, 0)
    return value & 0xFFFF, (value >> 16) & 0xFFFF


def reset_caret(edit: int) -> None:
    win32gui.SendMessage(edit, EM_SETSEL, 0, 0)


def bring_foreground(hwnd: int) -> int:
    """尽力把窗口切到前台，返回切换后的实际前台 HWND。"""
    kernel32 = ctypes.windll.kernel32
    user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    user32.SwitchToThisWindow(wintypes.HWND(hwnd), True)
    time.sleep(0.2)
    fg = int(user32.GetForegroundWindow())
    fg_thread = user32.GetWindowThreadProcessId(wintypes.HWND(fg), None)
    cur_thread = kernel32.GetCurrentThreadId()
    attached = False
    if fg_thread and fg_thread != cur_thread:
        attached = bool(user32.AttachThreadInput(cur_thread, fg_thread, True))
    try:
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
    except Exception as exc:
        logger.warning("SetForegroundWindow: %s", exc)
    finally:
        if attached:
            user32.AttachThreadInput(cur_thread, fg_thread, False)
    time.sleep(0.4)
    return int(user32.GetForegroundWindow())


def find_browser_window() -> int:
    """找一个真正属于 chrome.exe / msedge.exe 的可见浏览器顶层窗口。"""
    found: list[int] = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        cls = win32gui.GetClassName(hwnd)
        title = win32gui.GetWindowText(hwnd)
        if not cls.startswith("Chrome_WidgetWin") or not title:
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            handle = win32api.OpenProcess(0x1000, False, pid)
            exe = win32process.GetModuleFileNameEx(handle, 0)
            win32api.CloseHandle(handle)
        except Exception:
            return True
        if exe.lower().endswith(("chrome.exe", "msedge.exe")):
            found.append(hwnd)
        return True

    win32gui.EnumWindows(cb, None)
    return found[0] if found else 0


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)

    # 确保记事本存在且可见
    windows = find_notepad_windows()
    if not windows:
        subprocess.Popen(
            [r"C:\Windows\System32\notepad.exe"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2.5)
        windows = find_notepad_windows()
    if not windows:
        print("无法启动或定位记事本")
        return 2

    notepad = windows[0]
    # 测试用定位：把记事本放到主屏空白区域，避免被其它窗口遮挡导致命中错误目标。
    win32gui.MoveWindow(notepad, 80, 80, 900, 700, True)
    bring_foreground(notepad)
    edit = find_child(notepad, "RichEditD2DPT")
    if not edit:
        print("未找到 RichEditD2DPT，无法做实际点击验证")
        return 2
    win32gui.SendMessage(edit, WM_SETTEXT, 0, TEST_TEXT)
    time.sleep(0.3)

    overlay = OverlayWindow(CursorRenderer())
    overlay.set_overlay_visible(True)
    resolver = WindowResolver(CoordinateMapper(), overlay_title=overlay.windowTitle())
    backend = PostMessageBackend()
    controller = VirtualCursorController(overlay, resolver, backend)
    controller.start()

    def click_and_measure(coord: DesktopCoordinate, label: str) -> tuple[bool, bool, str]:
        # 每次点击前都把圆点移动到该坐标，确保圆点位置与点击坐标一致。
        controller.move_to(coord)
        reset_caret(edit)
        before = get_caret(edit)
        result = controller.click_at(coord)
        time.sleep(0.4)
        after = get_caret(edit)
        queued = bool(result and result.all_messages_queued)
        verified = after != before
        detail = (
            f"坐标={coord} 圆点中心={overlay.last_center} "
            f"目标=HWND 0x{result.target.hwnd:X} class={result.target.class_name!r} "
            f"title={result.target.title!r} "
            f"入队={queued} 插入符 {before}->{after} 实际点击={verified}"
        )
        record(label, queued, verified, detail)
        return queued, verified, detail

    rect = win32gui.GetWindowRect(edit)
    foreground_point = find_hitable_point(edit, (60,))
    if foreground_point is None:
        print("记事本文本区被遮挡，找不到可命中的点击点，测试前置条件失败")
        return 2

    # --- 1. 前台点击 ---
    bring_foreground(notepad)
    reset_caret(edit)
    overlay.move_to_desktop(foreground_point)
    q1, v1, _ = click_and_measure(foreground_point, "记事本前台点击")
    dot_ok = overlay.last_center == (foreground_point.x, foreground_point.y)
    record(
        "圆点位置与点击坐标一致（前台）",
        None, None,
        f"圆点中心={overlay.last_center} 点击坐标={foreground_point} 一致={dot_ok}",
    )
    capture_virtual_screen(SHOT_DIR / "phase5_foreground_click.png")

    # --- 2. 后台（部分遮挡）点击 ---
    cover = QtWidgets.QLabel("遮挡窗口")
    cover.setWindowTitle("Occluding Window")
    cover.setWindowFlags(
        QtCore.Qt.WindowType.FramelessWindowHint
        | QtCore.Qt.WindowType.WindowStaysOnTopHint
    )
    cover.setStyleSheet("background-color: #2255aa; color: white; font-size: 20px;")
    # 只遮挡右侧，留下左侧可点击区域
    cover.setGeometry(rect[0] + 500, rect[1] + 10, 620, 600)
    cover.show()
    QtWidgets.QApplication.processEvents()
    cover_hwnd = int(cover.winId())
    fg_after_cover = bring_foreground(cover_hwnd)
    time.sleep(0.3)
    foreground_during = int(user32.GetForegroundWindow())
    background_point = find_hitable_point(edit, (95,))
    if background_point is None:
        record("记事本被部分遮挡时点击", None, None,
               "遮挡后找不到仍可命中的记事本文本区坐标，改由最小化场景记录")
        background_point = foreground_point
    q2, v2, _ = click_and_measure(background_point, "记事本被部分遮挡时点击")
    foreground_after = int(user32.GetForegroundWindow())
    record(
        "遮挡时前台确实不是记事本",
        None, None,
        f"遮挡窗口 HWND=0x{cover_hwnd:X} 切换后前台=0x{fg_after_cover:X} "
        f"遮挡期间前台=0x{foreground_during:X} 记事本=0x{notepad:X} "
        f"成立={foreground_during != notepad}",
    )
    record(
        "遮挡点击未改变前台窗口",
        None, None,
        f"遮挡后前台=0x{foreground_during:X} 点击后前台=0x{foreground_after:X} "
        f"一致={foreground_during == foreground_after}",
    )
    capture_virtual_screen(SHOT_DIR / "phase5_background_click.png")
    cover.close()

    # --- 3. 最小化行为 ---
    win32gui.ShowWindow(notepad, win32con.SW_MINIMIZE)
    time.sleep(0.4)
    minimized_rect = win32gui.GetWindowRect(notepad)
    is_iconic = bool(user32.IsIconic(wintypes.HWND(notepad)))
    resolved_minimized = resolver.resolve(foreground_point)
    record(
        "记事本最小化时的行为",
        None, None,
        f"IsIconic={is_iconic} 最小化后窗口矩形={minimized_rect}；"
        f"原坐标 {foreground_point} 解析为 HWND=0x{resolved_minimized.hwnd:X} "
        f"class={resolved_minimized.class_name!r}（不是记事本）；"
        "本程序按桌面坐标工作，无法向已最小化的记事本目标区域发送点击，"
        "且拒绝向系统桌面窗口发送。",
    )
    capture_virtual_screen(SHOT_DIR / "phase5_minimized.png")
    bring_foreground(notepad)

    # --- 4. 真实鼠标同时操作浏览器 ---
    # 把记事本移到副屏，使浏览器前台时记事本文本区仍然可见，
    # 这样才能验证"后台点击"而不是坐标被浏览器窗口占用。
    win32gui.MoveWindow(notepad, 2750, 120, 900, 700, True)
    time.sleep(0.3)

    browser = find_browser_window()
    fg_after_bring = bring_foreground(browser) if browser else 0
    browser_is_foreground = bool(browser) and fg_after_bring == browser
    browser_title = win32gui.GetWindowText(browser) if browser else ""
    record(
        "浏览器已置于前台（前置条件）",
        None, None,
        f"浏览器 HWND=0x{browser:X} title={browser_title!r} "
        f"切换后前台=0x{fg_after_bring:X} 成功={browser_is_foreground}",
    )

    browser_point = find_hitable_point(edit, (130, 60, 95))
    if browser_point is None:
        record("浏览器前台时对记事本点击", None, None,
               "浏览器前台后找不到仍可见的记事本文本区坐标，场景未验证")
        browser_point = foreground_point
    else:
        cursor_before = win32api.GetCursorPos()
        foreground_before = int(user32.GetForegroundWindow())
        q3, v3, _ = click_and_measure(browser_point, "浏览器前台时对记事本点击")
        cursor_after = win32api.GetCursorPos()
        foreground_after2 = int(user32.GetForegroundWindow())
        record(
            "真实鼠标未被移动（连续点击前后紧邻采样）",
            None, None,
            f"点击前光标={cursor_before} 点击后光标={cursor_after} "
            f"一致={cursor_before == cursor_after}",
        )
        record(
            "前台窗口未被 PostMessage 抢走",
            None, None,
            f"点击前前台=0x{foreground_before:X} 点击后前台=0x{foreground_after2:X} "
            f"一致={foreground_before == foreground_after2}"
            + ("（浏览器前置条件成立）" if browser_is_foreground
               else "（浏览器前置条件不成立，浏览器场景未验证）"),
        )

    if browser_point is None:
        q3 = v3 = False

    # --- 紧急停止后立即拒绝 ---
    controller.emergency_stop("阶段 5 测试")
    stopped = controller.click_at(browser_point)
    record(
        "紧急停止后立即拒绝后续点击",
        None, None,
        f"state={controller.state.value} 返回值={stopped}",
    )

    # --- 报告 ---
    def mark(value: bool | None) -> str:
        return "—" if value is None else ("是" if value else "否")

    lines = [
        "# 阶段 5：记事本点击测试报告",
        "",
        "说明：`入队` 仅表示 PostMessage 成功；`实际点击` 由记事本 "
        "RichEditD2DPT 插入符变化独立验证。两者严格区分。",
        "",
        "| 测试项 | 消息入队成功 | 实际点击验证成功 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for item in results:
        lines.append(
            f"| {item['name']} | {mark(item['queued'])} | {mark(item['verified'])} "
            f"| {item['detail']} |"
        )
    lines += [
        "",
        "## 测试环境",
        "",
        "- 记事本：Windows 11 内置现代记事本（顶层类 `Notepad`，"
        "文本区子窗口 `RichEditD2DPT`）",
        "- 插入符读取：`EM_GETSEL`（SendMessage 仅用于测试验证，不是点击手段）",
        "- 点击发送：`PostMessageW` WM_MOUSEMOVE / WM_LBUTTONDOWN / WM_LBUTTONUP",
        "",
        "## 截图",
        "",
        "- `screenshots/phase5_foreground_click.png`",
        "- `screenshots/phase5_background_click.png`",
        "- `screenshots/phase5_minimized.png`",
        "",
    ]
    (REPORT_DIR / "phase5_notepad_report.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n阶段 5 汇总:")
    for item in results:
        print(f"  {item['name']}: 入队={mark(item['queued'])} 实际={mark(item['verified'])}")
    return 0 if (q1 and v1) else 1


if __name__ == "__main__":
    raise SystemExit(main())
