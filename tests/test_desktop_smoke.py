"""Phase 1.1：真实桌面冒烟测试（只解析窗口 + 移动圆点，不点击）。

运行：
    python tests/test_desktop_smoke.py

本测试严格不发送任何鼠标点击消息；仅读取窗口树、解析桌面坐标、
移动虚拟圆点。用于验证真实 Windows 桌面结构下安全拦截是否生效。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import win32api
import win32con
import win32gui

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from config import settings  # noqa: E402
from core.coordinate import DesktopCoordinate, enable_per_monitor_dpi_awareness  # noqa: E402

enable_per_monitor_dpi_awareness()

from PySide6 import QtWidgets  # noqa: E402

from core.window_resolver import CoordinateMapper, WindowResolver  # noqa: E402
from overlay.cursor_renderer import CursorRenderer  # noqa: E402
from overlay.overlay_window import OverlayWindow  # noqa: E402

REPORT_DIR = REPO / "reports"
REPORT_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT,
    handlers=[logging.FileHandler(REPORT_DIR / "phase11_desktop_smoke.log", mode="w", encoding="utf-8")],
)

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    logging.info("[%s] %s :: %s", "PASS" if ok else "FAIL", name, detail)


def find_windows_by_class(cls: str) -> list[int]:
    found: list[int] = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == cls:
            found.append(hwnd)
        return True

    win32gui.EnumWindows(cb, None)
    return found


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    overlay = OverlayWindow(CursorRenderer())
    overlay.set_overlay_visible(True)
    resolver = WindowResolver(CoordinateMapper(), overlay_title=overlay.windowTitle())

    progman = find_windows_by_class("Progman")
    record("找到 Progman 桌面窗口", bool(progman), f"HWND={[hex(h) for h in progman]}")
    if not progman:
        return 1

    root = progman[0]
    children: list[tuple[int, str, str]] = []

    def cb(hwnd, acc):
        acc.append((hwnd, win32gui.GetClassName(hwnd), win32gui.GetWindowText(hwnd)))
        return True

    win32gui.EnumChildWindows(root, cb, children)
    defview = [x for x in children if x[1] == "SHELLDLL_DefView"]
    listview = [
        x for x in children
        if x[1] == "SysListView32" and x[2] == "FolderView"
    ]
    record("找到 SHELLDLL_DefView", bool(defview), f"{[hex(x[0]) for x in defview]}")
    record("找到桌面 SysListView32(FolderView)", bool(listview),
           f"{[hex(x[0]) for x in listview]}")

    # 对真实桌面图标列表取一个屏幕坐标，检查解析器是否拒绝（不点击）。
    if listview:
        hwnd = listview[0][0]
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        if r - l > 20 and b - t > 20:
            coord = DesktopCoordinate(l + 30, t + 30)
            resolved = resolver.resolve(coord)
            record(
                "真实桌面图标区域解析被拒绝",
                bool(resolved.reject_reason),
                f"坐标={coord} hit={resolved.describe()} reason={resolved.reject_reason} "
                f"chain={[n.class_name for n in resolved.chain]}",
            )
            moved = overlay.move_to_desktop(coord)
            record(
                "圆点可移动到桌面图标坐标（不点击）",
                moved,
                f"坐标={coord} 圆点中心={overlay.last_center}",
            )
        else:
            record("真实桌面图标区域解析被拒绝", False,
                   f"桌面列表窗口尺寸异常 rect={(l, t, r, b)}")

    # 真实鼠标位置仅记录，不做判断（共享桌面可能有外部活动）。
    record("真实鼠标位置（仅记录）", True, f"{win32api.GetCursorPos()}")

    lines = [
        "# Phase 1.1：真实桌面冒烟测试报告（无点击）",
        "",
        "| 用例 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail} |")
    lines += [
        "",
        "本测试没有调用任何 PostMessage / SendInput / 鼠标点击 API；"
        "只读取窗口树并移动圆点。",
        "",
    ]
    (REPORT_DIR / "phase11_desktop_smoke_report.md").write_text("\n".join(lines), encoding="utf-8")

    failed = [r for r in results if not r[1]]
    print(f"\n真实桌面冒烟测试：{len(results) - len(failed)}/{len(results)} 通过")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
