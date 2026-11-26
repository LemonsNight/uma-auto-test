"""VirtualMouse Phase 1 - Windows 独立虚拟鼠标 PoC 入口。

严禁的调用在本项目中完全不存在：
    SetCursorPos / SendInput / mouse_event / pyautogui.*
点击唯一路径：PostMessage(WM_MOUSEMOVE / WM_LBUTTONDOWN / WM_LBUTTONUP)。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# 必须在创建 Qt 窗口前设置进程 DPI 感知。
from core.coordinate import enable_per_monitor_dpi_awareness

DPI_NOTE = enable_per_monitor_dpi_awareness()

from PySide6 import QtWidgets  # noqa: E402

from config import settings  # noqa: E402
from core.coordinate import DesktopCoordinate  # noqa: E402
from core.hotkey import GlobalHotkey  # noqa: E402
from core.input_backend import PostMessageBackend  # noqa: E402
from core.virtual_cursor import VirtualCursorController  # noqa: E402
from core.window_resolver import CoordinateMapper, WindowResolver  # noqa: E402
from overlay.cursor_renderer import CursorRenderer  # noqa: E402
from overlay.overlay_window import OverlayWindow  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

REPO = Path(__file__).resolve().parent
REPORT_DIR = REPO / "reports"
REPORT_DIR.mkdir(exist_ok=True)


def configure_logging() -> None:
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            REPORT_DIR / settings.LOG_FILENAME, mode="w", encoding="utf-8"
        ),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format=settings.LOG_FORMAT,
        datefmt=settings.LOG_DATE_FORMAT,
        handlers=handlers,
    )
    logger = logging.getLogger("VirtualMouse")
    logger.info("DPI 感知: %s", DPI_NOTE)
    logger.info("点击后端: PostMessageW（不移动真实鼠标）")
    logger.info("注意: PostMessage 入队成功不等于目标程序处理了点击")


def build_app():
    """构建并返回 (app, overlay, controller, window, hotkey)，便于测试复用。"""
    app = QtWidgets.QApplication(sys.argv)

    overlay = OverlayWindow(CursorRenderer())
    overlay.set_overlay_visible(True)

    resolver = WindowResolver(CoordinateMapper(), overlay_title=overlay.windowTitle())
    backend = PostMessageBackend()
    controller = VirtualCursorController(overlay, resolver, backend)
    window = MainWindow(controller, settings.HOTKEY_LABEL)

    hotkey = GlobalHotkey(
        target_hwnd_provider=window.winId,
        modifiers=settings.HOTKEY_MODIFIERS,
        vk=settings.HOTKEY_VK,
        label=settings.HOTKEY_LABEL,
    )
    hotkey.triggered.connect(
        lambda: controller.emergency_stop(f"全局热键 {settings.HOTKEY_LABEL}")
    )
    hotkey.registration_failed.connect(
        lambda message: controller.log_emitted.emit(f"热键警告：{message}")
    )

    return app, overlay, controller, window, hotkey


def main() -> int:
    configure_logging()
    app, overlay, controller, window, hotkey = build_app()

    window.show()
    QtWidgets.QApplication.processEvents()
    hotkey.register()

    controller.start()
    overlay.move_to_desktop(DesktopCoordinate(800, 400))

    logging.getLogger("VirtualMouse").info(
        "控制面板已启动；热键 %s 注册状态=%s",
        settings.HOTKEY_LABEL,
        hotkey.registered,
    )
    result = app.exec()
    hotkey.unregister()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
