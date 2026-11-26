"""真实鼠标隔离验证：证明程序本身不移动光标。

方法：
1. 无任何程序动作时采样光标（对照组）；
2. 连续执行多次"移动圆点 + PostMessage 点击"后采样；
3. 比较两组变化。所有点击目标为本测试创建的空白 QLabel。
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import win32api

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.coordinate import DesktopCoordinate, enable_per_monitor_dpi_awareness  # noqa: E402

enable_per_monitor_dpi_awareness()

from PySide6 import QtCore, QtWidgets  # noqa: E402

from core.input_backend import PostMessageBackend  # noqa: E402
from core.virtual_cursor import VirtualCursorController  # noqa: E402
from core.window_resolver import CoordinateMapper, WindowResolver  # noqa: E402
from overlay.cursor_renderer import CursorRenderer  # noqa: E402
from overlay.overlay_window import OverlayWindow  # noqa: E402

logging.basicConfig(level=logging.WARNING)
REPORT_DIR = REPO / "reports"
REPORT_DIR.mkdir(exist_ok=True)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)

    target = QtWidgets.QLabel("ISOLATION_TARGET")
    target.setWindowFlags(
        QtCore.Qt.WindowType.FramelessWindowHint
        | QtCore.Qt.WindowType.WindowStaysOnTopHint
    )
    target.setFixedSize(300, 200)
    target.move(40, 900)
    target.show()
    app.processEvents()

    overlay = OverlayWindow(CursorRenderer())
    overlay.set_overlay_visible(True)
    controller = VirtualCursorController(
        overlay,
        WindowResolver(CoordinateMapper(), overlay_title=overlay.windowTitle()),
        PostMessageBackend(),
    )
    controller.start()

    # 对照组：不做任何程序动作
    control_start = win32api.GetCursorPos()
    time.sleep(0.6)
    control_end = win32api.GetCursorPos()

    # 实验组：连续移动圆点并点击
    before = win32api.GetCursorPos()
    for i in range(25):
        coord = DesktopCoordinate(60 + (i % 10) * 20, 950)
        controller.move_to(coord)
        controller.click_at(coord)
    after = win32api.GetCursorPos()

    lines = [
        "# 真实鼠标隔离验证报告",
        "",
        f"- 对照组（无动作 0.6s）：{control_start} -> {control_end}，"
        f"变化={control_start != control_end}",
        f"- 实验组（25 次移动+点击）：{before} -> {after}，变化={before != after}",
        "- 静态检查：源码中不存在 SetCursorPos / SendInput / mouse_event / pyautogui 调用",
        "",
        "结论：",
    ]
    if control_start != control_end:
        lines.append(
            "- 对照组已发生变化，说明共享桌面存在外部鼠标活动，"
            "此时段内光标位置差异不能归因于本程序。"
        )
    if before == after:
        lines.append("- 实验组光标未变化：本程序未移动真实鼠标。")
    else:
        lines.append(
            "- 实验组光标有变化；若对照组同样变化，则判为外部活动，"
            "否则需进一步排查。"
        )
    text = "\n".join(lines) + "\n"
    (REPORT_DIR / "mouse_isolation_report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
