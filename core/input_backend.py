"""PostMessage 输入后端：唯一允许的点击发送路径。

严禁在此模块或任何其它模块中调用：
    SetCursorPos / SendInput / mouse_event / pyautogui.* / 任何移动真实鼠标的兜底。

重要语义：PostMessage 返回 True 仅代表消息成功入队，
**不代表目标程序处理了点击**，更不代表业务动作成功。
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass, field

from .coordinate import DesktopCoordinate, make_lparam
from .window_resolver import ResolvedTarget

logger = logging.getLogger(__name__)

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

_MESSAGE_NAMES = {
    WM_MOUSEMOVE: "WM_MOUSEMOVE",
    WM_LBUTTONDOWN: "WM_LBUTTONDOWN",
    WM_LBUTTONUP: "WM_LBUTTONUP",
}

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.PostMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.PostMessageW.restype = wintypes.BOOL


@dataclass
class MessageResult:
    """单条消息入队结果。"""

    message_id: int
    message_name: str
    hwnd: int
    client_x: int
    client_y: int
    wparam: int
    posted: bool
    last_error: int = 0

    def describe(self) -> str:
        status = "入队成功" if self.posted else f"入队失败(GetLastError={self.last_error})"
        return (
            f"{self.message_name} HWND=0x{self.hwnd:X} "
            f"client=({self.client_x}, {self.client_y}) wParam=0x{self.wparam:X} -> {status}"
        )


@dataclass
class ClickResult:
    """一次单击的完整结果，明确区分入队成功与实际点击验证。"""

    coord: DesktopCoordinate
    target: ResolvedTarget
    messages: list[MessageResult] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    errors: list[str] = field(default_factory=list)

    @property
    def all_messages_queued(self) -> bool:
        return bool(self.messages) and all(m.posted for m in self.messages)

    @property
    def verification(self) -> str:
        """永远返回"未验证"：本模块无法证明目标程序真的处理了点击。"""
        return "未验证（仅确认消息入队；实际点击需外部证据）"

    def describe(self) -> str:
        lines = [
            f"点击 {self.coord} -> {self.target.describe()}",
            f"  消息入队: {'全部成功' if self.all_messages_queued else '存在失败'}",
        ]
        for msg in self.messages:
            lines.append(f"    {msg.describe()}")
        lines.append(f"  实际点击验证: {self.verification}")
        for err in self.errors:
            lines.append(f"  错误: {err}")
        return "\n".join(lines)


class PostMessageBackend:
    """仅使用 PostMessageW 的点击后端。"""

    def click(self, coord: DesktopCoordinate, target: ResolvedTarget) -> ClickResult:
        if not target.is_safe_target:
            result = ClickResult(coord=coord, target=target)
            result.errors.append(f"目标被拒绝: {target.reject_reason}")
            logger.warning("拒绝点击 %s: %s", coord, target.reject_reason)
            return result

        result = ClickResult(coord=coord, target=target)
        sequence = (
            (WM_MOUSEMOVE, 0),
            (WM_LBUTTONDOWN, MK_LBUTTON),
            (WM_LBUTTONUP, 0),
        )

        for message_id, wparam in sequence:
            try:
                lparam = make_lparam(target.client_x, target.client_y)
            except ValueError as exc:
                result.errors.append(str(exc))
                break

            ctypes.set_last_error(0)
            ok = bool(
                user32.PostMessageW(
                    wintypes.HWND(target.hwnd),
                    wintypes.UINT(message_id),
                    wintypes.WPARAM(wparam),
                    wintypes.LPARAM(lparam),
                )
            )
            err = ctypes.get_last_error() if not ok else 0
            item = MessageResult(
                message_id=message_id,
                message_name=_MESSAGE_NAMES[message_id],
                hwnd=target.hwnd,
                client_x=target.client_x,
                client_y=target.client_y,
                wparam=wparam,
                posted=ok,
                last_error=err,
            )
            result.messages.append(item)
            logger.info("  %s", item.describe())
            if not ok:
                result.errors.append(
                    f"{item.message_name} 入队失败 GetLastError={err}；"
                    "可能原因：句柄失效、UIPI 权限不足、目标为受保护窗口"
                )
                # 入队失败则不再继续后续消息，避免产生半次点击。
                break

        if result.all_messages_queued:
            logger.info("消息全部入队，但这**不等于**目标程序已处理点击。见验证字段。")
        return result
