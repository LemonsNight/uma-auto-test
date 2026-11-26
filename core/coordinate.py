"""桌面坐标与 DPI 感知辅助。

关键：必须在创建任何 Qt 窗口或调用 Win32 坐标 API 之前设置进程 DPI 感知，
否则混合 DPI 多显示器下坐标会被系统虚拟化，导致圆点与点击坐标错位。
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from ctypes import wintypes


class DpiAwareness:
    UNAWARE = 0
    SYSTEM_AWARE = 1
    PER_MONITOR_AWARE = 2


_DPI_MODE_NONE = -1
_current_mode: int = _DPI_MODE_NONE


def query_actual_dpi_awareness() -> int | None:
    """查询系统记录的当前进程 DPI 感知级别；无法查询时返回 None。

    用于校验"设置调用成功"之外的事实状态，避免误报。
    """
    # Windows 10 1607+：从线程 DPI 感知上下文读取。
    try:
        context = ctypes.windll.user32.GetThreadDpiAwarenessContext()
        if context:
            value = ctypes.windll.user32.GetAwarenessFromDpiAwarenessContext(context)
            if value in (
                DpiAwareness.UNAWARE,
                DpiAwareness.SYSTEM_AWARE,
                DpiAwareness.PER_MONITOR_AWARE,
            ):
                return int(value)
    except Exception:
        pass
    # Windows 8.1+：shcore 查询进程级设置。
    try:
        value = ctypes.c_int()
        hr = ctypes.windll.shcore.GetProcessDpiAwareness(
            None, ctypes.byref(value)
        )
        if hr == 0:
            return int(value.value)
    except Exception:
        pass
    return None


def enable_per_monitor_dpi_awareness() -> str:
    """把当前进程设为 Per-Monitor DPI Aware，返回实际采用方式的说明。

    只影响本进程，不修改系统设置。重复调用是安全的。

    Phase 1.1：设置调用失败时查询系统实际状态，绝不因为调用返回而
    错误声称处于 PER_MONITOR_DPI_AWARE。不引入 PER_MONITOR_AWARE_V2。
    """
    global _current_mode
    if _current_mode != _DPI_MODE_NONE:
        return _dpi_mode_label(_current_mode)

    requested = False
    # Windows 10 1607+ 首选 shcore API。
    try:
        hr = ctypes.windll.shcore.SetProcessDpiAwareness(DpiAwareness.PER_MONITOR_AWARE)
        requested = hr == 0
    except Exception:
        pass

    # 兼容旧系统：仅在上一步未成功时尝试。
    if not requested:
        try:
            requested = bool(ctypes.windll.user32.SetProcessDPIAware())
        except Exception:
            pass

    actual = query_actual_dpi_awareness()
    if actual is not None:
        _current_mode = actual
        return _dpi_mode_label(actual)

    # 无法查询实际状态时，只按成功调用的结果报告，不冒充 PM aware。
    _current_mode = (
        DpiAwareness.PER_MONITOR_AWARE if requested else DpiAwareness.UNAWARE
    )
    return _dpi_mode_label(_current_mode)


def _dpi_mode_label(mode: int) -> str:
    return {
        DpiAwareness.PER_MONITOR_AWARE: "PER_MONITOR_DPI_AWARE",
        DpiAwareness.SYSTEM_AWARE: "SYSTEM_DPI_AWARE",
        DpiAwareness.UNAWARE: "DPI_UNAWARE（多显示器坐标可能不准确）",
    }.get(mode, "UNKNOWN")


def current_dpi_mode() -> str:
    return _dpi_mode_label(_current_mode)


@dataclass(frozen=True)
class DesktopCoordinate:
    """物理桌面坐标（虚拟屏幕坐标系，允许负数，例如副屏在主轴上方）。"""

    x: int
    y: int

    def __post_init__(self) -> None:
        if isinstance(self.x, bool) or isinstance(self.y, bool):
            raise TypeError("坐标必须是整数")
        if not isinstance(self.x, int) or not isinstance(self.y, int):
            raise TypeError(f"坐标必须是整数，收到 ({self.x!r}, {self.y!r})")
        # 不限制取值范围：多显示器布局下负数与超出主屏都是合法的。

    def to_point(self) -> wintypes.POINT:
        return wintypes.POINT(self.x, self.y)

    def __str__(self) -> str:
        return f"({self.x}, {self.y})"


def make_lparam(x: int, y: int) -> int:
    """把客户区坐标打包成鼠标消息的 LPARAM（两个 16 位有符号整数）。

    Windows 鼠标消息的 lParam 只能表示 -32768..32767 的坐标；
    超出范围时抛出 ValueError，避免静默截断成错误点击位置。
    """
    low = ctypes.c_short(x).value
    high = ctypes.c_short(y).value
    if low != x or high != y:
        raise ValueError(
            f"客户区坐标 ({x}, {y}) 超出鼠标消息 16 位有符号范围，拒绝发送"
        )
    return (low & 0xFFFF) | ((high & 0xFFFF) << 16)


def unpack_lparam(lparam: int) -> tuple[int, int]:
    """解包鼠标消息 LPARAM，用于测试。"""
    x = ctypes.c_short(lparam & 0xFFFF).value
    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
    return x, y
