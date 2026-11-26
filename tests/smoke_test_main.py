"""主程序装配冒烟测试：启动全套窗口/控制器/热键，2 秒后自动退出。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import main as app_module  # noqa: E402

from PySide6 import QtCore  # noqa: E402


def main() -> int:
    app_module.configure_logging()
    app, overlay, controller, window, hotkey = app_module.build_app()
    window.show()
    app.processEvents()
    hotkey.register()
    controller.start()
    from core.coordinate import DesktopCoordinate

    overlay.move_to_desktop(DesktopCoordinate(800, 400))

    check = {
        "overlay_hwnd_nonzero": overlay.native_hwnd() != 0,
        "overlay_visible": overlay.isVisible(),
        "dot_moved": overlay.last_center == (800, 400),
        "window_visible": window.isVisible(),
        "controller_running": controller.state.value == "running",
        "hotkey_registered": hotkey.registered,
    }
    from tools.screenshot import capture_virtual_screen

    QtCore.QTimer.singleShot(
        600,
        lambda: capture_virtual_screen(REPO / "reports" / "screenshots" / "control_panel.png"),
    )
    QtCore.QTimer.singleShot(1500, app.quit)
    app.exec()
    hotkey.unregister()

    for key, value in check.items():
        print(f"{key}: {'OK' if value else 'FAIL'}")
    return 0 if all(check.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
