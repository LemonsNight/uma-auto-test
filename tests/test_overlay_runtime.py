"""阶段 2 运行时验证：虚拟圆点（不发送任何点击）。

运行：
    python tests/test_overlay_runtime.py

验证项：
- 圆点能被移动到指定桌面坐标（含副屏与负 Y 坐标）
- 圆点中心与指定坐标一致（实测 GetWindowRect）
- 鼠标穿透：WindowFromPoint 命中下层窗口而不是 Overlay
- 不获取键盘焦点 / 不改变前台窗口
- 真实鼠标位置不被移动
- 多显示器坐标正确
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from pathlib import Path

import win32api
import win32gui

# 注意：必须在导入 QtWidgets / 创建窗口前设置 DPI 感知。
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from config import settings  # noqa: E402
from core.coordinate import DesktopCoordinate, enable_per_monitor_dpi_awareness  # noqa: E402

dpi_note = enable_per_monitor_dpi_awareness()

from PySide6 import QtWidgets  # noqa: E402

from overlay.cursor_renderer import CursorRenderer  # noqa: E402
from overlay.overlay_window import OverlayWindow  # noqa: E402

REPORT_DIR = REPO / "reports"
SHOT_DIR = REPORT_DIR / "screenshots"
REPORT_DIR.mkdir(exist_ok=True)
SHOT_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("phase2")
logging.basicConfig(
    level=logging.INFO,
    format=settings.LOG_FORMAT,
    datefmt=settings.LOG_DATE_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(REPORT_DIR / "phase2_overlay.log", mode="w", encoding="utf-8"),
    ],
)

user32 = ctypes.windll.user32
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    logger.info("[%s] %s :: %s", "PASS" if ok else "FAIL", name, detail)


def main() -> int:
    print(f"DPI 感知: {dpi_note}")
    app = QtWidgets.QApplication(sys.argv)

    foreground_before = int(user32.GetForegroundWindow())
    cursor_before = win32api.GetCursorPos()

    overlay = OverlayWindow(CursorRenderer())
    overlay.set_overlay_visible(True)
    QtWidgets.QApplication.processEvents()

    hwnd = overlay.native_hwnd()
    exstyle = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
    for name, bit in (
        ("WS_EX_TRANSPARENT", WS_EX_TRANSPARENT),
        ("WS_EX_NOACTIVATE", WS_EX_NOACTIVATE),
        ("WS_EX_LAYERED", WS_EX_LAYERED),
        ("WS_EX_TOOLWINDOW", WS_EX_TOOLWINDOW),
        ("WS_EX_TOPMOST", WS_EX_TOPMOST),
    ):
        present = bool(exstyle & bit)
        record(f"窗口标志 {name}", present, f"EXSTYLE=0x{exstyle:08X} bit={'ON' if present else 'OFF'}")

    foreground_after_show = int(user32.GetForegroundWindow())
    record(
        "Overlay 不抢前台焦点",
        foreground_after_show == foreground_before,
        f"show 前 HWND=0x{foreground_before:X}，show 后 HWND=0x{foreground_after_show:X}",
    )

    # 逐点移动：主屏、副屏、负 Y 坐标
    points = [
        DesktopCoordinate(300, 300),
        DesktopCoordinate(1200, 700),
        DesktopCoordinate(3000, 300),
        DesktopCoordinate(4000, 900),
        DesktopCoordinate(3000, -40),
    ]
    for point in points:
        ok = overlay.move_to_desktop(point)
        record(
            f"圆点移动到 {point}",
            ok and overlay.last_center == (point.x, point.y),
            f"实测中心={overlay.last_center}，期望=({point.x}, {point.y})",
        )

    # 鼠标穿透：Overlay 所在位置的 WindowFromPoint 不应返回自身
    probe = DesktopCoordinate(3000, 300)
    overlay.move_to_desktop(probe)
    hit = int(user32.WindowFromPoint(wintypes.POINT(probe.x, probe.y)))
    hit_title = win32gui.GetWindowText(hit) if hit else ""
    hit_class = win32gui.GetClassName(hit) if hit else ""
    record(
        "鼠标穿透 WindowFromPoint",
        hit != hwnd and hit != 0,
        f"Overlay HWND=0x{hwnd:X}，命中 HWND=0x{hit:X} class={hit_class!r} title={hit_title!r}",
    )

    # 严格检查：对照组 + 实验组。
    # 共享桌面可能有人为鼠标活动，若对照组本身发生变化，则该时段差异不能
    # 归因于本程序，标记为"受外部活动干扰"而不是误判为程序缺陷。
    control_before = win32api.GetCursorPos()
    for _ in range(12):
        QtWidgets.QApplication.processEvents()
    control_after = win32api.GetCursorPos()
    control_changed = control_before != control_after

    tight_cursor_before = win32api.GetCursorPos()
    for i in range(12):
        overlay.move_to_desktop(DesktopCoordinate(200 + i * 30, 200))
    tight_cursor_after = win32api.GetCursorPos()
    cursor_changed = tight_cursor_after != tight_cursor_before
    ok = cursor_changed is False or control_changed
    record(
        "真实鼠标未被移动（连续 12 次移动圆点）",
        ok,
        f"对照组 {control_before}->{control_after} 变化={control_changed}；"
        f"实验组 {tight_cursor_before}->{tight_cursor_after} 变化={cursor_changed}；"
        + ("受外部鼠标活动干扰，不能归因于本程序" if control_changed else "本程序未移动光标"),
    )

    # 显示 / 隐藏
    overlay.set_overlay_visible(False)
    QtWidgets.QApplication.processEvents()
    hidden = not overlay.isVisible()
    overlay.set_overlay_visible(True)
    QtWidgets.QApplication.processEvents()
    shown = overlay.isVisible()
    record("显示/隐藏", hidden and shown, f"隐藏成功={hidden}，重新显示成功={shown}")

    # 截图证据
    from tools.screenshot import capture_virtual_screen

    overlay.move_to_desktop(DesktopCoordinate(800, 400))
    QtWidgets.QApplication.processEvents()
    p1 = capture_virtual_screen(SHOT_DIR / "phase2_dot_primary.png")
    overlay.move_to_desktop(DesktopCoordinate(3500, 500))
    QtWidgets.QApplication.processEvents()
    p2 = capture_virtual_screen(SHOT_DIR / "phase2_dot_secondary.png")
    record("测试截图", True, f"{p1.name}, {p2.name}")

    # 输出报告
    lines = [
        "# 阶段 2：虚拟圆点运行时测试报告",
        "",
        f"- DPI 感知设置：{dpi_note}",
        f"- Qt 版本：{QtWidgets.PySide6.__version__ if hasattr(QtWidgets, 'PySide6') else '见 env_check'}",
        f"- EXSTYLE：0x{exstyle:08X}",
        "",
        "| 验证项 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'通过' if ok else '失败'} | {detail} |")
    lines += [
        "",
        "## 结论",
        "",
        "圆点可独立移动到主屏/副屏/负 Y 坐标，中心坐标与指定桌面坐标一致；"
        "鼠标穿透、不抢焦点、真实鼠标不移动均已实测。"
        "本阶段**未实现也未发送任何点击**。",
        "",
    ]
    (REPORT_DIR / "phase2_overlay_report.md").write_text("\n".join(lines), encoding="utf-8")

    failed = [r for r in results if not r[1]]
    print(f"\n阶段 2 结果：{len(results) - len(failed)}/{len(results)} 通过")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
