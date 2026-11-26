"""窗口解析与客户区坐标映射。

全部基于 WindowFromPoint / RealChildWindowFromPoint / ScreenToClient，
不触碰真实鼠标。
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass, field

import win32con
import win32gui

from .coordinate import DesktopCoordinate

logger = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.RealChildWindowFromPoint.argtypes = [wintypes.HWND, wintypes.POINT]
_user32.RealChildWindowFromPoint.restype = wintypes.HWND

# 系统桌面相关窗口：绝不向其发送模拟点击。
_DESKTOP_CLASSES = {"Progman", "WorkerW", "SHELLDLL_DefView"}
_DESKTOP_TITLES = {"Program Manager"}

# 已知可能受 UIPI / 系统保护限制的窗口类，只报告限制，不尝试绕过。
_RESTRICTED_CLASS_PREFIXES = (
    "Windows.UI.",
    "Windows.UI.Core",
    "ApplicationFrameWindow",
    "Chrome_WidgetWin",
)
_RESTRICTED_CLASS_EXACT = {"Shell_TrayWnd", "Progman"}


@dataclass
class ResolvedTarget:
    """一次坐标解析的结果。"""

    hwnd: int
    title: str
    class_name: str
    client_x: int
    client_y: int
    root_hwnd: int
    root_title: str
    is_child_window: bool = False
    reject_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_safe_target(self) -> bool:
        return self.reject_reason is None

    def describe(self) -> str:
        return (
            f"HWND=0x{self.hwnd:X} class={self.class_name!r} "
            f"title={self.title!r} client=({self.client_x}, {self.client_y})"
        )


class CoordinateMapper:
    """桌面坐标 -> 目标窗口客户区坐标。"""

    def screen_to_client(self, hwnd: int, coord: DesktopCoordinate) -> tuple[int, int]:
        if not win32gui.IsWindow(hwnd):
            raise ValueError(f"HWND 0x{hwnd:X} 已失效，无法转换坐标")
        x, y = win32gui.ScreenToClient(hwnd, (coord.x, coord.y))
        return int(x), int(y)

    def is_in_client_area(self, hwnd: int, client_x: int, client_y: int) -> bool:
        try:
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
        except Exception:
            return False
        return left <= client_x < right and top <= client_y < bottom


class WindowResolver:
    """按桌面坐标定位实际接收鼠标消息的窗口。"""

    def __init__(self, mapper: CoordinateMapper | None = None,
                 overlay_title: str = "VirtualMouse Overlay") -> None:
        self.mapper = mapper or CoordinateMapper()
        self.overlay_title = overlay_title

    def resolve(self, coord: DesktopCoordinate) -> ResolvedTarget:
        notes: list[str] = []

        hwnd = int(win32gui.WindowFromPoint((coord.x, coord.y)))
        if not hwnd or not win32gui.IsWindow(hwnd):
            return ResolvedTarget(
                hwnd=hwnd, title="", class_name="", client_x=coord.x, client_y=coord.y,
                root_hwnd=0, root_title="",
                reject_reason="WindowFromPoint 未返回有效窗口",
            )

        title = self._safe_window_text(hwnd)
        class_name = self._safe_class_name(hwnd)

        if title == self.overlay_title:
            return ResolvedTarget(
                hwnd=hwnd, title=title, class_name=class_name,
                client_x=coord.x, client_y=coord.y,
                root_hwnd=hwnd, root_title=title,
                reject_reason="命中 VirtualMouse 自身 Overlay（穿透失效？），拒绝发送",
            )

        root_hwnd = int(win32gui.GetAncestor(hwnd, win32con.GA_ROOT)) or hwnd
        root_title = self._safe_window_text(root_hwnd)

        # WindowFromPoint 本身返回的就是命中测试选定的窗口（现代记事本中
        # 是 RichEditD2DPT），通常已是实际接收鼠标消息的子窗口，应优先保留。
        # 只有当它返回顶层窗口时，才用 RealChildWindowFromPoint 进一步定位。
        target_hwnd = hwnd
        is_child = hwnd != root_hwnd
        if is_child:
            notes.append(
                f"WindowFromPoint 命中子窗口 HWND=0x{hwnd:X} class={class_name!r}"
            )
        else:
            try:
                raw_child = _user32.RealChildWindowFromPoint(
                    wintypes.HWND(root_hwnd), wintypes.POINT(coord.x, coord.y)
                )
                child = int(raw_child) if raw_child else 0
                if child and child != root_hwnd and win32gui.IsWindow(child):
                    child_class = self._safe_class_name(child)
                    child_title = self._safe_window_text(child)
                    # 忽略零尺寸/不包含该点的输入占位子窗口。
                    try:
                        cl, ct, cr, cb = win32gui.GetWindowRect(child)
                    except Exception:
                        cl = ct = cr = cb = 0
                    if (
                        cr > cl
                        and cb > ct
                        and cl <= coord.x < cr
                        and ct <= coord.y < cb
                        and child_class not in _DESKTOP_CLASSES
                        and child_title != self.overlay_title
                    ):
                        target_hwnd = child
                        is_child = True
                        notes.append(
                            f"定位到子窗口 HWND=0x{child:X} class={child_class!r} "
                            f"title={child_title!r}"
                        )
            except Exception as exc:
                notes.append(f"RealChildWindowFromPoint 不可用: {exc}")

        target_title = self._safe_window_text(target_hwnd)
        target_class = self._safe_class_name(target_hwnd)

        try:
            client_x, client_y = self.mapper.screen_to_client(target_hwnd, coord)
        except Exception as exc:
            notes.append(f"坐标转换失败: {exc}")
            client_x, client_y = coord.x, coord.y

        reject_reason = self._check_reject(target_class, target_title, target_hwnd)
        if not self.mapper.is_in_client_area(target_hwnd, client_x, client_y):
            notes.append(
                f"转换后坐标 ({client_x}, {client_y}) 不在客户区内，"
                "目标程序可能忽略该消息"
            )

        for prefix in _RESTRICTED_CLASS_PREFIXES:
            if target_class.startswith(prefix):
                notes.append(
                    f"窗口类 {target_class!r} 可能受 UIPI / 应用沙箱限制；"
                    "仅按实际入队结果报告，不尝试绕过"
                )
                break
        if target_class in _RESTRICTED_CLASS_EXACT:
            notes.append(f"系统窗口类 {target_class!r}，仅发送，不尝试绕过")

        result = ResolvedTarget(
            hwnd=target_hwnd,
            title=target_title,
            class_name=target_class,
            client_x=client_x,
            client_y=client_y,
            root_hwnd=root_hwnd,
            root_title=root_title,
            is_child_window=is_child,
            reject_reason=reject_reason,
            notes=notes,
        )
        logger.info("解析坐标 %s -> %s", coord, result.describe())
        for note in notes:
            logger.info("  note: %s", note)
        if reject_reason:
            logger.warning("拒绝目标: %s", reject_reason)
        return result

    @staticmethod
    def _check_reject(class_name: str, title: str, hwnd: int) -> str | None:
        if class_name in _DESKTOP_CLASSES:
            return f"系统桌面窗口 class={class_name!r}，禁止发送模拟点击"
        if title in _DESKTOP_TITLES:
            return f"系统桌面窗口 title={title!r}，禁止发送模拟点击"
        if not win32gui.IsWindow(hwnd):
            return "窗口句柄在解析过程中失效"
        if not win32gui.IsWindowEnabled(hwnd):
            return "目标窗口被禁用（IsWindowEnabled=False），可能被系统保护"
        return None

    @staticmethod
    def _safe_window_text(hwnd: int) -> str:
        try:
            return win32gui.GetWindowText(hwnd)
        except Exception:
            return ""

    @staticmethod
    def _safe_class_name(hwnd: int) -> str:
        try:
            return win32gui.GetClassName(hwnd)
        except Exception:
            return ""
