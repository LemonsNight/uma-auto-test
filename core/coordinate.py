"""桌面坐标与 DPI 感知辅助。

关键：必须在创建任何 Qt 窗口或调用 Win32 坐标 API 之前设置进程 DPI 感知，
否则混合 DPI 多显示器下坐标会被系统虚拟化，导致圆点与点击坐标错位。

Phase 1.1 Review Fix：
- 为所有 DPI Win32 API 声明完整 argtypes / restype，避免 64 位 HANDLE 截断。
- 查询失败时标记 UNKNOWN，绝不把未知状态冒充为已确认的 PER_MONITOR_DPI_AWARE。
- 保留现有 PER_MONITOR_DPI_AWARE（v1）方案，不引入 PMv2。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass


class DpiAwareness:
    UNAWARE = 0
    SYSTEM_AWARE = 1
    PER_MONITOR_AWARE = 2
    UNKNOWN = -1


_VALID_MODES = (
    DpiAwareness.UNAWARE,
    DpiAwareness.SYSTEM_AWARE,
    DpiAwareness.PER_MONITOR_AWARE,
)

# 64 位下 DPI_AWARENESS_CONTEXT 是句柄类型，必须用 HANDLE(c_void_p) 声明，
# 不能用 c_int，否则高位会被截断。
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shcore = None
try:
    _shcore = ctypes.WinDLL("shcore", use_last_error=True)
except OSError:  # 老系统无 shcore
    _shcore = None

_DPI_PROTOTYPES_READY = False


def _declare_dpi_prototypes() -> bool:
    """声明 DPI 相关 API 的参数与返回类型，返回是否全部声明成功。"""
    global _DPI_PROTOTYPES_READY
    if _DPI_PROTOTYPES_READY:
        return True

    ok = True
    try:
        _user32.GetThreadDpiAwarenessContext.argtypes = []
        _user32.GetThreadDpiAwarenessContext.restype = wintypes.HANDLE

        _user32.GetAwarenessFromDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        _user32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int

        _user32.SetProcessDPIAware.argtypes = []
        _user32.SetProcessDPIAware.restype = wintypes.BOOL
    except Exception:
        ok = False

    if _shcore is not None:
        try:
            _shcore.GetProcessDpiAwareness.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(ctypes.c_int)
            ]
            _shcore.GetProcessDpiAwareness.restype = ctypes.HRESULT

            _shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
            _shcore.SetProcessDpiAwareness.restype = ctypes.HRESULT
        except Exception:
            ok = False
    else:
        ok = False

    _DPI_PROTOTYPES_READY = ok
    return ok


_DPI_PROTOTYPES_DECLARED = _declare_dpi_prototypes()

_current_mode: int = DpiAwareness.UNKNOWN
_dpi_setup_attempted: bool = False


def dpi_api_declarations() -> dict[str, dict[str, object]]:
    """返回 DPI API 的声明信息，供测试核对 64 位安全类型。"""
    return {
        "GetThreadDpiAwarenessContext": {
            "argtypes": list(_user32.GetThreadDpiAwarenessContext.argtypes or []),
            "restype": _user32.GetThreadDpiAwarenessContext.restype,
        },
        "GetAwarenessFromDpiAwarenessContext": {
            "argtypes": list(_user32.GetAwarenessFromDpiAwarenessContext.argtypes or []),
            "restype": _user32.GetAwarenessFromDpiAwarenessContext.restype,
        },
        "SetProcessDPIAware": {
            "argtypes": list(_user32.SetProcessDPIAware.argtypes or []),
            "restype": _user32.SetProcessDPIAware.restype,
        },
        "GetProcessDpiAwareness": {
            "argtypes": (
                list(_shcore.GetProcessDpiAwareness.argtypes or [])
                if _shcore is not None else []
            ),
            "restype": (
                _shcore.GetProcessDpiAwareness.restype
                if _shcore is not None else None
            ),
        },
        "SetProcessDpiAwareness": {
            "argtypes": (
                list(_shcore.SetProcessDpiAwareness.argtypes or [])
                if _shcore is not None else []
            ),
            "restype": (
                _shcore.SetProcessDpiAwareness.restype
                if _shcore is not None else None
            ),
        },
        "prototypes_ready": _DPI_PROTOTYPES_READY,
    }


def _set_process_per_monitor() -> bool:
    """调用 SetProcessDpiAwareness(PER_MONITOR_AWARE)，返回是否成功。"""
    if _shcore is None:
        return False
    hr = _shcore.SetProcessDpiAwareness(DpiAwareness.PER_MONITOR_AWARE)
    return int(hr) == 0  # S_OK


def _set_process_system() -> bool:
    """旧系统兼容路径：SetProcessDPIAware。"""
    return bool(_user32.SetProcessDPIAware())


def query_actual_dpi_awareness() -> int | None:
    """查询系统记录的实际 DPI 感知级别；无法确认时返回 None（未知）。"""
    # Windows 10 1607+：从线程 DPI 感知上下文读取（HANDLE 已正确声明）。
    try:
        context = _user32.GetThreadDpiAwarenessContext()
        if context:
            value = int(_user32.GetAwarenessFromDpiAwarenessContext(context))
            if value in _VALID_MODES:
                return value
    except Exception:
        pass

    # Windows 8.1+：shcore 查询进程级设置。
    if _shcore is not None:
        try:
            value = ctypes.c_int()
            hr = _shcore.GetProcessDpiAwareness(None, ctypes.byref(value))
            if int(hr) == 0 and value.value in _VALID_MODES:
                return int(value.value)
        except Exception:
            pass
    return None


def _apply_dpi_awareness(set_pm_fn, set_system_fn, query_fn) -> int:
    """纯逻辑版：设置 + 查询 + 报告。可注入函数用于测试所有分支。

    查询失败一律返回 UNKNOWN，不根据设置调用结果推断实际状态。
    """
    requested = False
    try:
        requested = bool(set_pm_fn())
    except Exception:
        requested = False
    if not requested:
        try:
            requested = bool(set_system_fn())
        except Exception:
            requested = False

    actual = None
    try:
        actual = query_fn()
    except Exception:
        actual = None
    if actual in _VALID_MODES:
        return int(actual)
    return DpiAwareness.UNKNOWN


def enable_per_monitor_dpi_awareness() -> str:
    """把当前进程设为 Per-Monitor DPI Aware，返回实际采用方式的说明。

    只影响本进程，不修改系统设置。重复调用是安全的。

    查询失败时返回 UNKNOWN 标签，不冒充 PER_MONITOR_DPI_AWARE。
    """
    global _current_mode, _dpi_setup_attempted
    if _dpi_setup_attempted:
        return _dpi_mode_label(_current_mode)
    _dpi_setup_attempted = True
    _current_mode = _apply_dpi_awareness(
        _set_process_per_monitor, _set_process_system, query_actual_dpi_awareness
    )
    return _dpi_mode_label(_current_mode)


def reset_dpi_state_for_test() -> None:
    """仅供测试：重置缓存状态，使 enable() 可重复执行。"""
    global _current_mode, _dpi_setup_attempted
    _current_mode = DpiAwareness.UNKNOWN
    _dpi_setup_attempted = False


def _dpi_mode_label(mode: int) -> str:
    return {
        DpiAwareness.PER_MONITOR_AWARE: "PER_MONITOR_DPI_AWARE",
        DpiAwareness.SYSTEM_AWARE: "SYSTEM_DPI_AWARE",
        DpiAwareness.UNAWARE: "DPI_UNAWARE（多显示器坐标可能不准确）",
        DpiAwareness.UNKNOWN: "DPI_AWARENESS_UNKNOWN（查询失败或未确认，状态未知）",
    }.get(mode, "DPI_AWARENESS_UNKNOWN（状态未知）")


def current_dpi_mode() -> str:
    return _dpi_mode_label(_current_mode)


def current_dpi_mode_value() -> int:
    return _current_mode


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
