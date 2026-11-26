"""圆点绘制：只负责画，不负责窗口定位或输入。"""

from __future__ import annotations

from PySide6 import QtCore, QtGui

from config import settings


class CursorRenderer:
    """用 QPainter 绘制红色圆点与点击反馈。"""

    def __init__(self) -> None:
        self.normal_color = QtGui.QColor(*settings.DOT_COLOR)
        self.flash_color = QtGui.QColor(*settings.DOT_FLASH_COLOR)
        self.outline_color = QtGui.QColor(20, 20, 20, 210)
        self.glow_color = QtGui.QColor(*settings.DOT_COLOR, 70)

    def paint(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        flashing: bool,
        device_pixel_ratio: float,
    ) -> None:
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        center = rect.center()
        ratio = device_pixel_ratio if device_pixel_ratio > 0 else 1.0
        radius = (
            settings.DOT_FLASH_RADIUS_PX if flashing else settings.DOT_RADIUS_PX
        ) / ratio

        # 外圈光晕
        glow = QtGui.QRadialGradient(center, radius * 0.4, center, radius * 1.9)
        glow.setColorAt(0.0, self.glow_color)
        glow.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(glow))
        painter.drawEllipse(center, radius * 2.0, radius * 2.0)

        # 主体
        color = self.flash_color if flashing else self.normal_color
        pen = QtGui.QPen(self.outline_color)
        pen.setWidthF(settings.DOT_OUTLINE_PX / ratio)
        painter.setPen(pen)
        painter.setBrush(QtGui.QBrush(color))
        painter.drawEllipse(center, radius, radius)
