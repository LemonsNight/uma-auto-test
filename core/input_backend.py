"""PostMessage 输入后端：唯一允许的点击发送路径。

严禁在此模块或任何其它模块中调用：
    SetCursorPos / SendInput / mouse_event / pyautogui.* / 任何移动真实鼠标的兜底。

重要语义：PostMessage 返回 True 仅代表消息成功入队，
**不代表目标程序处理了点击**，更不代表业务动作成功。

Phase 1.1 安全加固：
- 每条消息独立记录结果，并引入 ClickStatus 明确区分失败阶段。
- 发送前与关键消息之间检查 HWND 有效性；失效立即停止，不切换到其它窗口。
- DOWN 失败不发送正常 UP。
- DOWN 成功但 UP 失败时，尝试对同一个 HWND 补发一次释放消息并记录结果；
  仍不报告为完整成功，且标注可能残留未释放按键状态。
- post_fn / is_window_fn 可注入，便于用 Mock 测试全部失败分支。
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from enum import Enum

import win32gui

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


class ClickStatus(str, Enum):
    """一次点击的明确结果状态。"""

    PENDING = "pending"
    REJECTED_TARGET = "rejected_target"        # 目标解析/安全策略拒绝
    TARGET_INVALID = "target_invalid"          # HWND 失效
    LPARAM_OUT_OF_RANGE = "lparam_out_of_range"
    MOUSEMOVE_FAILED = "mousemove_failed"
    DOWN_FAILED = "down_failed"
    UP_FAILED = "up_failed"
    COMPLETE_QUEUED = "complete_queued"        # 三条消息均入队（未验证实际点击）


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
    attempt: str = "primary"  # primary | release_recovery

    def describe(self) -> str:
        status = "入队成功" if self.posted else f"入队失败(GetLastError={self.last_error})"
        return (
            f"[{self.attempt}] {self.message_name} HWND=0x{self.hwnd:X} "
            f"client=({self.client_x}, {self.client_y}) wParam=0x{self.wparam:X} -> {status}"
        )


@dataclass
class HwndCheck:
    """关键阶段前的 HWND 有效性检查记录。"""

    stage: str
    hwnd: int
    valid: bool

    def describe(self) -> str:
        return f"{self.stage}: HWND=0x{self.hwnd:X} valid={self.valid}"


@dataclass
class ClickResult:
    """一次单击的完整结果，明确区分入队成功与实际点击验证。"""

    coord: DesktopCoordinate
    target: ResolvedTarget
    status: ClickStatus = ClickStatus.PENDING
    messages: list[MessageResult] = field(default_factory=list)
    hwnd_checks: list[HwndCheck] = field(default_factory=list)
    release_recovery: MessageResult | None = None
    button_release_uncertain: bool = False
    timestamp: float = field(default_factory=time.time)
    errors: list[str] = field(default_factory=list)

    @property
    def primary_messages(self) -> list[MessageResult]:
        return [m for m in self.messages if m.attempt == "primary"]

    @property
    def all_messages_queued(self) -> bool:
        """仅当三条主消息全部入队且状态为 COMPLETE_QUEUED 时为真。"""
        primary = self.primary_messages
        return (
            self.status is ClickStatus.COMPLETE_QUEUED
            and len(primary) == 3
            and all(m.posted for m in primary)
        )

    @property
    def is_complete(self) -> bool:
        return self.all_messages_queued

    @property
    def verification(self) -> str:
        """永远返回"未验证"：本模块无法证明目标程序真的处理了点击。"""
        return "未验证（仅确认消息入队；实际点击需外部证据）"

    def describe(self) -> str:
        lines = [
            f"点击 {self.coord} -> {self.target.describe()}",
            f"  状态: {self.status.value}",
            f"  三条主消息全部入队: {'是' if self.all_messages_queued else '否'}",
            f"  按键释放状态不确定: {'是' if self.button_release_uncertain else '否'}",
        ]
        for check in self.hwnd_checks:
            lines.append(f"  HWND 检查: {check.describe()}")
        for msg in self.messages:
            lines.append(f"    {msg.describe()}")
        if self.release_recovery is not None:
            lines.append(f"    释放补救: {self.release_recovery.describe()}")
        lines.append(f"  实际点击验证: {self.verification}")
        for err in self.errors:
            lines.append(f"  错误: {err}")
        return "\n".join(lines)


_PostFn = object  # 类型别名占位，避免导入 Callable 造成额外复杂度


class PostMessageBackend:
    """仅使用 PostMessageW 的点击后端。

    post_fn(hwnd, msg, wparam, lparam) -> (ok: bool, last_error: int)
    is_window_fn(hwnd) -> bool
    两者可注入用于 Mock 测试；生产路径使用真实 Win32 API。
    """

    def __init__(self, post_fn=None, is_window_fn=None) -> None:
        self._post_fn = post_fn or self._default_post
        self._is_window_fn = is_window_fn or self._default_is_window

    @staticmethod
    def _default_post(hwnd: int, msg: int, wparam: int, lparam: int) -> tuple[bool, int]:
        ctypes.set_last_error(0)
        ok = bool(
            user32.PostMessageW(
                wintypes.HWND(hwnd),
                wintypes.UINT(msg),
                wintypes.WPARAM(wparam),
                wintypes.LPARAM(lparam),
            )
        )
        return ok, ctypes.get_last_error() if not ok else 0

    @staticmethod
    def _default_is_window(hwnd: int) -> bool:
        try:
            return bool(win32gui.IsWindow(hwnd))
        except Exception:
            return False

    def click(self, coord: DesktopCoordinate, target: ResolvedTarget) -> ClickResult:
        result = ClickResult(coord=coord, target=target)

        if not target.is_safe_target:
            result.status = ClickStatus.REJECTED_TARGET
            result.errors.append(f"目标被拒绝: {target.reject_reason}")
            logger.warning("拒绝点击 %s: %s", coord, target.reject_reason)
            return result

        # 发送前检查目标 HWND。
        if not self._check_hwnd(result, "发送前"):
            result.status = ClickStatus.TARGET_INVALID
            result.errors.append("发送前目标 HWND 已失效，停止发送")
            return result

        try:
            lparam = make_lparam(target.client_x, target.client_y)
        except ValueError as exc:
            result.status = ClickStatus.LPARAM_OUT_OF_RANGE
            result.errors.append(str(exc))
            logger.error("坐标超出 LPARAM 范围，拒绝发送: %s", exc)
            return result

        # 1) WM_MOUSEMOVE
        move = self._send(result, WM_MOUSEMOVE, 0, lparam)
        if not move.posted:
            result.status = ClickStatus.MOUSEMOVE_FAILED
            result.errors.append(
                f"WM_MOUSEMOVE 入队失败 GetLastError={move.last_error}；停止后续消息"
            )
            return result

        # 2) WM_LBUTTONDOWN —— 再次检查 HWND，防止窗口在消息间销毁。
        if not self._check_hwnd(result, "WM_LBUTTONDOWN 前"):
            result.status = ClickStatus.TARGET_INVALID
            result.errors.append("WM_LBUTTONDOWN 前目标 HWND 失效，停止；未发送 DOWN")
            return result
        down = self._send(result, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        if not down.posted:
            result.status = ClickStatus.DOWN_FAILED
            result.errors.append(
                f"WM_LBUTTONDOWN 入队失败 GetLastError={down.last_error}；"
                "不发送正常 UP，避免产生误导性的完整点击"
            )
            return result

        # 3) WM_LBUTTONUP —— 关键消息前再次检查 HWND。
        if not self._check_hwnd(result, "WM_LBUTTONUP 前"):
            result.status = ClickStatus.UP_FAILED
            result.button_release_uncertain = True
            result.errors.append(
                "WM_LBUTTONUP 前目标 HWND 已失效；DOWN 已入队，"
                "无法向原目标补发释放，不能保证按键已释放"
            )
            return result

        up = self._send(result, WM_LBUTTONUP, 0, lparam)
        if up.posted:
            result.status = ClickStatus.COMPLETE_QUEUED
            logger.info("三条消息全部入队，但这**不等于**目标程序已处理点击。")
            return result

        # DOWN 成功但 UP 失败：记录不确定状态，尝试对原 HWND 补发释放。
        result.status = ClickStatus.UP_FAILED
        result.button_release_uncertain = True
        result.errors.append(
            f"WM_LBUTTONUP 入队失败 GetLastError={up.last_error}；"
            "DOWN 已入队，当前可能存在未释放的左键按下状态"
        )
        self._attempt_release_recovery(result, target, lparam)
        return result

    # ---------- 内部辅助 ----------
    def _check_hwnd(self, result: ClickResult, stage: str) -> bool:
        hwnd = result.target.hwnd
        valid = bool(self._is_window_fn(hwnd))
        result.hwnd_checks.append(HwndCheck(stage=stage, hwnd=hwnd, valid=valid))
        if not valid:
            logger.error("%s: HWND=0x%X 已失效", stage, hwnd)
        return valid

    def _send(
        self, result: ClickResult, message_id: int, wparam: int, lparam: int
    ) -> MessageResult:
        hwnd = result.target.hwnd
        ok, err = self._post_fn(hwnd, message_id, wparam, lparam)
        item = MessageResult(
            message_id=message_id,
            message_name=_MESSAGE_NAMES[message_id],
            hwnd=hwnd,
            client_x=result.target.client_x,
            client_y=result.target.client_y,
            wparam=wparam,
            posted=bool(ok),
            last_error=int(err or 0),
        )
        result.messages.append(item)
        logger.info("  %s", item.describe())
        return item

    def _attempt_release_recovery(
        self, result: ClickResult, target: ResolvedTarget, lparam: int
    ) -> None:
        """仅对原目标 HWND 补发一次 WM_LBUTTONUP，不投向任何其它窗口。"""
        if not self._check_hwnd(result, "释放补救前"):
            result.errors.append("原目标 HWND 已失效，无法补发释放消息")
            return
        ok, err = self._post_fn(target.hwnd, WM_LBUTTONUP, 0, lparam)
        recovery = MessageResult(
            message_id=WM_LBUTTONUP,
            message_name=_MESSAGE_NAMES[WM_LBUTTONUP],
            hwnd=target.hwnd,
            client_x=target.client_x,
            client_y=target.client_y,
            wparam=0,
            posted=bool(ok),
            last_error=int(err or 0),
            attempt="release_recovery",
        )
        result.release_recovery = recovery
        logger.warning("  %s", recovery.describe())
        if recovery.posted:
            result.errors.append(
                "已对原目标 HWND 补发 WM_LBUTTONUP（仅代表入队）；"
                "仍无法确认目标已释放按键，本次操作不报告为完整成功"
            )
        else:
            result.errors.append(
                f"补发释放消息仍失败 GetLastError={recovery.last_error}；"
                "按键释放状态无法保证"
            )
