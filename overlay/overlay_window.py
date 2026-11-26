"""透明、置顶、鼠标穿透的虚拟圆点 Overlay。

实测背景（见 reports/）：
- Qt 6.12 的 move() 在混合 DPI（100% 主屏 + 150% 副屏）下会把物理坐标
  当作逻辑坐标再缩放，move(3000,100) 实际落在 (3220,194)。
  因此定位使用 Win32 SetWindowPos（物理像素），窗口标志仍优先用 Qt。
- 已实测 WindowTransparentForInput / WindowDoesNotAcceptFocus / Tool
  在 Windows 11 上分别对应 WS_EX_TRANSPARENT / WS_EX_NOACTIVATE /
  WS_EX_TOOLWINDOW，并且确实生效。

本模块不包含任何点击发送逻辑，也不会移动真实鼠标。
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PySide6 import QtCore, QtGui, QtWidgets

from config import settings
from core.coordinate import DesktopCoordinate
from .cursor_renderer import CursorRenderer

logger = logging.getLogger(__name__)

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = wintypes.HWND(-1)

user32 = ctypes.windll.user32


class OverlayWindow(QtWidgets.QWidget):
    """承载圆点的无边框透明窗口。"""

    def __init__(self, renderer: CursorRenderer | None = None,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer or CursorRenderer()
        self._flashing = False
        self._last_center: tuple[int, int] | None = None
        self._move_verified = False

        self.setWindowTitle("VirtualMouse Overlay")
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.WindowTransparentForInput
            | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
            | QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(
            settings.WINDOW_SIZE_PX, settings.WINDOW_SIZE_PX
        )
        self.setToolTip("")

    # ---------- 绘制 ----------
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        try:
            self._renderer.paint(
                painter, self.rect(), self._flashing, self.devicePixelRatioF()
            )
        finally:
            painter.end()

    def flash_click(self) -> None:
        """短暂改变颜色作为视觉反馈（不代表点击已被目标处理）。"""
        self._flashing = True
        self.update()
        QtCore.QTimer.singleShot(settings.CLICK_FEEDBACK_MS, self._end_flash)

    def _end_flash(self) -> None:
        self._flashing = False
        self.update()

    # ---------- 显示 / 隐藏 ----------
    def set_overlay_visible(self, visible: bool) -> None:
        if visible:
            self.show()
        else:
            self.hide()

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        hwnd = self.native_hwnd()
        if hwnd:
            # 用 Win32 再次确认置顶，避免不同 Qt 版本标志实现差异。
            user32.SetWindowPos(
                wintypes.HWND(hwnd), HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )

    # ---------- 定位 ----------
    def native_hwnd(self) -> int:
        try:
            return int(self.winId())
        except Exception:
            return 0

    @staticmethod
    def _window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
        rect = wintypes.RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)

    def move_to_desktop(self, coord: DesktopCoordinate) -> bool:
        """把圆点中心移动到指定物理桌面坐标，并实测校验结果。

        使用 SetWindowPos + SWP_NOSIZE：Qt 在混合 DPI 下会缩放 move() 的坐标，
        而 SetWindowPos 的参数始终是物理像素。
        """
        hwnd = self.native_hwnd()
        if not hwnd or not self.isVisible():
            logger.warning("Overlay 尚未显示，无法显示圆点")
            return False

        rect = self._window_rect(hwnd)
        if rect is None:
            logger.error("GetWindowRect 失败 HWND=0x%X", hwnd)
            return False
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        if width <= 0 or height <= 0:
            logger.error("Overlay 尺寸异常: %s", rect)
            return False

        left = coord.x - width // 2
        top = coord.y - height // 2

        # 跨越 DPI 边界时 Qt 会异步改变窗口的物理尺寸（48 -> 72），
        # 需要多次读取真实矩形并收敛，不能只校正一次。
        rect: tuple[int, int, int, int] | None = None
        center_x = center_y = 0
        for _ in range(6):
            user32.SetWindowPos(
                wintypes.HWND(hwnd), None, left, top, 0, 0,
                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
            )
            QtWidgets.QApplication.processEvents()
            rect = self._window_rect(hwnd)
            if rect is None:
                return False
            center_x = (rect[0] + rect[2]) // 2
            center_y = (rect[1] + rect[3]) // 2
            if (center_x, center_y) == (coord.x, coord.y):
                break
            left += coord.x - center_x
            top += coord.y - center_y

        self._last_center = (center_x, center_y)
        self._move_verified = (center_x, center_y) == (coord.x, coord.y)
        logger.info(
            "Overlay move: target=%s rect=%s center=(%d, %d) verified=%s",
            coord, rect, center_x, center_y, self._move_verified,
        )
        return self._move_verified

    @property
    def last_center(self) -> tuple[int, int] | None:
        return self._last_center

    @property
    def move_verified(self) -> bool:
        return self._move_verified
